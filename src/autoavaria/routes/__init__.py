from .blueprint import web_bp
from . import (
    dashboard,
    upload,
    processing,
    logs,
    relatorio,
    erros,
    ai_config,
    configuracoes,
    edicao,
    manutencao,
    unificacao,
    historico,
)  # noqa: F401 - cada import registra rotas no web_bp como efeito colateral


def register_blueprints(app):
    app.register_blueprint(web_bp)
