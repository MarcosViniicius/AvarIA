"""
Carregador/salvador da configuração da aplicação Flask (config/config.json).

Este módulo é usado pelas rotas web (configurações, processamento em
background, etc). É diferente de
``autoavaria.services.extraction_pipeline.carregar_configuracao``, que é a
configuração usada exclusivamente pelo pipeline de extração via IA - as duas
funções têm o mesmo nome mas vivem em módulos diferentes e não devem ser
confundidas nem unificadas.
"""

import os
import json
import time

from ..core.paths import CONFIG_FILE as CONFIG_FILE_PATH
from .ai import obter_api_key_do_provedor

CONFIG_FILE = str(CONFIG_FILE_PATH)

# Cache para configurações
_config_cache = None
_config_cache_time = None
CONFIG_CACHE_TTL = 300  # 5 minutos


def carregar_configuracao():
    """Carrega configurações do arquivo JSON com cache."""
    global _config_cache, _config_cache_time

    # Verificar cache
    current_time = time.time()
    if (
        _config_cache is not None
        and _config_cache_time is not None
        and current_time - _config_cache_time < CONFIG_CACHE_TTL
    ):
        return _config_cache

    config_padrao = {
        "api": {
            "provider": "gemini",
            "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "modelo_selecionado": "gemini-2.5-flash-lite",
        },
        "processamento": {
            "modelo_gemini": "gemini-2.5-flash-lite",
            "temperatura": 0.1,
            "max_tokens": 4000,
            "timeout": 60,
            "tamanho_lote": 12,
            "max_workers": 3,
            "request_delay": 2.0,
            # "ia" (padrão) | "sem_ia" (código de barras, sem custo) | "hibrido"
            "modo_extracao": "ia",
            # Modo híbrido: depois de tantos dias sem a IA reconfirmar, um PLU
            # já resolvido localmente volta a ser enviado pra IA (o preço/kg
            # usado para calcular o peso pode ter mudado nesse meio tempo).
            "dias_para_reverificar_peso": 30,
        },
        "interface": {
            # "tema", "auto_refresh" e "logs_tempo_real" existiram aqui, mas
            # nenhuma tela jamais os lia - removidos (config.json de
            # instalações antigas pode ainda carregar essas chaves à toa;
            # inofensivo, só não são mais consideradas o padrão).
            "logs_detalhados_aplicacao": False,
        },
    }

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Mesclar com configuração padrão para garantir todas as chaves
                for key in config_padrao:
                    if key not in config:
                        config[key] = config_padrao[key]
                    elif isinstance(config_padrao[key], dict):
                        for subkey in config_padrao[key]:
                            if subkey not in config[key]:
                                config[key][subkey] = config_padrao[key][subkey]

                # Priorizar variáveis de ambiente
                variaveis_api = {
                    "GEMINI_API_KEY": "gemini_api_key",
                    "OPENAI_API_KEY": "openai_api_key",
                    "ANTHROPIC_API_KEY": "anthropic_api_key",
                    "OPENROUTER_API_KEY": "openrouter_api_key",
                }
                for variavel, campo in variaveis_api.items():
                    if os.environ.get(variavel):
                        config["api"][campo] = os.environ[variavel]

                # Atualizar cache
                _config_cache = config
                _config_cache_time = current_time
                return config
        else:
            # Criar arquivo de configuração padrão se não estiver na Vercel
            if "VERCEL" not in os.environ:
                salvar_configuracao(config_padrao)
            _config_cache = config_padrao
            _config_cache_time = current_time
            return config_padrao
    except Exception as e:
        print(f"Erro ao carregar configuração: {e}")
        return config_padrao


def salvar_configuracao(config):
    """Salva configurações no arquivo JSON e limpa cache."""
    global _config_cache, _config_cache_time

    # No ambiente Vercel, não tenta salvar no filesystem (read-only)
    if "VERCEL" in os.environ:
        print(
            "⚠️ Ambiente Vercel: configurações devem ser definidas como variáveis de ambiente"
        )
        return True

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Limpar cache
        _config_cache = None
        _config_cache_time = None
        return True
    except Exception as e:
        print(f"Erro ao salvar configuração: {e}")
        return False


def verificar_e_corrigir_configuracao(modo_extracao: str = None):
    """Verifica e corrige a configuração antes do processamento.

    No modo "sem_ia" não há chamada de IA nenhuma, então a chave de API do
    provedor não é exigida - só o código de barras é lido localmente.
    """
    config = carregar_configuracao()
    modo_extracao = (
        modo_extracao or config.get("processamento", {}).get("modo_extracao") or "ia"
    ).lower()

    if modo_extracao == "sem_ia":
        return True, "Modo sem IA: nenhuma API é necessária (leitura local de código de barras)"

    provider_name = (config.get("api", {}).get("provider") or "gemini").lower()
    api_key = obter_api_key_do_provedor(config, provider_name)

    if not api_key or api_key.strip() == "":
        return False, f"Chave da API do provedor '{provider_name}' não configurada"

    try:
        # Configuração já está em config/config.json (arquivo único)
        return True, f"Configuração válida ({provider_name} — API Key: {api_key[:8]}...)"

    except Exception as e:
        return False, f"Erro ao sincronizar configuração: {e}"
