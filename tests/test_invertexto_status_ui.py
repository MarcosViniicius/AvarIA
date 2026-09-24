"""Testes do bloco de status do invertexto no modal de unificacao.

Antes, o resultado do envio so aparecia num `confirm()` que sumia; nao dava
para recuperar o link depois. Agora fica um bloco visivel no modal com o link
pronto para copiar/abrir. Estes testes travam a estrutura e a logica.
"""

import re

import pytest

from autoavaria import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def html(client):
    return client.get("/historico/execucao/25").get_data(as_text=True)


@pytest.fixture(scope="module")
def js(client):
    return client.get("/static/js/historico-execucao.js").get_data(as_text=True)


class TestEstruturaDoBloco:
    @pytest.mark.parametrize("elemento", [
        "invertextoStatus",
        "invertextoStatusTitulo",
        "invertextoStatusDetalhe",
        "invertextoLink",
        "btnCopiarLinkInvertexto",
        "btnAbrirInvertexto",
    ])
    def test_elemento_existe(self, html, elemento):
        assert f'id="{elemento}"' in html

    def test_bloco_comeca_oculto(self, html):
        m = re.search(r'id="invertextoStatus"([^>]*)>', html)
        assert m is not None
        assert "d-none" in m.group(1)

    def test_link_e_somente_leitura(self, html):
        """O campo de link nao deve ser editavel."""
        m = re.search(r'id="invertextoLink"([^>]*)>', html)
        assert m is not None
        assert "readonly" in m.group(1)

    def test_botao_abrir_abre_em_nova_aba(self, html):
        m = re.search(r'id="btnAbrirInvertexto"([^>]*)>', html)
        assert m is not None
        assert 'target="_blank"' in m.group(1)
        # com noopener, para não dar acesso ao window.opener
        assert "noopener" in m.group(1)

    def test_aviso_de_texto_publico(self, html):
        """O bloco precisa lembrar que o link é público (privacidade)."""
        assert "Qualquer pessoa com este link pode ler o relatório" in html


class TestLogicaDoJs:
    def test_mostra_o_bloco_ao_ter_sucesso(self, js):
        assert "mostrarStatus" in js
        assert 'blocoStatus.classList.remove("d-none")' in js

    def test_usa_url_e_contagem_do_servidor(self, js):
        assert "res.dados.url" in js
        assert "res.dados.caracteres" in js

    def test_preenche_o_link_e_o_botao_abrir(self, js):
        assert "campoLink.value = url" in js
        assert 'btnAbrir.setAttribute("href", url)' in js

    def test_trata_falha_sem_alerta_que_some(self, js):
        assert "mostrarErroStatus" in js
        assert "alert-danger" in js

    def test_sucesso_apos_falha_volta_ao_visual_positivo(self, js):
        """O bloco é reaproveitado; um erro anterior não pode deixá-lo vermelho
        depois de um envio bem-sucedido."""
        assert 'alerta.classList.remove("alert-danger")' in js
        assert 'alerta.classList.add("alert-success")' in js

    def test_botao_copiar_copia_o_link(self, js):
        assert "btnCopiarLinkInvertexto" in js
        assert "navigator.clipboard.writeText(texto)" in js
