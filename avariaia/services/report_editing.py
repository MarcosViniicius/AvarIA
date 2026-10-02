"""
Leitura/escrita compartilhada do Excel mestre.

Usado por todas as rotas e serviços que precisam ler ou regravar o relatório
mestre (edição, unificação, exportação, debug, migração). Centralizar aqui
evita repetir ``pd.read_excel(..., sheet_name=None)`` em mais de uma dezena
de lugares — e, mais importante, garante que a correção de tipos abaixo seja
aplicada sempre, em qualquer ponto do app que leia o arquivo.

Nota de comportamento: dentre as 5 rotas de edição originais, apenas
``/mover_item`` pulava planilhas vazias ao regravar o arquivo (``if not
dataframe.empty``); as outras 4 gravavam todas as planilhas, vazias ou não.
Esse detalhe foi preservado via o parâmetro ``apenas_nao_vazias`` de
``salvar_todas_sheets``.
"""

import os
import shutil

import pandas as pd

# Colunas que devem sempre ser texto, mas que o pandas/openpyxl às vezes
# reinterpreta como número (ex.: "7896221600012" vira o float
# 7896221600012.0) ou como float64 vazio (quando TODA a coluna está "N/A" -
# uma planilha nova, por exemplo, pode não ter nenhuma Marca preenchida
# ainda; nesse caso o pandas lê a coluna inteira como NaN/float64, e depois
# uma edição tentando escrever texto nela falha com "Invalid value ... for
# dtype 'float64'"). A gravação em si já preserva o texto corretamente — o
# problema é só na leitura — então corrigimos aqui, num único lugar, para
# toda coluna de texto livre do relatório (a única numérica de verdade é
# "Quantidade", que fica de fora de propósito).
_COLUNAS_SEMPRE_TEXTO = (
    "Produto", "Peso", "Marca", "Código de Barras", "Arquivo",
    "Detalhes do Erro", "Observação da Mensagem", "Caminho da Imagem", "Ver Imagem",
)


def _corrigir_colunas_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige colunas numérico-como-texto que o pandas mal-interpretou ao ler."""

    def _limpar(valor):
        if pd.isna(valor):
            return "N/A"
        if isinstance(valor, float) and valor.is_integer():
            return str(int(valor))
        texto = str(valor).strip()
        return texto if texto else "N/A"

    for coluna in _COLUNAS_SEMPRE_TEXTO:
        if coluna in df.columns:
            df[coluna] = df[coluna].apply(_limpar)
    return df


def carregar_todas_sheets(arquivo_excel):
    """Lê todas as planilhas do arquivo Excel informado, com tipos corrigidos."""
    sheets = pd.read_excel(arquivo_excel, sheet_name=None, engine="openpyxl")
    return {nome: _corrigir_colunas_texto(df) for nome, df in sheets.items()}


def fazer_backup(arquivo_excel):
    """Cria uma cópia de backup (``.bak``) do arquivo Excel, se ele existir."""
    if os.path.exists(arquivo_excel):
        backup_file = f"{arquivo_excel}.bak"
        shutil.copy2(arquivo_excel, backup_file)


def salvar_todas_sheets(arquivo_excel, sheets, apenas_nao_vazias=False):
    """Regrava todas as planilhas no arquivo Excel.

    A escrita é atômica (temporário + ``os.replace``): uma falha no meio da
    gravação nunca deixa o mestre truncado no disco.

    Args:
        arquivo_excel: caminho do arquivo Excel a ser (re)escrito.
        sheets: dict {nome_da_planilha: DataFrame}.
        apenas_nao_vazias: se True, planilhas vazias são omitidas da
            gravação - comportamento original específico da rota
            ``/mover_item``.
    """
    import tempfile

    arquivo_excel = os.fspath(arquivo_excel)
    pasta = os.path.dirname(arquivo_excel) or "."
    os.makedirs(pasta, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".sheets_tmp_", suffix=".xlsx", dir=pasta, delete=False
        ) as arquivo_temp:
            temporario = arquivo_temp.name
        with pd.ExcelWriter(temporario, engine="openpyxl") as writer:
            for nome_sheet, dataframe in sheets.items():
                if apenas_nao_vazias and dataframe.empty:
                    continue
                dataframe.to_excel(writer, sheet_name=nome_sheet, index=False)
        os.replace(temporario, arquivo_excel)
        temporario = None
    finally:
        if temporario and os.path.exists(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass


def remover_linhas_por_caminho_imagem(sheets, caminhos):
    """Remove, de todas as planilhas, as linhas cujo 'Caminho da Imagem' está em `caminhos`.

    Usado antes de gravar o resultado de uma reanálise de execução (ver
    services/extraction_pipeline.py:reanalisar_execucao): sem remover as
    linhas antigas dessas mesmas imagens primeiro, a mesma imagem contaria
    duas vezes no relatório mestre (a versão antiga E a nova).
    """
    resultado = {}
    for nome, df in sheets.items():
        if "Caminho da Imagem" in df.columns and not df.empty:
            resultado[nome] = df[~df["Caminho da Imagem"].isin(caminhos)].reset_index(drop=True)
        else:
            resultado[nome] = df
    return resultado
