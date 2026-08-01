"""
EXPORTAÇÃO DE RELATÓRIOS (Excel / TXT)

Fonte única para gravar dataframes de itens em Excel e TXT. Antes deste
módulo, cada tela de exportação (relatório mestre, unificação, histórico por
execução) reimplementava sua própria escrita de arquivo — quatro escritores
de Excel e quatro de TXT, com pequenas diferenças acidentais entre eles
(um tinha hyperlink e autofit de coluna, os outros não; um detalhava campo a
campo, outro compactava tudo numa linha) que não representavam nenhuma
decisão de negócio, só implementações independentes divergindo com o tempo.

Existem DUAS formas de TXT porque isso sim é uma diferença real:

* ``escrever_txt_detalhado`` — um bloco por registro, campo a campo. Para
  dados crus (Avarias/Uso Interno/Erros como saem da extração, um registro
  por item).
* ``escrever_txt_compacto`` — uma linha por item ("PRODUTO | QUANTIDADE
  TOTAL [| CÓDIGO DE BARRAS]"). Para dados já unificados, onde cada linha
  já É o resumo consolidado de um produto - detalhar campo a campo não faria
  sentido nesse caso.
"""

import os
from datetime import datetime
from typing import Dict, Iterable, Optional

import pandas as pd
from openpyxl.styles import Font

_LARGURA_CABECALHO = 80


def filtrar_colunas(df: pd.DataFrame, colunas: Optional[Iterable[str]]) -> pd.DataFrame:
    """Restringe `df` às `colunas` pedidas que realmente existem nele.

    Se `colunas` for None/vazio, ou nenhuma delas existir no df, devolve o
    df original sem alteração (comportamento herdado dos exportadores
    antigos: um filtro que não bate com nada é tratado como "sem filtro").
    """
    if not colunas:
        return df
    existentes = [c for c in colunas if c in df.columns]
    return df[existentes] if existentes else df


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def escrever_xlsx(caminho: str, secoes: Dict[str, pd.DataFrame], aplicar_formatacao: bool = False) -> None:
    """Escreve um dict {nome_da_sheet: DataFrame} num arquivo .xlsx.

    Grava exatamente as seções recebidas, incluindo as vazias - decidir se
    uma seção vazia deve ou não aparecer no arquivo é responsabilidade de
    quem chama (filtrar antes), não deste escritor genérico.

    `aplicar_formatacao=True` acrescenta hyperlinks na coluna "Ver Imagem" e
    ajusta a largura das colunas ao conteúdo - usado no relatório mestre,
    onde o arquivo é aberto e navegado diretamente pelo usuário. Exports
    avulsos/filtrados não precisam disso.
    """
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for nome_sheet, df in secoes.items():
            df.to_excel(writer, sheet_name=nome_sheet, index=False)
        if aplicar_formatacao:
            _aplicar_formatacao_excel(writer, secoes)


def _aplicar_formatacao_excel(writer, secoes: Dict[str, pd.DataFrame]) -> None:
    """Hyperlinks na coluna 'Ver Imagem' + autofit de largura de coluna."""
    try:
        workbook = writer.book
        link_font = Font(color="0563C1", underline="single")

        for sheet_name, df in secoes.items():
            if sheet_name not in workbook.sheetnames or df.empty:
                continue
            sheet = workbook[sheet_name]
            try:
                headers = [cell.value for cell in sheet[1]]
                link_col_idx = headers.index("Ver Imagem") + 1
                for index, registro in df.iterrows():
                    if "Ver Imagem" in registro and pd.notna(registro["Ver Imagem"]):
                        link_cell = sheet.cell(row=index + 2, column=link_col_idx)
                        caminho_imagem = registro["Ver Imagem"]
                        if caminho_imagem.startswith("http"):
                            link_cell.hyperlink = caminho_imagem
                            link_cell.value = "Abrir Imagem"
                        else:
                            link_cell.hyperlink = f"file:///{caminho_imagem.replace(os.sep, '/')}"
                            link_cell.value = caminho_imagem
                        link_cell.font = link_font
            except (ValueError, IndexError):
                pass
            for column in sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        cell_length = len(str(cell.value))
                        if cell_length > max_length:
                            max_length = cell_length
                    except Exception:
                        pass
                adjusted_width = min(max_length + 2, 60)
                sheet.column_dimensions[column_letter].width = adjusted_width
    except Exception as e:
        print(f"⚠️ Erro na formatação do Excel: {e}")


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


