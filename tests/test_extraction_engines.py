"""Testes dos motores de extração (services/extraction_engines.py).

O motor de código de barras e o híbrido são testados com o leitor de
código de barras mockado (`barcode.ler_imagem`), para não depender de
imagens reais nem do zxing-cpp estar instalado. O comportamento do
`MotorIA` é verificado apenas por delegação - a lógica de IA em si já tem
cobertura própria em test_ai_extraction.py.
"""

from unittest.mock import MagicMock, patch

import pytest

from avariaia.services import catalogo, db, extraction_engines as engines
from avariaia.services.barcode import CodigoLido
from avariaia.services.conversa import ContextoImagem


def _codigo(texto, estrategia="original"):
    return CodigoLido(texto=texto, formato="EAN-13", estrategia=estrategia)


class TestMotorIA:
    def test_delega_para_ai_extraction(self):
        provider = MagicMock()
        motor = engines.MotorIA(provider)
        with patch.object(
            engines.ai_extraction, "extrair_dados_de_lote",
            return_value=({"a.jpg": {"tipo": "Erro"}}, 42),
        ) as mock_extrair:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})
        mock_extrair.assert_called_once()
        assert tokens == 42
        assert resultados == {"a.jpg": {"tipo": "Erro"}}


class TestMotorCodigoBarras:
    def test_ean_sem_categoria_nao_assume_uso_interno(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("7897274410245")]):
            resultado = motor.processar_imagem("qualquer.jpg", None)
        assert resultado["tipo"] == "Erro"
        assert "não informa" in resultado["detalhes"]

    def test_uso_interno_com_catalogo_traz_produto_e_marca(self, tmp_db):
        catalogo.registrar(
            "7897274410245", produto="LAVA-LOUÇAS", marca="GUARANI",
            categoria_padrao="Uso Interno",
        )
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("7897274410245")]):
            resultado = motor.processar_imagem("qualquer.jpg", None)
        item = resultado["itens"][0]
        assert item["produto"] == "LAVA-LOUÇAS"
        assert item["marca"] == "GUARANI"

    def test_balanca_sem_preco_no_catalogo_devolve_peso_na(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]):
            resultado = motor.processar_imagem("qualquer.jpg", None)
        assert resultado["tipo"] == "Avaria"
        assert resultado["itens"][0]["peso"] == "N/A"

    def test_balanca_com_preco_no_catalogo_calcula_peso(self, tmp_db):
        catalogo.registrar("00140", produto="MANGA", preco_kg=6.99, tipo="plu")
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]):
            resultado = motor.processar_imagem("qualquer.jpg", None)
        item = resultado["itens"][0]
        assert item["produto"] == "MANGA"
        assert item["peso"] == "0,738kg"

    def test_quantidade_do_contexto_e_aplicada(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        contexto = ContextoImagem(imagem="a.jpg", textos=["uso interno"], quantidade=7)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("7897274410245")]):
            resultado = motor.processar_imagem("a.jpg", contexto)
        assert resultado["itens"][0]["quantidade"] == 7

    def test_contexto_explicito_classifica_ean_como_avaria(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        contexto = ContextoImagem(imagem="a.jpg", textos=["produto avariado"], quantidade=1)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("7897274410245")]):
            resultado = motor.processar_imagem("a.jpg", contexto)
        assert resultado["tipo"] == "Avaria"

    def test_codigos_de_categorias_diferentes_permitem_resultado_misto(self, tmp_db):
        catalogo.registrar(
            "7897274410245", produto="LAVA-LOUÇAS", categoria_padrao="Uso Interno"
        )
        motor = engines.MotorCodigoBarras()
        codigos = [_codigo("2001400005167"), _codigo("7897274410245")]
        with patch.object(engines.barcode, "ler_imagem", return_value=codigos):
            resultado = motor.processar_imagem("a.jpg", None)
        assert resultado["tipo"] == "Misto"
        assert {item["categoria"] for item in resultado["itens"]} == {"Avaria", "Uso Interno"}

    def test_nenhum_codigo_lido_vira_erro(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[]):
            resultado = motor.processar_imagem("a.jpg", None)
        assert resultado["tipo"] == "Erro"

    def test_processar_lote_nao_consome_tokens(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[]):
            resultados, tokens = motor.processar_lote(["a.jpg", "b.jpg"], {})
        assert tokens == 0
        assert set(resultados.keys()) == {"a.jpg", "b.jpg"}


