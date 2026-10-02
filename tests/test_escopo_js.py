"""Regressão: nada pode chamar função de escopo fechado por atributo inline.

O bug relatado ("abrirModalUnificacao is not defined") era isso: o template
tinha `onclick="abrirModalUnificacao()"`, mas a função é declarada DENTRO do
`document.addEventListener("DOMContentLoaded", ...)` em historico-execucao.js.
Atributo inline executa no escopo global, onde ela não existe.

Este teste varre os templates por handlers inline (onclick/onchange/onsubmit)
e falha se a função chamada não estiver declarada no escopo global do seu
módulo. Também confere que os módulos de cada página estão declarados de forma
consistente.
"""

import re
from pathlib import Path

import pytest

from avariaia import create_app

TEMPLATES = Path(__file__).resolve().parents[1] / "avariaia" / "templates"
JS_DIR = Path(__file__).resolve().parents[1] / "avariaia" / "static" / "js"

# Handlers inline que ainda são legítimos: funções pequenas, deliberadamente
# globais (definidas com `function nome()` no escopo do módulo, fora de
# qualquer callback). Ver tests do próprio módulo.
_INLINE_PERMITIDO = set()


def _funcoes_globais_do_modulo(caminho: Path) -> set:
    """Funções disponíveis no escopo global a partir deste módulo.

    Aceita as duas formas usadas no projeto:
    - `function nome(...)` no topo (declaração clássica);
    - `window.nome = function(...)` (atribuição explícita, usada quando a
      função precisa mesmo ser alcançável por handler inline).
    """
    if not caminho.exists():
        return set()
    texto = caminho.read_text(encoding="utf-8")
    globais = {m.group(1) for m in re.finditer(r"^function\s+(\w+)", texto, re.M)}
    globais |= {m.group(1) for m in re.finditer(r"window\.(\w+)\s*=", texto)}
    return globais


def _chamadas_inline_do_template(caminho: Path) -> set:
    """Nomes de função chamados em atributos inline (onclick etc.).

    Ignora chamadas de membro (`window.location.reload()`, `this.foo()`) — o
    alvo é achar função NOSSA chamada pelo nome puro, que é a que quebra
    quando vive num escopo fechado.
    """
    texto = caminho.read_text(encoding="utf-8")
    chamadas = set()
    for m in re.finditer(r'\bon\w+\s*=\s*"([^"]+)"', texto):
        corpo = m.group(1)
        # remove chamadas de membro antes de procurar nomes puros
        corpo_sem_membros = re.sub(r"\b\w+(?:\.\w+)+\s*\(", "", corpo)
        for f in re.findall(r"(\w+)\s*\(", corpo_sem_membros):
            if f not in ("if", "return", "function"):
                chamadas.add(f)
    return chamadas


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_sem_onclick_para_funcao_de_escopo_fechado():
    """Handlers inline só podem chamar função global de verdade.

    Como os módulos declaram quase tudo dentro de DOMContentLoaded (para não
    poluir o escopo global), o esperado é que praticamente não haja handler
    inline em template nenhum.
    """
    # nomes declarados no escopo global, em qualquer módulo
    globais = set()
    for js in JS_DIR.rglob("*.js"):
        globais |= _funcoes_globais_do_modulo(js)

    problemas = []
    for template in TEMPLATES.glob("*.html"):
        for nome in _chamadas_inline_do_template(template):
            if nome in _INLINE_PERMITIDO:
                continue
            # presente no HTML mas não declarado globalmente em nenhum módulo
            if nome not in globais:
                problemas.append((template.name, nome))

    assert not problemas, (
        "Handler inline chamando função que não existe no escopo global "
        f"(vai dar 'is not defined' em runtime): {problemas}. "
        "Troque por delegação de eventos com data-*/id."
    )


def test_botao_unificar_do_historico_usa_delegacao(client):
    """O botão Unificar abre o modal pelo módulo único, sem onclick inline."""
    html = client.get("/historico/execucao/25").get_data(as_text=True)
    assert "data-unif-abrir" in html
    assert "abrirModalUnificacao()" not in html

    js = client.get("/static/js/unificacao-modal.js").get_data(as_text=True)
    assert 'querySelectorAll("[data-unif-abrir]")' in js


def test_unificacao_vive_num_modulo_unico(client):
    """A mesma parcial e o mesmo módulo servem Relatório e Histórico.

    Antes havia duas implementações concorrentes (relatorio-acoes.js e
    historico-execucao.js), com ids e funções duplicados — origem de bugs.
    """
    rel = client.get("/relatorio").get_data(as_text=True)
    hist = client.get("/historico/execucao/25").get_data(as_text=True)
    for html in (rel, hist):
        assert "js/unificacao-modal.js" in html

    # nenhum dos dois pode voltar a ter a função de unificação
    for modulo in ("js/relatorio-acoes.js", "js/historico-execucao.js"):
        js = client.get(f"/static/{modulo}").get_data(as_text=True)
        codigo = re.sub(r"//[^\n]*", "", js)
        codigo = re.sub(r"/\*.*?\*/", "", codigo, flags=re.S)
        assert "function abrirModalUnificacao" not in codigo, modulo


def test_funcoes_do_modulo_do_historico_estao_no_escopo_do_modulo():
    """Sanidade: nenhuma função do módulo ficou declarada fora do listener."""
    js = (JS_DIR / "historico-execucao.js").read_text(encoding="utf-8")
    # nenhuma declaração de função solta no topo (todas dentro do DOMContentLoaded)
    assert not re.search(r"^function\s+\w+", js, re.M), (
        "Função declarada no escopo global do módulo: o resto do arquivo usa "
        "o escopo do DOMContentLoaded; misturar os dois confunde as chamadas."
    )
