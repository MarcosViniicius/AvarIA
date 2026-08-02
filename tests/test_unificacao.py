"""Testes de routes/unificacao.py.

Bug relatado: "Unificar Relatório" somava itens de TODAS as análises já
feitas (lendo o Excel mestre acumulado), quando deveria unificar só o que
está sendo mostrado na tela - a última execução (mesma fonte que
routes/relatorio.py usa). Uma execução antiga com o mesmo produto não pode
entrar na soma de uma unificação feita depois.
"""

import pytest

from autoavaria import create_app
from autoavaria.routes import unificacao as unificacao_route
from autoavaria.services import db
from autoavaria.services.report_editing import carregar_todas_sheets


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


def _item_avaria(produto, peso):
    return {
        "Produto": produto, "Quantidade": "1", "Peso": peso,
        "Observação da Mensagem": "Nenhuma", "Caminho da Imagem": f"{produto}.jpg",
    }


class TestSemExecucaoNoBanco:
    def test_unificar_retorna_erro(self, app, ambiente):
        resposta = app.test_client().post("/api/unificar_relatorio", json={"formato": "xlsx"})
        assert resposta.status_code == 400
        assert resposta.get_json()["success"] is False

    def test_opcoes_retorna_404(self, app, ambiente):
        resposta = app.test_client().get("/api/opcoes_unificacao")
        assert resposta.status_code == 404


class TestUnificarUsaSoAUltimaExecucao:
    def test_produto_de_execucao_antiga_nao_entra_na_soma(self, app, ambiente):
        """O caso real do bug: uma execução antiga (TOMATE, 5kg) não pode
        somar com a mais recente (TOMATE, 3kg) - o total unificado tem que
        refletir só a última execução (3kg), não o acumulado (8kg)."""
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "5kg")])
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg")])

        sucesso, mensagem, caminho = unificacao_route.processar_unificacao_completa()
        assert sucesso is True

        sheets = carregar_todas_sheets(caminho)
        df = sheets["Avarias"]
        assert len(df) == 1
        assert df.iloc[0]["Produto"] == "TOMATE"
        assert df.iloc[0]["Quantidade Total"] == "3,000 kg"

    def test_ainda_unifica_itens_repetidos_dentro_da_mesma_execucao(self, app, ambiente):
        """A unificação em si continua funcionando normalmente - só o
        ESCOPO (que execução considerar) que mudou."""
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "5kg")])
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg"), _item_avaria("TOMATE", "2kg")])

        sucesso, mensagem, caminho = unificacao_route.processar_unificacao_completa()
        assert sucesso is True

        sheets = carregar_todas_sheets(caminho)
        df = sheets["Avarias"]
        assert len(df) == 1
        assert df.iloc[0]["Quantidade Total"] == "5,000 kg"

    def test_opcoes_unificacao_reflete_so_a_ultima_execucao(self, app, ambiente):
        _registrar_execucao(itens_avarias=[_item_avaria("BANANA", "1kg")])
        _registrar_execucao(itens_avarias=[_item_avaria("MACA", "1kg")])

        resposta = app.test_client().get("/api/opcoes_unificacao")
        assert resposta.status_code == 200
        assert "Avarias" in resposta.get_json()["secoes"]

    def test_txt_tambem_usa_so_a_ultima_execucao(self, app, ambiente):
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "5kg")])
        _registrar_execucao(itens_avarias=[_item_avaria("TOMATE", "3kg")])

        sucesso, mensagem, caminho = unificacao_route.processar_unificacao_txt()
        assert sucesso is True

        conteudo = open(caminho, encoding="utf-8").read()
        assert "3,000 kg" in conteudo
        assert "8,000 kg" not in conteudo
