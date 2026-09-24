"""Testes da tela de Configurações reformulada (3 abas) e do resumo de dados.

Contexto: a tela tinha 4 abas, sendo duas problemáticas — "Modo de
Processamento" (uma configuração só) e "Edição de Dados" (sem dado algum, só
botões que levavam a outro lugar). Agora são 3: Processamento, Dados e
Gerenciamento, e a aba Dados mostra o estado real antes de oferecer ações.
"""

import pytest

from autoavaria import create_app
from autoavaria.services import resumo_dados


@pytest.fixture
def client(tmp_db):
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestEstruturaDaTela:
    def test_tem_tres_abas(self, client):
        html = client.get("/configuracoes").get_data(as_text=True)
        assert 'data-bs-target="#api"' in html
        assert 'data-bs-target="#data"' in html
        assert 'data-bs-target="#manage"' in html

    def test_nao_existe_mais_aba_separada_de_modo(self, client):
        """O modo de extração foi fundido na aba de processamento."""
        html = client.get("/configuracoes").get_data(as_text=True)
        assert 'id="advanced"' not in html
        assert 'data-bs-target="#advanced"' not in html
        # mas o campo continua existindo (dentro da aba de processamento)
        assert 'id="modoExtracao"' in html

    def test_aba_processamento_tem_api_e_modo_juntos(self, client):
        html = client.get("/configuracoes").get_data(as_text=True)
        # o formulário único carrega tanto os campos de API quanto o modo
        assert 'id="apiProvider"' in html
        assert 'id="modoExtracao"' in html
        assert html.index('id="apiProvider"') < html.index('id="modoExtracao"')

    def test_aba_dados_mostra_informacao(self, client):
        html = client.get("/configuracoes").get_data(as_text=True)
        # estado do sistema (não só botões)
        assert "Execuções" in html
        assert "Tokens consumidos" in html
        assert "Relatórios unificados" in html

    def test_aba_gerenciamento_separa_risco(self, client):
        html = client.get("/configuracoes").get_data(as_text=True)
        assert "Limpeza segura" in html
        assert "Ações destrutivas" in html
        # o aviso de irreversibilidade precisa existir
        assert "não podem ser desfeitas" in html

    def test_backup_de_config_fica_com_a_config_nao_com_os_dados(self, client):
        """Antes o link de backup aparecia na aba de dados, o que confundia."""
        html = client.get("/configuracoes").get_data(as_text=True)
        # há UM único link de backup, e ele está fora da aba de dados
        assert html.count("Baixar backup das configura") == 1
        pos_backup = html.index("Baixar backup das configura")
        pos_aba_dados = html.index('id="data"')
        assert pos_backup < pos_aba_dados

    def test_acoes_de_manutencao_preservadas(self, client):
        """A reformulação não pode sumir com nenhuma ação existente."""
        html = client.get("/configuracoes").get_data(as_text=True)
        for tipo in ("exportacoes", "logs", "imagens", "relatorio", "reprocessar_tudo"):
            assert f'data-type="{tipo}"' in html, f"ação {tipo} desapareceu"


class TestResumoDados:
    def test_sem_relatorio_marca_inexistente(self, tmp_db, monkeypatch):
        from autoavaria.core import paths

        monkeypatch.setattr(resumo_dados, "ARQUIVO_SAIDA_EXCEL", paths.RESULTADOS_DIR / "nao_existe.xlsx")
        resumo = resumo_dados.obter_resumo_dados()
        assert resumo["relatorio"]["existe"] is False
        assert resumo["relatorio"]["total_itens"] == 0

    def test_devolve_estrutura_esperada(self, tmp_db):
        resumo = resumo_dados.obter_resumo_dados()
        for chave in ("relatorio", "execucoes", "tokens", "unificados", "imagens"):
            assert chave in resumo, f"faltou {chave}"
        assert set(resumo["imagens"]) == {"total", "processadas", "pendentes"}