def _cabecalho(titulo: str) -> list:
    linha = "=" * _LARGURA_CABECALHO
    return [linha, titulo, f"Data de Geração: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", linha, ""]


def _rodape() -> list:
    linha = "=" * _LARGURA_CABECALHO
    return ["", linha, "FIM DO RELATÓRIO", linha]


def _gravar_linhas(caminho: str, linhas: list) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))


def escrever_txt_detalhado(
    caminho: str, titulo: str, secoes: Dict[str, pd.DataFrame], excluir_colunas: Iterable[str] = ("Ver Imagem",)
) -> None:
    """TXT campo-a-campo: um bloco 'Registro #N:' por linha do dataframe.

    Colunas com "observ" ou "detalhes" no nome (ex.: "Observação da
    Mensagem", "Detalhes do Erro") ganham bloco próprio em vez de ficarem
    na mesma linha do rótulo - são as colunas de texto livre, que tendem a
    ser mais longas.
    """
    excluir = set(excluir_colunas or ())
    linhas = _cabecalho(titulo)

    for nome_secao, df in secoes.items():
        if df is None or df.empty:
            continue

        linhas.append("\n" + "=" * _LARGURA_CABECALHO)
        linhas.append(nome_secao.upper())
        linhas.append("=" * _LARGURA_CABECALHO + "\n")
        linhas.append(f"Total de registros: {len(df)}")
        linhas.append("-" * _LARGURA_CABECALHO + "\n")

        colunas = [c for c in df.columns if c not in excluir]
        for idx, row in df.iterrows():
            linhas.append(f"Registro #{idx + 1}:")
            linhas.append("-" * 40)
            for col in colunas:
                valor = row[col]
                if pd.isna(valor) or valor == "" or str(valor).lower() == "nan":
                    valor = "-"
                if "observ" in col.lower() or "detalhes" in col.lower():
                    linhas.append(f"\n{col}:")
                    linhas.append(f"  {valor}")
                else:
                    linhas.append(f"{col}: {valor}")
            linhas.append("")

    linhas += _rodape()
    _gravar_linhas(caminho, linhas)


def escrever_txt_compacto(caminho: str, titulo: str, secoes: Dict[str, pd.DataFrame]) -> None:
    """TXT compacto: uma linha 'PRODUTO | QUANTIDADE TOTAL [| CÓDIGO DE BARRAS]'
    por item - para seções já unificadas."""
    linhas = _cabecalho(titulo)

    for nome_secao, df in secoes.items():
        if df is None or df.empty:
            continue

        linhas.append("-" * _LARGURA_CABECALHO)
        linhas.append(f"SEÇÃO: {nome_secao.upper()}")
        linhas.append("-" * _LARGURA_CABECALHO)

        tem_codigo = "Código de Barras" in df.columns
        cabecalho_colunas = (
            "PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS" if tem_codigo else "PRODUTO | QUANTIDADE TOTAL"
        )
        linhas.append(cabecalho_colunas)
        linhas.append("-" * _LARGURA_CABECALHO)

        for _, row in df.iterrows():
            partes = [str(row.get("Produto", "N/A")), str(row.get("Quantidade Total", "N/A"))]
            if tem_codigo:
                partes.append(str(row.get("Código de Barras", "N/A")))
            linhas.append(" | ".join(partes))

        linhas.append("")
        linhas.append(f"Total de itens: {len(df)}")
        linhas.append("")

    linhas += _rodape()
    _gravar_linhas(caminho, linhas)
