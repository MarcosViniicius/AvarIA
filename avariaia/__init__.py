import os
import sys
from pathlib import Path

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


def _register_static_versioning(app):
    """Expõe static_v(path) nos templates: carimba a URL com o mtime do arquivo.

    O CacheMiddleware serve /static/* com ``max-age=31536000`` (1 ano). Sem
    trocar a URL a cada alteração, o navegador continua usando o arquivo
    antigo — foi assim que uma correção de JS "não fazia efeito" depois de
    editada. O mtime garante que cada edição gere uma URL nova.
    """

    static_dir = APP_PACKAGE_ROOT / "static"

    @app.template_global()
    def static_v(filename: str) -> str:
        try:
            mtime = int(os.path.getmtime(static_dir / filename))
        except OSError:
            mtime = 0
        return f"/static/{filename}?v={mtime}"


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


def _configurar_invertexto_no_primeiro_boot():
    """Captura a config do invertexto uma única vez, no primeiro boot.

    O token do notepad vem embutido no HTML público da página do invertexto —
    não é gerado aqui, então precisa ser lido de lá. Roda só quando ainda não
    há token guardado, e nunca deixa uma falha de rede derrubar o app: sem
    internet, o sistema sobe normal e a exportação fica desabilitada.
    """
    from .services import invertexto

    if invertexto.configurado():
        return
    try:
        from .scripts.configurar_invertexto import configurar

        configurar(verbose=False)
    except Exception as e:
        print(f"⚠️ Integração com o invertexto indisponível: {e}")


def _importar_logs_legados():
    """Importa logs/log_mestre.txt e log_consumo_tokens.txt para o SQLite.

    Uma vez, no boot. Idempotente (ver db.importar_logs_dos_arquivos). Os
    arquivos continuam sendo escritos junto com o banco; esta importação só
    garante que o histórico anterior à migração não se perca.
    """
    try:
        from .core.paths import LOG_CONSUMO_FILE, LOG_PROCESSADOS_FILE
        from .services import db as db_service

        resultado = db_service.importar_logs_dos_arquivos(
            LOG_PROCESSADOS_FILE, LOG_CONSUMO_FILE
        )
        if resultado["processados"] or resultado["consumo"]:
            print(
                f"📥 Logs importados para o banco: "
                f"{resultado['processados']} processados, {resultado['consumo']} consumo"
            )
    except Exception as e:
        print(f"⚠️ Não foi possível importar os logs legados: {e}")


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
    db_service.recuperar_execucoes_orfas()
    db_service.backfill_relatorios_unificados(RESULTADOS_DIR)
    campo_migration.executar_migracao_campos()
    try:
        # Idempotente e rápido (poucas centenas de linhas): mantém o catálogo
        # do modo "sem IA" atualizado com tudo que a IA já identificou.
        catalogo.popular_do_historico()
    except Exception as e:
        print(f"⚠️ Não foi possível popular o catálogo a partir do histórico: {e}")
    _configurar_invertexto_no_primeiro_boot()
    _importar_logs_legados()
    register_blueprints(app)
    _register_endpoint_aliases(app)
    register_error_handlers(app)
    _register_static_versioning(app)
    init_optimizations(app)
    return app
