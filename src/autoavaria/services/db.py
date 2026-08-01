"""
CAMADA DE PERSISTÊNCIA (SQLite)

Guarda o histórico de execuções de processamento, os itens extraídos e o
índice de relatórios unificados gerados. O Excel continua sendo o arquivo
de trabalho/exportação principal — este banco é uma camada adicional que
não substitui nada do fluxo existente, apenas registra o histórico para a
tela de "Histórico de Relatórios".
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.paths import ARQUIVO_SAIDA_EXCEL, DATABASE_DIR, DATABASE_FILE
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
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def buscar_item_por_caminho(
    categoria: str, caminho_imagem: str, valores_atuais: Optional[Dict[str, str]] = None
) -> Optional[int]:
    """Encontra o `report_items.id` correspondente a uma linha do Excel.

    O Excel (editado via routes/edicao.py) não guarda o id do banco — só tem
    posição de linha, que não é estável entre execuções. `categoria +
    caminho_imagem` é a melhor chave disponível para correlacionar as duas
    fontes, mas uma foto pode gerar mais de um item (ex.: "2 alface, 4
    coentro" na mesma imagem), o que tornaria essa chave ambígua sozinha.

    Por isso: se houver mais de uma linha com a mesma categoria+caminho,
    `valores_atuais` (o restante da linha, ANTES da edição) é usado para
    desempatar - só retorna um id quando exatamente uma linha bate com todos
    os valores informados. Se não for possível identificar com segurança
    qual linha é, devolve None e o chamador simplesmente não sincroniza essa
    edição com o banco (a gravação no Excel, que é a fonte principal,
    continua acontecendo normalmente).
    """
    if not caminho_imagem:
        return None
    with get_connection() as conn:
        linhas = conn.execute(
            "SELECT * FROM report_items WHERE categoria = ? AND caminho_imagem = ?",
            (categoria, caminho_imagem),
        ).fetchall()

    if not linhas:
        return None
    if len(linhas) == 1:
        return linhas[0]["id"]

    if not valores_atuais:
        return None

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

    return candidatas[0] if len(candidatas) == 1 else None


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

    if ARQUIVO_SAIDA_EXCEL.exists():
        from .report_editing import carregar_todas_sheets  # import tardio: evita ciclo services -> services

        try:
            sheets = carregar_todas_sheets(str(ARQUIVO_SAIDA_EXCEL))
        except Exception as e:
            print(f"⚠️ Não foi possível ler o Excel mestre para o resumo do histórico: {e}")
            sheets = {}

        df_avarias = sheets.get("Avarias")
        if df_avarias is not None and not df_avarias.empty:
            totais_dict["total_avarias"] = len(df_avarias)
            if "Peso" in df_avarias.columns:
                pesos = (extrair_peso_de_valor(v) for v in df_avarias["Peso"])
                totais_dict["peso_total_avarias_kg"] = round(sum(p for p in pesos if p), 3)
            if "Produto" in df_avarias.columns:
                contagem = df_avarias["Produto"].value_counts().head(5)
                top_produtos_avaria = [
                    {"produto": produto, "ocorrencias": int(qtd)} for produto, qtd in contagem.items()
                ]

        df_uso = sheets.get("Uso Interno")
        if df_uso is not None:
            totais_dict["total_uso_interno"] = len(df_uso)

        df_erros = sheets.get("Erros de Análise")
        if df_erros is not None:
            totais_dict["total_erros"] = len(df_erros)

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
