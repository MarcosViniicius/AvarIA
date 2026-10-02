"""
CAMADA DE PERSISTÊNCIA (SQLite)

Guarda o histórico de execuções de processamento, os itens extraídos e o
índice de relatórios unificados gerados. O Excel continua sendo o arquivo
de trabalho/exportação principal — este banco é uma camada adicional que
não substitui nada do fluxo existente, apenas registra o histórico para a
tela de "Histórico de Relatórios".
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.paths import DATABASE_DIR, DATABASE_FILE
from .unification import extrair_peso_de_valor

SCHEMA = """
CREATE TABLE IF NOT EXISTS processing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL DEFAULT 'processamento',
    iniciado_em TEXT NOT NULL,
    finalizado_em TEXT,
    status TEXT NOT NULL DEFAULT 'em_andamento',
    imagens_total INTEGER NOT NULL DEFAULT 0,
    avarias INTEGER NOT NULL DEFAULT 0,
    uso_interno INTEGER NOT NULL DEFAULT 0,
    erros INTEGER NOT NULL DEFAULT 0,
    tokens_consumidos INTEGER NOT NULL DEFAULT 0,
    mensagem TEXT
);

CREATE TABLE IF NOT EXISTS report_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES processing_runs(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL,
    produto TEXT,
    peso TEXT,
    marca TEXT,
    codigo_barras TEXT,
    detalhes TEXT,
    observacao_mensagem TEXT,
    caminho_imagem TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_items_run ON report_items(run_id);
CREATE INDEX IF NOT EXISTS idx_report_items_categoria ON report_items(categoria);

CREATE TABLE IF NOT EXISTS unified_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    arquivo_xlsx TEXT,
    arquivo_txt TEXT,
    secoes TEXT,
    total_itens INTEGER NOT NULL DEFAULT 0,
    resumo TEXT,
    origem TEXT NOT NULL DEFAULT 'app'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unified_reports_arquivo
    ON unified_reports(COALESCE(arquivo_xlsx, ''), COALESCE(arquivo_txt, ''));

CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES processing_runs(id) ON DELETE CASCADE,
    registrado_em TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    detalhes TEXT
);

-- Catálogo de produtos usado pela extração SEM IA: traduz o código lido da
-- foto para nome/peso/marca. Ver services/catalogo.py.
--   tipo 'ean' -> código de barras do produto industrializado
--   tipo 'plu' -> código interno da balança (produto pesado na loja)
-- preco_kg é um FATOR DE CONVERSÃO interno (a etiqueta de balança só
-- codifica o valor total, não o peso) - nunca é exibido ao usuário nem vira
-- coluna de relatório. O que importa para o app é produto + peso.
CREATE TABLE IF NOT EXISTS catalogo_produtos (
    codigo TEXT PRIMARY KEY,
    tipo TEXT NOT NULL DEFAULT 'ean',
    produto TEXT,
    marca TEXT,
    preco_kg REAL,
    categoria_padrao TEXT,
    origem TEXT NOT NULL DEFAULT 'manual',
    vezes_visto INTEGER NOT NULL DEFAULT 1,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalogo_tipo ON catalogo_produtos(tipo);

-- Fila de PLUs cujo peso calculado saiu implausível (ver
-- catalogo.aprender_preco_kg) - guardado para não descartar silenciosamente
-- uma leitura estranha, mas SEM aplicar automaticamente no catálogo.
CREATE TABLE IF NOT EXISTS catalogo_revisoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL DEFAULT 'plu',
    produto TEXT,
    peso_kg_proposto REAL,
    motivo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);

