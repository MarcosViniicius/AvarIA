"""
RELATÓRIO MESTRE A PARTIR DO BANCO

O "Excel mestre" era a FONTE da verdade: o pipeline escrevia nele, as telas de
edição liam e gravavam nele, e o banco guardava uma cópia. Isso criava dois
problemas:

1. **Divergência.** As duas fontes podiam discordar — e discordavam: medido no
   acervo real, o banco tinha 12 avarias e 166 itens de Uso Interno que o Excel
   não tinha (itens de execuções cuja escrita no arquivo se perdeu).
2. **Custo.** Toda leitura para exibir/exportar exigia abrir e parsear um .xlsx.

Agora o SQLite é a fonte e este módulo monta a visão "mestre" sob demanda:
todas as execuções, deduplicadas, no formato que as telas e a exportação
esperam. O .xlsx passa a ser gerado SÓ quando alguém pede para baixar.

Chave de deduplicação (por categoria, definida em `_chave_dedup`):
- **Avarias**: produto + peso + imagem. O mesmo produto pesado na mesma foto,
  vindo de duas execuções, é a mesma linha.
- **Uso Interno**: produto + código de barras + imagem. Aqui o peso é "N/A" por
  natureza (item de estoque), então não entra na chave.
- **Erros de Análise**: arquivo + detalhe + imagem.

A ordem de leitura é a REAL: itens de execuções mais recentes têm precedência
na dedup (o primeiro encontrado vence), para uma correção posterior aparecer no
lugar da versão antiga.
"""

from typing import Any, Dict, List

from . import db

# Mantido igual a relatorio_view._COLUNAS_POR_CATEGORIA para as telas e o export
# usarem exatamente as mesmas colunas.
COLUNAS_POR_CATEGORIA = {
    "Avarias": ["Produto", "Quantidade", "Peso", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
    "Uso Interno": ["Produto", "Quantidade", "Marca", "Código de Barras", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
    "Erros de Análise": ["Arquivo", "Detalhes do Erro", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
}
ORDEM_CATEGORIAS = ["Avarias", "Uso Interno", "Erros de Análise"]


def _chave_dedup(categoria: str, item: Dict[str, Any]) -> tuple:
    """Chave que identifica uma linha "igual" dentro da categoria.

    Normaliza o que o usuário vê como igual: espaços e o separador decimal do
    peso (o banco tem "1.856kg" de execuções antigas e "1,856kg" das novas).
    """
    produto = str(item.get("produto") or "").strip().lower()

    if categoria == "Uso Interno":
        return (produto, str(item.get("codigo_barras") or "").strip(), str(item.get("caminho_imagem") or ""))

    if categoria == "Erros de Análise":
        return (
            str(item.get("detalhes") or "").strip(),
            str(item.get("caminho_imagem") or ""),
        )

    peso = str(item.get("peso") or "").strip().lower().replace(" ", "")
    # "1.856kg" e "1,856kg" são o mesmo peso.
    peso_normalizado = peso.replace(".", ",")
    return (produto, peso_normalizado, str(item.get("caminho_imagem") or ""))


def _linha(categoria: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Converte uma linha de `report_items` para o formato de exibição.

    Inclui ``id_linha`` (o id do item no banco) para a tela de Editar Dados
    conseguir se referir à linha ao salvar. As exportações montam os
    dataframes com colunas explícitas (COLUNAS_POR_CATEGORIA), então esse
    campo auxiliar não vaza para o arquivo gerado.
    """
    caminho = item.get("caminho_imagem")
    base = {"id_linha": item.get("id")}
    if categoria == "Erros de Análise":
        base.update({
            "Arquivo": item.get("produto"),
            "Detalhes do Erro": item.get("detalhes"),
            "Observação da Mensagem": item.get("observacao_mensagem"),
            "Caminho da Imagem": caminho,
            "Ver Imagem": caminho,
        })
    elif categoria == "Uso Interno":
        base.update({
            "Produto": item.get("produto"),
            "Quantidade": item.get("quantidade"),
            "Marca": item.get("marca"),
            "Código de Barras": item.get("codigo_barras"),
            "Observação da Mensagem": item.get("observacao_mensagem"),
            "Caminho da Imagem": caminho,
            "Ver Imagem": caminho,
        })
    else:
        base.update({
            "Produto": item.get("produto"),
            "Quantidade": item.get("quantidade"),
            "Peso": item.get("peso"),
            "Observação da Mensagem": item.get("observacao_mensagem"),
            "Caminho da Imagem": caminho,
            "Ver Imagem": caminho,
        })
    return base


def obter_secoes_mestre() -> Dict[str, Any]:
    """Visão mestre (todas as execuções, deduplicada) no formato das telas.

    Devolve ``{categoria: {"colunas": [...], "dados": [...], "total": n}}`` —
    o mesmo contrato de `relatorio_view._construir_dados_relatorio`, para ser
    intercambiável.
    """
    itens = db.listar_todos_itens()

    vistas: Dict[tuple, Dict[str, Any]] = {}
    for item in itens:
        categoria = item.get("categoria")
        if not categoria:
            continue
        # A categoria entra na chave: sem o prefixo, uma linha de "Avarias" e
        # outra de "Uso Interno" com o mesmo produto/peso-vazio/imagem colidiam
        # e uma delas era descartada (contar_por_categoria já prefixa).
        chave = (categoria,) + _chave_dedup(categoria, item)
        if chave in vistas:
            continue  # já entrou uma versão (a mais recente, pela ordem)
        vistas[chave] = item

    agrupado: Dict[str, List[Dict[str, Any]]] = {}
    for item in vistas.values():
        agrupado.setdefault(item["categoria"], []).append(_linha(item["categoria"], item))

    secoes: Dict[str, Any] = {}
    categorias = ORDEM_CATEGORIAS + [c for c in agrupado if c not in ORDEM_CATEGORIAS]
    for categoria in categorias:
        registros = agrupado.get(categoria)
        if not registros:
            continue
        secoes[categoria] = {
            "colunas": COLUNAS_POR_CATEGORIA.get(categoria, []),
            "dados": registros,
            "total": len(registros),
        }
    return secoes


def obter_sheets_mestre() -> "Dict[str, Any]":
    """Visão mestre como ``{categoria: pandas.DataFrame}``.

    Mesmo formato de `report_editing.carregar_todas_sheets` (que lia o Excel
    mestre), para as rotas de exportação continuarem funcionando sem tocar em
    arquivo: elas só trocam de onde as sheets vêm. As colunas já saem na ordem
    de exibição de cada categoria.
    """
    import pandas as pd

    secoes = obter_secoes_mestre()
    sheets = {}
    for categoria, info in secoes.items():
        colunas = info["colunas"]
        sheets[categoria] = pd.DataFrame(info["dados"], columns=colunas)
    return sheets


def contar_por_categoria() -> Dict[str, int]:
    """Número de linhas por categoria na visão mestre (para os painéis).

    Mais barato que `obter_secoes_mestre` quando só a contagem interessa (o
    resumo do histórico e a aba Dados não precisam montar as linhas).
    """
    contagem: Dict[str, int] = {}
    vistas = set()
    for item in db.listar_todos_itens():
        categoria = item.get("categoria")
        if not categoria:
            continue
        chave = (categoria,) + _chave_dedup(categoria, item)
        if chave in vistas:
            continue
        vistas.add(chave)
        contagem[categoria] = contagem.get(categoria, 0) + 1
    return contagem
