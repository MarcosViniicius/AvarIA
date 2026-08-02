"""Testes de services/export_service.py - fonte única de escrita Excel/TXT.

Consolida o que antes eram 4 escritores de Excel e 4 de TXT independentes
(routes/relatorio.py, routes/unificacao.py, services/execucao_export.py,
services/excel_report.py), cada um com pequenas diferenças acidentais.
"""

import pandas as pd
import pytest

from autoavaria.services import export_service as es


class TestFiltrarColunas:
    def test_sem_filtro_devolve_original(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        assert list(es.filtrar_colunas(df, None).columns) == ["a", "b"]

    def test_filtro_restringe_as_colunas_existentes(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        resultado = es.filtrar_colunas(df, ["a", "c"])
        assert list(resultado.columns) == ["a", "c"]

    def test_filtro_sem_nenhuma_coluna_valida_devolve_original(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        resultado = es.filtrar_colunas(df, ["x", "y"])
        assert list(resultado.columns) == ["a", "b"]


class TestEscreverXlsx:
    def test_grava_cada_secao_como_sheet(self, tmp_path):
        caminho = tmp_path / "teste.xlsx"
        secoes = {
            "Avarias": pd.DataFrame([{"Produto": "Tomate"}]),
            "Uso Interno": pd.DataFrame([{"Produto": "Copo"}]),
        }
        es.escrever_xlsx(str(caminho), secoes)

        lido = pd.read_excel(caminho, sheet_name=None)
        assert set(lido.keys()) == {"Avarias", "Uso Interno"}
        assert lido["Avarias"]["Produto"].tolist() == ["Tomate"]

    def test_grava_sheet_vazia_se_recebida(self, tmp_path):
        caminho = tmp_path / "teste.xlsx"
        es.escrever_xlsx(str(caminho), {"Vazia": pd.DataFrame(columns=["Produto"])})
        lido = pd.read_excel(caminho, sheet_name=None)
        assert "Vazia" in lido

    def test_formatacao_aplica_hyperlink_em_ver_imagem(self, tmp_path):
        caminho = tmp_path / "teste.xlsx"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Ver Imagem": "C:/fotos/a.jpg"}])}
        es.escrever_xlsx(str(caminho), secoes, aplicar_formatacao=True)

        import openpyxl
        wb = openpyxl.load_workbook(caminho)
        celula = wb["Avarias"].cell(row=2, column=2)  # coluna "Ver Imagem"
        assert celula.hyperlink is not None

    def test_sem_formatacao_nao_aplica_hyperlink(self, tmp_path):
        caminho = tmp_path / "teste.xlsx"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Ver Imagem": "C:/fotos/a.jpg"}])}
        es.escrever_xlsx(str(caminho), secoes, aplicar_formatacao=False)

        import openpyxl
        wb = openpyxl.load_workbook(caminho)
        celula = wb["Avarias"].cell(row=2, column=2)
        assert celula.hyperlink is None


class TestEscreverTxtDetalhado:
    def test_formato_registro_por_registro(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Peso": "1kg"}])}
        es.escrever_txt_detalhado(str(caminho), "TESTE", secoes)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "Registro #1:" in conteudo
        assert "Produto: Tomate" in conteudo
        assert "Peso: 1kg" in conteudo

    def test_coluna_observacao_ganha_bloco_proprio(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Observação da Mensagem": "perda total"}])}
        es.escrever_txt_detalhado(str(caminho), "TESTE", secoes)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "Observação da Mensagem:\n  perda total" in conteudo

    def test_coluna_excluida_nao_aparece(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Ver Imagem": "a.jpg"}])}
        es.escrever_txt_detalhado(str(caminho), "TESTE", secoes)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "Ver Imagem" not in conteudo

    def test_secao_vazia_e_pulada(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        secoes = {"Avarias": pd.DataFrame(columns=["Produto"])}
        es.escrever_txt_detalhado(str(caminho), "TESTE", secoes)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "AVARIAS" not in conteudo

    def test_valor_vazio_vira_traco(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        secoes = {"Avarias": pd.DataFrame([{"Produto": "Tomate", "Peso": None}])}
        es.escrever_txt_detalhado(str(caminho), "TESTE", secoes)

        conteudo = caminho.read_text(encoding="utf-8")
        assert "Peso: -" in conteudo

    def test_cabecalho_e_rodape_presentes(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        es.escrever_txt_detalhado(str(caminho), "MEU TITULO", {"Avarias": pd.DataFrame([{"Produto": "X"}])})

        conteudo = caminho.read_text(encoding="utf-8")
        assert "MEU TITULO" in conteudo
        assert "FIM DO RELATÓRIO" in conteudo


class TestEscreverTxtCompacto:
    def test_formato_uma_linha_por_item_sem_codigo(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        df = pd.DataFrame([{"Produto": "TOMATE", "Quantidade Total": "1,500 kg"}])
        es.escrever_txt_compacto(str(caminho), "TESTE", {"Avarias": df})

        conteudo = caminho.read_text(encoding="utf-8")
        assert "TOMATE | 1,500 kg" in conteudo
        assert "PRODUTO | QUANTIDADE TOTAL" in conteudo
        assert "CÓDIGO DE BARRAS" not in conteudo.split("SEÇÃO: AVARIAS")[1].split("---")[0]

    def test_formato_uma_linha_por_item_com_codigo(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        df = pd.DataFrame([{"Produto": "ABSOLUTO", "Quantidade Total": "5", "Código de Barras": "789"}])
        es.escrever_txt_compacto(str(caminho), "TESTE", {"Uso Interno": df})

        conteudo = caminho.read_text(encoding="utf-8")
        assert "ABSOLUTO | 5 | 789" in conteudo
        assert "PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS" in conteudo

    def test_secao_vazia_e_pulada(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        es.escrever_txt_compacto(str(caminho), "TESTE", {"Avarias": pd.DataFrame(columns=["Produto"])})
        conteudo = caminho.read_text(encoding="utf-8")
        assert "SEÇÃO" not in conteudo

    def test_total_de_itens_correto(self, tmp_path):
        caminho = tmp_path / "teste.txt"
        df = pd.DataFrame([{"Produto": "A", "Quantidade Total": "1"}, {"Produto": "B", "Quantidade Total": "2"}])
        es.escrever_txt_compacto(str(caminho), "TESTE", {"Avarias": df})
        conteudo = caminho.read_text(encoding="utf-8")
        assert "Total de itens: 2" in conteudo
