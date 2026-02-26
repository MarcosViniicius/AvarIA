def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return error

    @app.errorhandler(500)
    def internal_error(error):
        return error
