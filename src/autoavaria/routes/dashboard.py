"""Rotas do painel principal (`/`) e da API de estatísticas (`/api/stats`)."""

from flask import jsonify, make_response, render_template, request

from .blueprint import web_bp as app
from ..services.config_service import verificar_e_corrigir_configuracao
from ..services.stats import obter_estatisticas, obter_resultados_recentes


@app.route("/")
def index():
    """Página principal com cache de resposta."""
    response = make_response()

    # Cache para melhor performance
    if request.headers.get("Cache-Control") != "no-cache":
        response.headers["Cache-Control"] = "public, max-age=60"  # 1 minuto

    stats = obter_estatisticas()
    resultados = obter_resultados_recentes()

    # Avisa ANTES de o usuário tentar processar e só descobrir no meio do
    # caminho (routes/processing.py já fazia essa mesma checagem, mas só na
    # hora de processar). Não avisa se o modo salvo é "sem_ia" - não precisa
    # de chave nenhuma.
    config_ok, config_msg = verificar_e_corrigir_configuracao()

    # Renderizar template
    html = render_template(
        "index.html", stats=stats, resultados=resultados,
        chave_api_ausente=not config_ok, mensagem_config=config_msg,
    )
    response.set_data(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"

    return response


@app.route("/api/stats")
def api_stats():
    """API para obter estatísticas atualizadas."""
    return jsonify(obter_estatisticas())
