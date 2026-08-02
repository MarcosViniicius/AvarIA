"""Testes de services/excel_report.py - a escrita do relatório mestre.

Migrado na Fase 5 para delegar a escrita real (services/export_service.py),
mas mantendo o comportamento específico: mescla com o Excel existente,
preenche Quantidade ausente com 1, e nunca cria aba vazia.
"""

import openpyxl
import pandas as pd
import pytest

from autoavaria.services.excel_report import salvar_relatorio_excel


class TestSalvarRelatorioExcel:
    def test_cria_arquivo_novo_com_as_tres_abas(self, tmp_path):
        caminho = str(tmp_path / "relatorio.xlsx")
        salvar_relatorio_excel(
            caminho,
            [{"Produto": "Tomate", "Peso": "1kg", "Caminho da Imagem": "a.jpg", "Ver Imagem": "a.jpg"}],
            [{"Produto": "Copo", "Código de Barras": "789", "Caminho da Imagem": "b.jpg", "Ver Imagem": "b.jpg"}],
            [{"Arquivo": "c.jpg", "Detalhes do Erro": "sem info"}],
        )
        sheets = pd.read_excel(caminho, sheet_name=None)
        assert set(sheets.keys()) == {"Avarias", "Uso Interno", "Erros de Análise"}

    def test_nao_cria_aba_vazia(self, tmp_path):
        caminho = str(tmp_path / "relatorio.xlsx")
        salvar_relatorio_excel(caminho, [{"Produto": "Tomate"}], [], [])
        sheets = pd.read_excel(caminho, sheet_name=None)
        assert set(sheets.keys()) == {"Avarias"}

    def test_mescla_com_arquivo_existente(self, tmp_path):
        caminho = str(tmp_path / "relatorio.xlsx")
        salvar_relatorio_excel(caminho, [{"Produto": "Tomate"}], [], [])
        salvar_relatorio_excel(caminho, [{"Produto": "Alface"}], [], [])

        df = pd.read_excel(caminho, sheet_name="Avarias")
        assert sorted(df["Produto"].tolist()) == ["Alface", "Tomate"]

    def test_quantidade_ausente_vira_1(self, tmp_path):
        caminho = str(tmp_path / "relatorio.xlsx")
        salvar_relatorio_excel(caminho, [{"Produto": "Tomate"}], [], [])
        df = pd.read_excel(caminho, sheet_name="Avarias")
        assert df["Quantidade"].tolist() == [1]

    def test_aplica_hyperlink_em_ver_imagem(self, tmp_path):
        caminho = str(tmp_path / "relatorio.xlsx")
        salvar_relatorio_excel(
            caminho,
            [{"Produto": "Tomate", "Ver Imagem": "C:/fotos/a.jpg"}],
            [], [],
        )
        wb = openpyxl.load_workbook(caminho)
        headers = [c.value for c in wb["Avarias"][1]]
        col_idx = headers.index("Ver Imagem") + 1
        celula = wb["Avarias"].cell(row=2, column=col_idx)
        assert celula.hyperlink is not None
