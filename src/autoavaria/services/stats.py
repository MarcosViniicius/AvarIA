"""
Estatísticas e resultados recentes usados pelo dashboard (`/`, `/api/stats`).

Importa os caminhos diretamente de ``autoavaria.core.paths`` (em vez de
``autoavaria.routes.context``) para não criar uma dependência de services ->
routes.
"""

import os
from datetime import datetime

import pandas as pd

from .report_editing import carregar_todas_sheets
from ..core.paths import (
    UPLOAD_FOLDER as UPLOAD_FOLDER_PATH,
    LOG_PROCESSADOS_FILE as LOG_PROCESSADOS_FILE_PATH,
    LOG_CONSUMO_FILE as LOG_CONSUMO_FILE_PATH,
    ARQUIVO_SAIDA_EXCEL as ARQUIVO_SAIDA_EXCEL_PATH,
)

DIRETORIO_IMAGENS = str(UPLOAD_FOLDER_PATH)
LOG_PROCESSADOS_FILE = str(LOG_PROCESSADOS_FILE_PATH)
LOG_CONSUMO_FILE = str(LOG_CONSUMO_FILE_PATH)
ARQUIVO_SAIDA_EXCEL = str(ARQUIVO_SAIDA_EXCEL_PATH)
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")


def carregar_logs_processados():
    """Carrega os logs de arquivos já processados."""
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return set()
    try:
        arquivos_processados = set()
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    # Formato novo: "2025-09-26 12:00:00 - Processado: arquivo.jpg"
                    if " - Processado: " in linha:
                        nome_arquivo = linha.split(" - Processado: ")[-1]
                        arquivos_processados.add(nome_arquivo)
                    # Formato antigo: apenas o nome do arquivo
                    else:
                        arquivos_processados.add(linha)
        return arquivos_processados
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()


def obter_estatisticas():
    """Obtém estatísticas do sistema."""
    stats = {
        "imagens_total": 0,
        "imagens_processadas": 0,
        "imagens_pendentes": 0,
        "ultimo_processamento": "Nunca",
        "tokens_consumidos_hoje": 0,
        "relatorio_existe": False,
    }

    try:
        # Imagens realmente presentes na pasta agora.
        imagens_na_pasta = []
        if os.path.exists(DIRETORIO_IMAGENS):
            imagens_na_pasta = [
                f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)
            ]
        stats["imagens_total"] = len(imagens_na_pasta)

        # "Processadas" é a INTERSEÇÃO entre o que está na pasta agora e o
        # que o log diz já ter processado - nunca o tamanho bruto do log.
        # Sem isso, apagar imagens (ex.: "Limpar Imagens" em Configurações,
        # que não mexe no log) deixava processadas > total, um número sem
        # sentido no dashboard.
        processadas_no_log = carregar_logs_processados()
        stats["imagens_processadas"] = sum(1 for f in imagens_na_pasta if f in processadas_no_log)
        stats["imagens_pendentes"] = stats["imagens_total"] - stats["imagens_processadas"]

        # Último processamento - cache por arquivo
        if os.path.exists(LOG_PROCESSADOS_FILE):
            mod_time = os.path.getmtime(LOG_PROCESSADOS_FILE)
            stats["ultimo_processamento"] = datetime.fromtimestamp(mod_time).strftime(
                "%d/%m/%Y %H:%M"
            )

        # Tokens consumidos hoje - otimizado
        if os.path.exists(LOG_CONSUMO_FILE):
            hoje = datetime.now().strftime("%Y-%m-%d")
            try:
                with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
                    # Ler apenas últimas linhas para performance
                    lines = f.readlines()[-50:]  # Últimas 50 linhas
                    for linha in lines:
                        if hoje in linha and "tokens consumidos:" in linha:
                            tokens_str = (
                                linha.split("tokens consumidos:")[1]
                                .strip()
                                .replace(",", "")
                            )
                            stats["tokens_consumidos_hoje"] += int(tokens_str)
            except (ValueError, IndexError):
                pass

        # Verifica se existe relatório
        stats["relatorio_existe"] = os.path.exists(ARQUIVO_SAIDA_EXCEL)

    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")

    return stats


def obter_resultados_recentes():
    """Obtém os resultados mais recentes do relatório."""
    resultados = {"avarias": [], "uso_interno": [], "erros": []}

    try:
        if os.path.exists(ARQUIVO_SAIDA_EXCEL):
            # Ler as últimas 10 entradas de cada tipo
            sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)

            if "Avarias" in sheets:
                df_avarias = sheets["Avarias"].tail(10)
                # Tratar valores NaN
                df_avarias = df_avarias.fillna("-")
                resultados["avarias"] = df_avarias.to_dict("records")

            if "Uso Interno" in sheets:
                df_uso = sheets["Uso Interno"].tail(10)
                # Tratar valores NaN
                df_uso = df_uso.fillna("-")
                resultados["uso_interno"] = df_uso.to_dict("records")

            if "Erros de Análise" in sheets:
                df_erros = sheets["Erros de Análise"].tail(10)
                # Tratar valores NaN
                df_erros = df_erros.fillna("-")
                resultados["erros"] = df_erros.to_dict("records")

    except Exception as e:
        print(f"Erro ao ler resultados: {e}")

    return resultados
