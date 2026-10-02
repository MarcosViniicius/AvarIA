"""Matriz de classificação/categorização — CURADA (sem duplicatas).

Complementa (não repete) `test_extraction_engines.py` e `test_ai_extraction.py`:
aqui só estão os casos que NÃO tinham cobertura antes — sinais de categoria,
prioridades, variações de catálogo, comportamento da balança, erros de leitor,
aprendizado defensivo e saneamento de relatório. Os casos base (EAN→Erro,
balança→N/A/0,738kg, Misto válido, híbrido→IA) continuam nos arquivos origem.

Regras (ver docs/ARQUITETURA_PROCESSAMENTO.md):
- EAN sozinho NUNCA decide categoria → Erro orientando.
- Balança (prefixo 2) é SEMPRE Avaria.
- Quantidade só vem da conversa; default 1.
"""

from unittest.mock import MagicMock, patch

import pytest

from avariaia.services import catalogo, extraction_engines as engines
from avariaia.services import ai_extraction
from avariaia.services.barcode import CodigoLido
from avariaia.services.conversa import ContextoImagem


def _codigo(texto, estrategia="original"):
    return CodigoLido(texto=texto, formato="EAN-13", estrategia=estrategia)


def _ctx(texto="", quantidade=None):
    textos = [texto] if texto else []
    return ContextoImagem(imagem="a.jpg", textos=textos, quantidade=quantidade)


EAN = "7897274410245"
BALANCA = "2001400005167"  # PLU 00140, total R$ 5,16


# ---------------------------------------------------------------------------
# Sinais de categoria no texto (unitário — o motor só tinha 1 caso via E2E)
# ---------------------------------------------------------------------------

class TestCategoriaDoContexto:
    @pytest.mark.parametrize("texto", [
        "produto avariado", "AVARIA total", "quebrado na entrega",
        "estragada", "danificado", "vencido", "perda de hoje", "descarte",
    ])
    def test_sinais_de_avaria(self, texto):
        assert engines._categoria_do_contexto(_ctx(texto)) == "Avaria"

    @pytest.mark.parametrize("texto", [
        "uso interno", "consumo interno", "para a equipe", "funcionários",
    ])
    def test_sinais_de_uso_interno(self, texto):
        assert engines._categoria_do_contexto(_ctx(texto)) == "Uso Interno"

    @pytest.mark.parametrize("texto", ["", "foto da entrega", "7897274410245", "produto bonito"])
    def test_texto_neutro_nao_decide(self, texto):
        assert engines._categoria_do_contexto(_ctx(texto)) is None

    def test_none_nao_decide(self):
        assert engines._categoria_do_contexto(None) is None

    def test_avaria_tem_prioridade_sobre_uso_interno(self):
        assert engines._categoria_do_contexto(_ctx("avaria para uso interno")) == "Avaria"


class TestCategoriaCatalogo:
    @pytest.mark.parametrize("categoria", ["avaria", "Avarias", "AVARIA"])
    def test_variacoes_avaria(self, categoria):
        assert engines._categoria_catalogo({"categoria_padrao": categoria}) == "Avaria"

    @pytest.mark.parametrize("categoria", ["Uso Interno", "uso_interno", "USO INTERNO"])
    def test_variacoes_uso_interno(self, categoria):
        assert engines._categoria_catalogo({"categoria_padrao": categoria}) == "Uso Interno"

    @pytest.mark.parametrize("categoria", ["", "desconhecida", None])
    def test_categoria_desconhecida(self, categoria):
        assert engines._categoria_catalogo({"categoria_padrao": categoria}) is None


# ---------------------------------------------------------------------------
# Motor sem IA: só casos sem cobertura prévia
# ---------------------------------------------------------------------------