class TestMotorHibrido:
    def test_resolvido_localmente_nao_chama_ia(self, tmp_db):
        catalogo.registrar(
            "7897274410245", produto="LAVA-LOUÇAS", marca="GUARANI",
            categoria_padrao="Uso Interno",
        )
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("7897274410245")]), \
             patch.object(engines.ai_extraction, "extrair_dados_de_lote") as mock_ia:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})
        mock_ia.assert_not_called()
        assert tokens == 0
        assert resultados["a.jpg"]["tipo"] == "Uso Interno"

    def test_balanca_sem_preco_vai_para_ia(self, tmp_db):
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=({"a.jpg": {"tipo": "Avaria", "itens": [{"produto": "MANGA", "peso": "0,738kg"}]}}, 100),
             ) as mock_ia:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})
        mock_ia.assert_called_once()
        assert tokens == 100
        assert resultados["a.jpg"]["itens"][0]["produto"] == "MANGA"

    def test_nenhum_codigo_lido_vai_para_ia(self, tmp_db):
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=({"a.jpg": {"tipo": "Erro", "detalhes": "sem info"}}, 50),
             ) as mock_ia:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})
        mock_ia.assert_called_once()
        assert tokens == 50

    def test_hibrido_aprende_preco_kg_da_resposta_da_ia(self, tmp_db):
        """O motor híbrido deve ensinar o catálogo com o que a IA descobriu."""
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=(
                     {"a.jpg": {"tipo": "Avaria", "itens": [
                         {"produto": "MANGA", "peso": "0,738kg", "codigo_barras": "2001400005167"}
                     ]}},
                     100,
                 ),
             ):
            motor.processar_lote(["a.jpg"], {})
        entrada = catalogo.buscar("00140")
        assert entrada is not None
        assert entrada["preco_kg"] == pytest.approx(6.99, abs=0.01)

    def test_hibrido_aprende_produto_ean_da_resposta_da_ia(self, tmp_db):
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=(
                     {"a.jpg": {"tipo": "Uso Interno", "itens": [
                         {"produto": "LAVA-LOUÇAS", "marca": "GUARANI", "codigo_barras": "7897274410245"}
                     ]}},
                     10,
                 ),
             ):
            motor.processar_lote(["a.jpg"], {})
        entrada = catalogo.buscar("7897274410245")
        assert entrada is not None
        assert entrada["produto"] == "LAVA-LOUÇAS"

    def test_ia_alucina_peso_absurdo_nao_e_aprendido_no_catalogo(self, tmp_db):
        """Se a IA disser um peso implausível, o catálogo não deve aceitar -
        senão o erro se propagaria para toda leitura futura desse PLU."""
        provider = MagicMock()
        motor = engines.MotorHibrido(provider)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=(
                     {"a.jpg": {"tipo": "Avaria", "itens": [
                         {"produto": "MANGA", "peso": "50,000kg", "codigo_barras": "2001400005167"}
                     ]}},
                     100,
                 ),
             ):
            motor.processar_lote(["a.jpg"], {})
        assert catalogo.buscar("00140") is None
        assert len(catalogo.listar_revisoes_pendentes()) == 1

    def test_plu_resolvido_mas_desatualizado_volta_para_ia(self, tmp_db):
        """Preço/kg aprendido há muito tempo não deve ser confiado para sempre."""
        import datetime as dt

        ha_60_dias = (dt.datetime.now() - dt.timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        catalogo.registrar("00140", produto="MANGA", preco_kg=6.99, tipo="plu")
        with db.get_connection() as conn:
            conn.execute("UPDATE catalogo_produtos SET atualizado_em = ? WHERE codigo = ?", (ha_60_dias, "00140"))

        provider = MagicMock()
        motor = engines.MotorHibrido(provider, dias_para_reverificar=30)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]), \
             patch.object(
                 engines.ai_extraction, "extrair_dados_de_lote",
                 return_value=({"a.jpg": {"tipo": "Avaria", "itens": [{"produto": "MANGA", "peso": "0,738kg"}]}}, 100),
             ) as mock_ia:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})

        mock_ia.assert_called_once()  # apesar de já ter preço/kg, é antigo demais
        assert tokens == 100

    def test_plu_resolvido_e_recente_nao_vai_para_ia(self, tmp_db):
        """Contraste com o teste acima: preço/kg recém-aprendido é confiado."""
        catalogo.registrar("00140", produto="MANGA", preco_kg=6.99, tipo="plu")  # atualizado_em = agora

        provider = MagicMock()
        motor = engines.MotorHibrido(provider, dias_para_reverificar=30)
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005167")]), \
             patch.object(engines.ai_extraction, "extrair_dados_de_lote") as mock_ia:
            resultados, tokens = motor.processar_lote(["a.jpg"], {})

        mock_ia.assert_not_called()
        assert tokens == 0
        assert resultados["a.jpg"]["itens"][0]["peso"] == "0,738kg"


class TestConstruirMotor:
    def test_modo_ia_precisa_de_provider(self):
        with pytest.raises(ValueError):
            engines.construir_motor(engines.MODO_IA, provider=None)

    def test_modo_hibrido_precisa_de_provider(self):
        with pytest.raises(ValueError):
            engines.construir_motor(engines.MODO_HIBRIDO, provider=None)

    def test_modo_sem_ia_nao_precisa_de_provider(self):
        motor = engines.construir_motor(engines.MODO_SEM_IA, provider=None)
        assert isinstance(motor, engines.MotorCodigoBarras)

    def test_modo_padrao_e_ia(self):
        provider = MagicMock()
        motor = engines.construir_motor("", provider=provider)
        assert isinstance(motor, engines.MotorIA)

    def test_modo_desconhecido_cai_para_ia(self):
        provider = MagicMock()
        motor = engines.construir_motor("modo-que-nao-existe", provider=provider)
        assert isinstance(motor, engines.MotorIA)

    def test_sem_ia_indisponivel_cai_para_ia_se_tiver_provider(self):
        provider = MagicMock()
        with patch.object(engines.barcode, "LEITURA_DISPONIVEL", False):
            motor = engines.construir_motor(engines.MODO_SEM_IA, provider=provider)
        assert isinstance(motor, engines.MotorIA)

    def test_hibrido_propaga_dias_para_reverificar(self):
        provider = MagicMock()
        motor = engines.construir_motor(engines.MODO_HIBRIDO, provider=provider, dias_para_reverificar=7)
        assert motor.dias_para_reverificar == 7

    def test_hibrido_sem_dias_usa_padrao_da_classe(self):
        provider = MagicMock()
        motor = engines.construir_motor(engines.MODO_HIBRIDO, provider=provider)
        assert motor.dias_para_reverificar == catalogo.DIAS_PARA_REVERIFICAR_PADRAO

    def test_sem_ia_indisponivel_sem_provider_levanta_erro(self):
        with patch.object(engines.barcode, "LEITURA_DISPONIVEL", False):
            with pytest.raises(RuntimeError):
                engines.construir_motor(engines.MODO_SEM_IA, provider=None)