-- Acervo de arquivos: metadados no banco, bytes no disco (ver
-- services/arquivos.py). O nome FÍSICO é aleatório (uuid) para nunca colidir;
-- o nome que o usuário vê é `nome_original`. `hash_sha256` é o hash do
-- conteúdo ORIGINAL (nunca da versão recomprimida) e é a chave de dedup.
CREATE TABLE IF NOT EXISTS arquivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_original TEXT NOT NULL,
    nome_fisico TEXT NOT NULL UNIQUE,
    pasta TEXT NOT NULL DEFAULT 'pendentes',
    extensao TEXT,
    tipo_mime TEXT,
    tamanho INTEGER NOT NULL DEFAULT 0,
    hash_sha256 TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arquivos_hash ON arquivos(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_arquivos_nome_original ON arquivos(nome_original);
CREATE INDEX IF NOT EXISTS idx_arquivos_pasta ON arquivos(pasta);

-- Arquivos já processados: era o logs/log_mestre.txt (uma linha por arquivo).
-- O texto funcionava, mas exigia ler o arquivo inteiro para responder "esta
-- imagem já foi analisada?" — e havia DUAS implementações quase idênticas
-- (extraction_pipeline.carregar_logs e stats.carregar_logs_processados) que
-- podiam divergir. Agora é uma linha por arquivo, com índice por nome.
-- O .txt continua sendo escrito em paralelo para compatibilidade (ver
-- services/extraction_pipeline.py:registrar_log).
CREATE TABLE IF NOT EXISTS arquivos_processados (
    nome TEXT PRIMARY KEY,
    processado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arquivos_processados_data ON arquivos_processados(processado_em);

-- Consumo de tokens por operação: era o logs/log_consumo_tokens.txt.
-- A tabela token_usage (por execução) já existia e é preenchida pelo pipeline;
-- esta guarda o registro CRU do log, que também cobre execuções que não têm
-- run_id (ex.: reanálises antigas), preservando o histórico do arquivo.
CREATE TABLE IF NOT EXISTS consumo_tokens_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registrado_em TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    detalhes TEXT
);
CREATE INDEX IF NOT EXISTS idx_consumo_tokens_data ON consumo_tokens_log(registrado_em);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def migrar_banco_legado() -> bool:
    """Migra o banco do nome antigo (`autoavaria.db`) para o novo (`avariaia.db`).

    Copia (não move) — o SQLite é a fonte da verdade do histórico, então o
    arquivo antigo é preservado como `.bak` antes de qualquer coisa. Só roda
    quando o novo ainda não existe e o antigo existe; se a cópia falhar,
    levanta erro para o boot abortar em vez de criar um banco vazio por cima
    do histórico. Usa `DATABASE_DIR`/`DATABASE_FILE` do módulo (patcháveis nos
    testes).
    """
    import shutil

    legado = DATABASE_DIR / "autoavaria.db"
    if DATABASE_FILE.exists() or not legado.exists():
        return False

    try:
        shutil.copy2(legado, DATABASE_FILE)
    except OSError as e:
        raise RuntimeError(
            f"Não foi possível migrar o banco {legado} para {DATABASE_FILE}: {e}"
        ) from e

    backup = legado.parent / (legado.name + ".bak")
    try:
        if not backup.exists():
            os.replace(legado, backup)
    except OSError:
        pass  # o arquivo antigo continua no lugar (já é um backup natural)

    print(f"📦 Banco migrado: {legado.name} -> {DATABASE_FILE.name} (backup preservado)")
    return True


@contextmanager
def get_connection():
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Cria as tabelas do banco (idempotente) e aplica migrações de colunas. Chamado na inicialização do app."""
    migrar_banco_legado()
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrar_colunas_report_items(conn)
        _migrar_colunas_processing_runs(conn)


def _migrar_colunas_report_items(conn) -> None:
    """Adiciona colunas novas a bancos criados antes da separação Peso/Marca/Código de Barras."""
    colunas_existentes = {row["name"] for row in conn.execute("PRAGMA table_info(report_items)").fetchall()}
    for coluna in ("peso", "marca", "codigo_barras"):
        if coluna not in colunas_existentes:
            conn.execute(f"ALTER TABLE report_items ADD COLUMN {coluna} TEXT")
    # Quantidade veio depois: linhas antigas assumem 1, que é o que sempre
    # significaram na prática (uma linha = um item).
    if "quantidade" not in colunas_existentes:
        conn.execute("ALTER TABLE report_items ADD COLUMN quantidade INTEGER NOT NULL DEFAULT 1")


def _migrar_colunas_processing_runs(conn) -> None:
    """Adiciona o versionamento (linhagem de reanálises) a bancos criados
    antes de existir o botão "Reanalisar" do Histórico."""
    colunas_existentes = {row["name"] for row in conn.execute("PRAGMA table_info(processing_runs)").fetchall()}
    if "raiz_execucao_id" not in colunas_existentes:
        conn.execute("ALTER TABLE processing_runs ADD COLUMN raiz_execucao_id INTEGER")
        # Execuções antigas viram linhagens de um item só (raiz = ela mesma).
        conn.execute("UPDATE processing_runs SET raiz_execucao_id = id WHERE raiz_execucao_id IS NULL")
    if "versao" not in colunas_existentes:
        conn.execute("ALTER TABLE processing_runs ADD COLUMN versao INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_processing_runs_raiz ON processing_runs(raiz_execucao_id)"
    )


# ---------------------------------------------------------------------------
# Execuções de processamento (processing_runs)
# ---------------------------------------------------------------------------

def iniciar_execucao(tipo: str = "processamento", imagens_total: int = 0) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO processing_runs (tipo, iniciado_em, status, imagens_total)
               VALUES (?, ?, 'em_andamento', ?)""",
            (tipo, _now(), imagens_total),
        )
        run_id = cursor.lastrowid
        # Toda execução nova começa a própria linhagem (versão 1, raiz = si
        # mesma) - reanálises de verdade entram por iniciar_reanalise_de_execucao.
        conn.execute("UPDATE processing_runs SET raiz_execucao_id = ? WHERE id = ?", (run_id, run_id))
        return run_id


