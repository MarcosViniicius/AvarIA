"""Testes do service de configuração (services/config_service.py): cache,
env override e defaults."""
import json

from autoavaria.services import config_service


def _reset_cache(monkeypatch):
    monkeypatch.setattr(config_service, "_config_cache", None)
    monkeypatch.setattr(config_service, "_config_cache_time", None)


def test_recarrega_arquivo_quando_expira_ttl(tmp_path, monkeypatch):
    caminho = tmp_path / "config.json"
    caminho.write_text(json.dumps({"api": {"provider": "openai", "openai_api_key": "primeira"}}), encoding="utf-8")
    monkeypatch.setattr(config_service, "CONFIG_FILE", str(caminho))
    monkeypatch.setattr(config_service, "CONFIG_CACHE_TTL", 10)
    monkeypatch.setattr(config_service.time, "time", lambda: 100)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _reset_cache(monkeypatch)

    assert config_service.carregar_configuracao()["api"]["openai_api_key"] == "primeira"
    caminho.write_text(json.dumps({"api": {"provider": "openai", "openai_api_key": "segunda"}}), encoding="utf-8")

    monkeypatch.setattr(config_service.time, "time", lambda: 105)
    assert config_service.carregar_configuracao()["api"]["openai_api_key"] == "primeira"
    monkeypatch.setattr(config_service.time, "time", lambda: 111)
    assert config_service.carregar_configuracao()["api"]["openai_api_key"] == "segunda"


def test_variavel_openrouter_tem_precedencia_sobre_config(tmp_path, monkeypatch):
    caminho = tmp_path / "config.json"
    caminho.write_text(
        json.dumps({"api": {"provider": "openrouter", "openrouter_api_key": ""}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_service, "CONFIG_FILE", str(caminho))
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter")
    _reset_cache(monkeypatch)

    config = config_service.carregar_configuracao()
    assert config["api"]["openrouter_api_key"] == "env-openrouter"
