"""
MÓDULO DE PROVEDORES DE IA
Suporte unificado para múltiplas APIs de IA (Gemini, OpenAI, Claude, OpenRouter)

Cada provedor implementa ``gerar_conteudo(partes)``, onde ``partes`` é uma
lista ORDENADA de blocos de texto e imagem, ex:
    [
        {"tipo": "texto", "texto": "Analise os itens a seguir..."},
        {"tipo": "texto", "texto": "Arquivo: IMG-1.jpg"},
        {"tipo": "imagem", "caminho": "/caminho/IMG-1.jpg"},
        {"tipo": "texto", "texto": "Arquivo: IMG-2.jpg"},
        {"tipo": "imagem", "caminho": "/caminho/IMG-2.jpg"},
    ]

Preservar a ORDEM importa: o prompt do analisador intercala o texto de
contexto de cada arquivo logo antes da imagem correspondente, o que ajuda o
modelo a associar corretamente qual texto pertence a qual foto quando várias
imagens são enviadas no mesmo lote. Todos os provedores recebem a mesma
sequência, na mesma ordem — a diferença é só o formato de "envelope" que
cada API exige.
"""

import base64
import json
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class AIProvider(ABC):
    """Classe base abstrata para provedores de IA."""

    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        """
        Args:
            api_key: Chave da API
            model: Nome do modelo
            config: Configurações adicionais (temperatura, max_tokens, timeout)
        """
        self.api_key = api_key
        self.model = model
        self.config = config or {}
        self.temperatura = self.config.get("temperatura", 0.1)
        self.max_tokens = self.config.get("max_tokens", 4000)
        self.timeout = self.config.get("timeout", 60)

    @abstractmethod
    def gerar_conteudo(self, partes: List[Dict[str, Any]]) -> Tuple[str, int]:
        """
        Gera conteúdo a partir de uma sequência ordenada de partes (texto/imagem).

        Args:
            partes: lista de {"tipo": "texto", "texto": str} ou
                    {"tipo": "imagem", "caminho": str}, na ordem em que devem
                    ser enviadas ao modelo.

        Returns:
            Tupla (resposta_texto, tokens_consumidos)
        """
        raise NotImplementedError

    @abstractmethod
    def get_modelos_disponiveis(self) -> List[str]:
        """Retorna lista de modelos disponíveis para este provedor."""
        raise NotImplementedError

    @property
    @abstractmethod
    def nome_provedor(self) -> str:
        """Nome do provedor."""
        raise NotImplementedError


