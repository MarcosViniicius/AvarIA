"""Testes dos provedores de IA (services/ai.py).

O Gemini foi validado com uma chamada real à API (ver conversa/changelog) —
aqui cobrimos a montagem de conteúdo e o parsing de resposta com mocks dos
clientes de SDK, já que não há chaves reais de OpenAI/Claude/OpenRouter
disponíveis neste ambiente para um teste de integração de verdade.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from avariaia.services.ai import (
    AIProviderFactory,
    CAMPO_API_KEY_POR_PROVEDOR,
    ClaudeProvider,
    GeminiProvider,
    OpenAIProvider,
    OpenRouterProvider,
    construir_provedor_de_config,
    obter_api_key_do_provedor,
)


def _partes_exemplo(caminho_imagem):
    return [
        {"tipo": "texto", "texto": "Instrução do prompt"},
        {"tipo": "texto", "texto": "Arquivo: img.jpg"},
        {"tipo": "imagem", "caminho": caminho_imagem},
    ]


@pytest.fixture
def imagem_fake(tmp_path):
    from PIL import Image

    caminho = tmp_path / "img.jpg"
    Image.new("RGB", (4, 4), color="red").save(caminho)
    return str(caminho)


class TestGeminiProvider:
    """Gemini foi validado com chamadas reais à API (google-genai) durante o
    desenvolvimento; aqui garantimos que a montagem da requisição não regride."""

    def test_monta_conteudo_preserva_ordem_texto_imagem(self, imagem_fake):
        from PIL import Image

        with patch("google.genai.Client"):
            provider = GeminiProvider("fake-key", "gemini-2.5-flash", {})
        conteudo = provider._montar_conteudo(_partes_exemplo(imagem_fake))

        assert conteudo[0] == "Instrução do prompt"
        assert conteudo[1] == "Arquivo: img.jpg"
        assert isinstance(conteudo[2], Image.Image)

    def test_gerar_conteudo_usa_json_mode_temperatura_e_timeout_em_ms(self, imagem_fake):
        resposta_falsa = SimpleNamespace(
            text='{"a": 1}',
            usage_metadata=SimpleNamespace(total_token_count=77),
        )
        with patch("google.genai.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.models.generate_content.return_value = resposta_falsa

            provider = GeminiProvider("fake-key", "gemini-2.5-flash", {"temperatura": 0.3, "max_tokens": 900, "timeout": 45})
            texto, tokens = provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        assert texto == '{"a": 1}'
        assert tokens == 77

        kwargs = mock_client.models.generate_content.call_args.kwargs
        assert kwargs["model"] == "gemini-2.5-flash"
        config = kwargs["config"]
        assert config.temperature == 0.3
        assert config.max_output_tokens == 900
        assert config.response_mime_type == "application/json"
        # google-genai usa milissegundos; self.timeout é configurado em segundos.
        assert config.http_options.timeout == 45_000

    def test_thinking_desligado_para_nao_estourar_o_orcamento_de_tokens(self, imagem_fake):
        """Regressão: o "thinking" do Gemini 2.5 consome o mesmo max_output_tokens
        da resposta. Com ele ligado, lotes de várias imagens estouravam o limite e
        o JSON vinha truncado ("Unterminated string"), falhando as 3 tentativas."""
        resposta_falsa = SimpleNamespace(text="{}", usage_metadata=SimpleNamespace(total_token_count=1))
        with patch("google.genai.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.models.generate_content.return_value = resposta_falsa

            provider = GeminiProvider("fake-key", "gemini-2.5-flash", {})
            provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.thinking_config.thinking_budget == 0

    def test_thinking_budget_zero_nao_e_usado_em_modelos_3x(self, imagem_fake):
        """Regressão: testado ao vivo que gemini-3.5-flash-lite REJEITA
        thinking_budget=0 com 400 INVALID_ARGUMENT (o range aceito é model
        dependent). O bug original do orçamento não se repete nesses modelos
        mesmo sem desligar o thinking, então simplesmente não mandamos
        thinking_config nenhum para eles."""
        resposta_falsa = SimpleNamespace(text="{}", usage_metadata=SimpleNamespace(total_token_count=1))
        with patch("google.genai.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.models.generate_content.return_value = resposta_falsa

            provider = GeminiProvider("fake-key", "gemini-3.5-flash-lite", {})
            provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.thinking_config is None

    @pytest.mark.parametrize("modelo", ["gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite"])
    def test_thinking_budget_zero_usado_em_todos_os_modelos_2x(self, imagem_fake, modelo):
        resposta_falsa = SimpleNamespace(text="{}", usage_metadata=SimpleNamespace(total_token_count=1))
        with patch("google.genai.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.models.generate_content.return_value = resposta_falsa

            provider = GeminiProvider("fake-key", modelo, {})
            provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        config = mock_client.models.generate_content.call_args.kwargs["config"]
        assert config.thinking_config.thinking_budget == 0

    def test_get_modelos_filtra_por_suporte_a_generate_content(self):
        modelo_com_visao = SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"])
        modelo_sem_visao = SimpleNamespace(name="models/embedding-001", supported_actions=["embedContent"])

        with patch("google.genai.Client") as MockClient:
            mock_client = MockClient.return_value
            mock_client.models.list.return_value = [modelo_com_visao, modelo_sem_visao]

            provider = GeminiProvider("fake-key", "gemini-2.5-flash", {})
            modelos = provider.get_modelos_disponiveis()

        assert modelos == ["gemini-2.5-flash"]


class TestOpenAIProvider:
    def test_monta_conteudo_preserva_ordem_texto_imagem(self, imagem_fake):
        with patch("openai.OpenAI"):
            provider = OpenAIProvider("fake-key", "gpt-4o-mini", {})
        content = provider._montar_conteudo(_partes_exemplo(imagem_fake))

        assert content[0] == {"type": "text", "text": "Instrução do prompt"}
        assert content[1] == {"type": "text", "text": "Arquivo: img.jpg"}
        assert content[2]["type"] == "image_url"
        assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_gerar_conteudo_usa_json_mode_e_retorna_texto_e_tokens(self, imagem_fake):
        resposta_falsa = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
            usage=SimpleNamespace(total_tokens=42),
        )
        with patch("openai.OpenAI") as MockOpenAI:
            mock_client = MockOpenAI.return_value
            mock_client.chat.completions.create.return_value = resposta_falsa

            provider = OpenAIProvider("fake-key", "gpt-4o-mini", {"temperatura": 0.2, "max_tokens": 500, "timeout": 15})
            texto, tokens = provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        assert texto == '{"a": 1}'
        assert tokens == 42
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 500
        assert kwargs["timeout"] == 15

    def test_gerar_conteudo_tenta_de_novo_sem_json_mode_se_recusado(self, imagem_fake):
        resposta_falsa = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(total_tokens=1),
        )
        with patch("openai.OpenAI") as MockOpenAI:
            mock_client = MockOpenAI.return_value
            mock_client.chat.completions.create.side_effect = [Exception("response_format não suportado"), resposta_falsa]

            provider = OpenAIProvider("fake-key", "gpt-4o-mini", {})
            texto, tokens = provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        assert texto == "ok"
        assert mock_client.chat.completions.create.call_count == 2
        segunda_chamada_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "response_format" not in segunda_chamada_kwargs


class TestOpenRouterProvider:
    def test_usa_base_url_do_openrouter_e_nao_forca_json_mode(self, imagem_fake):
        resposta_falsa = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
            usage=SimpleNamespace(total_tokens=10),
        )
        with patch("openai.OpenAI") as MockOpenAI:
            mock_client = MockOpenAI.return_value
            mock_client.chat.completions.create.return_value = resposta_falsa

            provider = OpenRouterProvider("fake-key", "openai/gpt-4o-mini", {})
            provider.gerar_conteudo(_partes_exemplo(imagem_fake))

            MockOpenAI.assert_called_once_with(api_key="fake-key", base_url="https://openrouter.ai/api/v1")

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "response_format" not in kwargs


class TestClaudeProvider:
    def test_monta_conteudo_com_blocos_de_imagem_base64(self, imagem_fake):
        with patch("anthropic.Anthropic"):
            provider = ClaudeProvider("fake-key", "claude-3-5-haiku-20241022", {})
        content = provider._montar_conteudo(_partes_exemplo(imagem_fake))

        assert content[0] == {"type": "text", "text": "Instrução do prompt"}
        assert content[2]["type"] == "image"
        assert content[2]["source"]["type"] == "base64"
        assert content[2]["source"]["media_type"] == "image/jpeg"

    def test_gerar_conteudo_soma_tokens_entrada_e_saida(self, imagem_fake):
        resposta_falsa = SimpleNamespace(
            content=[SimpleNamespace(text='{"a": 1}')],
            usage=SimpleNamespace(input_tokens=30, output_tokens=12),
        )
        with patch("anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = resposta_falsa

            provider = ClaudeProvider("fake-key", "claude-3-5-haiku-20241022", {})
            texto, tokens = provider.gerar_conteudo(_partes_exemplo(imagem_fake))

        assert texto == '{"a": 1}'
        assert tokens == 42


class TestConfigDoProvedor:
    def test_mapa_de_campos_api_key(self):
        assert CAMPO_API_KEY_POR_PROVEDOR["gemini"] == "gemini_api_key"
        assert CAMPO_API_KEY_POR_PROVEDOR["claude"] == "anthropic_api_key"
        assert CAMPO_API_KEY_POR_PROVEDOR["anthropic"] == "anthropic_api_key"
        assert CAMPO_API_KEY_POR_PROVEDOR["openrouter"] == "openrouter_api_key"

    def test_obter_api_key_do_provedor(self):
        config = {"api": {"provider": "openai", "openai_api_key": "sk-123"}}
        assert obter_api_key_do_provedor(config, "openai") == "sk-123"
        assert obter_api_key_do_provedor(config, "claude") == ""

    def test_construir_provedor_le_schema_real_da_tela_configuracoes(self):
        """Regressão: o schema real salvo pela tela é api.provider + api.modelo_selecionado
        + api.{provider}_api_key — NÃO processamento.modelo_openai como a versão antiga assumia."""
        config = {
            "api": {
                "provider": "openai",
                "openai_api_key": "sk-teste",
                "modelo_selecionado": "gpt-4o-mini",
            },
            "processamento": {"temperatura": 0.2, "max_tokens": 800, "timeout": 20},
        }
        with patch("openai.OpenAI"):
            provider = construir_provedor_de_config(config)

        assert isinstance(provider, OpenAIProvider)
        assert provider.model == "gpt-4o-mini"
        assert provider.api_key == "sk-teste"
        assert provider.temperatura == 0.2

    def test_construir_provedor_sem_api_key_da_erro_claro(self):
        config = {"api": {"provider": "claude"}, "processamento": {}}
        with pytest.raises(ValueError, match="claude"):
            construir_provedor_de_config(config)

    def test_construir_provedor_sem_modelo_da_erro_claro(self):
        config = {"api": {"provider": "openai", "openai_api_key": "sk-1"}, "processamento": {}}
        with pytest.raises(ValueError, match="modelo"):
            construir_provedor_de_config(config)


class TestAIProviderFactory:
    def test_listar_provedores(self):
        provedores = AIProviderFactory.listar_provedores()
        assert set(provedores) == {"gemini", "openai", "claude", "anthropic", "openrouter"}

    def test_criar_provedor_invalido_leva_erro(self):
        with pytest.raises(ValueError, match="não suportado"):
            AIProviderFactory.criar_provedor("bard", "key", "model")


class TestCacheDeModelos:
    """Regressão: /api/listar_modelos fazia uma chamada de rede ao vivo pro
    provedor de IA em TODA visita à tela de Configurações — sem chave real
    configurada para o provedor, isso podia ficar "Pending" por muito tempo
    no navegador. Um cache com TTL evita repetir a chamada externa."""

    def setup_method(self):
        AIProviderFactory._CACHE_MODELOS.clear()

    def test_segunda_chamada_usa_cache_em_vez_de_bater_na_api_de_novo(self, monkeypatch):
        chamadas = {"n": 0}

        def fake(cls, provider_name, api_key=None):
            chamadas["n"] += 1
            return ["modelo-a"]

        monkeypatch.setattr(AIProviderFactory, "_obter_modelos_sem_cache", classmethod(fake))

        AIProviderFactory.obter_modelos("gemini", "chave-x")
        AIProviderFactory.obter_modelos("gemini", "chave-x")
        AIProviderFactory.obter_modelos("gemini", "chave-x")

        assert chamadas["n"] == 1

    def test_chaves_de_api_diferentes_nao_compartilham_cache(self, monkeypatch):
        chamadas = {"n": 0}

        def fake(cls, provider_name, api_key=None):
            chamadas["n"] += 1
            return [f"modelo-{api_key}"]

        monkeypatch.setattr(AIProviderFactory, "_obter_modelos_sem_cache", classmethod(fake))

        AIProviderFactory.obter_modelos("gemini", "chave-x")
        AIProviderFactory.obter_modelos("gemini", "chave-y")

        assert chamadas["n"] == 2

    def test_cache_expira_apos_o_ttl(self, monkeypatch):
        chamadas = {"n": 0}

        def fake(cls, provider_name, api_key=None):
            chamadas["n"] += 1
            return ["modelo-a"]

        monkeypatch.setattr(AIProviderFactory, "_obter_modelos_sem_cache", classmethod(fake))
        monkeypatch.setattr(AIProviderFactory, "_CACHE_MODELOS_TTL_SEGUNDOS", 0)

        AIProviderFactory.obter_modelos("gemini", "chave-x")
        AIProviderFactory.obter_modelos("gemini", "chave-x")

        assert chamadas["n"] == 2
