"""
Middleware de compressão e otimização para Flask - CORRIGIDO
"""

from flask import request


class CacheMiddleware:
    """Middleware para headers de cache estático."""

    def __init__(self, app):
        self.app = app

        # Configurações de cache por tipo de arquivo
        self.cache_config = {
            ".css": "public, max-age=31536000",  # 1 ano
            ".js": "public, max-age=31536000",  # 1 ano
            ".png": "public, max-age=86400",  # 1 dia
            ".jpg": "public, max-age=86400",  # 1 dia
            ".jpeg": "public, max-age=86400",  # 1 dia
            ".ico": "public, max-age=86400",  # 1 dia
            ".woff": "public, max-age=31536000",  # 1 ano
            ".woff2": "public, max-age=31536000",  # 1 ano
        }

        app.after_request(self.add_cache_headers)

    def add_cache_headers(self, response):
        """Adiciona headers de cache apropriados."""
        if request.endpoint == "static":
            # Obter extensão do arquivo
            filename = request.path
            ext = None
            if "." in filename:
                ext = "." + filename.rsplit(".", 1)[1].lower()

            # Aplicar cache config
            if ext in self.cache_config:
                response.headers["Cache-Control"] = self.cache_config[ext]

                # Adicionar ETag para arquivos estáticos
                if hasattr(response, "get_etag"):
                    etag = response.get_etag()
                    if etag[0]:
                        response.headers["ETag"] = etag[0]

        return response


def init_optimizations(app):
    """Inicializa todas as otimizações de performance."""

    # Cache headers apenas (removido compressão problemática)
    CacheMiddleware(app)

    # Headers de segurança básicos
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

    # Headers de compressão simples (deixar para servidor web)
    @app.after_request
    def add_compression_headers(response):
        # Apenas adicionar headers que indicam que podemos comprimir
        if response.content_type and any(
            ct in response.content_type
            for ct in ["text/", "application/json", "application/javascript"]
        ):
            response.headers["Vary"] = "Accept-Encoding"
        return response

    # Otimizações do Jinja2
    app.jinja_env.auto_reload = False
    app.jinja_env.cache_size = 400

    print("✅ Otimizações de performance aplicadas (versão corrigida)")
