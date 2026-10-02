"""Smoke test: a aplicação sobe e as páginas principais respondem.

Usa o ambiente real (config/resultados/database reais, só leitura via GET)
como guarda de regressão contra erros de importação/rota quebrada — não
valida conteúdo de negócio, só que nada quebrou ao montar o app.
"""

import pytest

from avariaia import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


ROTAS_SOMENTE_LEITURA = [
    "/",
    "/upload",
    "/relatorio",
    "/editar_dados",
    "/logs",
    "/configuracoes",
    "/historico",
    "/api/stats",
    "/api/logs",
]


@pytest.mark.parametrize("rota", ROTAS_SOMENTE_LEITURA)
def test_rota_nao_quebra(client, rota):
    resposta = client.get(rota)
    assert resposta.status_code < 500, f"{rota} retornou {resposta.status_code}"


def test_download_config_nao_vaza_chave_de_api(client):
    import json
    from avariaia.core.paths import CONFIG_FILE

    if not CONFIG_FILE.exists():
        pytest.skip("config/config.json não existe neste ambiente")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config_real = json.load(f)
    chave_real = config_real.get("api", {}).get("gemini_api_key", "")

    resposta = client.get("/download_config")
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    if chave_real:
        assert chave_real not in corpo
        assert "REMOVIDA_POR_SEGURANCA" in corpo


def test_historico_execucao_inexistente_retorna_404(client):
    resposta = client.get("/historico/execucao/999999999")
    assert resposta.status_code == 404
