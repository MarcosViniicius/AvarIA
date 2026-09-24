"""Regressão: o JS não pode referenciar ids que não existem no HTML.

O bug relatado ("Ocorreu um erro inesperado" ao unificar) era exatamente isso:
`historico-execucao.js` chamava `getElementById("btnIniciarUnificacaoExec")`,
mas o template usa `id="btnUnificarExec"`. O getElementById devolvia null, o
`.classList` estourava TypeError, e o handler global transformava a exceção num
aviso genérico — escondendo a causa.

Este teste varre todos os módulos JS carregados pelas páginas e confere que
todo id literal usado em getElementById existe em ALGUMA página. Um id que não
existe em lugar nenhum é, no mínimo, código morto — e no caso do bug, era uma
quebra real no meio da função.
"""

import re

import pytest

from autoavaria import create_app

PAGINAS = [
    "/", "/upload", "/relatorio", "/historico", "/configuracoes",
    "/logs", "/editar_dados", "/historico/execucao/25",
]

MODULOS_JS = [
    "js/main.js", "js/image-modal.js", "js/relatorio.min.js",
    "js/reanalise-selecao.js", "js/editar_dados.js",
    "js/historico-execucao.js", "js/relatorio-acoes.js",
    "js/pages/dashboard.js", "js/pages/upload.js",
    "js/pages/configuracoes.js", "js/pages/logs.js",
]

# Ids de componentes dinâmicos que o JS cria/remove em runtime, ou de telas
# que não estão na lista de páginas testadas. Documentados aqui de propósito:
# se um novo aparecer, o teste falha e obriga a decidir (implementar o
# elemento ou remover a referência).
IDS_DINAMICOS_CONHECIDOS = {
    "btnReanalisarErros",  # legado do modal de reanálise antigo; guardado por `if (modalElement)`
}


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def ids_no_js(client):
    todos = ""
    for modulo in MODULOS_JS:
        resposta = client.get(f"/static/{modulo}")
        if resposta.status_code == 200:
            todos += resposta.get_data(as_text=True)
    return {
        i for i in re.findall(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', todos)
        if not i.isupper()  # ignora ids montados dinamicamente (ex.: template)
    }


@pytest.fixture(scope="module")
def ids_no_html(client):
    presentes = set()
    for pagina in PAGINAS:
        html = client.get(pagina).get_data(as_text=True)
        presentes |= set(re.findall(r'id="([^"]+)"', html))
    return presentes


def test_nenhum_id_orfao(ids_no_js, ids_no_html):
    orfaos = sorted(ids_no_js - ids_no_html - IDS_DINAMICOS_CONHECIDOS)
    assert not orfaos, (
        "Ids usados no JS que não existem em nenhuma página: "
        f"{orfaos}. Se o elemento foi criado dinamicamente, adicione em "
        "IDS_DINAMICOS_CONHECIDOS; senão, corrija a referência."
    )


def test_unificacao_usa_o_id_correto_do_botao(client):
    """O caso específico do bug: o botão de unificar é `btnUnificarExec`."""
    html = client.get("/historico/execucao/25").get_data(as_text=True)
    assert 'id="btnUnificarExec"' in html

    js = client.get("/static/js/historico-execucao.js").get_data(as_text=True)
    # remove comentários: o id antigo pode ser citado na explicação do bug
    codigo = re.sub(r"//[^\n]*", "", js)
    codigo = re.sub(r"/\*.*?\*/", "", codigo, flags=re.S)
    # a referência antiga (id inexistente) não pode voltar ao código
    assert "btnIniciarUnificacaoExec" not in codigo
    # e o id certo precisa ser de fato usado para esconder/mostrar o botão
    assert 'getElementById("btnUnificarExec")' in codigo


def test_bloco_do_invertexto_e_escondido_ao_reabrir(client):
    """Não pode sobrar o link de uma unificação anterior no modal."""
    js = client.get("/static/js/historico-execucao.js").get_data(as_text=True)
    # aparece tanto no abrir quanto no iniciar
    assert js.count('getElementById("invertextoStatus")') >= 2
