"""
Exportação (Excel/TXT) e unificação de dados de UMA execução específica do
Histórico. Diferente do relatório mestre (arquivo único, sempre mesclado),
cada chamada aqui gera um arquivo novo e independente contendo só os itens
daquela execução — os dados vêm do banco (services/db.py), não do Excel.
"""

from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd

from ..core.paths import RESULTADOS_DIR
from .excel_report import salvar_relatorio_excel
from .export_service import (
    escrever_txt_compacto,
    escrever_txt_detalhado,
    escrever_xlsx,
    filtrar_colunas,
    renderizar_txt_compacto,
)
from .unification import renderizar_secciones_como_texto, unificar_itens_avarias, unificar_itens_uso_interno


def _listas_por_categoria(dados_por_categoria: Dict) -> Tuple[list, list, list]:
    avarias = dados_por_categoria.get("Avarias", {}).get("dados", [])
    uso_interno = dados_por_categoria.get("Uso Interno", {}).get("dados", [])
    erros = dados_por_categoria.get("Erros de Análise", {}).get("dados", [])
    return avarias, uso_interno, erros


# Colunas que existem só para a interface (não são dado do produto) e não
# devem aparecer no arquivo gerado nem influenciar a unificação.
_COLUNAS_INTERNAS = ("id_linha",)


def _unificar_sem_colunas_internas(linhas, funcao_unificacao):
    """Aplica `funcao_unificacao` a `linhas` (dicts) descartando colunas internas.

    Chamar `funcao_unificacao(pd.DataFrame(linhas))` passava `id_linha` adiante:
    o registro consolidado herdava o id de um item qualquer do grupo (o
    primeiro), e a coluna técnica ia parar no Excel unificado. Aqui os dicts
    são limpos antes; sem linhas, devolve DataFrame vazio (mesmo contrato de
    antes, quando a lista estava vazia).
    """
    if not linhas:
        return pd.DataFrame()
    limpas = [
        {k: v for k, v in linha.items() if k not in _COLUNAS_INTERNAS}
        for linha in linhas
    ]
    return funcao_unificacao(pd.DataFrame(limpas))[0]


def gerar_excel_execucao(run_id: int, dados_por_categoria: Dict) -> str:
    """Gera um Excel novo (não mescla com o mestre) só com os itens desta execução."""
    avarias, uso_interno, erros = _listas_por_categoria(dados_por_categoria)
    nome_arquivo = f"Historico_Execucao_{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    caminho = str(RESULTADOS_DIR / nome_arquivo)
    salvar_relatorio_excel(caminho, avarias, uso_interno, erros)
    return nome_arquivo


def gerar_txt_execucao(run_id: int, dados_por_categoria: Dict) -> str:
    """Gera um TXT com os itens desta execução, no mesmo formato usado no
    export do relatório mestre (services/export_service.escrever_txt_detalhado)."""
    nome_arquivo = f"Historico_Execucao_{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    caminho = str(RESULTADOS_DIR / nome_arquivo)

    secoes = {
        categoria: pd.DataFrame(sheet.get("dados", []))
        for categoria, sheet in dados_por_categoria.items()
        if sheet.get("dados")
    }
    escrever_txt_detalhado(caminho, f"HISTÓRICO DE EXECUÇÃO #{run_id}", secoes)
    return nome_arquivo


def montar_secoes_unificadas(
    dados_por_categoria: Dict,
    formato: str = "xlsx",
    secoes: Optional[list] = None,
    colunas: Optional[Dict] = None,
) -> Dict[str, pd.DataFrame]:
    """Monta as seções unificadas de uma execução, aplicando o recorte pedido.

    ``secoes=None`` mantém o comportamento histórico: Avarias + Uso Interno
    (as únicas unificáveis), sem Erros. Quando ``secoes`` é informado, só as
    seções listadas entram; no xlsx, "Erros de Análise" também pode entrar
    (cru, sem unificação — não faz sentido consolidar erros).

    Devolve ``{nome_secao: DataFrame}``; vazio significa que a seleção não
    produziu nada (quem chama decide como sinalizar).
    """
    avarias = dados_por_categoria.get("Avarias", {}).get("dados", [])
    uso_interno = dados_por_categoria.get("Uso Interno", {}).get("dados", [])
    erros = dados_por_categoria.get("Erros de Análise", {}).get("dados", [])

    selecionadas = set(secoes) if secoes else None
    colunas = colunas or {}
    secoes_saida: Dict[str, pd.DataFrame] = {}

    if (selecionadas is None or "Avarias" in selecionadas) and avarias:
        df = _unificar_sem_colunas_internas(avarias, unificar_itens_avarias)
        df = filtrar_colunas(df, colunas.get("Avarias"))
        if not df.empty:
            secoes_saida["Avarias"] = df

    if (selecionadas is None or "Uso Interno" in selecionadas) and uso_interno:
        df = _unificar_sem_colunas_internas(uso_interno, unificar_itens_uso_interno)
        df = filtrar_colunas(df, colunas.get("Uso Interno"))
        if not df.empty:
            secoes_saida["Uso Interno"] = df

    if (
        formato == "xlsx"
        and selecionadas is not None
        and "Erros de Análise" in selecionadas
        and erros
    ):
        df_erros = pd.DataFrame(erros)
        df_erros = filtrar_colunas(df_erros, colunas.get("Erros de Análise"))
        if not df_erros.empty:
            secoes_saida["Erros de Análise"] = df_erros

    return secoes_saida


def gerar_unificado_execucao(
    run_id: int,
    dados_por_categoria: Dict,
    formato: str = "xlsx",
    return_contenido: bool = False,
    secoes: Optional[list] = None,
    colunas: Optional[Dict] = None,
) -> Tuple[str, int, Optional[str]]:
    """Gera um relatório unificado (Avarias + Uso Interno) escopado a esta execução.

    Com ``secoes``/``colunas``, respeita o recorte escolhido no modal (o mesmo
    contrato da unificação do mestre). No formato txt, apenas Avarias/Uso
    Interno entram (o compacto não comporta blocos de erro). Se a seleção não
    produzir nenhuma linha, levanta ``ValueError`` — quem chama devolve 400 em
    vez de gravar um arquivo vazio.

    Retorna (nome_archivo, total_itens_unificados[, contenido]). O nome do
    arquivo começa com "Relatorio_Unificado_" de propósito, para reaproveitar a
    rota de download já existente (``download_relatorio_unificado``).
    """
    secoes_saida = montar_secoes_unificadas(dados_por_categoria, formato, secoes, colunas)

    if formato == "txt":
        secoes_saida = {
            nome: df
            for nome, df in secoes_saida.items()
            if nome in ("Avarias", "Uso Interno")
        }

    if not secoes_saida:
        raise ValueError("Nada para unificar: as seções selecionadas estão vazias.")

    total_itens = sum(len(df) for df in secoes_saida.values())

    nome_arquivo = f"Relatorio_Unificado_Execucao{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{formato}"
    caminho = str(RESULTADOS_DIR / nome_arquivo)

    titulo = f"RELATÓRIO UNIFICADO - EXECUÇÃO #{run_id}"
    if formato == "txt":
        escrever_txt_compacto(caminho, titulo, secoes_saida)
    else:
        escrever_xlsx(caminho, secoes_saida)

    contenido = None
    if return_contenido:
        contenido = (
            renderizar_txt_compacto(titulo, secoes_saida)
            if formato == "txt"
            else renderizar_secciones_como_texto(secoes_saida)
        )
    return nome_arquivo, total_itens, contenido