def _codificar_imagem_base64(caminho: str) -> str:
    with open(caminho, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode("utf-8")


def _media_type_da_imagem(caminho: str) -> str:
    ext = caminho.lower().rsplit(".", 1)[-1] if "." in caminho else "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    return f"image/{ext if ext in ('png', 'jpeg', 'gif', 'webp') else 'jpeg'}"


class GeminiProvider(AIProvider):
    """Provedor Google Gemini."""

    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        except ImportError:
            raise ImportError("google-genai não está instalado. Execute: pip install google-genai")

    def _montar_conteudo(self, partes: List[Dict[str, Any]]) -> list:
        from PIL import Image

        conteudo = []
        for parte in partes:
            if parte["tipo"] == "texto":
                conteudo.append(parte["texto"])
            elif parte["tipo"] == "imagem":
                conteudo.append(Image.open(parte["caminho"]))
        return conteudo

    @staticmethod
    def _thinking_config_para_modelo(nome_modelo: str):
        """Decide a config de "pensamento" certa pra cada geração do Gemini.

        Modelos 2.x "pensam" antes de responder, e esse raciocínio consome o
        mesmo orçamento de max_output_tokens — sem desligar, um lote de
        várias imagens estoura o limite ANTES de escrever o JSON de verdade,
        cortando a resposta no meio (bug real observado em produção). Essa
        tarefa é classificação direta, não precisa de raciocínio estendido,
        então desligamos com thinking_budget=0 nesses modelos.

        Testado ao vivo: no Gemini 3.5, thinking_budget=0 é REJEITADO pela
        API (400 INVALID_ARGUMENT) - "o range permitido é model dependent"
        segundo o próprio SDK. Mas o bug original não se repete nele mesmo
        sem desligar o pensamento (testado com max_output_tokens=4000, igual
        produção: resposta completa e JSON válido) - então para 3.x+
        simplesmente não mandamos thinking_config nenhum, em vez de arriscar
        adivinhar um valor que a API de uma geração futura aceite.
        """
        from google.genai import types

        if nome_modelo.startswith("gemini-2"):
            return types.ThinkingConfig(thinking_budget=0)
        return None

    def gerar_conteudo(self, partes: List[Dict[str, Any]]) -> Tuple[str, int]:
        """Gera conteúdo usando Gemini, com temperatura/max_tokens/timeout aplicados de verdade."""
        from google.genai import types

        conteudo = self._montar_conteudo(partes)

        config = types.GenerateContentConfig(
            temperature=self.temperatura,
            max_output_tokens=self.max_tokens,
            response_mime_type="application/json",
            thinking_config=self._thinking_config_para_modelo(self.model),
            # google-genai usa milissegundos; self.timeout vem em segundos (config.json/UI).
            http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=conteudo,
            config=config,
        )

        tokens = 0
        if response.usage_metadata:
            tokens = response.usage_metadata.total_token_count or 0

        return response.text, tokens

    def get_modelos_disponiveis(self) -> List[str]:
        """Busca modelos Gemini disponíveis com suporte a visão/multimodal em tempo real."""
        try:
            modelos = [
                m.name.replace('models/', '')
                for m in self.client.models.list()
                if m.supported_actions and 'generateContent' in m.supported_actions
            ]
            return sorted(modelos) if modelos else _MODELOS_PADRAO_GEMINI
        except Exception as e:
            print(f"⚠️ Erro ao buscar modelos Gemini: {e}")
            return _MODELOS_PADRAO_GEMINI

    @property
    def nome_provedor(self) -> str:
        return "Gemini (Google)"


_MODELOS_PADRAO_GEMINI = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


class OpenAIProvider(AIProvider):
    """Provedor OpenAI (também é a base do OpenRouterProvider, que muda só o base_url)."""

    _BASE_URL: Optional[str] = None  # None = endpoint oficial da OpenAI

    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from openai import OpenAI
            kwargs = {"api_key": self.api_key}
            if self._BASE_URL:
                kwargs["base_url"] = self._BASE_URL
            self.client = OpenAI(**kwargs)
        except ImportError:
            raise ImportError("openai não está instalado. Execute: pip install openai")

    def _montar_conteudo(self, partes: List[Dict[str, Any]]) -> list:
        """Monta o array `content` de uma mensagem, preservando a ordem texto/imagem."""
        content = []
        for parte in partes:
            if parte["tipo"] == "texto":
                content.append({"type": "text", "text": parte["texto"]})
            elif parte["tipo"] == "imagem":
                base64_image = _codificar_imagem_base64(parte["caminho"])
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                })
        return content

    def _suporta_json_mode(self) -> bool:
        """Só forçamos response_format na OpenAI oficial (modelos gpt-4o* documentados a suportar)."""
        return self._BASE_URL is None

    def gerar_conteudo(self, partes: List[Dict[str, Any]]) -> Tuple[str, int]:
        """Gera conteúdo usando a Chat Completions API (OpenAI ou compatível)."""
        messages = [{"role": "user", "content": self._montar_conteudo(partes)}]

        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=self.temperatura,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        if self._suporta_json_mode():
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception:
            if "response_format" in kwargs:
                # Alguns modelos/proxies rejeitam response_format; tenta de novo sem ele.
                kwargs.pop("response_format")
                response = self.client.chat.completions.create(**kwargs)
            else:
                raise

        tokens = response.usage.total_tokens if response.usage else 0
        texto = response.choices[0].message.content
        return texto, tokens

    def get_modelos_disponiveis(self) -> List[str]:
        """Busca modelos OpenAI disponíveis com suporte a visão em tempo real."""
        try:
            modelos_response = self.client.models.list()
            modelos_com_visao = ['gpt-4o', 'gpt-4-turbo', 'gpt-4-vision', 'vision']
            modelos = [
                m.id for m in modelos_response.data
                if any(k in m.id.lower() for k in modelos_com_visao)
            ]
            return sorted(modelos, reverse=True) if modelos else list(_MODELOS_PADRAO_OPENAI)
        except Exception as e:
            print(f"⚠️ Erro ao buscar modelos OpenAI: {e}")
            return list(_MODELOS_PADRAO_OPENAI)

    @property
    def nome_provedor(self) -> str:
        return "OpenAI"


