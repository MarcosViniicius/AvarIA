"""
GERAÇÃO DO RELATÓRIO EXCEL

Grava os itens extraídos (Avarias / Uso Interno / Erros de Análise) no
arquivo Excel mestre, mesclando com o conteúdo já existente e aplicando
formatação + hyperlinks para abrir as imagens. Extraído de extrair-dados.py.
"""

import os
import tempfile
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
    """Salva os dados extraídos atomicamente, mesclando com o arquivo existente.

    A escrita acontece em um arquivo temporário na mesma pasta e só substitui
    o relatório atual depois que o novo XLSX foi fechado com sucesso. Erros
    são propagados para o pipeline, que não deve marcar as imagens como
    processadas se o relatório não foi persistido.
    """
    arquivo_saida = os.fspath(arquivo_saida)
    pasta_saida = os.path.dirname(arquivo_saida) or "."
    os.makedirs(pasta_saida, exist_ok=True)
    temporario = None
    try:
        print("📊 Gerando relatório Excel...")
        sheets = {}
        if os.path.exists(arquivo_saida):
            # Não substituir silenciosamente um mestre ilegível por um arquivo
            # contendo apenas o lote atual: isso apagaria o histórico do Excel.
            sheets = carregar_todas_sheets(arquivo_saida)
            print("✅ Arquivo Excel existente carregado para atualização.")

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
        if not secoes:
            secoes = {"Sem Dados": pd.DataFrame()}

        with tempfile.NamedTemporaryFile(
            prefix=".relatorio_tmp_", suffix=".xlsx", dir=pasta_saida, delete=False
        ) as arquivo_temp:
            temporario = arquivo_temp.name

        escrever_xlsx(temporario, secoes, aplicar_formatacao=True)
        os.replace(temporario, arquivo_saida)
        temporario = None

        print(f"\n📋 RELATÓRIO SALVO: {arquivo_saida}")
        print(f"  ├─ Novas Avarias: {len(novas_avarias)}")
        print(f"  ├─ Novos Usos Internos: {len(novos_usos_internos)}")
        print(f"  └─ Novos Erros: {len(novos_erros)}")

    except Exception as e:
        print(f"❌ Erro crítico ao salvar o arquivo Excel: {e}")
        raise
    finally:
        if temporario and os.path.exists(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass


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