class TestMotorCodigoBarrasCasosNovos:
    def test_ean_com_texto_uso_interno_vira_uso_interno(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo(EAN)]):
            res = motor.processar_imagem("a.jpg", _ctx("para uso interno da equipe"))
        assert res["tipo"] == "Uso Interno"

    def test_ean_com_catalogo_avarias_plural_sem_texto(self, tmp_db):
        catalogo.registrar(EAN, produto="TOMATE", categoria_padrao="Avarias")
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo(EAN)]):
            res = motor.processar_imagem("a.jpg", None)
        assert res["tipo"] == "Avaria"

    def test_texto_vence_catalogo_divergente(self, tmp_db):
        catalogo.registrar(EAN, produto="X", categoria_padrao="Uso Interno")
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo(EAN)]):
            res = motor.processar_imagem("a.jpg", _ctx("quebrado"))
        assert res["tipo"] == "Avaria"

    def test_balanca_e_sempre_avaria_mesmo_com_texto_uso_interno(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo(BALANCA)]):
            res = motor.processar_imagem("a.jpg", _ctx("uso interno"))
        assert res["tipo"] == "Avaria"

    def test_balanca_dv_quebrado_vira_erro(self, tmp_db):
        from avariaia.services import barcode
        assert barcode.interpretar_etiqueta_balanca("2001400005160") is None
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo("2001400005160")]):
            res = motor.processar_imagem("a.jpg", None)
        assert res["tipo"] == "Erro"

    def test_dois_eans_mesma_categoria_nao_e_misto(self, tmp_db):
        catalogo.registrar(EAN, produto="A", categoria_padrao="Uso Interno")
        catalogo.registrar("7898339101122", produto="B", categoria_padrao="Uso Interno")
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem",
                          return_value=[_codigo(EAN), _codigo("7898339101122")]):
            res = motor.processar_imagem("a.jpg", None)
        assert res["tipo"] == "Uso Interno"
        assert len(res["itens"]) == 2

    def test_leitor_quebra_vira_erro(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", side_effect=RuntimeError("sem deps")):
            res = motor.processar_imagem("a.jpg", None)
        assert res["tipo"] == "Erro"

    def test_sem_quantidade_default_1(self, tmp_db):
        motor = engines.MotorCodigoBarras()
        with patch.object(engines.barcode, "ler_imagem", return_value=[_codigo(BALANCA)]):
            res = motor.processar_imagem("a.jpg", None)
        assert res["itens"][0]["quantidade"] == 1


# ---------------------------------------------------------------------------
# Híbrido / aprendizado: só casos sem cobertura prévia
# ---------------------------------------------------------------------------

class TestMotorHibridoCasosNovos:
    def test_quantidade_aplicada_no_resultado_da_ia(self, tmp_db):
        motor = engines.MotorHibrido(MagicMock())
        ctx = {"a.jpg": ContextoImagem(imagem="a.jpg", textos=["x"], quantidade=4)}
        resposta = {"a.jpg": {"tipo": "Avaria", "itens": [{"produto": "P", "peso": "N/A"}]}}
        with patch.object(engines.barcode, "ler_imagem", return_value=[]), \
             patch.object(engines.ai_extraction, "extrair_dados_de_lote",
                          return_value=(resposta, 1)):
            resultados, _ = motor.processar_lote(["a.jpg"], ctx)
        assert resultados["a.jpg"]["itens"][0]["quantidade"] == 4

    def test_aprender_ignora_codigo_invalido(self, tmp_db):
        engines._aprender_do_resultado({
            "a.jpg": {"tipo": "Avaria", "itens": [
                {"produto": "X", "codigo_barras": "123"},
                {"produto": "Y", "codigo_barras": "N/A"},
                {"produto": "Z"},
            ]}})
        assert catalogo.contar().get("total", 0) == 0

    def test_aprender_nao_quebra_com_excecao(self, tmp_db):
        with patch.object(catalogo, "aprender", side_effect=RuntimeError("db fora")):
            engines._aprender_do_resultado({
                "a.jpg": {"tipo": "Uso Interno", "itens": [
                    {"produto": "P", "codigo_barras": EAN}]}})

    def test_peso_para_float_variantes(self):
        assert engines._peso_para_float("0,738kg") == pytest.approx(0.738)
        assert engines._peso_para_float("1.804 kg") == pytest.approx(1.804)
        assert engines._peso_para_float(0.5) == pytest.approx(0.5)
        assert engines._peso_para_float("N/A") is None
        assert engines._peso_para_float("") is None
        assert engines._peso_para_float(None) is None
        assert engines._peso_para_float("0kg") is None


# ---------------------------------------------------------------------------
# Split Misto / relatório: só casos sem cobertura prévia
# ---------------------------------------------------------------------------

def _processar(nome, resultado, msg=""):
    av, uso, err = [], [], []
    ai_extraction.processar_resultado_arquivo(
        nome, {nome: resultado}, {nome: msg}, "/tmp", av, uso, err)
    return av, uso, err


class TestSplitMistoCasosNovos:
    def test_misto_com_item_sem_categoria_vira_erro(self):
        res = {"tipo": "Misto", "itens": [
            {"categoria": "Avaria", "produto": "P", "peso": "1kg"},
            {"produto": "SEM CATEGORIA"},
        ]}
        av, uso, err = _processar("a.jpg", res)
        assert not av and not uso and len(err) == 1

    def test_misto_vazio_vira_erro(self):
        av, uso, err = _processar("a.jpg", {"tipo": "Misto", "itens": []})
        assert len(err) == 1

    def test_uso_interno_sem_itens_vira_erro(self):
        av, uso, err = _processar("a.jpg", {"tipo": "Uso Interno"})
        assert not uso and len(err) == 1

    def test_tipo_desconhecido_vira_erro(self):
        av, uso, err = _processar("a.jpg", {"tipo": "Indefinido", "itens": []})
        assert len(err) == 1

    @pytest.mark.parametrize("qtd,esperado", [
        (None, 1), (0, 1), (-3, 1), ("abc", 1), ("5", 5), (7, 7),
    ])
    def test_quantidade_do_item_saneada(self, qtd, esperado):
        assert ai_extraction._quantidade_do_item({"quantidade": qtd}) == esperado

    def test_observacao_quebra_de_linha_vira_pipe(self):
        av, _, _ = _processar("a.jpg",
                              {"tipo": "Avaria",
                               "itens": [{"produto": "P", "peso": "1kg"}]},
                              msg="linha1\nlinha2")
        assert av[0]["Observação da Mensagem"] == "linha1 | linha2"

    def test_observacao_vazia_vira_nenhuma(self):
        av, _, _ = _processar("a.jpg",
                              {"tipo": "Avaria",
                               "itens": [{"produto": "P", "peso": "1kg"}]})
        assert av[0]["Observação da Mensagem"] == "Nenhuma"
