"""Testes dos parsers usados para migrar o campo 'Detalhes' combinado
(formato antigo) para Peso / Marca / Código de Barras separados."""

from autoavaria.services.campo_migration import (
    _dividir_detalhes_uso_interno,
    _peso_bruto_de_detalhes,
)


class TestPesoBrutoDeDetalhes:
    def test_extrai_peso_do_texto_combinado(self):
        assert _peso_bruto_de_detalhes("Peso: 1,5kg") == "1,5kg"

    def test_sem_prefixo_peso_retorna_texto_bruto(self):
        assert _peso_bruto_de_detalhes("500g") == "500g"

    def test_vazio_retorna_na(self):
        assert _peso_bruto_de_detalhes("") == "N/A"
        assert _peso_bruto_de_detalhes(None) == "N/A"


class TestDividirDetalhesUsoInterno:
    def test_extrai_marca_e_codigo(self):
        marca, codigo = _dividir_detalhes_uso_interno("Marca: Camil | Cód. Barras: 7891910030477")
        assert marca == "Camil"
        assert codigo == "7891910030477"

    def test_so_marca_sem_codigo(self):
        marca, codigo = _dividir_detalhes_uso_interno("Marca: X")
        assert marca == "X"
        assert codigo == "N/A"

    def test_vazio(self):
        marca, codigo = _dividir_detalhes_uso_interno("")
        assert marca == "N/A"
        assert codigo == "N/A"
