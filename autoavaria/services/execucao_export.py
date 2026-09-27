"""
Exportação (Excel/TXT) e unificação de dados de UMA execução específica do
Histórico. Diferente do relatório mestre (arquivo único, sempre mesclado),
cada chamada aqui gera um arquivo novo e independente contendo só os itens
daquela execução — os dados vêm do banco (services/db.py), não do Excel.
"""

from datetime import datetime
from typing import Dict, Tuple

import pandas as pd

from ..core.paths import RESULTADOS_DIR
from .excel_report import salvar_relatorio_excel
from .export_service import (
    escrever_txt_compacto,
    escrever_txt_detalhado,
    escrever_xlsx,
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


def gerar_unificado_execucao(run_id: int, dados_por_categoria: Dict, formato: str = "xlsx", return_contenido: bool = False) -> Tuple[str, int]:
    """Gera um relatório unificado (Avarias + Uso Interno) escopado a esta execução.

    Retorna (nome_archivo, total_itens_unificados). O nome do archivo começa
    com "Relatorio_Unificado_" de propósito, para reaproveitar a rota de
    download já existente (``download_relatorio_unificado``).

    Si ``return_contenido=True``, añade un tercer elemento com el texto
    visible de lo generado (para mostrar/copiar en pantalla).
    """
    avarias = dados_por_categoria.get("Avarias", {}).get("dados", [])
    uso_interno = dados_por_categoria.get("Uso Interno", {}).get("dados", [])

    # `id_linha` é técnica: identifica o item no banco para a tela de Histórico
    # editar/excluir (ver services/relatorio_view.py). Num relatório de
    # auditoria ela não tem sentido e, ao consolidar um grupo, acabava fixando
    # o id de UM item arbitrário do grupo como se fosse o do produto unificado.
    df_avarias_unif = _unificar_sem_colunas_internas(avarias, unificar_itens_avarias)
    df_uso_unif = _unificar_sem_colunas_internas(uso_interno, unificar_itens_uso_interno)
    total_itens = len(df_avarias_unif) + len(df_uso_unif)

    nome_arquivo = f"Relatorio_Unificado_Execucao{run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{formato}"
    caminho = str(RESULTADOS_DIR / nome_arquivo)

    secoes = {}
    if not df_avarias_unif.empty:
        secoes["Avarias"] = df_avarias_unif
    if not df_uso_unif.empty:
        secoes["Uso Interno"] = df_uso_unif

    titulo = f"RELATÓRIO UNIFICADO - EXECUÇÃO #{run_id}"
    if formato == "txt":
        escrever_txt_compacto(caminho, titulo, secoes)
    else:
        escrever_xlsx(caminho, secoes or {"Sem Dados": pd.DataFrame()})

    if return_contenido:
        contenido = (
            renderizar_txt_compacto(titulo, secoes)
            if formato == "txt"
            else renderizar_secciones_como_texto(secoes)
        )
        return nome_arquivo, total_itens, contenido
    return nome_arquivo, total_itens
