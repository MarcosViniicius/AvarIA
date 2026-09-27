"""
Rota de descoberta de modelos de IA: `/api/listar_modelos/<provider>`.

Antes existiam mais 3 rotas aqui (`/api/provedores_disponiveis`,
`/api/modelos_disponiveis/<provider>`, `/api/testar_configuracao`) - nenhuma
chamada por nenhum template/JS (a lista de provedores já está fixa no
`<select>` de configuracoes.html, e `modelos_disponiveis` era um duplicado
mais fraco desta rota, sem considerar a API key). `testar_configuracao`
também devolvia os 8 primeiros caracteres da chave de API na resposta -
inconsistente com a mascaração feita em `/api/configuracoes` (ver
routes/configuracoes.py). Removidas por serem código morto.
"""

from flask import jsonify

from .blueprint import web_bp as app
from ..services.config_service import carregar_configuracao


@app.route("/api/listar_modelos/<provider>")
def api_listar_modelos(provider):
    """
    API para listar modelos disponíveis de um provedor em tempo real.

    Args:
        provider: Nome do provedor (gemini, openai, claude, openrouter)

    Returns:
        JSON com lista de modelos disponíveis
    """
    try:
        from autoavaria.services.ai import AIProviderFactory

        # Normalizar nome do provedor
        provider = provider.lower()

        # Obter configuração para pegar API key
        config = carregar_configuracao()
        api_keys = config.get("api", {})

        # Mapear nomes de provedores para chaves de configuração
        provider_key_map = {
            "gemini": "gemini_api_key",
            "openai": "openai_api_key",
            "claude": "anthropic_api_key",
            "anthropic": "anthropic_api_key",
            "openrouter": "openrouter_api_key"
        }

        # Obter API key do provedor
        api_key = None
        if provider in provider_key_map:
            api_key = api_keys.get(provider_key_map[provider], "")

        # Obter lista de modelos
        modelos = AIProviderFactory.obter_modelos(provider, api_key)

        if not modelos:
            return jsonify({
                "error": f"Provedor '{provider}' não encontrado ou sem modelos disponíveis"
            }), 404

        return jsonify({
            "provider": provider,
            "modelos": modelos,
            "success": True
        })

    except Exception as e:
        import traceback
        erro_completo = traceback.format_exc()
        print(f"❌ Erro ao listar modelos do provedor {provider}: {erro_completo}")
        return jsonify({
            "error": str(e),
            "success": False
        }), 500