def finalizar_execucao(
    run_id: int,
    status: str,
    avarias: int = 0,
    uso_interno: int = 0,
    erros: int = 0,
    tokens_consumidos: int = 0,
    mensagem: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE processing_runs
               SET finalizado_em = ?, status = ?, avarias = ?, uso_interno = ?,
                   erros = ?, tokens_consumidos = ?, mensagem = ?
               WHERE id = ?""",
            (_now(), status, avarias, uso_interno, erros, tokens_consumidos, mensagem, run_id),
        )


def registrar_itens(run_id: int, categoria: str, itens: Iterable[Dict[str, Any]]) -> None:
    """Grava os itens extraídos (Avarias / Uso Interno / Erros de Análise) de uma execução."""
    linhas = []
    agora = _now()
    for item in itens:
        produto = item.get("Produto") or item.get("Arquivo")
        linhas.append(
            (
                run_id,
                categoria,
                produto,
                item.get("Peso"),
                item.get("Marca"),
                item.get("Código de Barras"),
                item.get("Detalhes do Erro"),
                item.get("Observação da Mensagem"),
                item.get("Caminho da Imagem"),
                _quantidade(item),
                agora,
            )
        )
    if not linhas:
        return
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO report_items
               (run_id, categoria, produto, peso, marca, codigo_barras, detalhes, observacao_mensagem, caminho_imagem, quantidade, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            linhas,
        )


def _quantidade(item: Dict[str, Any]) -> int:
    """Quantidade do item, com 1 como padrão para linhas sem a informação."""
    try:
        valor = int(item.get("Quantidade") or 1)
    except (TypeError, ValueError):
        return 1
    return valor if valor > 0 else 1


# Mapeia os nomes de campo exibidos na tela (iguais aos usados no Excel) para
# as colunas reais da tabela report_items.
_CAMPO_PARA_COLUNA = {
    "Produto": "produto",
    "Arquivo": "produto",
    "Quantidade": "quantidade",
    "Peso": "peso",
    "Marca": "marca",
    "Código de Barras": "codigo_barras",
    "Detalhes": "detalhes",
    "Detalhes do Erro": "detalhes",
    "Observação da Mensagem": "observacao_mensagem",
    "Caminho da Imagem": "caminho_imagem",
}


def obter_item(item_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM report_items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def atualizar_item_campo(item_id: int, campo: str, valor: str) -> bool:
    """Atualiza um único campo (nome de exibição, ex: 'Produto') de um item histórico."""
    coluna = _CAMPO_PARA_COLUNA.get(campo)
    if not coluna:
        return False
    with get_connection() as conn:
        cursor = conn.execute(f"UPDATE report_items SET {coluna} = ? WHERE id = ?", (valor, item_id))
        return cursor.rowcount > 0


def atualizar_item_completo(item_id: int, dados: Dict[str, str]) -> bool:
    """Atualiza vários campos de um item histórico de uma vez (edição de linha completa)."""
    campos_validos = {}
    for campo, valor in dados.items():
        coluna = _CAMPO_PARA_COLUNA.get(campo)
        if coluna:
            campos_validos[coluna] = valor
    if not campos_validos:
        return False
    with get_connection() as conn:
        set_clause = ", ".join(f"{coluna} = ?" for coluna in campos_validos)
        valores = list(campos_validos.values()) + [item_id]
        cursor = conn.execute(f"UPDATE report_items SET {set_clause} WHERE id = ?", valores)
        return cursor.rowcount > 0


def mover_item_categoria(item_id: int, nova_categoria: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE report_items SET categoria = ? WHERE id = ?", (nova_categoria, item_id)
        )
        return cursor.rowcount > 0


def excluir_item(item_id: int) -> Optional[int]:
    """Exclui um item histórico e retorna o run_id ao qual pertencia (ou None se não existir)."""
    with get_connection() as conn:
        row = conn.execute("SELECT run_id FROM report_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM report_items WHERE id = ?", (item_id,))
        return row["run_id"]


# ---------------------------------------------------------------------------
# Erros de análise (usado pelo GerenciadorErros / reanálise de erros)
# ---------------------------------------------------------------------------

def listar_erros_por_arquivo() -> List[Dict[str, Any]]:
    """Itens da categoria 'Erros de Análise' no ESTADO ATUAL, mais recentes primeiro.

    Base do `GerenciadorErros.obter_erros_pendentes`. Como na visão mestre, só
    entram os erros da versão mais recente de cada linhagem: um erro que já foi
    corrigido por uma reanálise não deve reaparecer. A ordem é por execução mais
    nova, para a reanálise partir sempre da versão vigente. Itens sem execução
    (manuais) entram sempre.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ri.*
               FROM report_items ri
               LEFT JOIN processing_runs pr ON pr.id = ri.run_id
               LEFT JOIN (
                   SELECT raiz_execucao_id, MAX(id) AS ultimo_run
                   FROM processing_runs
                   GROUP BY COALESCE(raiz_execucao_id, id)
               ) ultima ON ultima.ultimo_run = pr.id
               WHERE ri.categoria = 'Erros de Análise'
                 AND (ri.run_id IS NULL OR ultima.ultimo_run IS NOT NULL)
               ORDER BY COALESCE(pr.id, 0) DESC, ri.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def excluir_erros_do_arquivo(nome_arquivo: str) -> int:
    """Remove as linhas de erro de um arquivo (erro corrigido na reanálise).

    Devolve quantas saíram e recalcula as contagens das execuções afetadas,
    senão os números do Histórico ficariam com erros que já não existem.
    """
    with get_connection() as conn:
        runs = {
            row["run_id"]
            for row in conn.execute(
                "SELECT DISTINCT run_id FROM report_items "
                "WHERE categoria = 'Erros de Análise' AND produto = ?",
                (nome_arquivo,),
            )
            if row["run_id"] is not None
        }
        cursor = conn.execute(
            "DELETE FROM report_items WHERE categoria = 'Erros de Análise' AND produto = ?",
            (nome_arquivo,),
        )
        removidos = cursor.rowcount

    for run_id in runs:
        recalcular_contagens(run_id)
    return removidos


def anotar_tentativa_reanalise(nome_arquivo: str, detalhe: str) -> int:
    """Anexa uma observação às linhas de erro de um arquivo (falhou de novo).

    O equivalente, no banco, ao que o GerenciadorErros fazia no Excel: registra
    que houve tentativa e que não resolveu. Devolve quantas linhas mudaram.
    """
    if not nome_arquivo:
        return 0
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE report_items
               SET detalhes = COALESCE(detalhes, '') || ?
               WHERE categoria = 'Erros de Análise' AND produto = ?""",
            (detalhe, nome_arquivo),
        )
        return cursor.rowcount


def adicionar_item(run_id: Optional[int], categoria: str, dados: Dict[str, str]) -> int:
    """Adiciona um novo item histórico à execução informada.

    `run_id=None` registra o item sem vínculo com uma execução automática
    (ex.: linha adicionada manualmente pela tela de edição) - fica no banco
    para consistência, mas não aparece em nenhum "Histórico > Execução".
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO report_items
               (run_id, categoria, produto, peso, marca, codigo_barras, detalhes, observacao_mensagem, caminho_imagem, quantidade, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                categoria,
                dados.get("Produto") or dados.get("Arquivo"),
                dados.get("Peso"),
                dados.get("Marca"),
                dados.get("Código de Barras"),
                dados.get("Detalhes") or dados.get("Detalhes do Erro"),
                dados.get("Observação da Mensagem"),
                dados.get("Caminho da Imagem"),
                _quantidade(dados),
                _now(),
            ),
        )
        return cursor.lastrowid


