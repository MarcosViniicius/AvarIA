"""
CATÁLOGO DE PRODUTOS (tradução código → produto)

O leitor de código de barras (`services/barcode.py`) devolve números. Este
módulo traduz esses números em produto e peso — que é o que o relatório
precisa (o app não trata preço como dado de interesse; ele só aparece aqui
como conta interna, ver abaixo).

Dois tipos de entrada:

* ``ean`` — código de barras do produto industrializado. Guarda nome e marca.
* ``plu`` — código interno da balança. A etiqueta só codifica o VALOR TOTAL,
  não o peso, então guardamos ``preco_kg`` como um fator de conversão interno
  (peso = total ÷ preco_kg). Isso nunca é exibido ao usuário nem vira coluna
  de relatório — existe só para permitir calcular o peso sem IA.

O catálogo **se preenche sozinho**: toda vez que a IA analisa uma imagem cujo
código de barras também foi lido, o par (código → produto/peso) é aprendido
aqui. Quanto mais o modo híbrido roda, mais o modo sem IA consegue resolver
sozinho. Ver `aprender()` e `popular_do_historico()`.

Duas salvaguardas contra dado ruim entrando no catálogo:

* **Plausibilidade** — um peso implausível (ex.: IA "vendo" 50kg num tomate)
  não é aprendido; vai para a fila de revisão (`catalogo_revisoes`) em vez de
  corromper o cálculo de todo mundo que usar aquele código depois.
* **Expiração** — o preço por quilo de um produto muda com o tempo (já vimos
  cenoura a R$10,99 e R$7,99 no mesmo histórico). Uma entrada não é confiada
  para sempre: depois de `DIAS_PARA_REVERIFICAR_PADRAO` dias sem confirmação
  da IA, o modo híbrido volta a consultá-la. Ver `esta_desatualizado()`.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from . import db

# Peso plausível para um único item de balança. Fora dessa faixa, o peso
# calculado provavelmente veio de uma leitura ruim da IA (ou de um preço/kg
# desatualizado) e não deve ser aprendido no catálogo.
PESO_KG_MINIMO = 0.02   # 20g - menor unidade razoável (ex.: tempero, alho)
PESO_KG_MAXIMO = 30.0   # 30kg - maior peso razoável para um item de balança

# Depois de tantos dias sem a IA reconfirmar, uma entrada de balança é
# considerada desatualizada e volta a ser enviada para a IA no modo híbrido,
# mesmo já tendo um preço/kg aprendido - preço muda, e sem isso o peso
# calculado ficaria errado silenciosamente para sempre.
DIAS_PARA_REVERIFICAR_PADRAO = 30

# Valores que a IA usa para "não sei" e que não devem virar entrada de catálogo.
_VALORES_VAZIOS = {"", "n/a", "na", "none", "null", "nan", "nenhuma", "nenhum", "-"}


def _limpo(valor: Any) -> str:
    """Normaliza um valor vindo da IA/planilha, devolvendo '' quando é vazio."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() in _VALORES_VAZIOS else texto


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------


def buscar(codigo: str) -> Optional[Dict[str, Any]]:
    """Busca uma entrada do catálogo pelo código (EAN ou PLU)."""
    codigo = _limpo(codigo)
    if not codigo:
        return None
    with db.get_connection() as conn:
        linha = conn.execute(
            "SELECT * FROM catalogo_produtos WHERE codigo = ?", (codigo,)
        ).fetchone()
    return dict(linha) if linha else None


def listar(tipo: Optional[str] = None, limite: int = 500) -> List[Dict[str, Any]]:
    """Lista entradas do catálogo, opcionalmente filtrando por tipo."""
    with db.get_connection() as conn:
        if tipo:
            linhas = conn.execute(
                """SELECT * FROM catalogo_produtos WHERE tipo = ?
                   ORDER BY vezes_visto DESC, produto ASC LIMIT ?""",
                (tipo, limite),
            ).fetchall()
        else:
            linhas = conn.execute(
                """SELECT * FROM catalogo_produtos
                   ORDER BY vezes_visto DESC, produto ASC LIMIT ?""",
                (limite,),
            ).fetchall()
    return [dict(l) for l in linhas]


