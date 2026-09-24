"""Testes da classificação dos resultados retornados pela IA (services/ai_extraction.py)."""

import json

import pytest

from autoavaria.services.ai_extraction import extrair_dados_de_lote, processar_resultado_arquivo


class _ProviderFalso:
    """Provider de mentira para testar extrair_dados_de_lote sem chamar API nenhuma."""

    def __init__(self, resposta_texto="{}", tokens=10, excecao=None):
        self.resposta_texto = resposta_texto
        self.tokens = tokens
        self.excecao = excecao
        self.chamadas = []

    def gerar_conteudo(self, partes):
        self.chamadas.append(partes)
        if self.excecao:
            raise self.excecao
        return self.resposta_texto, self.tokens


@pytest.fixture
def imagem_valida(tmp_path):
    from PIL import Image

    caminho = tmp_path / "IMG-boa.jpg"
    Image.new("RGB", (4, 4), color="blue").save(caminho)
    return str(caminho)


@pytest.fixture
def imagem_corrompida(tmp_path):
    caminho = tmp_path / "IMG-corrompida.jpg"
    caminho.write_bytes(b"isso nao e uma imagem de verdade")
    return str(caminho)


class TestExtrairDadosDeLoteComImagemCorrompida:
    def test_imagem_corrompida_nao_derruba_as_outras_do_lote(self, imagem_valida, imagem_corrompida):
        """Regressão: antes, 1 imagem corrompida abortava o lote inteiro sem nem chamar a IA."""
        resposta = json.dumps({"IMG-boa.jpg": {"tipo": "Avaria", "itens": [{"produto": "TOMATE", "peso": "1kg"}]}})
        provider = _ProviderFalso(resposta_texto=resposta, tokens=50)

        resultado, tokens = extrair_dados_de_lote([imagem_corrompida, imagem_valida], provider, {})

        # A imagem corrompida vira erro isolado...
        assert resultado["IMG-corrompida.jpg"]["tipo"] == "Erro"
        # ...mas a IA FOI chamada, e a imagem boa foi classificada normalmente.
        assert resultado["IMG-boa.jpg"]["tipo"] == "Avaria"
        assert tokens == 50
        assert len(provider.chamadas) == 1

    def test_lote_so_com_imagens_corrompidas_nao_chama_a_ia(self, imagem_corrompida):
        provider = _ProviderFalso()
        resultado, tokens = extrair_dados_de_lote([imagem_corrompida], provider, {})

        assert resultado["IMG-corrompida.jpg"]["tipo"] == "Erro"
        assert tokens == 0
        assert len(provider.chamadas) == 0  # não desperdiça uma chamada de API à toa

    def test_lote_vazio_nao_chama_a_ia(self):
        provider = _ProviderFalso()
        resultado, tokens = extrair_dados_de_lote([], provider, {})
        assert resultado == {}
        assert tokens == 0
        assert len(provider.chamadas) == 0


class TestExtrairDadosDeLoteParsingDeJson:
    def test_aceita_json_puro_sem_cercas(self, imagem_valida):
        provider = _ProviderFalso(resposta_texto='{"IMG-boa.jpg": {"tipo": "Erro", "detalhes": "x"}}')
        resultado, _ = extrair_dados_de_lote([imagem_valida], provider, {})
        assert resultado["IMG-boa.jpg"]["detalhes"] == "x"

    def test_aceita_json_com_cercas_markdown(self, imagem_valida):
        provider = _ProviderFalso(resposta_texto='```json\n{"IMG-boa.jpg": {"tipo": "Erro", "detalhes": "y"}}\n```')
        resultado, _ = extrair_dados_de_lote([imagem_valida], provider, {})
        assert resultado["IMG-boa.jpg"]["detalhes"] == "y"

    def test_json_invalido_apos_todas_tentativas_marca_erro(self, imagem_valida, monkeypatch):
        import autoavaria.services.ai_extraction as ai_extraction_module

        monkeypatch.setattr(ai_extraction_module, "RETRY_DELAY_SECONDS", 0)
        provider = _ProviderFalso(resposta_texto="isso não é json")
        resultado, tokens = extrair_dados_de_lote([imagem_valida], provider, {})

        assert resultado["IMG-boa.jpg"]["tipo"] == "Erro"
        assert tokens == 0
        assert len(provider.chamadas) == 3  # esgotou as 3 tentativas