def buscar_itens_por_caminho(
    categoria: str, caminho_imagem: str, valores_atuais: Optional[Dict[str, Any]] = None
) -> List[int]:
    """Todos os `report_items.id` que correspondem a uma linha do Excel.

    O Excel (editado via routes/edicao.py) não guarda o id do banco — só tem
    posição de linha, que não é estável. `categoria + caminho_imagem` é a
    melhor chave disponível, mas uma foto pode gerar mais de um item (ex.: "2
    alface, 4 coentro" na mesma imagem) — e a MESMA imagem pode ter sido
    processada em várias execuções, gerando linhas equivalentes em cada uma
    (`report_items` guarda por execução; o Excel mestre acumula).

    Por isso devolvemos a LISTA de correspondências:
    - uma só linha com categoria+caminho -> essa;
    - várias, mas `valores_atuais` (o resto da linha ANTES da edição) bate
      exatamente em algumas -> essas (é o mesmo dado duplicado entre
      execuções: editar uma deve refletir em todas);
    - várias e nenhuma bate exatamente -> lista vazia (ambíguo de verdade:
      são itens diferentes na mesma foto, não dá para saber qual);
    - sem `valores_atuais`, havendo mais de uma -> lista vazia.

    Quem chama decide o que fazer com "não achou" — antes isso era silencioso
    e a edição ia só para o Excel, deixando o Histórico desatualizado.
    """
    if not caminho_imagem:
        return []
    with get_connection() as conn:
        linhas = conn.execute(
            "SELECT * FROM report_items WHERE categoria = ? AND caminho_imagem = ?",
            (categoria, caminho_imagem),
        ).fetchall()

    if not linhas:
        return []
    if len(linhas) == 1:
        return [linhas[0]["id"]]
    if not valores_atuais:
        return []

    candidatas = []
    for linha in linhas:
        bate = True
        for campo, valor_esperado in valores_atuais.items():
            coluna = _CAMPO_PARA_COLUNA.get(campo)
            if not coluna:
                continue
            if str(linha[coluna] or "") != str(valor_esperado or ""):
                bate = False
                break
        if bate:
            candidatas.append(linha["id"])

    return candidatas


def buscar_item_por_caminho(
    categoria: str, caminho_imagem: str, valores_atuais: Optional[Dict[str, Any]] = None
) -> Optional[int]:
    """Um único `report_items.id`, quando não há ambiguidade (None se houver).

    Mantida para quem precisa de uma linha só. A edição usa
    `buscar_itens_por_caminho` para atualizar todas as correspondências.
    """
    candidatas = buscar_itens_por_caminho(categoria, caminho_imagem, valores_atuais)
    return candidatas[0] if len(candidatas) == 1 else None


def atualizar_itens_campo(item_ids: List[int], campo: str, novo_valor) -> int:
    """Atualiza um campo de vários itens de uma vez. Devolve quantos mudaram."""
    if not item_ids:
        return 0
    coluna = _CAMPO_PARA_COLUNA.get(campo)
    if not coluna:
        return 0
    marcadores = ",".join("?" for _ in item_ids)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE report_items SET {coluna} = ? WHERE id IN ({marcadores})",
            (novo_valor, *item_ids),
        )
        return cursor.rowcount


def atualizar_itens_completo(item_ids: List[int], dados: Dict[str, Any]) -> int:
    """Atualiza vários campos de vários itens. Devolve quantos itens mudaram."""
    if not item_ids or not dados:
        return 0
    campos = {k: v for k, v in dados.items() if k in _CAMPO_PARA_COLUNA}
    if not campos:
        return 0
    atribuicoes = ", ".join(f"{_CAMPO_PARA_COLUNA[k]} = ?" for k in campos)
    marcadores = ",".join("?" for _ in item_ids)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE report_items SET {atribuicoes} WHERE id IN ({marcadores})",
            (*campos.values(), *item_ids),
        )
        return cursor.rowcount


def excluir_itens(item_ids: List[int]) -> set:
    """Exclui vários itens. Devolve o conjunto de run_ids afetados."""
    if not item_ids:
        return set()
    marcadores = ",".join("?" for _ in item_ids)
    with get_connection() as conn:
        runs = {
            row["run_id"]
            for row in conn.execute(
                f"SELECT DISTINCT run_id FROM report_items WHERE id IN ({marcadores})",
                item_ids,
            )
            if row["run_id"] is not None
        }
        conn.execute(f"DELETE FROM report_items WHERE id IN ({marcadores})", item_ids)
    return runs


