"""Testes de routes/dashboard.py e do aviso de chave de API ausente.

Antes, a falta de chave só era percebida no MEIO do processamento (o
usuário subia os arquivos, clicava em processar, e só aí via o erro). Agora
o Dashboard e a tela de Upload avisam antes, e sugerem o modo "Sem IA" como
alternativa sem custo.
"""

import pytest

from avariaia import create_app
from avariaia.services import config_service


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def config_sem_chave(monkeypatch):
    """Simula uma configuração sem nenhuma chave de API, modo IA (padrão)."""
    def fake_carregar():
        return {
            "api": {"provider": "gemini", "gemini_api_key": "", "openai_api_key": "",
                     "anthropic_api_key": "", "openrouter_api_key": ""},
            "processamento": {"modo_extracao": "ia"},
            "interface": {},
        }
    monkeypatch.setattr(config_service, "carregar_configuracao", fake_carregar)


@pytest.fixture
def config_com_chave(monkeypatch):
    def fake_carregar():
        return {
            "api": {"provider": "gemini", "gemini_api_key": "AIzaFAKE123", "openai_api_key": "",
                     "anthropic_api_key": "", "openrouter_api_key": ""},
            "processamento": {"modo_extracao": "ia"},
            "interface": {},
        }
    monkeypatch.setattr(config_service, "carregar_configuracao", fake_carregar)


@pytest.fixture
def config_sem_chave_modo_sem_ia(monkeypatch):
    def fake_carregar():
        return {
            "api": {"provider": "gemini", "gemini_api_key": "", "openai_api_key": "",
                     "anthropic_api_key": "", "openrouter_api_key": ""},
            "processamento": {"modo_extracao": "sem_ia"},
            "interface": {},
        }
    monkeypatch.setattr(config_service, "carregar_configuracao", fake_carregar)


class TestAvisoChaveAusente:
    def test_dashboard_mostra_aviso_sem_chave(self, app, config_sem_chave):
        resposta = app.test_client().get("/")
        html = resposta.get_data(as_text=True)
        assert "Nenhuma chave de API configurada" in html

    def test_dashboard_nao_mostra_aviso_com_chave(self, app, config_com_chave):
        resposta = app.test_client().get("/")
        html = resposta.get_data(as_text=True)
        assert "Nenhuma chave de API configurada" not in html

    def test_dashboard_nao_mostra_aviso_no_modo_sem_ia(self, app, config_sem_chave_modo_sem_ia):
        """Modo sem_ia não precisa de chave nenhuma - o aviso seria falso alarme."""
        resposta = app.test_client().get("/")
        html = resposta.get_data(as_text=True)
        assert "Nenhuma chave de API configurada" not in html

    def test_upload_mostra_aviso_sem_chave(self, app, config_sem_chave):
        resposta = app.test_client().get("/upload")
        html = resposta.get_data(as_text=True)
        assert "Nenhuma chave de API configurada" in html

    def test_aviso_sugere_modo_sem_ia_e_link_de_configuracao(self, app, config_sem_chave):
        resposta = app.test_client().get("/")
        html = resposta.get_data(as_text=True)
        assert "Sem IA" in html
        assert 'href="/configuracoes"' in html
