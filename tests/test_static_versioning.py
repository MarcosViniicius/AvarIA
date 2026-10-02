"""Testes do versionamento de estáticos (``static_v``).

Contexto: o CacheMiddleware serve ``/static/*`` com ``Cache-Control:
max-age=31536000`` (um ano). Sem carimbar a URL com o mtime do arquivo, o
navegador continua usando a versão antiga depois de uma edição — foi
exatamente o que fez uma correção de JS "não surtir efeito" e custou horas
de depuração. Estes testes travam esse comportamento.
"""

import re

import pytest

from avariaia import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestStaticVersioning:
    def test_static_v_adiciona_versao(self, client):
        html = client.get("/").get_data(as_text=True)
        urls = re.findall(r"/static/[^\"']+\?v=\d+", html)
        # base.html referencia o núcleo do design system + js/main.js
        for modulo in (
            "css/tokens.css?v=",
            "css/base.css?v=",
            "css/layout.css?v=",
            "css/navbar.css?v=",
            "css/components.css?v=",
            "css/overlays.css?v=",
            "css/utilities.css?v=",
            "css/responsive.css?v=",
        ):
            assert any(modulo in u for u in urls), f"núcleo sem {modulo}"
        assert any("js/main.js?v=" in u for u in urls)

    def test_versao_e_o_mtime_do_arquivo(self, client):
        app = create_app()
        with app.test_request_context():
            valor = app.jinja_env.globals["static_v"]("js/main.js")
        assert re.fullmatch(r"/static/js/main\.js\?v=\d+", valor)

    def test_arquivo_inexistente_nao_quebra(self, client):
        app = create_app()
        with app.test_request_context():
            valor = app.jinja_env.globals["static_v"]("js/nao-existe.js")
        assert valor == "/static/js/nao-existe.js?v=0"

    def test_templates_de_acao_incluem_seus_modulos(self, client):
        """As páginas que têm JS próprio precisam carregá-lo."""
        casos = {
            "/editar_dados": "js/editar_dados.js",
            "/relatorio": "js/relatorio-acoes.js",
            "/historico/execucao/22": "js/historico-execucao.js",
            "/": "js/pages/dashboard.js",
            "/upload": "js/pages/upload.js",
            "/logs": "js/pages/logs.js",
            "/configuracoes": "js/pages/configuracoes.js",
        }
        for pagina, modulo in casos.items():
            html = client.get(pagina).get_data(as_text=True)
            assert modulo in html, f"{pagina} não carrega {modulo}"

    def test_css_por_pagina(self, client):
        """Dashboard e upload carregam seu CSS; as demais usam só o núcleo."""
        nucleo = "css/components.css"
        for pagina in ("/", "/upload", "/relatorio", "/logs", "/configuracoes"):
            html = client.get(pagina).get_data(as_text=True)
            assert nucleo in html, f"{pagina} sem núcleo CSS"
            assert "css/style.css" not in html, f"{pagina} ainda usa style.css"
        assert "css/pages/dashboard.css" in client.get("/").get_data(as_text=True)
        assert "css/pages/upload.css" in client.get("/upload").get_data(as_text=True)
        assert "css/pages/dashboard.css" not in client.get("/upload").get_data(as_text=True)

    def test_sem_style_ou_script_inline(self, client):
        """Nenhum template pode ter <style> ou <script> de lógica inline.

        Exceções legítimas (pequenas, precisam ser inline):
        - o fundo do <html> no base.html (evita flash antes do CSS carregar);
        - o bootstrap de tema (localStorage antes do primeiro paint);
        - window.RUN_ID (dado do servidor para o módulo da página).
        """
        for pagina in (
            "/",
            "/upload",
            "/relatorio",
            "/historico",
            "/logs",
            "/configuracoes",
            "/editar_dados",
            "/historico/execucao/22",
        ):
            html = client.get(pagina).get_data(as_text=True)
            for m in re.finditer(r"<style[^>]*>(.*?)</style>", html, re.S):
                assert len(m.group(1)) < 300, f"{pagina} tem <style> grande inline"
            for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
                corpo = m.group(1).strip()
                # bootstrap de dados (tema, RUN_ID) é legítimo; lógica não
                assert len(corpo) < 800, f"{pagina} tem JS inline com {len(corpo)} chars"
                assert "function " not in corpo or "RUN_ID" in corpo or "avariaia-theme" in corpo, (
                    f"{pagina} tem função JS inline"
                )

    def test_historico_execucao_injeta_run_id(self, client):
        """O módulo lê window.RUN_ID; o template precisa defini-lo antes."""
        html = client.get("/historico/execucao/22").get_data(as_text=True)
        assert "window.RUN_ID" in html
        assert re.search(r"window\.RUN_ID\s*=\s*22\s*;", html)

    def test_nenhum_url_for_static_cru_nos_templates(self, client):
        """Se alguém voltar a usar url_for('static', ...), perde o carimbo."""
        for pagina in (
            "/",
            "/upload",
            "/relatorio",
            "/historico",
            "/logs",
            "/configuracoes",
            "/editar_dados",
            "/historico/execucao/22",
        ):
            html = client.get(pagina).get_data(as_text=True)
            assert "url_for" not in html, f"{pagina} deixou url_for cru no HTML"
