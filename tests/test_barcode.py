"""Testes do módulo de leitura de código de barras (modo sem IA)."""

import numpy as np
import pytest

zxingcpp = pytest.importorskip("zxingcpp")
cv2 = pytest.importorskip("cv2")

from avariaia.services import barcode


def _gerar_imagem_ean13(codigo: str, escala: int = 4):
    """Gera uma imagem sintética de um EAN-13 para testes de ponta a ponta."""
    bc = zxingcpp.create_barcode(codigo, format=zxingcpp.EAN13)
    imagem = zxingcpp.write_barcode_to_image(bc, scale=escala)
    return np.array(imagem)


class TestEan13Valido:
    def test_codigo_valido_e_aceito(self):
        assert barcode.ean13_valido("7897274410245") is True

    def test_digito_verificador_errado_e_rejeitado(self):
        # último dígito trocado (era 5)
        assert barcode.ean13_valido("7897274410241") is False

    def test_tamanho_errado_e_rejeitado(self):
        assert barcode.ean13_valido("78991001373") is False  # 11 dígitos

    def test_nao_numerico_e_rejeitado(self):
        assert barcode.ean13_valido("789727441024A") is False

    def test_casos_reais_divergentes_entre_ia_e_leitor(self):
        """Casos reais onde IA e leitor de código de barras discordaram.

        Verificados manualmente: em todos, a leitura da IA tinha o dígito
        verificador quebrado, e a do leitor de código de barras era válida.
        """
        casos_ia_errados = [
            "7892339101122",
            "7896231601591",
            "7898967873167",
            "7893095558583",
        ]
        casos_leitor_corretos = [
            "7898339101122",
            "7896221600159",
            "7898967875167",
            "7893095558593",
        ]
        for errado in casos_ia_errados:
            assert barcode.ean13_valido(errado) is False
        for correto in casos_leitor_corretos:
            assert barcode.ean13_valido(correto) is True


class TestEtiquetaBalanca:
    def test_prefixo_2_eh_balanca(self):
        assert barcode.eh_etiqueta_balanca("2001400005167") is True

    def test_prefixo_diferente_nao_eh_balanca(self):
        assert barcode.eh_etiqueta_balanca("7897274410245") is False

    def test_interpreta_plu_e_total(self):
        # Etiqueta real: MANGA, peso 0,738kg, total R$ 5,16
        resultado = barcode.interpretar_etiqueta_balanca("2001400005167")
        assert resultado is not None
        plu, total = resultado
        assert plu == "00140"
        assert total == pytest.approx(5.16)

    def test_codigo_invalido_devolve_none(self):
        assert barcode.interpretar_etiqueta_balanca("2001400005160") is None  # DV errado

    def test_plu_consistente_para_mesmo_produto(self):
        """PLU deve bater entre etiquetas diferentes do mesmo produto (validado com dados reais)."""
        tangerinas = ["2002700007134", "2002700012978", "2002700009398", "2002700035403"]
        plus = {barcode.interpretar_etiqueta_balanca(c)[0] for c in tangerinas}
        assert plus == {"00270"}


class TestCalcularPeso:
    def test_peso_bate_com_etiqueta_real(self):
        # MANGA: total R$5,16, R$/kg 6,99 -> peso 0,738kg (conferido na etiqueta)
        assert barcode.calcular_peso(5.16, 6.99) == pytest.approx(0.738, abs=0.001)

    def test_preco_zero_devolve_none(self):
        assert barcode.calcular_peso(5.16, 0) is None

    def test_preco_none_devolve_none(self):
        assert barcode.calcular_peso(5.16, None) is None


@pytest.mark.skipif(not barcode.LEITURA_DISPONIVEL, reason="opencv/zxing-cpp não instalados")
class TestLeituraDeImagem:
    def test_le_codigo_gerado_sinteticamente(self, tmp_path):
        codigo = "7897274410245"
        imagem = _gerar_imagem_ean13(codigo)
        caminho = tmp_path / "codigo.png"
        cv2.imwrite(str(caminho), imagem)

        lidos = barcode.ler_imagem(str(caminho))

        assert len(lidos) == 1
        assert lidos[0].texto == codigo
        assert lidos[0].eh_balanca is False

    def test_le_etiqueta_de_balanca_sinteticamente(self, tmp_path):
        codigo = "2001400005167"
        imagem = _gerar_imagem_ean13(codigo)
        caminho = tmp_path / "balanca.png"
        cv2.imwrite(str(caminho), imagem)

        lidos = barcode.ler_imagem(str(caminho))

        assert len(lidos) == 1
        assert lidos[0].texto == codigo
        assert lidos[0].eh_balanca is True

    def test_imagem_inexistente_devolve_lista_vazia(self, tmp_path):
        assert barcode.ler_imagem(str(tmp_path / "nao_existe.jpg")) == []

    def test_imagem_sem_codigo_devolve_lista_vazia(self, tmp_path):
        # Imagem em branco, sem nenhum código de barras.
        imagem_branca = np.full((200, 200), 255, dtype=np.uint8)
        caminho = tmp_path / "branco.png"
        cv2.imwrite(str(caminho), imagem_branca)
        assert barcode.ler_imagem(str(caminho), tentar_ladrilhos=False) == []
