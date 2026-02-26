from flask import Flask

from .core.paths import APP_PACKAGE_ROOT, ensure_directories
from .core.logging import configure_logging
from .settings import load_flask_settings
from .errors import register_error_handlers
from .routes import register_blueprints
from .services.optimization import init_optimizations


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
    register_blueprints(app)
    _register_endpoint_aliases(app)
    register_error_handlers(app)
    init_optimizations(app)
    return app
