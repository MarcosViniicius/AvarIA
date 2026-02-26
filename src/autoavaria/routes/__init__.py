from .web import web_bp


def register_blueprints(app):
    app.register_blueprint(web_bp)
