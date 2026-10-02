"""Testes da exportação para o invertexto (services/invertexto.py).

Cobre o que importa sem depender da rede:
- `sanitizar` remove as colunas internas (caminho do disco) preservando os
  dados de negócio, e funciona com seções de colunas diferentes;
- o envio falha de forma clara sem token e acima do limite de caracteres;
- a rota regenera o conteúdo no servidor (não aceita texto do cliente) e
  responde 400 quando a integração não está configurada.
"""

import pytest

from avariaia import create_app
from avariaia.services import invertexto


CONTEUDO_EXEMPLO = (
    "Avarias\n"
    "-------\n"
    "Produto\tQuantidade Total\tQuantidade\tPeso\tObservação da Mensagem\tCaminho da Imagem\tVer Imagem\n"
    "TOMATE\t3,096 kg\t1\t1,334kg\tNenhuma\tD:\\proj\\imagens_processadas\\uuid.jpg\tD:\\proj\\img\\uuid.jpg\n"
    "\n"
    "Uso Interno\n"
    "-----------\n"
    "Produto\tQuantidade Total\tCódigo de Barras\tQuantidade\tMarca\tObservação da Mensagem\tCaminho da Imagem\tVer Imagem\n"
    "CAFE\t6\t7891910030477\t1\tUNIAO\tNenhuma\tD:\\proj\\img\\xyz.jpg\tD:\\proj\\img\\xyz.jpg\n"
)


class TestSanitizar:
    def test_remove_caminho_do_disco(self):
        saida = invertexto.sanitizar(CONTEUDO_EXEMPLO)
        assert "D:\\proj" not in saida
        assert "imagens_processadas" not in saida

    def test_preserva_dados_de_negocio(self):
        saida = invertexto.sanitizar(CONTEUDO_EXEMPLO)
        assert "TOMATE" in saida
        assert "3,096 kg" in saida
        assert "7891910030477" in saida
        assert "UNIAO" in saida

    def test_funciona_com_secoes_de_colunas_diferentes(self):
        """Avarias e Uso Interno têm cabeçalhos distintos; os índices são
        aprendidos por seção, não fixos."""
        saida = invertexto.sanitizar(CONTEUDO_EXEMPLO)
        linhas = saida.splitlines()
        # o cabeçalho de Uso Interno deve manter Código de Barras
        cabecalho_ui = next(l for l in linhas if "Código de Barras" in l)
        assert "Caminho da Imagem" not in cabecalho_ui
        assert "Código de Barras" in cabecalho_ui

    def test_texto_vazio(self):
        assert invertexto.sanitizar("") == ""
        assert invertexto.sanitizar(None) == ""

    def test_remove_caminho_cru_em_observacao(self):
        """Rede de segurança: caminho absoluto fora do cabeçalho."""
        saida = invertexto.sanitizar("linha solta\tD:\\algum\\caminho\\arquivo.jpg\tfim")
        assert "D:\\algum" not in saida


class TestEnvio:
    def test_sem_token_falha_claro(self, monkeypatch):
        monkeypatch.setattr(invertexto, "_config_invertexto", lambda: {})
        sucesso, mensagem = invertexto.enviar("qualquer coisa")
        assert sucesso is False
        assert "não configurada" in mensagem.lower()

    def test_texto_vazio_falha(self, monkeypatch):
        monkeypatch.setattr(invertexto, "_config_invertexto", lambda: {"token": "x"})
        sucesso, mensagem = invertexto.enviar("")
        assert sucesso is False
        assert "nada para enviar" in mensagem.lower()

    def test_acima_do_limite_falha_antes_de_enviar(self, monkeypatch):
        monkeypatch.setattr(invertexto, "_config_invertexto", lambda: {"token": "x"})
        sucesso, mensagem = invertexto.enviar("a" * (invertexto.LIMITE_CARACTERES + 1))
        assert sucesso is False
        assert "limite" in mensagem.lower()

    def test_config_publica_nunca_vaza_token(self, monkeypatch):
        monkeypatch.setattr(
            invertexto, "_config_invertexto",
            lambda: {"token": "segredo-grande-1234", "url": "https://x/y"},
        )
        publica = invertexto.obter_config_publica()
        assert "token" not in publica
        assert "segredo-grande-1234" not in str(publica)
        assert publica["token_final"] == "1234"  # só os 4 últimos, para reconhecer


class TestRota:
    @pytest.fixture
    def client(self, tmp_db):
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    def test_rota_existe_e_nao_aceita_texto_do_cliente(self, client, monkeypatch, tmp_db):
        """Mesmo enviando texto no corpo, o servidor regenera o conteúdo."""
        from avariaia.services import db

        capturado = {}
        monkeypatch.setattr(invertexto, "configurado", lambda: True)
        def fake_enviar(texto, token=None):
            capturado["texto"] = texto
            return True, "ok"
        monkeypatch.setattr(invertexto, "enviar", fake_enviar)

        run_id = db.iniciar_execucao("processamento", imagens_total=1)
        db.registrar_itens(run_id, "Avarias", [{
            "Produto": "TOMATE", "Quantidade": 1, "Peso": "1kg",
            "Observação da Mensagem": "Nenhuma",
            "Caminho da Imagem": "C:\\disco\\x.jpg", "Ver Imagem": "C:\\disco\\x.jpg",
        }])
        db.finalizar_execucao(run_id, "concluido")

        resposta = client.post(
            f"/historico/execucao/{run_id}/enviar_invertexto",
            json={"texto": "CONTEUDO MALICIOSO DO CLIENTE"},
        )
        assert resposta.status_code == 200
        # o texto enviado veio do banco, não do corpo
        assert "CONTEUDO MALICIOSO" not in capturado["texto"]
        assert "TOMATE" in capturado["texto"]

    def test_sem_configuracao_responde_400(self, client, monkeypatch, tmp_db):
        from avariaia.services import db

        monkeypatch.setattr(invertexto, "configurado", lambda: False)
        run_id = db.iniciar_execucao("processamento", imagens_total=1)
        db.finalizar_execucao(run_id, "concluido")

        resposta = client.post(f"/historico/execucao/{run_id}/enviar_invertexto", json={})
        assert resposta.status_code == 400
        assert resposta.get_json()["success"] is False

    def test_execucao_inexistente_404(self, client):
        assert client.post("/historico/execucao/999999/enviar_invertexto", json={}).status_code == 404
