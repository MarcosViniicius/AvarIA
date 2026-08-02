"""Testes de leitura/escrita do Excel mestre (services/report_editing.py).

Cobre principalmente a regressão do "Código de Barras" virando float
(7896221600012 -> 7896221600012.0) ao ser lido de volta pelo pandas.
"""

import pandas as pd
import pytest

from autoavaria.services.report_editing import (
    carregar_todas_sheets,
    fazer_backup,
    salvar_todas_sheets,
)


def test_codigo_de_barras_nao_vira_float_ao_reler(tmp_path):
    """Regressão: gravar '7896221600012' e reler não pode devolver 7896221600012.0."""
    caminho = tmp_path / "teste.xlsx"
    df = pd.DataFrame(
        [
            {"Produto": "Item A", "Marca": "X", "Código de Barras": "7896221600012"},
            {"Produto": "Item B", "Marca": "Y", "Código de Barras": "7891910030477"},
        ]
    )
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Uso Interno", index=False)

    sheets = carregar_todas_sheets(str(caminho))
    coluna = sheets["Uso Interno"]["Código de Barras"]

    valores = [str(v) for v in coluna]
    assert valores == ["7896221600012", "7891910030477"]
    assert not any(v.endswith(".0") for v in valores)


def test_codigo_de_barras_ausente_vira_na(tmp_path):
    caminho = tmp_path / "teste.xlsx"
    df = pd.DataFrame([{"Produto": "Item A", "Código de Barras": "123"}, {"Produto": "Item B", "Código de Barras": None}])
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Uso Interno", index=False)

    sheets = carregar_todas_sheets(str(caminho))
    assert sheets["Uso Interno"]["Código de Barras"].tolist() == ["123", "N/A"]


def test_coluna_toda_na_nao_vira_float64(tmp_path):
    """Regressão: se TODA a coluna Marca é 'N/A' (planilha nova, por ex.),
    o pandas lia a coluna inteira como NaN/float64. Editar essa célula
    depois com um valor de texto falhava com "Invalid value ... for dtype
    'float64'". Toda coluna de texto livre do relatório deve vir sempre
    como string ao reler, independente do conteúdo."""
    caminho = tmp_path / "teste.xlsx"
    df = pd.DataFrame(
        [
            {"Produto": "SACO DE LIXO", "Marca": "N/A", "Peso": "N/A"},
            {"Produto": "COPO", "Marca": "N/A", "Peso": "N/A"},
        ]
    )
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Uso Interno", index=False)

    sheets = carregar_todas_sheets(str(caminho))
    coluna_marca = sheets["Uso Interno"]["Marca"]

    assert coluna_marca.dtype != "float64"
    # e, principalmente, dá pra escrever um valor de texto na célula sem erro
    sheets["Uso Interno"].at[0, "Marca"] = "PLASTPACK"
    assert sheets["Uso Interno"].at[0, "Marca"] == "PLASTPACK"


def test_salvar_e_recarregar_preserva_dados(tmp_path):
    caminho = tmp_path / "teste.xlsx"
    sheets = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Peso": "1kg"}])}
    salvar_todas_sheets(str(caminho), sheets)

    recarregado = carregar_todas_sheets(str(caminho))
    assert recarregado["Avarias"]["Produto"].tolist() == ["Tomate"]


def test_salvar_apenas_nao_vazias_omite_sheets_vazias(tmp_path):
    caminho = tmp_path / "teste.xlsx"
    sheets = {
        "Avarias": pd.DataFrame([{"Produto": "Tomate"}]),
        "Uso Interno": pd.DataFrame(columns=["Produto"]),
    }
    salvar_todas_sheets(str(caminho), sheets, apenas_nao_vazias=True)

    recarregado = carregar_todas_sheets(str(caminho))
    assert "Avarias" in recarregado
    assert "Uso Interno" not in recarregado


def test_fazer_backup_cria_copia(tmp_path):
    caminho = tmp_path / "teste.xlsx"
    pd.DataFrame([{"a": 1}]).to_excel(caminho, index=False)

    fazer_backup(str(caminho))

    assert (tmp_path / "teste.xlsx.bak").exists()


def test_fazer_backup_sem_arquivo_nao_falha(tmp_path):
    fazer_backup(str(tmp_path / "nao_existe.xlsx"))  # não deve levantar exceção


class TestRemoverLinhasPorCaminhoImagem:
    def test_remove_linhas_das_imagens_informadas(self):
        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {
            "Avarias": pd.DataFrame(
                {"Produto": ["Tomate", "Alface"], "Caminho da Imagem": ["/a/IMG-1.jpg", "/a/IMG-2.jpg"]}
            ),
        }
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Avarias"]["Produto"]) == ["Alface"]

    def test_sheet_sem_coluna_caminho_imagem_fica_intacta(self):
        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Outra": pd.DataFrame({"Coisa": [1, 2]})}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Outra"]["Coisa"]) == [1, 2]

    def test_sheet_vazia_fica_intacta(self):
        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Avarias": pd.DataFrame(columns=["Produto", "Caminho da Imagem"])}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert resultado["Avarias"].empty

    def test_nenhum_caminho_correspondente_mantem_todas_as_linhas(self):
        from autoavaria.services.report_editing import remover_linhas_por_caminho_imagem

        sheets = {"Avarias": pd.DataFrame({"Produto": ["Tomate"], "Caminho da Imagem": ["/a/IMG-9.jpg"]})}
        resultado = remover_linhas_por_caminho_imagem(sheets, {"/a/IMG-1.jpg"})
        assert list(resultado["Avarias"]["Produto"]) == ["Tomate"]