_MODELOS_PADRAO_OPENAI = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision-preview"]


class ClaudeProvider(AIProvider):
    """Provedor Anthropic Claude."""

    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError("anthropic não está instalado. Execute: pip install anthropic")

    def _montar_conteudo(self, partes: List[Dict[str, Any]]) -> list:
        content = []
        for parte in partes:
            if parte["tipo"] == "texto":
                content.append({"type": "text", "text": parte["texto"]})
            elif parte["tipo"] == "imagem":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _media_type_da_imagem(parte["caminho"]),
                        "data": _codificar_imagem_base64(parte["caminho"]),
                    },
                })
        return content

    def gerar_conteudo(self, partes: List[Dict[str, Any]]) -> Tuple[str, int]:
        """Gera conteúdo usando a Messages API da Anthropic."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperatura,
            messages=[{"role": "user", "content": self._montar_conteudo(partes)}],
            timeout=self.timeout,
        )

        tokens = response.usage.input_tokens + response.usage.output_tokens
        texto = response.content[0].text
        return texto, tokens

    def get_modelos_disponiveis(self) -> List[str]:
        """Modelos Claude disponíveis (Anthropic não fornece API de listagem, lista mantida manualmente)."""
        return [
            "claude-sonnet-4-5-20250929",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]

    @property
    def nome_provedor(self) -> str:
        return "Claude (Anthropic)"


class OpenRouterProvider(OpenAIProvider):
    """Provedor OpenRouter — reaproveita o OpenAIProvider (API compatível), só troca o endpoint."""

    _BASE_URL = "https://openrouter.ai/api/v1"

    def get_modelos_disponiveis(self) -> List[str]:
        """Busca modelos com suporte a visão disponíveis no OpenRouter."""
        try:
            import requests

            response = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                modelos = [
                    m["id"] for m in data.get("data", [])
                    if m.get("architecture", {}).get("modality") == "multimodal"
                    or any(k in m.get("id", "").lower() for k in ("vision", "gemini", "gpt-4o", "claude-3"))
                ]
                if modelos:
                    return sorted(modelos)

            return list(_MODELOS_PADRAO_OPENROUTER)
        except Exception as e:
            print(f"⚠️ Erro ao buscar modelos OpenRouter: {e}")
            return list(_MODELOS_PADRAO_OPENROUTER)

    @property
    def nome_provedor(self) -> str:
        return "OpenRouter"


_MODELOS_PADRAO_OPENROUTER = [
    "anthropic/claude-3.5-sonnet",
    "google/gemini-flash-1.5",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "meta-llama/llama-3.2-90b-vision",
]


class AIProviderFactory:
    """Factory para criar instâncias de provedores de IA."""

    PROVIDERS = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "claude": ClaudeProvider,
        "anthropic": ClaudeProvider,  # Alias
        "openrouter": OpenRouterProvider,
    }

    @classmethod
    def criar_provedor(cls, provider_name: str, api_key: str, model: str, config: Dict[str, Any] = None) -> AIProvider:
        """
        Args:
            provider_name: Nome do provedor (gemini, openai, claude, openrouter)
            api_key: Chave da API
            model: Nome do modelo
            config: Configurações adicionais (temperatura/max_tokens/timeout)

        Raises:
            ValueError: Se o provedor não for suportado
        """
        provider_name = provider_name.lower()

        if provider_name not in cls.PROVIDERS:
            raise ValueError(
                f"Provedor '{provider_name}' não suportado. "
                f"Provedores disponíveis: {', '.join(cls.PROVIDERS.keys())}"
            )

        provider_class = cls.PROVIDERS[provider_name]
        return provider_class(api_key, model, config)

    @classmethod
    def listar_provedores(cls) -> List[str]:
        return list(cls.PROVIDERS.keys())

    # Cache em memória da lista de modelos por provedor: {(provider, api_key): (timestamp, modelos)}.
    # Sem isso, TODA visita à tela de Configurações fazia uma chamada de rede ao
    # vivo pro provedor de IA só pra popular um <select> — e se essa chamada
    # externa demorasse ou travasse, a página inteira parecia travada
    # ("Pending" no DevTools). O catálogo de modelos muda raramente, então um
    # cache de alguns minutos é seguro e imperceptível para o usuário.
    _CACHE_MODELOS: Dict[tuple, tuple] = {}
    _CACHE_MODELOS_TTL_SEGUNDOS = 600  # 10 minutos

    @classmethod
    def obter_modelos(cls, provider_name: str, api_key: str = None) -> List[str]:
        provider_name = provider_name.lower()

        if provider_name not in cls.PROVIDERS:
            return []

        chave_cache = (provider_name, api_key or "")
        em_cache = cls._CACHE_MODELOS.get(chave_cache)
        if em_cache and (time.time() - em_cache[0]) < cls._CACHE_MODELOS_TTL_SEGUNDOS:
            return em_cache[1]

        modelos = cls._obter_modelos_sem_cache(provider_name, api_key)
        cls._CACHE_MODELOS[chave_cache] = (time.time(), modelos)
        return modelos

    @classmethod
    def _obter_modelos_sem_cache(cls, provider_name: str, api_key: str = None) -> List[str]:
        provider_class = cls.PROVIDERS[provider_name]
        try:
            if not api_key:
                if provider_name in ["claude", "anthropic"]:
                    temp_instance = provider_class("dummy_key", "dummy_model", {})
                    return temp_instance.get_modelos_disponiveis()
                return []

            temp_instance = provider_class(api_key, "dummy_model", {})
            return temp_instance.get_modelos_disponiveis()
        except Exception as e:
            print(f"⚠️ Erro ao obter modelos de {provider_name}: {e}")
            try:
                temp_instance = provider_class("dummy_key", "dummy_model", {})
                return temp_instance.get_modelos_disponiveis()
            except Exception:
                return []


# Mapeia o nome do provedor para o campo de api_key correspondente em config["api"].
CAMPO_API_KEY_POR_PROVEDOR = {
    "gemini": "gemini_api_key",
    "openai": "openai_api_key",
    "claude": "anthropic_api_key",
    "anthropic": "anthropic_api_key",
    "openrouter": "openrouter_api_key",
}


def obter_api_key_do_provedor(config: Dict[str, Any], provider_name: str) -> str:
    """Retorna a api_key configurada para o provedor informado."""
    campo = CAMPO_API_KEY_POR_PROVEDOR.get(provider_name.lower())
    if not campo:
        return ""
    return config.get("api", {}).get(campo, "") or ""


def construir_provedor_de_config(config: Dict[str, Any]) -> AIProvider:
    """Constrói o AIProvider configurado a partir de um dict de config já carregado.

    Lê exatamente os campos que a tela de Configurações grava
    (``api.provider``, ``api.modelo_selecionado``, ``api.{provider}_api_key``),
    e usa ``processamento`` (temperatura/max_tokens/timeout) como parâmetros
    de geração — os mesmos campos para qualquer provedor escolhido.
    """
    api_config = config.get("api", {})
    provider_name = (api_config.get("provider") or "gemini").lower()

    api_key = obter_api_key_do_provedor(config, provider_name)
    if not api_key:
        raise ValueError(f"Chave de API não configurada para o provedor '{provider_name}'.")

    modelo = api_config.get("modelo_selecionado")
    if not modelo:
        modelo = config.get("processamento", {}).get("modelo_gemini") if provider_name == "gemini" else None
    if not modelo:
        raise ValueError(f"Nenhum modelo selecionado para o provedor '{provider_name}'.")

    return AIProviderFactory.criar_provedor(provider_name, api_key, modelo, config.get("processamento", {}))


def carregar_provedor_de_config(config_path: str = None) -> AIProvider:
    """Lê config/config.json do disco e constrói o AIProvider configurado."""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "config.json"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    return construir_provedor_de_config(config)
