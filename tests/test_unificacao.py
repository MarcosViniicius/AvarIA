"""Testes de routes/unificacao.py.

O escopo da unificação passou a ser a VISÃO MESTRE do banco (todas as
execuções, deduplicadas - ver services/mestre.py), a mesma fonte do relatório
que aparece na tela de Relatório.

Antes o escopo era só a ÚLTIMA execução. Isso partia de uma premissa que não
vale mais: a de que o Excel mestre acumulava duplicatas de reenvios. Com o
banco como fonte e a dedup por conteúdo (produto + peso/detalhe + imagem), o
mesmo item vindo de execuções diferentes é UMA linha só - não há inflação a
evitar, e unificar "o relatório" passa a significar o relatório inteiro, como a
tela promete.

Dois cenários precisam ficar claros:
- item IGUAL em execuções diferentes -> 1 linha (dedup), nunca a soma dobrada;
- itens DIFERENTES (mesmo produto, pesos/imagens distintas) -> entram todos.
"""

import pytest

from avariaia import create_app
from avariaia.routes import unificacao as unificacao_route
from avariaia.services import db
from avariaia.services.report_editing import carregar_todas_sheets


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def ambiente(app, tmp_path, monkeypatch, tmp_db):
    (tmp_path / "resultados").mkdir()
    monkeypatch.setattr(unificacao_route, "BASE_PATH", str(tmp_path))
    return {"resultados": tmp_path / "resultados"}


def _registrar_execucao(itens_avarias=None, itens_uso_interno=None, status="concluido"):
    run_id = db.iniciar_execucao("processamento", imagens_total=1)
    if itens_avarias:
        db.registrar_itens(run_id, "Avarias", itens_avarias)
    if itens_uso_interno:
        db.registrar_itens(run_id, "Uso Interno", itens_uso_interno)
    db.finalizar_execucao(run_id, status, avarias=len(itens_avarias or []))
    return run_id


def _item_avaria(produto, peso, caminho=None):
    return {
        "Produto": produto, "Quantidade": "1", "Peso": peso,
        "Observação da Mensagem": "Nenhuma",
        "Caminho da Imagem": caminho or f"{produto}.jpg",
    }


class TestSemDadosNoBanco:
    def test_unificar_retorna_erro(self, app, ambiente):
        resposta = app.test_client().post("/api/unificar_relatorio", json={"formato": "xlsx"})
        assert resposta.status_code == 400
        assert resposta.get_json()["success"] is False

    def test_opcoes_retorna_404(self, app, ambiente):
        resposta = app.test_client().get("/api/opcoes_unificacao")
        assert resposta.status_code == 404


class TestEscopoDaUnificacao:
    def test_item_igual_em_execucoes_antigas_nao_infla(self, app, ambiente):
        """A mesma imagem/linha em duas execuções é UM dado (dedup), não dois.

        É a garantia que a regra antiga ("só a última execução") tentava dar:
        não contar a mesma coisa duas vezes. Agora vem da deduplicação.
        """
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg", caminho="t.jpg")])
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg", caminho="t.jpg")])

        sucesso, _, caminho = unificacao_route.processar_unificacao_completa()
        assert sucesso is True

        df = carregar_todas_sheets(caminho)["Avarias"]
        assert len(df) == 1
        assert df.iloc[0]["Produto"] == "TOMATE"
        assert df.iloc[0]["Quantidade Total"] == "3,000 kg"  # não 6kg

    def test_itens_diferentes_de_execucoes_diferentes_entram(self, app, ambiente):
        """Produtos distintos (ou a mesma fruta pesada em fotos diferentes) são
        dados diferentes: o relatório inteiro precisa mostrá-los."""
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "5kg", caminho="a.jpg")])
        _registrar_execucao(itens_avarias=[_item_avaria("BANANA", "3kg", caminho="b.jpg")])

        sucesso, _, caminho = unificacao_route.processar_unificacao_completa()
        assert sucesso is True

        df = carregar_todas_sheets(caminho)["Avarias"]
        produtos = sorted(df["Produto"])
        assert produtos == ["BANANA", "TOMATE"]

    def test_ainda_unifica_itens_repetidos_na_mesma_execucao(self, app, ambiente):
        """Mesmo produto, pesos diferentes: a unificação soma as quantidades."""
        _registrar_execucao(itens_avarias=[
            _item_avaria("TOMATE", "3kg", caminho="a.jpg"),
            _item_avaria("TOMATE", "2kg", caminho="b.jpg"),
        ])

        sucesso, _, caminho = unificacao_route.processar_unificacao_completa()
        assert sucesso is True

        df = carregar_todas_sheets(caminho)["Avarias"]
        assert len(df) == 1
        assert df.iloc[0]["Quantidade Total"] == "5,000 kg"

    def test_opcoes_unificacao_lista_as_secoes_do_mestre(self, app, ambiente):
        _registrar_execucao(itens_avarias=[_item_avaria("BANANA", "1kg", caminho="a.jpg")])
        _registrar_execucao(itens_avarias=[_item_avaria("MACA", "1kg", caminho="b.jpg")])

        resposta = app.test_client().get("/api/opcoes_unificacao")
        assert resposta.status_code == 200
        assert "Avarias" in resposta.get_json()["secoes"]

    def test_txt_nao_infla_item_repetido(self, app, ambiente):
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg", caminho="t.jpg")])
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg", caminho="t.jpg")])

        sucesso, _, caminho = unificacao_route.processar_unificacao_txt()
        assert sucesso is True

        conteudo = open(caminho, encoding="utf-8").read()
        assert "3,000 kg" in conteudo
        assert "6,000 kg" not in conteudo

    def test_execucao_de_erro_nao_esconde_o_resto(self, app, ambiente):
        """Uma execução que falhou (sem itens) não pode zerar a unificação.

        Era o bug observado: a "última execução" era um run falho/vazio e a
        unificação passava a não encontrar nada.
        """
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg", caminho="t.jpg")])
        _registrar_execucao(itens_avarias=[], status="erro")  # run vazio por último

        sucesso, mensagem, caminho = unificacao_route.processar_unificacao_txt()
        assert sucesso is True, mensagem
        conteudo = open(caminho, encoding="utf-8").read()
        assert "TOMATE" in conteudo
