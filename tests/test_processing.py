"""Testes de routes/processing.py.

Bug relatado: clicar em "Processar" extraía os arquivos comprimidos DUAS
vezes seguidas - uma vez em iniciar_processamento() (síncrono, precisa
checar se sobrou alguma imagem antes de decidir se vale a pena disparar a
thread de processamento) e outra dentro da própria thread
(processar_em_background). O conteúdo não duplicava (nome_para_gravar
detecta o conteúdo já extraído), mas a extração rodava - e demorava - duas
vezes à toa a cada clique.
"""

import pytest

from autoavaria.routes import processing as processing_route


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    pasta_imagens = tmp_path / "imagens"
    pasta_imagens.mkdir()
    monkeypatch.setattr(processing_route, "DIRETORIO_IMAGENS", str(pasta_imagens))
    monkeypatch.setattr(processing_route, "carregar_configuracao", lambda: {"processamento": {}})
    monkeypatch.setattr(
        processing_route, "verificar_e_corrigir_configuracao", lambda modo=None: (True, "ok")
    )
    return {"imagens": pasta_imagens}


class TestExtracaoNaoRepeteNoBackground:
    def test_reaproveita_resultado_previo_em_vez_de_extrair_de_novo(self, ambiente, monkeypatch):
        chamadas = []

        def fake_extrair(pasta, callback=None):
            chamadas.append(pasta)
            return {"arquivos_encontrados": 2, "arquivos_extraidos": 2, "detalhes": {}}

        monkeypatch.setattr(processing_route, "extrair_arquivos_comprimidos", fake_extrair)

        # Pasta sem imagens: a função para logo depois do bloco de extração
        # (early return "Nenhuma imagem encontrada"), sem precisar mockar o
        # pipeline de IA inteiro.
        processing_route.processar_em_background(
            resultado_extracao_previo={"arquivos_encontrados": 2, "arquivos_extraidos": 2, "detalhes": {}}
        )

        assert chamadas == []

    def test_sem_resultado_previo_ainda_extrai_normalmente(self, ambiente, monkeypatch):
        """Comportamento de fallback: se por algum motivo não houver
        resultado prévio (ex.: erro na extração síncrona), a thread continua
        extraindo por conta própria - não deve silenciosamente pular a
        extração."""
        chamadas = []

        def fake_extrair(pasta, callback=None):
            chamadas.append(pasta)
            return {"arquivos_encontrados": 0, "arquivos_extraidos": 0, "detalhes": {}}

        monkeypatch.setattr(processing_route, "extrair_arquivos_comprimidos", fake_extrair)

        processing_route.processar_em_background()

        assert len(chamadas) == 1

    def test_rota_processar_passa_o_resultado_ja_calculado_para_a_thread(self, monkeypatch, tmp_path):
        """Teste de integração leve: a rota /processar não deve deixar a
        thread reextrair o que ela mesma já extraiu de forma síncrona."""
        from autoavaria import create_app

        pasta_imagens = tmp_path / "imagens"
        pasta_imagens.mkdir()
        (pasta_imagens / "IMG-1.jpg").write_bytes(b"x")

        app = create_app()
        app.config["TESTING"] = True
        monkeypatch.setattr(processing_route, "DIRETORIO_IMAGENS", str(pasta_imagens))

        chamadas = []

        def fake_extrair(pasta, callback=None):
            chamadas.append(pasta)
            return {"arquivos_encontrados": 0, "arquivos_extraidos": 0, "detalhes": {}}

        monkeypatch.setattr(processing_route, "extrair_arquivos_comprimidos", fake_extrair)

        capturado = {}

        class ThreadFalsa:
            def __init__(self, target=None, args=()):
                capturado["target"] = target
                capturado["args"] = args

            def start(self):
                pass

        monkeypatch.setattr(processing_route.threading, "Thread", ThreadFalsa)

        client = app.test_client()
        resposta = client.post("/processar", json={})

        assert resposta.get_json()["success"] is True
        # extrair_arquivos_comprimidos só foi chamado UMA vez (dentro da
        # rota, de forma síncrona) - a thread (aqui, substituída por
        # ThreadFalsa) recebeu esse resultado pronto como argumento.
        assert len(chamadas) == 1
        assert capturado["target"] is processing_route.processar_em_background
        assert capturado["args"][1] == {"arquivos_encontrados": 0, "arquivos_extraidos": 0, "detalhes": {}}