def contar() -> Dict[str, int]:
    """Conta entradas por tipo (para exibir na tela de configurações)."""
    with db.get_connection() as conn:
        linhas = conn.execute(
            "SELECT tipo, COUNT(*) AS total FROM catalogo_produtos GROUP BY tipo"
        ).fetchall()
    contagem = {linha["tipo"]: linha["total"] for linha in linhas}
    contagem["total"] = sum(contagem.values())
    return contagem


# ---------------------------------------------------------------------------
# Escrita / aprendizado
# ---------------------------------------------------------------------------


def registrar(
    codigo: str,
    produto: str = "",
    marca: str = "",
    preco_kg: Optional[float] = None,
    categoria_padrao: str = "",
    tipo: str = "",
    origem: str = "manual",
) -> bool:
    """Insere ou atualiza uma entrada do catálogo.

    Atualização é **não destrutiva**: um campo novo vazio nunca apaga um
    valor que já estava preenchido. Assim uma leitura ruim posterior não
    estraga uma entrada boa registrada antes.
    """
    codigo = _limpo(codigo)
    if not codigo:
        return False

    produto = _limpo(produto)
    marca = _limpo(marca)
    categoria_padrao = _limpo(categoria_padrao)
    tipo = _limpo(tipo) or _inferir_tipo(codigo)

    atual = buscar(codigo)
    agora = db._now()

    if atual is None:
        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO catalogo_produtos
                   (codigo, tipo, produto, marca, preco_kg, categoria_padrao,
                    origem, vezes_visto, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (codigo, tipo, produto, marca, preco_kg, categoria_padrao, origem, agora),
            )
        return True

    with db.get_connection() as conn:
        conn.execute(
            """UPDATE catalogo_produtos SET
                   produto = ?, marca = ?, preco_kg = ?, categoria_padrao = ?,
                   vezes_visto = vezes_visto + 1, atualizado_em = ?
               WHERE codigo = ?""",
            (
                produto or atual["produto"],
                marca or atual["marca"],
                preco_kg if preco_kg is not None else atual["preco_kg"],
                categoria_padrao or atual["categoria_padrao"],
                agora,
                codigo,
            ),
        )
    return True


def _inferir_tipo(codigo: str) -> str:
    """PLU tem 5 dígitos; EAN-13 tem 13."""
    return "plu" if len(codigo) == 5 else "ean"


def aprender(
    codigo: str,
    produto: str = "",
    marca: str = "",
    categoria: str = "",
    preco_kg: Optional[float] = None,
) -> bool:
    """Aprende uma associação código → produto a partir de um resultado de IA.

    Chamado pelo motor híbrido: quando a IA analisa uma imagem e o código de
    barras também foi lido, guardamos o par para que na próxima vez o modo
    sem IA resolva sozinho, de graça.
    """
    if not _limpo(produto) and preco_kg is None:
        return False  # nada de útil para guardar
    return registrar(
        codigo=codigo,
        produto=produto,
        marca=marca,
        preco_kg=preco_kg,
        categoria_padrao=categoria,
        origem="ia",
    )


def aprender_preco_kg(plu: str, produto: str, total_reais: float, peso_kg: float) -> bool:
    """Deriva e guarda o fator de conversão (preço/kg) de um PLU a partir de um
    par (peso, total) confiável — normalmente o peso que a IA acabou de ler.

    Valida o PESO (não o preço) contra uma faixa plausível antes de aprender:
    é o peso que o app entrega no relatório, então é ele que precisa ser
    correto. Um peso implausível quase sempre indica que a IA leu errado a
    etiqueta - aprender esse valor propagaria o erro para toda leitura futura
    daquele PLU. Nesses casos o par vai para a fila de revisão em vez de
    silenciosamente ser aceito ou descartado.
    """
    if not peso_kg or peso_kg <= 0 or not total_reais or total_reais <= 0:
        return False

    if not (PESO_KG_MINIMO <= peso_kg <= PESO_KG_MAXIMO):
        propor_revisao(
            codigo=plu,
            produto=produto,
            peso_kg_proposto=peso_kg,
            motivo=(
                f"Peso {peso_kg:.3f}kg fora da faixa plausível "
                f"({PESO_KG_MINIMO}kg–{PESO_KG_MAXIMO}kg) para um item de balança."
            ),
        )
        return False

    preco = round(total_reais / peso_kg, 2)
    return registrar(
        codigo=plu,
        produto=produto,
        preco_kg=preco,
        categoria_padrao="Avarias",
        tipo="plu",
        origem="ia",
    )


