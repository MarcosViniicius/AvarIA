from flask import Flask

from .core.paths import APP_PACKAGE_ROOT, RESULTADOS_DIR, ensure_directories
from .core.logging import configure_logging
from .settings import load_flask_settings
from .errors import register_error_handlers
from .routes import register_blueprints
from .services.optimization import init_optimizations
from .services import db as db_service
from .services import campo_migration
from .services import catalogo


def _register_endpoint_aliases(app):
    rules = list(app.url_map.iter_rules())
    for rule in rules:
        if not rule.endpoint.startswith("web."):
            continue
        short_endpoint = rule.endpoint.split(".", 1)[1]
        if short_endpoint in app.view_functions:
            continue
        app.add_url_rule(
            rule.rule,
            endpoint=short_endpoint,
            view_func=app.view_functions[rule.endpoint],
            defaults=rule.defaults,
            methods=rule.methods,
            provide_automatic_options=False,
        )


def create_app():
    app = Flask(
        __name__,
        template_folder=str(APP_PACKAGE_ROOT / "templates"),
        static_folder=str(APP_PACKAGE_ROOT / "static"),
    )
    app.config.update(load_flask_settings())
    configure_logging()
    ensure_directories()
    db_service.init_db()
    db_service.backfill_relatorios_unificados(RESULTADOS_DIR)
    campo_migration.executar_migracao_campos()
    try:
        # Idempotente e rápido (poucas centenas de linhas): mantém o catálogo
        # do modo "sem IA" atualizado com tudo que a IA já identificou.
        catalogo.popular_do_historico()
    except Exception as e:
        print(f"⚠️ Não foi possível popular o catálogo a partir do histórico: {e}")
    register_blueprints(app)
    _register_endpoint_aliases(app)
    register_error_handlers(app)
    init_optimizations(app)
    return app
