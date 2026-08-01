"""
MONTAGEM DA VISÃO DE RELATÓRIO A PARTIR DO BANCO (itens de uma execução)

Agrupa os itens de uma execução (`report_items`, ver services/db.py) no
mesmo formato ``{categoria: {colunas, dados, total}}`` usado pela tela de
Relatório (routes/relatorio.py) e pela tela de detalhe de execução do
Histórico (routes/historico.py) - extraído para um único lugar para as duas
telas nunca divergirem sobre como uma execução é exibida.
"""

from typing import Any, Dict, List

_COLUNAS_POR_CATEGORIA = {
    "Avarias": ["Produto", "Quantidade", "Peso", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
    "Uso Interno": ["Produto", "Quantidade", "Marca", "Código de Barras", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
    "Erros de Análise": ["Arquivo", "Detalhes do Erro", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"],
}
_ORDEM_CATEGORIAS = ["Avarias", "Uso Interno", "Erros de Análise"]


def _construir_registro(categoria: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Monta o dict de exibição de um item, no formato de colunas da categoria."""
    if categoria == "Avarias":
        campos = {"Produto": item["produto"], "Quantidade": item["quantidade"], "Peso": item["peso"]}
    elif categoria == "Uso Interno":
        campos = {
            "Produto": item["produto"],
            "Quantidade": item["quantidade"],
            "Marca": item["marca"],
            "Código de Barras": item["codigo_barras"],
        }
    elif categoria == "Erros de Análise":
        campos = {"Arquivo": item["produto"], "Detalhes do Erro": item["detalhes"]}
    else:
        campos = {"Produto": item["produto"], "Detalhes": item["detalhes"]}

    return {
        "id_linha": item["id"],
        **campos,
        "Observação da Mensagem": item["observacao_mensagem"],
        "Caminho da Imagem": item["caminho_imagem"],
        "Ver Imagem": item["caminho_imagem"],
    }


def _construir_dados_relatorio(itens: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrupa os itens de uma execução por categoria no formato da página de Relatório."""
    agrupado: Dict[str, List[Dict[str, Any]]] = {}
    for item in itens:
        agrupado.setdefault(item["categoria"], []).append(item)

    dados = {}
    categorias_ordenadas = _ORDEM_CATEGORIAS + [c for c in agrupado if c not in _ORDEM_CATEGORIAS]
    for categoria in categorias_ordenadas:
        registros_brutos = agrupado.get(categoria)
        if not registros_brutos:
            continue

        registros = [_construir_registro(categoria, item) for item in registros_brutos]

        colunas_padrao = ["Produto", "Detalhes", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
        dados[categoria] = {
            "colunas": _COLUNAS_POR_CATEGORIA.get(categoria, colunas_padrao),
            "dados": registros,
            "total": len(registros),
        }
    return dados
