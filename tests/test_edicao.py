"""Testes de routes/edicao.py.

A tela de edição lê a visão mestre do BANCO (services/mestre.py) e cada edição
grava direto nos itens (`report_items`). A linha carrega `id_linha` = id do item
no banco; uma mesma linha exibida pode corresponder a vários itens (mesma
imagem em execuções diferentes), e a edição é propagada para todos.
"""

import pytest

from avariaia import create_app
from avariaia.services import db


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def ambiente(app, tmp_path, monkeypatch, tmp_db):
    run_id = db.iniciar_execucao("processamento", imagens_total=2)
    db.registrar_itens(
        run_id, "Avarias",
        [{"Produto": "TOMATE", "Quantidade": "1", "Peso": "1,5kg",
          "Observação da Mensagem": "Nenhuma", "Caminho da Imagem": "a.jpg"}],
    )
    db.registrar_itens(
        run_id, "Uso Interno",
        [{"Produto": "SACO DE LIXO", "Quantidade": "2", "Marca": "N/A",
          "Código de Barras": "789", "Observação da Mensagem": "Nenhuma",
          "Caminho da Imagem": "b.jpg"}],
    )
    return {
        "run_id": run_id,
        "id_avaria": db.buscar_item_por_caminho("Avarias", "a.jpg"),
        "id_uso": db.buscar_item_por_caminho("Uso Interno", "b.jpg"),
    }


class TestSalvarEdicaoSincronizaBanco:
    def test_edita_campo_unico_e_reflete_no_banco(self, app, ambiente):
        client = app.test_client()
        resposta = client.post(
            "/salvar_edicao",
            json={"sheet_name": "Avarias", "linha_id": ambiente["id_avaria"],
                  "campo": "Produto", "novo_valor": "TOMATE ITALIANO"},
        )
        assert resposta.get_json()["success"] is True

        item_id = db.buscar_item_por_caminho("Avarias", "a.jpg")
        assert db.obter_item(item_id)["produto"] == "TOMATE ITALIANO"

    def test_edicao_completa_reflete_no_banco(self, app, ambiente):
        client = app.test_client()
        resposta = client.post(
            "/salvar_edicao_completa",
            json={
                "sheet_name": "Uso Interno", "linha_id": ambiente["id_uso"],
                "dados_linha": {"Produto": "SACO DE LIXO 100L", "Marca": "PLASTPACK"},
            },
        )
        assert resposta.get_json()["success"] is True

        item_id = db.buscar_item_por_caminho("Uso Interno", "b.jpg")
        item = db.obter_item(item_id)
        assert item["produto"] == "SACO DE LIXO 100L"
        assert item["marca"] == "PLASTPACK"


class TestExcluirLinhaSincronizaBanco:
    def test_exclusao_remove_do_banco_tambem(self, app, ambiente):
        client = app.test_client()
        assert db.buscar_item_por_caminho("Avarias", "a.jpg") is not None

        resposta = client.post(
            "/excluir_linha",
            json={"sheet_name": "Avarias", "linha_id": ambiente["id_avaria"]},
        )
        assert resposta.get_json()["success"] is True

        assert db.buscar_item_por_caminho("Avarias", "a.jpg") is None

    def test_exclusao_recalcula_contagem_da_execucao(self, app, ambiente):
        client = app.test_client()
        client.post(
            "/excluir_linha",
            json={"sheet_name": "Avarias", "linha_id": ambiente["id_avaria"]},
        )

        execucao = db.obter_execucao(ambiente["run_id"])
        assert execucao["avarias"] == 0


class TestMoverItemSincronizaBanco:
    def test_movimentacao_muda_categoria_no_banco(self, app, ambiente):
        client = app.test_client()
        resposta = client.post(
            "/mover_item",
            json={"sheet_origem": "Avarias", "sheet_destino": "Uso Interno",
                  "linha_id": ambiente["id_avaria"]},
        )
        assert resposta.get_json()["success"] is True

        # não está mais em Avarias no banco...
        assert db.buscar_item_por_caminho("Avarias", "a.jpg") is None
        # ...e passou a existir em Uso Interno
        item_id = db.buscar_item_por_caminho("Uso Interno", "a.jpg")
        assert item_id is not None
        assert db.obter_item(item_id)["categoria"] == "Uso Interno"


class TestAdicionarLinhaSincronizaBanco:
    def test_nova_linha_manual_entra_no_banco_sem_run_id(self, app, ambiente):
        client = app.test_client()
        resposta = client.post(
            "/adicionar_linha",
            json={
                "sheet_name": "Avarias",
                "dados_linha": {"Produto": "BATATA", "Quantidade": "3", "Peso": "2kg"},
            },
        )
        assert resposta.get_json()["success"] is True

        with db.get_connection() as conn:
            linha = conn.execute(
                "SELECT * FROM report_items WHERE produto = 'BATATA'"
            ).fetchone()
        assert linha is not None
        assert linha["run_id"] is None
