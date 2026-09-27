from flask import render_template


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return (
            render_template(
                "erro.html",
                codigo=404,
                icone="compass",
                titulo="Página não encontrada",
                descricao="O endereço acessado não existe ou foi movido. "
                "Confira o link ou volte para o início.",
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error):
        return (
            render_template(
                "erro.html",
                codigo=500,
                icone="exclamation-triangle",
                titulo="Algo deu errado",
                descricao="O servidor não conseguiu concluir a solicitação. "
                "Tente novamente em instantes.",
            ),
            500,
        )