def excluir_itens_por_caminho(caminhos) -> int:
    """Remove TODAS as linhas cujo `caminho_imagem` esteja na lista.

    Usado pela reanálise seletiva do mestre: uma imagem pode ter gerado linhas
    em várias categorias e em várias execuções; ao reprocessá-la, todas as
    versões antigas saem do banco e só as novas permanecem. Recalcula as
    contagens das execuções afetadas para o Histórico não ficar inflado.

    Devolve quantas linhas foram removidas.
    """
    caminhos = [str(c) for c in caminhos if c]
    if not caminhos:
        return 0
    marcadores = ",".join("?" for _ in caminhos)
    with get_connection() as conn:
        runs = {
            row["run_id"]
            for row in conn.execute(
                f"SELECT DISTINCT run_id FROM report_items WHERE caminho_imagem IN ({marcadores})",
                caminhos,
            )
            if row["run_id"] is not None
        }
        cursor = conn.execute(
            f"DELETE FROM report_items WHERE caminho_imagem IN ({marcadores})", caminhos
        )
        removidos = cursor.rowcount

    for run_id in runs:
        recalcular_contagens(run_id)
    return removidos


def mover_itens_categoria(item_ids: List[int], nova_categoria: str) -> int:
    """Move vários itens de categoria. Devolve quantos mudaram."""
    if not item_ids:
        return 0
    marcadores = ",".join("?" for _ in item_ids)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE report_items SET categoria = ? WHERE id IN ({marcadores})",
            (nova_categoria, *item_ids),
        )
        return cursor.rowcount



def recalcular_contagens(run_id: int) -> None:
    """Recalcula avarias/uso_interno/erros da execução a partir dos itens atuais no banco."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT categoria, COUNT(*) AS total FROM report_items WHERE run_id = ? GROUP BY categoria",
            (run_id,),
        ).fetchall()
        contagens = {row["categoria"]: row["total"] for row in rows}
        conn.execute(
            "UPDATE processing_runs SET avarias = ?, uso_interno = ?, erros = ? WHERE id = ?",
            (
                contagens.get("Avarias", 0),
                contagens.get("Uso Interno", 0),
                contagens.get("Erros de Análise", 0),
                run_id,
            ),
        )


def registrar_consumo_tokens(run_id: Optional[int], tokens: int, detalhes: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO token_usage (run_id, registrado_em, tokens, detalhes)
               VALUES (?, ?, ?, ?)""",
            (run_id, _now(), tokens, detalhes),
        )


def listar_execucoes(limite: int = 50) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM processing_runs ORDER BY id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
        return [dict(row) for row in rows]


