"""Testes do bloco de status do invertexto no modal de unificação.

Antes, o resultado do envio só aparecia num `confirm()` que sumia; não dava
para recuperar o link depois. Agora fica um bloco visível no modal com o link
pronto para copiar/abrir.

Depois da consolidação, a unificação (modal, vista prévia, envio) vive num
módulo único — `js/unificacao-modal.js` — servindo a tela de Relatório e o
Histórico de execução. Estes testes miram esse módulo e a parcial única.
"""

import re

import pytest

from avariaia import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def html(client):
    """Parcial renderizada na tela de Relatório."""
    return client.get("/relatorio").get_data(as_text=True)


@pytest.fixture(scope="module")
def js(client):
    """Módulo único da unificação."""
    return client.get("/static/js/unificacao-modal.js").get_data(as_text=True)


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
        m = re.search(r'id="invertextoLink"([^>]*)>', html)
        assert m is not None
        assert "readonly" in m.group(1)

    def test_botao_abrir_abre_em_nova_aba(self, html):
        m = re.search(r'id="btnAbrirInvertexto"([^>]*)>', html)
        assert m is not None
        assert 'target="_blank"' in m.group(1)
        assert "noopener" in m.group(1)

    def test_aviso_de_texto_publico(self, html):
        assert "Qualquer pessoa com este link pode ler o relatório" in html


class TestLogicaDoJs:
    def test_mostra_o_bloco_ao_ter_sucesso(self, js):
        assert "mostrarStatusInvertexto" in js
        assert 'bloco.classList.remove("d-none")' in js

    def test_usa_url_e_contagem_do_servidor(self, js):
        assert "res.dados.url" in js
        assert "res.dados.caracteres" in js

    def test_preenche_o_link_e_o_botao_abrir(self, js):
        assert 'el("invertextoLink").value = url' in js
        assert 'el("btnAbrirInvertexto").setAttribute("href", url)' in js

    def test_trata_falha_sem_alerta_que_some(self, js):
        assert "mostrarErroInvertexto" in js
        assert "alert-danger" in js

    def test_sucesso_apos_falha_volta_ao_visual_positivo(self, js):
        """O bloco é reaproveitado; um erro anterior não pode deixá-lo vermelho
        depois de um envio bem-sucedido."""
        assert 'alerta.classList.remove("alert-danger")' in js
        assert 'alerta.classList.add("alert-success")' in js

    def test_botao_copiar_copia_o_link(self, js):
        assert "copiarLink" in js
        assert "navigator.clipboard.writeText(texto)" in js

    def test_escolhe_a_rota_conforme_o_escopo(self, js):
        """Mestre e execução usam rotas diferentes para a MESMA ação."""
        assert "apiInvertexto" in js
        assert "/historico/execucao/" in js
        assert "/api/enviar_invertexto" in js
        assert "/api/unificar_relatorio" in js
