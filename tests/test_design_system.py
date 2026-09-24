"""Testes do design system aplicado (tokens, tipografia, formas).

Trava as decisões do documento de design para que uma edição futura não
desfaça, sem querer, o que caracteriza a identidade:

- canvas near-black #101010 como única superfície de página;
- um único acento (electric green #00d992), reservado a CTA/status/ícone;
- hairline sólida #3d3a39 como sistema de elevação (card NÃO tem sombra);
- Inter (narrativa) + JetBrains Mono (código, métricas);
- raios 6px botão, 8px card, pill só em tag;
- display em weight 400 (calmo) com tracking negativo.
"""

import re

import pytest

from autoavaria import create_app


@pytest.fixture(scope="module")
def css():
    """Conteúdo dos CSS do núcleo, para inspeção."""
    app = create_app()
    app.config["TESTING"] = True
    cliente = app.test_client()
    arquivos = (
        "tokens.css", "base.css", "components.css",
        "navbar.css", "utilities.css", "overlays.css",
    )
    return {
        nome: cliente.get(f"/static/css/{nome}").get_data(as_text=True)
        for nome in arquivos
    }


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestTokens:
    @pytest.mark.parametrize("token, valor", [
        ("--bg", "#101010"),
        ("--accent", "#00d992"),
        ("--accent-hi", "#2fd6a1"),
        ("--accent-lo", "#10b981"),
        ("--line", "#3d3a39"),
        ("--text", "#f2f2f2"),
        ("--text-2", "#bdbdbd"),
        ("--text-3", "#8b949e"),
        ("--canvas-soft", "#1a1a1a"),
    ])
    def test_paleta_do_design(self, css, token, valor):
        assert re.search(rf"{re.escape(token)}:\s*{re.escape(valor)}", css["tokens.css"])

    @pytest.mark.parametrize("token, valor", [
        ("--r-sm", "6px"),
        ("--r", "8px"),
        ("--r-pill", "9999px"),
    ])
    def test_escala_de_raios(self, css, token, valor):
        assert re.search(rf"{re.escape(token)}:\s*{re.escape(valor)}", css["tokens.css"])

    def test_card_sem_sombra_material(self, css):
        """O design usa hairline como elevação; sombra material é proibida."""
        assert re.search(r"--card-shadow:\s*none", css["tokens.css"])

    def test_fontes_inter_e_mono(self, css):
        assert '"Inter"' in css["tokens.css"]
        assert "JetBrains Mono" in css["tokens.css"]
        # a face antiga não deve voltar
        assert "Geist" not in css["tokens.css"]

    def test_verde_reservado_nao_e_preenchimento_de_texto(self, css):
        """O acento não pode virar `background` de bloco de texto largo."""
        # no corpo (base.css) o acento só aparece em foco/link/chip
        base = css["base.css"]
        usos = re.findall(r"background:\s*var\(--accent\)", base)
        # `::selection` e `.skip-link` são estados, não preenchimento de texto
        assert len(usos) <= 1


class TestTipografia:
    def test_display_calmo_weight_400(self, css):
        """Hero não pode ser headline pesado (700+)."""
        bloco = re.search(r"h1,\s*\n(?:[^{]*)\{([^}]*)\}", css["base.css"])
        assert bloco is not None
        assert "font-weight: 400" in bloco.group(1)

    def test_tracking_do_display(self, css):
        assert "-0.65px" in css["base.css"]  # display-xl
        assert "-0.9px" in css["base.css"]   # display-lg

    def test_body_16px_lineheight_165(self, css):
        bloco = re.search(r"body\s*\{([^}]*)\}", css["base.css"])
        assert "font-size: 1rem" in bloco.group(1)
        assert "1.65" in bloco.group(1)

    def test_eyebrow_uppercase_com_tracking(self, css):
        assert ".eyebrow" in css["base.css"]
        assert "2.52px" in css["base.css"]
        assert "text-transform: uppercase" in css["base.css"]

    def test_code_chip_existe(self, css):
        assert ".code-chip" in css["base.css"]

    def test_selection_e_calt(self, css):
        assert '"calt" 1' in css["base.css"]
        assert "::selection" in css["base.css"]

    def test_divisor_tracejado_do_design(self, css):
        assert "rgba(79, 93, 117, 0.4)" in css["base.css"]


class TestComponentes:
    def test_card_e_hairline_sem_sombra(self, css):
        bloco = re.search(r"\.card\s*\{([^}]*)\}", css["components.css"])
        assert bloco is not None
        assert "box-shadow: none" in bloco.group(1)
        assert "var(--line)" in bloco.group(1)

    def test_card_interior_24px(self, css):
        bloco = re.search(r"\.card-body\s*\{([^}]*)\}", css["components.css"])
        assert "padding: 1.5rem" in bloco.group(1)

    def test_input_usa_canvas_soft(self, css):
        bloco = re.search(r"\.form-control,\s*\n\.form-select\s*\{([^}]*)\}", css["components.css"])
        assert bloco is not None
        assert "var(--canvas-soft)" in bloco.group(1)

    def test_botao_raio_6px(self, css):
        bloco = re.search(r"\.btn\s*\{([^}]*)\}", css["components.css"])
        assert "border-radius: var(--r-sm)" in bloco.group(1)

    def test_tokens_inexistentes_nao_se_tornaram_transparente_quebrado(self, css):
        """--inset-hi virou transparent: nenhum lugar deve usá-lo esperando brilho."""
        for nome, conteudo in css.items():
            assert "0 1px 2px rgba(0, 0, 0, 0.3)" not in conteudo, nome


class TestFontesCarregadas:
    def test_html_carrega_inter_e_jetbrains(self, client):
        html = client.get("/").get_data(as_text=True)
        assert "family=Inter" in html
        assert "JetBrains" in html
        assert "family=Geist" not in html