def recuperar_execucoes_orfas() -> int:
    """Marca como 'erro' as execuções presas em 'em_andamento'. Devolve quantas.

    Chamado no boot (ver create_app). Uma execução só pode estar em andamento
    enquanto o processo está vivo; se o app subiu e há uma nesse estado, o
    processo que a criou morreu no meio (queda, Ctrl+C, reload do dev server) e
    ela nunca vai terminar sozinha.

    Sem isto, uma execução órfã fica no topo do Histórico para sempre e passa a
    ser "a última execução" — escondendo a última que concluiu de verdade em
    tudo que consulta o topo da lista (relatório, unificação/exportação,
    resumo). Foi exatamente o que quebrou o envio ao invertexto: dois runs
    órfãos vazios escondiam a execução com 74 imagens.

    A mensagem registra que a marcação foi automática, para não se confundir
    com uma falha real de processamento.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """UPDATE processing_runs
               SET status = 'erro',
                   finalizado_em = ?,
                   mensagem = COALESCE(mensagem, 'Execução interrompida (recuperada na inicialização)')
               WHERE status = 'em_andamento'""",
            (_now(),),
        )
        return cursor.rowcount


def listar_todos_itens() -> List[Dict[str, Any]]:
    """Itens que formam o ESTADO ATUAL (visão mestre), dos mais recentes aos antigos.

    Base da visão mestre (services/mestre.py). Só entram os itens da VERSÃO MAIS
    RECENTE de cada linhagem (``raiz_execucao_id``): uma reanálise por execução
    cria uma nova versão e mantém a antiga no banco como histórico, mas o
    relatório mestre deve refletir apenas o resultado mais novo — nunca a versão
    antiga e a nova somadas.

    Execuções comuns são linhagens de uma versão só (raiz = ela mesma), então
    entram integralmente; a deduplicação entre linhagens diferentes (a mesma
    imagem reprocessada em execuções distintas) é feita em mestre.py pela chave
    de conteúdo.

    A ordenação é por ``processing_runs.id DESC`` (a execução), não por
    ``report_items.id``, para o critério ser "execução mais recente" e não
    "linha inserida por último".

    Itens sem execução (``run_id IS NULL``), adicionados à mão pela tela de
    edição, entram sempre — não pertencem a linhagem nenhuma.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ri.*
               FROM report_items ri
               LEFT JOIN processing_runs pr ON pr.id = ri.run_id
               LEFT JOIN (
                   SELECT raiz_execucao_id, MAX(id) AS ultimo_run
                   FROM processing_runs
                   GROUP BY COALESCE(raiz_execucao_id, id)
               ) ultima ON ultima.ultimo_run = pr.id
               WHERE ri.run_id IS NULL OR ultima.ultimo_run IS NOT NULL
               ORDER BY COALESCE(pr.id, 0) DESC, ri.id DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def obter_execucao(run_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM processing_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        execucao = dict(row)
        itens = conn.execute(
            "SELECT * FROM report_items WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        execucao["itens"] = [dict(item) for item in itens]
        return execucao


def iniciar_reanalise_de_execucao(raiz_execucao_id: int, imagens_total: int = 0) -> int:
    """Inicia uma reanálise vinculada à mesma linhagem de `raiz_execucao_id`.

    A versão é sempre a próxima da linhagem inteira (não da execução
    reanalisada especificamente) - garante uma linha do tempo linear mesmo
    que, no futuro, alguém chame isso a partir de uma versão que não seja a
    mais recente (a rota que expõe isso ao usuário já bloqueia esse caso -
    ver routes/historico.py)."""
    with get_connection() as conn:
        maior_versao = conn.execute(
            "SELECT COALESCE(MAX(versao), 0) AS maior FROM processing_runs WHERE raiz_execucao_id = ?",
            (raiz_execucao_id,),
        ).fetchone()["maior"]
        cursor = conn.execute(
            """INSERT INTO processing_runs
               (tipo, iniciado_em, status, imagens_total, raiz_execucao_id, versao)
               VALUES ('reanalise', ?, 'em_andamento', ?, ?, ?)""",
            (_now(), imagens_total, raiz_execucao_id, maior_versao + 1),
        )
        return cursor.lastrowid


def listar_versoes(raiz_execucao_id: int) -> List[Dict[str, Any]]:
    """Todas as execuções de uma linhagem (versões da mesma análise), da mais antiga para a mais nova."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM processing_runs WHERE raiz_execucao_id = ? ORDER BY versao",
            (raiz_execucao_id,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Relatórios unificados
# ---------------------------------------------------------------------------

def registrar_relatorio_unificado(
    arquivo_xlsx: Optional[str],
    arquivo_txt: Optional[str],
    secoes: Optional[List[str]] = None,
    total_itens: int = 0,
    resumo: Optional[Dict[str, Any]] = None,
    criado_em: Optional[str] = None,
    origem: str = "app",
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO unified_reports
               (criado_em, arquivo_xlsx, arquivo_txt, secoes, total_itens, resumo, origem)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                criado_em or _now(),
                arquivo_xlsx,
                arquivo_txt,
                json.dumps(secoes or [], ensure_ascii=False),
                total_itens,
                json.dumps(resumo or {}, ensure_ascii=False),
                origem,
            ),
        )


def registrar_unificado_gerado(
    *,
    nome_arquivo: str,
    formato: str,
    secoes: Optional[List[str]] = None,
    total_itens: int = 0,
    execucao_id: Optional[int] = None,
    contagem_por_secao: Optional[Dict[str, Any]] = None,
    origem: str = "app",
) -> None:
    """Registra um relatório unificado recém-gerado, num formato único.

    Antes, cada rota montava o ``resumo`` do seu jeito (uma mandava só
    ``execucao_id``, outra nada), e a tela de Histórico não tinha como
    distinguir um unificado global de um escopado a uma execução. Aqui o
    formato é sempre o mesmo, venha a chamada do escopo global
    (``/api/unificar_relatorio``) ou do escopo por execução
    (``/historico/execucao/<id>/unificar``).
    """
    resumo: Dict[str, Any] = {"escopo": "execucao" if execucao_id else "global"}
    if execucao_id is not None:
        resumo["execucao_id"] = execucao_id
    if contagem_por_secao:
        resumo["contagem_por_secao"] = contagem_por_secao

    registrar_relatorio_unificado(
        arquivo_xlsx=nome_arquivo if formato == "xlsx" else None,
        arquivo_txt=nome_arquivo if formato == "txt" else None,
        secoes=secoes,
        total_itens=total_itens,
        resumo=resumo,
        origem=origem,
    )


def listar_relatorios_unificados(limite: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM unified_reports ORDER BY criado_em DESC LIMIT ?", (limite,)
        ).fetchall()
        resultado = []
        for row in rows:
            item = dict(row)
            item["secoes"] = json.loads(item.get("secoes") or "[]")
            item["resumo"] = json.loads(item.get("resumo") or "{}")
            resultado.append(item)
        return resultado


def remover_relatorios_unificados_por_arquivo(nomes_arquivo) -> int:
    """Remove do índice as entradas cujo arquivo (xlsx ou txt) foi apagado do disco."""
    nomes = list(nomes_arquivo)
    if not nomes:
        return 0
    with get_connection() as conn:
        placeholders = ",".join("?" for _ in nomes)
        cursor = conn.execute(
            f"DELETE FROM unified_reports WHERE arquivo_xlsx IN ({placeholders}) OR arquivo_txt IN ({placeholders})",
            nomes + nomes,
        )
        return cursor.rowcount


def arquivos_ja_indexados() -> set:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT arquivo_xlsx, arquivo_txt FROM unified_reports"
        ).fetchall()
    conhecidos = set()
    for row in rows:
        if row["arquivo_xlsx"]:
            conhecidos.add(row["arquivo_xlsx"])
        if row["arquivo_txt"]:
            conhecidos.add(row["arquivo_txt"])
    return conhecidos


def contar_itens_com_imagem() -> int:
    """Conta quantos itens históricos têm uma imagem associada (usado para avisar antes de limpar imagens)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM report_items WHERE caminho_imagem IS NOT NULL AND caminho_imagem != ''"
        ).fetchone()
        return row["total"]


# ---------------------------------------------------------------------------
# Arquivos já processados (era o logs/log_mestre.txt)
# ---------------------------------------------------------------------------

def registrar_arquivo_processado(nome: str, quando: Optional[str] = None) -> None:
    """Marca um arquivo como processado. Idempotente (o nome é a chave)."""
    if not nome:
        return
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO arquivos_processados (nome, processado_em)
               VALUES (?, ?)
               ON CONFLICT(nome) DO NOTHING""",
            (nome, quando or _now()),
        )


def listar_arquivos_processados() -> set:
    """Conjunto de nomes já processados — a fonte da verdade atual."""
    with get_connection() as conn:
        return {
            row["nome"]
            for row in conn.execute("SELECT nome FROM arquivos_processados")
        }


def limpar_arquivos_processados() -> int:
    """Remove todo o histórico de processados. Devolve quantos saíram."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM arquivos_processados")
        return cursor.rowcount