class TestProcessarResultadoArquivo:
    def test_avaria_gera_linha_com_peso(self):
        resultados = {"IMG-1.jpg": {"tipo": "Avaria", "itens": [{"produto": "TOMATE", "peso": "1kg"}]}}
        avarias, uso_interno, erros = [], [], []

        processar_resultado_arquivo("IMG-1.jpg", resultados, {}, "/imagens", avarias, uso_interno, erros)

        assert len(avarias) == 1
        assert avarias[0]["Produto"] == "TOMATE"
        assert avarias[0]["Peso"] == "1kg"
        assert not uso_interno and not erros

    def test_avaria_sem_peso_vira_na(self):
        resultados = {"IMG-1.jpg": {"tipo": "Avaria", "itens": [{"produto": "TOMATE"}]}}
        avarias = []
        processar_resultado_arquivo("IMG-1.jpg", resultados, {}, "/imagens", avarias, [], [])
        assert avarias[0]["Peso"] == "N/A"

    def test_uso_interno_gera_linha_com_marca_e_codigo(self):
        resultados = {
            "IMG-2.jpg": {
                "tipo": "Uso Interno",
                "itens": [{"produto": "SACO DE LIXO", "marca": "X", "codigo_barras": "123"}],
            }
        }
        uso_interno = []
        processar_resultado_arquivo("IMG-2.jpg", resultados, {}, "/imagens", [], uso_interno, [])

        assert uso_interno[0]["Produto"] == "SACO DE LIXO"
        assert uso_interno[0]["Marca"] == "X"
        assert uso_interno[0]["Código de Barras"] == "123"

    def test_resultado_misto_separa_itens_por_categoria(self):
        resultados = {
            "IMG-misto.jpg": {
                "tipo": "Misto",
                "itens": [
                    {"categoria": "Avaria", "produto": "TOMATE", "peso": "0,5kg"},
                    {"categoria": "Uso Interno", "produto": "SACO", "codigo_barras": "123"},
                ],
            }
        }
        avarias, uso_interno, erros = [], [], []
        processar_resultado_arquivo(
            "IMG-misto.jpg", resultados, {}, "/imagens", avarias, uso_interno, erros
        )
        assert [item["Produto"] for item in avarias] == ["TOMATE"]
        assert [item["Produto"] for item in uso_interno] == ["SACO"]
        assert not erros

    def test_categoria_sem_itens_vira_erro(self):
        erros = []
        processar_resultado_arquivo(
            "IMG-vazia.jpg", {"IMG-vazia.jpg": {"tipo": "Avaria", "itens": []}},
            {}, "/imagens", [], [], erros,
        )
        assert len(erros) == 1
        assert "não retornou itens" in erros[0]["Detalhes do Erro"]

    def test_erro_gera_linha_com_detalhes(self):
        resultados = {"IMG-3.jpg": {"tipo": "Erro", "detalhes": "Falha na API"}}
        erros = []
        processar_resultado_arquivo("IMG-3.jpg", resultados, {}, "/imagens", [], [], erros)

        assert erros[0]["Arquivo"] == "IMG-3.jpg"
        assert erros[0]["Detalhes do Erro"] == "Falha na API"

    def test_arquivo_nao_retornado_vira_erro(self):
        """Se o lote não devolveu resultado pra esse arquivo, deve virar erro (não deve estourar)."""
        erros = []
        processar_resultado_arquivo("IMG-4.jpg", {}, {}, "/imagens", [], [], erros)
        assert len(erros) == 1
        assert erros[0]["Arquivo"] == "IMG-4.jpg"

    def test_multiplos_itens_na_mesma_imagem(self):
        """Uma foto pode conter vários produtos (ex: mensagem de texto lista vários itens)."""
        resultados = {
            "IMG-5.jpg": {
                "tipo": "Avaria",
                "itens": [
                    {"produto": "COENTRO", "peso": "N/A"},
                    {"produto": "ALFACE", "peso": "N/A"},
                ],
            }
        }
        avarias = []
        processar_resultado_arquivo("IMG-5.jpg", resultados, {}, "/imagens", avarias, [], [])
        assert len(avarias) == 2
        assert {a["Produto"] for a in avarias} == {"COENTRO", "ALFACE"}

    def test_mesma_imagem_compartilhada_entre_produtos(self):
        """Itens da mesma foto devem apontar para o mesmo caminho de imagem."""
        resultados = {
            "IMG-6.jpg": {
                "tipo": "Avaria",
                "itens": [{"produto": "A", "peso": "1kg"}, {"produto": "B", "peso": "2kg"}],
            }
        }
        avarias = []
        processar_resultado_arquivo("IMG-6.jpg", resultados, {}, "/imagens", avarias, [], [])
        assert avarias[0]["Caminho da Imagem"] == avarias[1]["Caminho da Imagem"]
