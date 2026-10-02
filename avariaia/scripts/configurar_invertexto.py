"""
CAPTURA DA CONFIGURAÇÃO DO INTERTEXTO

Busca a página do notepad, extrai o token e a URL e grava em
config/config.json. Roda uma única vez; depois disso o token fica guardado e a
exportação passa a funcionar sem nenhuma configuração manual.

Por que capturar em vez de gerar: o token pertence ao invertexto (identifica o
notepad) e vem embutido no HTML público da página. Gerar um aqui seria
recusado pelo serviço. Este script lê o valor real e persiste.

Uso:
    python -m avariaia.scripts.configurar_invertexto
    python -m avariaia.scripts.configurar_invertexto --url https://www.invertexto.com/outro
    python -m avariaia.scripts.configurar_invertexto --token TOKEN --url URL

Também é chamado automaticamente no primeiro boot (ver create_app), de forma
silenciosa e tolerante a falha: se não houver internet, o app sobe normal e a
exportação fica desabilitada.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request

from ..services import invertexto

TIMEOUT_SEGUNDOS = 20
_PADRAO_TOKEN = re.compile(r"var\s+token\s*=\s*'([^']+)'")
_PADRAO_URL = re.compile(r"https://www\.invertexto\.com/[\w-]+")


def extrair_token(html: str) -> str:
    """Token do notepad embutido no HTML da página ('' se não achar)."""
    m = _PADRAO_TOKEN.search(html)
    return m.group(1).strip() if m else ""


def capturar(url: str) -> tuple:
    """Busca `url` e devolve (token, url_final). Levanta em caso de falha."""
    requisicao = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(requisicao, timeout=TIMEOUT_SEGUNDOS) as resposta:
        html = resposta.read().decode("utf-8", "replace")

    token = extrair_token(html)
    if not token:
        raise ValueError(
            "Não encontrei o token do notepad na página. Confira se a URL é "
            "de um notepad do invertexto (ex.: https://www.invertexto.com/autoava)."
        )

    m = _PADRAO_URL.search(url if "invertexto.com" in url else html)
    url_final = m.group(0) if m else url
    return token, url_final


def configurar(url: str = invertexto.URL_PADRAO, verbose: bool = True) -> bool:
    """Captura e grava a configuração. Devolve True/False (não levanta)."""
    try:
        token, url_final = capturar(url)
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        if verbose:
            print(f"⚠️  Não foi possível configurar o invertexto automaticamente: {e}")
        return False

    if invertexto.salvar_config(token, url_final):
        if verbose:
            print(f"✅ invertexto configurado: {url_final} (token ...{token[-4:]})")
        return True

    if verbose:
        print("⚠️  Token capturado, mas não consegui salvar config/config.json.")
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Configura a exportação para o invertexto.")
    parser.add_argument("--url", default=invertexto.URL_PADRAO, help="URL do notepad")
    parser.add_argument("--token", help="Token (pula a captura e usa este direto)")
    args = parser.parse_args(argv)

    if args.token:
        ok = invertexto.salvar_config(args.token, args.url)
        print("✅" if ok else "⚠️", "Configuração salva." if ok else "Falha ao salvar.")
        return 0 if ok else 1

    return 0 if configurar(args.url) else 1


if __name__ == "__main__":
    sys.exit(main())