# ---------------------------------------------------------------------------
# Consumo de tokens (era o logs/log_consumo_tokens.txt)
# ---------------------------------------------------------------------------

def registrar_consumo_log(tokens: int, detalhes: Optional[str] = None,
                          quando: Optional[str] = None) -> None:
    """Grava uma linha do log de consumo (valores já acumulados)."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO consumo_tokens_log (registrado_em, tokens, detalhes)
               VALUES (?, ?, ?)""",
            (quando or _now(), int(tokens or 0), detalhes),
        )


def listar_consumo_log(limite: int = 500) -> List[Dict[str, Any]]:
    """Linhas do log de consumo, mais recentes primeiro."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT registrado_em, tokens, detalhes
               FROM consumo_tokens_log
               ORDER BY id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
    return [dict(r) for r in rows]


def limpar_consumo_log() -> int:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM consumo_tokens_log")
        return cursor.rowcount


def importar_logs_dos_arquivos(log_processados, log_consumo) -> Dict[str, int]:
    """Importa os .txt legados para o banco (idempotente).

    Lê o formato histórico de cada um:
    - processados: "2026-07-23 23:27:36 - Processado: IMG-1.jpg" ou só o nome;
    - consumo:     "2026-07-23 23:27:36 - Tokens consumidos: 1,234 - detalhes".

    Chamado uma vez no boot (ver create_app). Rodar de novo não duplica:
    processados tem chave primária por nome; consumo é importado só se a tabela
    estiver vazia (senão cada boot repetiria o histórico do arquivo).
    """
    importadas_processados = 0
    importadas_consumo = 0

    try:
        if log_processados and log_processados.exists():
            registros = [
                (nome, quando)
                for nome, quando in _ler_nomes_processados(log_processados)
                if nome
            ]
            with get_connection() as conn:
                antes = conn.execute("SELECT COUNT(*) AS n FROM arquivos_processados").fetchone()["n"]
                conn.executemany(
                    """INSERT INTO arquivos_processados (nome, processado_em)
                       VALUES (?, ?)
                       ON CONFLICT(nome) DO NOTHING""",
                    [(nome, quando or _now()) for nome, quando in registros],
                )
                depois = conn.execute("SELECT COUNT(*) AS n FROM arquivos_processados").fetchone()["n"]
                importadas_processados = depois - antes
    except Exception as e:
        print(f"⚠️ Falha ao importar log de processados: {e}")

    try:
        if log_consumo and log_consumo.exists():
            with get_connection() as conn:
                vazio = conn.execute(
                    "SELECT COUNT(*) AS n FROM consumo_tokens_log"
                ).fetchone()["n"] == 0
                if vazio:
                    registros = list(_ler_consumo(log_consumo))
                    conn.executemany(
                        """INSERT INTO consumo_tokens_log (registrado_em, tokens, detalhes)
                           VALUES (?, ?, ?)""",
                        registros,
                    )
                    importadas_consumo = len(registros)
    except Exception as e:
        print(f"⚠️ Falha ao importar log de consumo: {e}")

    return {"processados": importadas_processados, "consumo": importadas_consumo}


def _ler_nomes_processados(caminho) -> List[tuple]:
    """Extrai (nome, quando) do log de processados, preservando a data.

    Aceita o formato atual ("2026-07-23 23:27:36 - Processado: IMG-1.jpg") e o
    legado (só o nome, sem data — aí `quando` fica None). Preservar a data
    importa: sem ela, a estatística de "último processamento" mentiria, dizendo
    que tudo rodou no dia da migração.
    """
    import re

    padrao = re.compile(r"^(?P<quando>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*-\s*Processado:\s*(?P<nome>.+)$")
    registros = []
    with open(caminho, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            m = padrao.match(linha)
            if m:
                registros.append((m.group("nome").strip(), m.group("quando")))
            else:
                # Formato legado: apenas o nome do arquivo, sem data.
                registros.append((linha, None))
    return registros


def _ler_consumo(caminho):
    """Gera (quando, tokens, detalhes) a partir do log de consumo legado."""
    import re

    padrao = re.compile(
        r"^(?P<quando>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*-\s*"
        r"Tokens consumidos:\s*(?P<tokens>[\d.,]+)\s*(?:-\s*(?P<detalhes>.*))?$"
    )
    with open(caminho, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            m = padrao.match(linha)
            if not m:
                continue
            try:
                tokens = int(m.group("tokens").replace(".", "").replace(",", ""))
            except ValueError:
                continue
            yield (m.group("quando"), tokens, m.group("detalhes"))


# ---------------------------------------------------------------------------
# Resumo agregado (para a tela de histórico)
# ---------------------------------------------------------------------------

def resumo_geral() -> Dict[str, Any]:
    """Resumo para a tela de Histórico.

    Duas fontes deliberadamente diferentes:
    - ``total_execucoes``/``total_tokens``/``por_mes`` vêm do banco (são
      métricas de HISTÓRICO de atividade — quantas vezes rodou, quanto
      consumiu — legítimas mesmo somando execuções antigas).
    - ``total_avarias``/``total_uso_interno``/``total_erros``/peso/top
      produtos vêm do Excel mestre atual (ESTADO atual, já deduplicado).
      Somar isso a partir do banco inflaria os números com duplicatas de
      quando uma mesma imagem era reprocessada (bug já corrigido, mas cujo
      histórico de execuções antigas continua no banco de propósito).
    """
    with get_connection() as conn:
        totais_execucao = conn.execute(
            """SELECT
                   COUNT(*) AS total_execucoes,
                   COALESCE(SUM(tokens_consumidos), 0) AS total_tokens
               FROM processing_runs"""
        ).fetchone()
        por_mes = conn.execute(
            """SELECT substr(iniciado_em, 1, 7) AS mes,
                      COUNT(*) AS execucoes,
                      COALESCE(SUM(avarias), 0) AS avarias,
                      COALESCE(SUM(uso_interno), 0) AS uso_interno,
                      COALESCE(SUM(erros), 0) AS erros
               FROM processing_runs
               GROUP BY mes
               ORDER BY mes DESC
               LIMIT 12"""
        ).fetchall()
        total_unificados = conn.execute(
            "SELECT COUNT(*) AS total FROM unified_reports"
        ).fetchone()

    totais_dict = dict(totais_execucao)
    totais_dict.update(
        {"total_avarias": 0, "total_uso_interno": 0, "total_erros": 0, "peso_total_avarias_kg": 0.0}
    )
    top_produtos_avaria: List[Dict[str, Any]] = []

    # Totais do ESTADO atual (não do histórico de atividade): vêm da visão
    # mestre do banco, deduplicada — a mesma que as telas e o export usam.
    # Antes liam o Excel mestre, que podia divergir (o arquivo é só um export).
    from . import mestre  # import tardio: evita ciclo services -> services

    try:
        secoes = mestre.obter_secoes_mestre()
    except Exception as e:
        print(f"⚠️ Não foi possível montar a visão mestre para o resumo: {e}")
        secoes = {}

    linhas_avarias = secoes.get("Avarias", {}).get("dados", [])
    if linhas_avarias:
        totais_dict["total_avarias"] = len(linhas_avarias)
        pesos = (extrair_peso_de_valor(linha.get("Peso")) for linha in linhas_avarias)
        totais_dict["peso_total_avarias_kg"] = round(sum(p for p in pesos if p), 3)

        contagem: Dict[str, int] = {}
        for linha in linhas_avarias:
            nome = str(linha.get("Produto") or "").strip()
            if nome:
                contagem[nome] = contagem.get(nome, 0) + 1
        top_produtos_avaria = [
            {"produto": produto, "ocorrencias": qtd}
            for produto, qtd in sorted(contagem.items(), key=lambda kv: -kv[1])[:5]
        ]

    totais_dict["total_uso_interno"] = len(secoes.get("Uso Interno", {}).get("dados", []))
    totais_dict["total_erros"] = len(secoes.get("Erros de Análise", {}).get("dados", []))

    return {
        "totais": totais_dict,
        "por_mes": [dict(row) for row in por_mes],
        "total_relatorios_unificados": total_unificados["total"],
        "top_produtos_avaria": top_produtos_avaria,
    }


# ---------------------------------------------------------------------------
# Backfill: indexa relatórios unificados que já existem em disco mas ainda
# não foram registrados no banco (histórico anterior à existência do banco).
# ---------------------------------------------------------------------------

def backfill_relatorios_unificados(resultados_dir: Path) -> int:
    import re

    padrao = re.compile(r"Relatorio_Unificado_(\d{8})_(\d{6})\.(xlsx|txt)$")
    encontrados: Dict[str, Dict[str, Any]] = {}

    if not resultados_dir.exists():
        return 0

    for arquivo in resultados_dir.iterdir():
        m = padrao.match(arquivo.name)
        if not m:
            continue
        data, hora, ext = m.groups()
        chave = f"{data}_{hora}"
        registro = encontrados.setdefault(
            chave,
            {
                "criado_em": f"{data[0:4]}-{data[4:6]}-{data[6:8]} {hora[0:2]}:{hora[2:4]}:{hora[4:6]}",
                "arquivo_xlsx": None,
                "arquivo_txt": None,
            },
        )
        registro[f"arquivo_{ext}"] = arquivo.name

    ja_indexados = arquivos_ja_indexados()
    novos = 0
    for registro in encontrados.values():
        if registro["arquivo_xlsx"] in ja_indexados or registro["arquivo_txt"] in ja_indexados:
            continue
        registrar_relatorio_unificado(
            arquivo_xlsx=registro["arquivo_xlsx"],
            arquivo_txt=registro["arquivo_txt"],
            criado_em=registro["criado_em"],
            origem="backfill",
        )
        novos += 1
    return novos