def esta_desatualizado(atualizado_em: Optional[str], dias: int = DIAS_PARA_REVERIFICAR_PADRAO) -> bool:
    """True se a entrada não é confirmada pela IA há mais de `dias` dias.

    Usado pelo motor híbrido para decidir se um PLU já resolvido localmente
    ainda merece confiança ou se é hora de reconsultar a IA - protege contra
    preço desatualizado (a etiqueta não avisa quando o preço/kg mudou).
    """
    if not atualizado_em:
        return True
    try:
        ultima_confirmacao = datetime.strptime(atualizado_em, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True
    return (datetime.now() - ultima_confirmacao) > timedelta(days=dias)


# ---------------------------------------------------------------------------
# Fila de revisão (pesos implausíveis)
# ---------------------------------------------------------------------------


def propor_revisao(codigo: str, produto: str, peso_kg_proposto: float, motivo: str, tipo: str = "plu") -> None:
    """Registra um peso implausível para revisão manual, sem aplicá-lo ao catálogo."""
    agora = db._now()
    with db.get_connection() as conn:
        existente = conn.execute(
            "SELECT id FROM catalogo_revisoes WHERE codigo = ?", (codigo,)
        ).fetchone()
        if existente:
            conn.execute(
                """UPDATE catalogo_revisoes
                   SET produto = ?, peso_kg_proposto = ?, motivo = ?, criado_em = ?
                   WHERE id = ?""",
                (produto, peso_kg_proposto, motivo, agora, existente["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO catalogo_revisoes
                   (codigo, tipo, produto, peso_kg_proposto, motivo, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (codigo, tipo, produto, peso_kg_proposto, motivo, agora),
            )
    print(f"⚠️ Peso implausível para {codigo} ({produto}): {motivo} — não aprendido no catálogo.")


def listar_revisoes_pendentes() -> List[Dict[str, Any]]:
    """Lista os pesos implausíveis ainda não revisados manualmente."""
    with db.get_connection() as conn:
        linhas = conn.execute(
            "SELECT * FROM catalogo_revisoes ORDER BY criado_em DESC"
        ).fetchall()
    return [dict(l) for l in linhas]


# ---------------------------------------------------------------------------
# Carga inicial a partir do histórico já existente
# ---------------------------------------------------------------------------


def popular_do_historico() -> Dict[str, int]:
    """Preenche o catálogo com o que a IA já extraiu em execuções anteriores.

    Evita que o modo sem IA comece do zero: o banco já tem centenas de itens
    analisados, e cada um com código de barras vira uma entrada de catálogo.
    Idempotente — pode rodar quantas vezes quiser.
    """
    inseridos_ean = 0
    with db.get_connection() as conn:
        linhas = conn.execute(
            """SELECT produto, marca, codigo_barras, categoria
               FROM report_items
               WHERE codigo_barras IS NOT NULL AND TRIM(codigo_barras) <> ''"""
        ).fetchall()

    for linha in linhas:
        codigo = _limpo(linha["codigo_barras"])
        # Só aceitamos códigos válidos: o histórico veio da IA e sabidamente
        # contém códigos com dígito trocado, que não devem poluir o catálogo.
        from .barcode import ean13_valido

        if not ean13_valido(codigo):
            continue
        if registrar(
            codigo=codigo,
            produto=linha["produto"] or "",
            marca=linha["marca"] or "",
            categoria_padrao=linha["categoria"] or "",
            tipo="ean",
            origem="historico",
        ):
            inseridos_ean += 1

    return {"ean": inseridos_ean, "total": contar().get("total", 0)}
