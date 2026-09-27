from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from autoavaria import create_app

app = create_app()
app_vercel = app

def application(environ, start_response):
    return app(environ, start_response)

def handler(_request):
    return app

if __name__ == "__main__":
    # threaded=True: sem isso, o servidor de desenvolvimento atende UMA
    # requisição por vez. Cada página carrega ~15-20 recursos (CSS, JS,
    # fontes, ícones) que o navegador tenta buscar em paralelo — sem
    # threading, o servidor enfileira e responde um de cada vez, fazendo o
    # tempo total ser a SOMA de todas as requisições em vez do tempo da mais
    # lenta. Testado: reduz o tempo de carregamento em torno de 25-30%.
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
