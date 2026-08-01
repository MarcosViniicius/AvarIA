"""
GERAÇÃO DO RELATÓRIO EXCEL

Grava os itens extraídos (Avarias / Uso Interno / Erros de Análise) no
arquivo Excel mestre, mesclando com o conteúdo já existente e aplicando
formatação + hyperlinks para abrir as imagens. Extraído de extrair-dados.py.
"""

import os
from typing import Dict, List

import pandas as pd

from .export_service import escrever_xlsx
from .report_editing import carregar_todas_sheets

COLUNAS_AVARIAS = ["Produto", "Quantidade", "Peso", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
COLUNAS_USO_INTERNO = ["Produto", "Quantidade", "Marca", "Código de Barras", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]
COLUNAS_ERROS = ["Arquivo", "Detalhes do Erro", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem"]

# Quantidade é uma coluna nova: planilhas geradas antes dela não a possuem.
# Ao mesclar, as linhas antigas ficariam com célula vazia — preenchemos com 1,
# que é o que elas sempre significaram na prática (um item por linha).
QUANTIDADE_PADRAO = 1


def salvar_relatorio_excel(
    arquivo_saida: str,
    novas_avarias: List[Dict],
    novos_usos_internos: List[Dict],
    novos_erros: List[Dict],
) -> None:
    """Salva os dados extraídos em um arquivo Excel com múltiplas abas (mescla com o existente)."""
    try:
        print("📊 Gerando relatório Excel...")
        sheets = {}
        if os.path.exists(arquivo_saida):
            try:
                sheets = carregar_todas_sheets(arquivo_saida)
                print("✅ Arquivo Excel existente carregado para atualização.")
            except Exception as e:
                print(f"⚠️ Erro ao ler Excel existente: {e}. Um novo arquivo será criado.")

        df_novas_avarias = pd.DataFrame(novas_avarias, columns=COLUNAS_AVARIAS)
        df_novos_usos_internos = pd.DataFrame(novos_usos_internos, columns=COLUNAS_USO_INTERNO)
        df_novos_erros = pd.DataFrame(novos_erros, columns=COLUNAS_ERROS)

        df_avarias_final = pd.concat(
            [sheets.get("Avarias", pd.DataFrame(columns=COLUNAS_AVARIAS)), df_novas_avarias],
            ignore_index=True,
        )
        df_uso_interno_final = pd.concat(
            [sheets.get("Uso Interno", pd.DataFrame(columns=COLUNAS_USO_INTERNO)), df_novos_usos_internos],
            ignore_index=True,
        )
        df_erros_final = pd.concat(
            [sheets.get("Erros de Análise", pd.DataFrame(columns=COLUNAS_ERROS)), df_novos_erros],
            ignore_index=True,
        )

        _garantir_quantidade(df_avarias_final)
        _garantir_quantidade(df_uso_interno_final)

        # Sheets vazias não vão para o arquivo - preserva o comportamento
        # original (mescla apenas do que já existia, sem criar aba vazia
        # nova quando nem o arquivo antigo nem este lote têm nada daquela
        # categoria).
        secoes = {
            nome: df
            for nome, df in [
                ("Avarias", df_avarias_final),
                ("Uso Interno", df_uso_interno_final),
                ("Erros de Análise", df_erros_final),
            ]
            if not df.empty
        }
        escrever_xlsx(arquivo_saida, secoes, aplicar_formatacao=True)

        print(f"\n📋 RELATÓRIO SALVO: {arquivo_saida}")
        print(f"  ├─ Novas Avarias: {len(novas_avarias)}")
        print(f"  ├─ Novos Usos Internos: {len(novos_usos_internos)}")
        print(f"  └─ Novos Erros: {len(novos_erros)}")

    except Exception as e:
        print(f"❌ Erro crítico ao salvar o arquivo Excel: {e}")


def _garantir_quantidade(df: pd.DataFrame) -> None:
    """Preenche a coluna Quantidade nas linhas que vieram sem ela.

    Mantém a compatibilidade com planilhas geradas antes da coluna existir:
    elas são mescladas normalmente e as linhas antigas assumem 1.
    """
    if df.empty:
        return
    if "Quantidade" not in df.columns:
        df["Quantidade"] = QUANTIDADE_PADRAO
        return
    df["Quantidade"] = (
        pd.to_numeric(df["Quantidade"], errors="coerce").fillna(QUANTIDADE_PADRAO).astype(int)
    )
