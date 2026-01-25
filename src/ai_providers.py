"""
MÓDULO DE PROVEDORES DE IA
Suporte unificado para múltiplas APIs de IA
Criado em: 24/01/2026
"""

import os
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Classe base abstrata para provedores de IA."""
    
    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        """
        Inicializa o provedor de IA.
        
        Args:
            api_key: Chave da API
            model: Nome do modelo
            config: Configurações adicionais (temperatura, max_tokens, etc.)
        """
        self.api_key = api_key
        self.model = model
        self.config = config or {}
        self.temperatura = self.config.get("temperatura", 0.1)
        self.max_tokens = self.config.get("max_tokens", 4000)
        self.timeout = self.config.get("timeout", 30)
    
    @abstractmethod
    def gerar_conteudo(self, prompt: str, imagens: List[Any] = None) -> Tuple[str, int]:
        """
        Gera conteúdo usando a API.
        
        Args:
            prompt: Prompt de texto
            imagens: Lista de imagens (opcional)
        
        Returns:
            Tupla (resposta_texto, tokens_consumidos)
        """
        pass
    
    @abstractmethod
    def get_modelos_disponiveis(self) -> List[str]:
        """Retorna lista de modelos disponíveis para este provedor."""
        pass
    
    @property
    @abstractmethod
    def nome_provedor(self) -> str:
        """Nome do provedor."""
        pass


class GeminiProvider(AIProvider):
    """Provedor Google Gemini."""
    
    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            import google.generativeai as genai
            self.genai = genai
            self.genai.configure(api_key=self.api_key)
            self.client = self.genai.GenerativeModel(self.model)
        except ImportError:
            raise ImportError("google-generativeai não está instalado. Execute: pip install google-generativeai")
    
    def gerar_conteudo(self, prompt: str, imagens: List[Any] = None) -> Tuple[str, int]:
        """Gera conteúdo usando Gemini."""
        from PIL import Image
        
        conteudo = []
        
        # Adicionar imagens se fornecidas
        if imagens:
            for img_path in imagens:
                try:
                    img = Image.open(img_path)
                    conteudo.append(img)
                except Exception as e:
                    print(f"⚠️ Erro ao carregar imagem {img_path}: {e}")
        
        # Adicionar prompt
        conteudo.append(prompt)
        
        # Configurar geração
        generation_config = {
            "temperature": self.temperatura,
            "max_output_tokens": self.max_tokens,
        }
        
        # Gerar resposta
        response = self.client.generate_content(
            conteudo,
            generation_config=generation_config,
            request_options={"timeout": self.timeout}
        )
        
        # Calcular tokens (estimativa para Gemini)
        tokens = response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0
        
        return response.text, tokens
    
    def get_modelos_disponiveis(self) -> List[str]:
        """Modelos Gemini disponíveis com suporte a visão/multimodal."""
        return [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash",
        ]
    
    @property
    def nome_provedor(self) -> str:
        return "Gemini (Google)"


class OpenAIProvider(AIProvider):
    """Provedor OpenAI."""
    
    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError("openai não está instalado. Execute: pip install openai")
    
    def gerar_conteudo(self, prompt: str, imagens: List[Any] = None) -> Tuple[str, int]:
        """Gera conteúdo usando OpenAI."""
        import base64
        
        messages = []
        content = []
        
        # Adicionar texto
        content.append({
            "type": "text",
            "text": prompt
        })
        
        # Adicionar imagens se fornecidas e modelo suporta
        if imagens and "vision" in self.model.lower() or "gpt-4" in self.model.lower():
            for img_path in imagens:
                try:
                    with open(img_path, "rb") as img_file:
                        base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        })
                except Exception as e:
                    print(f"⚠️ Erro ao carregar imagem {img_path}: {e}")
        
        messages.append({
            "role": "user",
            "content": content
        })
        
        # Gerar resposta
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperatura,
            max_tokens=self.max_tokens,
            timeout=self.timeout
        )
        
        tokens = response.usage.total_tokens
        texto = response.choices[0].message.content
        
        return texto, tokens
    
    def get_modelos_disponiveis(self) -> List[str]:
        """Modelos OpenAI disponíveis com suporte a visão."""
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4-vision-preview",
        ]
    
    @property
    def nome_provedor(self) -> str:
        return "OpenAI"


class ClaudeProvider(AIProvider):
    """Provedor Anthropic Claude."""
    
    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.api_key)
        except ImportError:
            raise ImportError("anthropic não está instalado. Execute: pip install anthropic")
    
    def gerar_conteudo(self, prompt: str, imagens: List[Any] = None) -> Tuple[str, int]:
        """Gera conteúdo usando Claude."""
        import base64
        
        content = []
        
        # Adicionar imagens se fornecidas
        if imagens:
            for img_path in imagens:
                try:
                    with open(img_path, "rb") as img_file:
                        base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                        
                        # Detectar tipo de imagem
                        ext = img_path.lower().split('.')[-1]
                        media_type = f"image/{ext if ext in ['png', 'jpeg', 'jpg', 'gif', 'webp'] else 'jpeg'}"
                        
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_image
                            }
                        })
                except Exception as e:
                    print(f"⚠️ Erro ao carregar imagem {img_path}: {e}")
        
        # Adicionar texto
        content.append({
            "type": "text",
            "text": prompt
        })
        
        # Gerar resposta
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperatura,
            messages=[{
                "role": "user",
                "content": content
            }],
            timeout=self.timeout
        )
        
        tokens = response.usage.input_tokens + response.usage.output_tokens
        texto = response.content[0].text
        
        return texto, tokens
    
    def get_modelos_disponiveis(self) -> List[str]:
        """Modelos Claude disponíveis."""
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ]
    
    @property
    def nome_provedor(self) -> str:
        return "Claude (Anthropic)"


class OpenRouterProvider(AIProvider):
    """Provedor OpenRouter (acesso a múltiplos modelos)."""
    
    def __init__(self, api_key: str, model: str, config: Dict[str, Any] = None):
        super().__init__(api_key, model, config)
        try:
            from openai import OpenAI
            # OpenRouter usa API compatível com OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://openrouter.ai/api/v1"
            )
        except ImportError:
            raise ImportError("openai não está instalado. Execute: pip install openai")
    
    def gerar_conteudo(self, prompt: str, imagens: List[Any] = None) -> Tuple[str, int]:
        """Gera conteúdo usando OpenRouter."""
        import base64
        
        messages = []
        content = []
        
        # Adicionar texto
        content.append({
            "type": "text",
            "text": prompt
        })
        
        # Adicionar imagens se fornecidas
        if imagens:
            for img_path in imagens:
                try:
                    with open(img_path, "rb") as img_file:
                        base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        })
                except Exception as e:
                    print(f"⚠️ Erro ao carregar imagem {img_path}: {e}")
        
        messages.append({
            "role": "user",
            "content": content
        })
        
        # Gerar resposta
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperatura,
            max_tokens=self.max_tokens,
            timeout=self.timeout
        )
        
        tokens = response.usage.total_tokens if response.usage else 0
        texto = response.choices[0].message.content
        
        return texto, tokens
    
    def get_modelos_disponiveis(self) -> List[str]:
        """Modelos OpenRouter com suporte a visão."""
        return [
            "anthropic/claude-3.5-sonnet",
            "google/gemini-pro-1.5",
            "openai/gpt-4o",
            "openai/gpt-4-turbo",
            "meta-llama/llama-3.2-90b-vision",
            "qwen/qwen-2-vl-72b",
        ]
    
    @property
    def nome_provedor(self) -> str:
        return "OpenRouter"


# Factory para criar provedores
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
        Cria uma instância do provedor especificado.
        
        Args:
            provider_name: Nome do provedor (gemini, openai, claude, openrouter)
            api_key: Chave da API
            model: Nome do modelo
            config: Configurações adicionais
        
        Returns:
            Instância do provedor
        
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
        """Retorna lista de provedores suportados."""
        return list(cls.PROVIDERS.keys())
    
    @classmethod
    def obter_modelos(cls, provider_name: str) -> List[str]:
        """
        Obtém lista de modelos disponíveis para um provedor.
        
        Args:
            provider_name: Nome do provedor
        
        Returns:
            Lista de modelos
        """
        provider_name = provider_name.lower()
        
        if provider_name not in cls.PROVIDERS:
            return []
        
        # Criar instância temporária apenas para obter modelos
        provider_class = cls.PROVIDERS[provider_name]
        try:
            temp_instance = provider_class("dummy_key", "dummy_model", {})
            return temp_instance.get_modelos_disponiveis()
        except:
            # Se falhar, retornar lista padrão
            return []


def carregar_provedor_de_config(config_path: str = None) -> AIProvider:
    """
    Carrega o provedor de IA baseado na configuração.
    
    Args:
        config_path: Caminho para o arquivo config.json
    
    Returns:
        Instância do provedor configurado
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config",
            "config.json"
        )
    
    # Carregar configuração
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Obter configurações da API
    api_config = config.get("api", {})
    provider_name = api_config.get("provider", "gemini")
    
    # Obter API key baseado no provedor
    api_key_map = {
        "gemini": api_config.get("gemini_api_key"),
        "openai": api_config.get("openai_api_key"),
        "claude": api_config.get("anthropic_api_key"),
        "anthropic": api_config.get("anthropic_api_key"),
        "openrouter": api_config.get("openrouter_api_key"),
    }
    
    api_key = api_key_map.get(provider_name.lower())
    
    if not api_key:
        raise ValueError(f"API key não configurada para o provedor '{provider_name}'")
    
    # Obter modelo
    model_key = f"modelo_{provider_name.lower()}"
    model = config.get("processamento", {}).get(model_key)
    
    # Se não houver modelo específico, usar o padrão
    if not model:
        if provider_name.lower() == "gemini":
            model = config.get("processamento", {}).get("modelo_gemini", "gemini-2.0-flash-exp")
        elif provider_name.lower() == "openai":
            model = "gpt-4o-mini"
        elif provider_name.lower() in ["claude", "anthropic"]:
            model = "claude-3-5-haiku-20241022"
        elif provider_name.lower() == "openrouter":
            model = "google/gemini-pro-1.5"
    
    # Obter configurações de processamento
    proc_config = config.get("processamento", {})
    
    # Criar e retornar provedor
    return AIProviderFactory.criar_provedor(
        provider_name,
        api_key,
        model,
        proc_config
    )


if __name__ == "__main__":
    # Teste básico
    print("🧪 Testando módulo de provedores de IA...\n")
    
    print("📋 Provedores suportados:")
    for provider in AIProviderFactory.listar_provedores():
        print(f"   • {provider}")
        modelos = AIProviderFactory.obter_modelos(provider)
        if modelos:
            print(f"     Modelos: {', '.join(modelos[:3])}...")
    
    print("\n✅ Módulo carregado com sucesso!")
