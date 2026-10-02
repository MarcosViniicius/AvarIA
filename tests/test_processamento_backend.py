"""Backend/processamento — CURADO (só gaps, sem duplicatas).

Complementa `test_barcode.py`, `test_conversa.py`, `test_catalogo.py`,
`test_unification.py`, `test_excel_report.py` e `test_export_service.py`.
Cada teste aqui cobre um cenário que NÃO existia antes (edge de validação,
multilinha, ordenação de conversa, produtos distintos, aba Sem Dados).
O comportamento base continua nos arquivos origem.
"""

import datetime as dt

import pandas as pd

from avariaia.services import barcode, conversa, excel_report
from avariaia.services import extraction_engines as engines


class TestBarcodeEdgesNovos:
    def test_ean_com_espacos_e_aceito(self):
        assert barcode.ean13_valido("  7897274410245  ") is True

    def test_ean_14_digitos_vazio_e_na_rejeitados(self):
        assert barcode.ean13_valido("78972744102455") is False
        assert barcode.ean13_valido("") is False
        assert barcode.ean13_valido("N/A") is False

    def test_preco_negativo_devolve_none(self):
        assert barcode.calcular_peso(5.16, -1) is None

    def test_ean_normal_nao_e_balanca_interpretavel(self):
        assert barcode.interpretar_etiqueta_balanca("7897274410245") is None

    def test_formatar_peso_direto(self):
        assert engines._formatar_peso(0.738) == "0,738kg"
        assert engines._formatar_peso(1.5) == "1,500kg"


class TestConversaCasosNovos:
    def test_linha_de_peso_nao_contamina_legenda_multilinha(self):
        assert conversa.extrair_quantidade("0,738kg\n7") == 7

    def test_mencao_explicita_fora_da_janela_associa_e_quantifica(self):
        from datetime import datetime
        msgs = [
            conversa.Mensagem(datetime(2026, 7, 1, 14, 0), "F", "", imagem="a.jpg"),
            conversa.Mensagem(datetime(2026, 7, 1, 18, 0), "F",
                              "ver a.jpg com atenção: 4 unidades"),
        ]
        ctx = conversa.construir_contextos(msgs)
        assert "4 unidades" in ctx["a.jpg"].texto
        assert ctx["a.jpg"].quantidade == 4

    def test_encontrar_conversa_escolhe_primeiro_ordenado(self, tmp_path):
        (tmp_path / "b.txt").write_text("x", encoding="utf-8")
        (tmp_path / "a.txt").write_text("y", encoding="utf-8")
        assert conversa.encontrar_arquivo_conversa(str(tmp_path)).endswith("a.txt")

    def test_sem_txt_devolve_none(self, tmp_path):
        assert conversa.encontrar_arquivo_conversa(str(tmp_path)) is None


class TestUnificacaoCasosNovos:
    def test_produtos_diferentes_nao_agrupam(self):
        df = pd.DataFrame([("A", "1kg", 1), ("B", "1kg", 1)],
                          columns=["Produto", "Peso", "Quantidade"])
        uni, _ = __import__("avariaia.services.unification",
                            fromlist=["unificar_itens_avarias"]).unificar_itens_avarias(df)
        assert len(uni) == 2


class TestExcelCasosNovos:
    def test_lote_vazio_gera_aba_sem_dados(self, tmp_path):
        saida = str(tmp_path / "vazio.xlsx")
        excel_report.salvar_relatorio_excel(saida, [], [], [])
        sheets = pd.read_excel(saida, sheet_name=None)
        assert "Sem Dados" in sheets

    def test_catalogo_expiracao_borda(self, tmp_db):
        from avariaia.services import catalogo
        agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        assert catalogo.esta_desatualizado(agora, dias=30) is False
        assert catalogo.esta_desatualizado(None) is True
