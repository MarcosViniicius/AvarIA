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
from .export_service import escrever_txt_compacto, escrever_txt_detalhado, escrever_xlsx
from .unification import unificar_itens_avarias, unificar_itens_uso_interno


def _listas_por_categoria(dados_por_categoria: Dict) -> Tuple[list, list, list]:
    avarias = dados_por_categoria.get("Avarias", {}).get("dados", [])
    uso_interno = dados_por_categoria.get("Uso Interno", {}).get("dados", [])
    erros = dados_por_categoria.get("Erros de Análise", {}).get("dados", [])
    return avarias, uso_interno, erros


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


def gerar_unificado_execucao(run_id: int, dados_por_categoria: Dict, formato: str = "xlsx") -> Tuple[str, int]:
    """Gera um relatório unificado (Avarias + Uso Interno) escopado a esta execução.

    Retorna (nome_arquivo, total_itens_unificados). O nome do arquivo começa
    com "Relatorio_Unificado_" de propósito, para reaproveitar a rota de
    download já existente (``download_relatorio_unificado``).
    """
    avarias = dados_por_categoria.get("Avarias", {}).get("dados", [])
    uso_interno = dados_por_categoria.get("Uso Interno", {}).get("dados", [])

    df_avarias_unif = unificar_itens_avarias(pd.DataFrame(avarias))[0] if avarias else pd.DataFrame()
    df_uso_unif = unificar_itens_uso_interno(pd.DataFrame(uso_interno))[0] if uso_interno else pd.DataFrame()
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

    return nome_arquivo, total_itens
