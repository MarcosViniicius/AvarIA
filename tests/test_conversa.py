"""Testes do parser da conversa do WhatsApp (services/conversa.py)."""

import pytest

from avariaia.services import conversa


def _escrever(tmp_path, conteudo: str) -> str:
    caminho = tmp_path / "conversa.txt"
    caminho.write_text(conteudo, encoding="utf-8")
    return str(caminho)


class TestExtrairQuantidade:
    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("7", 7),
            ("7 unidades", 7),
            ("3 cx", 3),
            ("x2", 2),
            ("2x", 2),
            ("5 un", 5),
            ("7 pacotes de arroz", 7),
            ("4 fardos de água", 4),
        ],
    )
    def test_padroes_reconhecidos(self, texto, esperado):
        assert conversa.extrair_quantidade(texto) == esperado

    @pytest.mark.parametrize(
        "texto",
        [
            "0,738kg",
            "R$ 5,16",
            "peso 1,5 kg",
            "2 alface e 4 coentro",  # múltiplos itens na mesma linha - ambíguo, não interpretamos
            "tres unidades",  # por extenso não é reconhecido
            "",
        ],
    )
    def test_nao_confunde_peso_preco_com_quantidade(self, texto):
        assert conversa.extrair_quantidade(texto) is None

    def test_nenhum_texto_devolve_none(self):
        assert conversa.extrair_quantidade(None) is None


class TestParsearMensagens:
    def test_legenda_na_mesma_mensagem_vira_continuacao(self, tmp_path):
        conteudo = (
            "11/07/2026 16:43 - Marcos Lucena: ‎IMG-20260711-WA0041.jpg (arquivo anexado)\n"
            "7\n"
        )
        caminho = _escrever(tmp_path, conteudo)
        mensagens = conversa.parsear_mensagens(caminho)
        assert len(mensagens) == 1
        assert mensagens[0].imagem == "IMG-20260711-WA0041.jpg"
        assert mensagens[0].texto == "7"

    def test_ruido_do_sistema_e_ignorado(self, tmp_path):
        conteudo = (
            "20/01/2026 06:54 - As mensagens e ligações são protegidas com a "
            "criptografia de ponta a ponta. Somente as pessoas que fazem parte "
            "da conversa podem ler, ouvir e compartilhar esse conteúdo. *Saiba mais*\n"
            "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\n"
        )
        caminho = _escrever(tmp_path, conteudo)
        mensagens = conversa.parsear_mensagens(caminho)
        assert len(mensagens) == 1
        assert mensagens[0].imagem == "IMG-0001.jpg"

    def test_mensagem_sem_anexo_e_texto_puro(self, tmp_path):
        conteudo = "01/07/2026 14:29 - Fulano: perda de hoje: 4 coentro\n"
        caminho = _escrever(tmp_path, conteudo)
        mensagens = conversa.parsear_mensagens(caminho)
        assert len(mensagens) == 1
        assert mensagens[0].eh_anexo is False
        assert "coentro" in mensagens[0].texto


class TestConstruirContextos:
    def test_comentario_logo_apos_a_foto_e_associado(self, tmp_path):
        conteudo = (
            "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\n"
            "01/07/2026 14:30 - Fulano: esse aqui é uso interno\n"
        )
        caminho = _escrever(tmp_path, conteudo)
        contextos = conversa.mapear_contextos(str(tmp_path))
        assert "uso interno" in contextos["IMG-0001.jpg"].texto

    def test_comentario_fora_da_janela_nao_e_associado(self, tmp_path):
        conteudo = (
            "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\n"
            "01/07/2026 15:10 - Fulano: comentário tardio nao relacionado\n"  # 41min depois
        )
        caminho = _escrever(tmp_path, conteudo)
        contextos = conversa.mapear_contextos(str(tmp_path))
        assert contextos["IMG-0001.jpg"].texto == ""

    def test_proxima_foto_interrompe_associacao(self, tmp_path):
        conteudo = (
            "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\n"
            "01/07/2026 14:30 - Fulano: ‎IMG-0002.jpg (arquivo anexado)\n"
            "01/07/2026 14:31 - Fulano: comentário sobre a segunda foto\n"
        )
        caminho = _escrever(tmp_path, conteudo)
        contextos = conversa.mapear_contextos(str(tmp_path))
        assert contextos["IMG-0001.jpg"].texto == ""
        assert "segunda foto" in contextos["IMG-0002.jpg"].texto

    def test_quantidade_populada_no_contexto(self, tmp_path):
        conteudo = "11/07/2026 16:43 - Marcos: ‎IMG-0041.jpg (arquivo anexado)\n7\n"
        caminho = _escrever(tmp_path, conteudo)
        contextos = conversa.mapear_contextos(str(tmp_path))
        assert contextos["IMG-0041.jpg"].quantidade == 7

    def test_sem_arquivo_txt_devolve_vazio(self, tmp_path):
        assert conversa.mapear_contextos(str(tmp_path)) == {}

    def test_caso_real_linguica_de_frango(self, tmp_path):
        """Caso real que motivou este parser: legenda '7' numa foto de linguiça."""
        conteudo = (
            "11/07/2026 16:43 - Marcos Lucena: ‎IMG-20260711-WA0041.jpg (arquivo anexado)\n"
            "7\n"
        )
        caminho = _escrever(tmp_path, conteudo)
        contextos = conversa.mapear_contextos(str(tmp_path))
        ctx = contextos["IMG-20260711-WA0041.jpg"]
        assert ctx.quantidade == 7
        assert ctx.texto == "7"


class TestCompatibilidadeAssinaturaAntiga:
    def test_mapear_mensagens_para_imagens_devolve_dict_simples(self, tmp_path):
        conteudo = "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\nlegenda aqui\n"
        caminho = _escrever(tmp_path, conteudo)
        mapeamento = conversa.mapear_mensagens_para_imagens(str(tmp_path))
        assert mapeamento == {"IMG-0001.jpg": "legenda aqui"}

    def test_imagens_sem_texto_nao_aparecem_no_mapeamento(self, tmp_path):
        conteudo = "01/07/2026 14:29 - Fulano: ‎IMG-0001.jpg (arquivo anexado)\n"
        caminho = _escrever(tmp_path, conteudo)
        mapeamento = conversa.mapear_mensagens_para_imagens(str(tmp_path))
        assert mapeamento == {}
