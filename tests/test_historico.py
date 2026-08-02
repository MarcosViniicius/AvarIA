"""
Testes de routes/historico.py — foco na rota de reanálise versionada
(`POST /historico/execucao/<run_id>/reanalisar`) e nos dados de versão
passados a `historico_execucao` (usados pela UI da Tarefa 9).
"""

import time

import pytest

from autoavaria import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestHistoricoReanalisar:
    def test_bloqueia_reanalise_de_versao_que_nao_e_a_mais_recente(self, client, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        tmp_db.iniciar_reanalise_de_execucao(run_id)  # cria a versão 2, mais recente

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()

        assert corpo["success"] is False
        assert "mais recente" in corpo["message"].lower()

    def test_execucao_inexistente_retorna_404(self, client):
        resposta = client.post("/historico/execucao/9999/reanalisar")
        assert resposta.status_code == 404

    def test_bloqueia_se_ja_ha_processamento_ativo(self, client, tmp_db, monkeypatch):
        from autoavaria.services import app_state

        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        monkeypatch.setattr(app_state, "processamento_ativo", True)

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()
        assert corpo["success"] is False

    def test_reanalise_da_versao_mais_recente_inicia_com_sucesso(self, client, tmp_db, monkeypatch):
        from autoavaria.services import app_state

        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        monkeypatch.setattr(app_state, "processamento_ativo", False)

        chamadas = {}

        def fake_reanalisar_execucao(rid, callback_progresso=None):
            chamadas["run_id"] = rid
            return {"sucesso": True, "run_id": rid + 100, "total_arquivos": 0, "avarias": 0, "uso_interno": 0, "erros": 0}

        monkeypatch.setattr(
            "autoavaria.services.extraction_pipeline.reanalisar_execucao", fake_reanalisar_execucao
        )

        resposta = client.post(f"/historico/execucao/{run_id}/reanalisar")
        corpo = resposta.get_json()
        assert corpo["success"] is True

        time.sleep(0.2)  # dá tempo da thread de background rodar
        assert chamadas["run_id"] == run_id


class TestHistoricoExecucaoBotaoReanalisar:
    """Contrato entre a rota (Tarefa 8) e a UI (Tarefa 9): só a versão mais
    recente de uma linhagem deve receber o botão "Reanalisar" - a página de
    uma versão antiga deve escondê-lo (ver `eh_versao_mais_recente` em
    routes/historico.py e o `{% if eh_versao_mais_recente %}` no template)."""

    def test_versao_antiga_nao_mostra_botao_reanalisar_e_versao_nova_mostra(self, client, tmp_db):
        run_id = tmp_db.iniciar_execucao("processamento")
        tmp_db.finalizar_execucao(run_id, "concluido")
        nova_versao_id = tmp_db.iniciar_reanalise_de_execucao(run_id)
        tmp_db.finalizar_execucao(nova_versao_id, "concluido")

        # Busca o atributo `id="btnReanalisar"` do <button> em si, não a
        # string "btnReanalisar" pura - ela também aparece dentro do
        # <script> (ex.: `getElementById("btnReanalisar")`), que é renderizado
        # em toda página independente de `eh_versao_mais_recente`.
        resposta_antiga = client.get(f"/historico/execucao/{run_id}")
        assert resposta_antiga.status_code == 200
        assert b'id="btnReanalisar"' not in resposta_antiga.data

        resposta_nova = client.get(f"/historico/execucao/{nova_versao_id}")
        assert resposta_nova.status_code == 200
        assert b'id="btnReanalisar"' in resposta_nova.data
