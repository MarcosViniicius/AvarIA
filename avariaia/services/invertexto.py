"""
EXPORTAÇÃO PARA O INTERTEXTO (notepad online)

Envia o relatório unificado para um notepad público do invertexto.com, para
consulta rápida por link (ex.: https://www.invertexto.com/autoava).

Como funciona: o próprio site usa um endpoint AJAX interno
(`/ajax/notepad.php`) que recebe `token` + `saved_text`. O token identifica o
notepad e vem embutido no HTML público da página — NÃO é um segredo de API,
mas também não é gerado aqui: quem gera é o invertexto, por isso ele é
capturado uma vez e guardado em config/config.json (arquivo não versionado,
ver AGENTS.md). Sem token configurado, a exportação fica desabilitada.

Privacidade: o texto de um notepad sem senha é PÚBLICO. A rota de unificação
avisa o usuário antes de enviar. Por isso também existe `sanitizar()`: o
relatório interno carrega o "Caminho da Imagem" com o caminho absoluto do
disco de quem processou, que não faz sentido compartilhar e é removido.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

from .config_service import carregar_configuracao, salvar_configuracao

LIMITE_CARACTERES = 50000  # limite do próprio invertexto
URL_PADRAO = "https://www.invertexto.com/autoava"
ENDPOINT = "https://www.invertexto.com/ajax/notepad.php"
TIMEOUT_SEGUNDOS = 20

# Colunas internas que não devem sair do sistema num relatório para terceiros.
_COLUNAS_A_REMOVER = ("Caminho da Imagem", "Ver Imagem", "id_linha")


def _config_invertexto() -> Dict[str, str]:
    config = carregar_configuracao()
    return config.get("invertexto", {}) or {}


def configurado() -> bool:
    """True se há token guardado (senão a exportação fica desabilitada)."""
    return bool((_config_invertexto().get("token") or "").strip())


def obter_config_publica() -> Dict[str, object]:
    """Config da integração para a UI (nunca devolve o token inteiro)."""
    cfg = _config_invertexto()
    token = (cfg.get("token") or "").strip()
    return {
        "url": cfg.get("url") or URL_PADRAO,
        "configurado": bool(token),
        # só o suficiente para o usuário reconhecer a configuração
        "token_final": token[-4:] if token else "",
    }


def salvar_config(token: str, url: Optional[str] = None) -> bool:
    """Guarda token/url em config.json (usado pelo script de captura)."""
    config = carregar_configuracao()
    config.setdefault("invertexto", {})
    config["invertexto"]["token"] = (token or "").strip()
    if url:
        config["invertexto"]["url"] = url.strip()
    return salvar_configuracao(config)


def sanitizar(contenido: str) -> str:
    """Remove colunas internas (caminho do disco) do texto da unificação.

    O texto é montado por `renderizar_txt_compacto`/`renderizar_secciones_como_texto`
    no formato ``NOME \\t VALOR \\t ...`` por linha, com um cabeçalho de colunas
    no início de cada seção. Removemos as colunas que são puro ruído fora do
    sistema — o caminho absoluto da máquina que processou — preservando todo o
    resto (produto, quantidade, peso, código).

    Os índices são aprendidos do cabeçalho de cada seção (a linha que contém os
    nomes das colunas), então funciona mesmo quando as seções têm colunas
    diferentes (Avarias vs Uso Interno).
    """
    if not contenido:
        return ""

    indices_atuais: list = []
    saida = []

    for linha in contenido.splitlines():
        if "\t" not in linha:
            # Linha de título/separador de seção: o próximo cabeçalho de
            # colunas redefine os índices.
            indices_atuais = []
            saida.append(linha)
            continue

        celulas = linha.split("\t")

        # Esta linha é o cabeçalho de colunas? Aprende os índices a remover.
        if any(c.strip() in _COLUNAS_A_REMOVER for c in celulas):
            indices_atuais = [
                i for i, c in enumerate(celulas)
                if c.strip() in _COLUNAS_A_REMOVER
            ]

        if indices_atuais:
            celulas = [
                c for i, c in enumerate(celulas) if i not in indices_atuais
            ]

        saida.append("\t".join(celulas))

    texto = "\n".join(saida)

    # Rede de segurança: caminho absoluto cru que tenha escapado (ex.: dentro
    # de uma observação) vira um marcador neutro.
    texto = re.sub(r"[A-Za-z]:\\[^\t\n\r]*", "[imagem]", texto)

    return texto


def enviar(texto: str, token: Optional[str] = None) -> Tuple[bool, str]:
    """Envia `texto` ao notepad. Devolve (sucesso, mensagem).

    O chamador deve enviar conteúdo já sanitizado (ver `sanitizar`).
    """
    token = (token or _config_invertexto().get("token") or "").strip()
    if not token:
        return False, "Integração com o invertexto não configurada (token ausente)."

    if not texto or not texto.strip():
        return False, "Nada para enviar."

    if len(texto) > LIMITE_CARACTERES:
        return False, (
            f"O texto tem {len(texto):,} caracteres e passa do limite de "
            f"{LIMITE_CARACTERES:,} do invertexto. Reduza a seleção de seções/colunas."
        )

    dados = urllib.parse.urlencode({"token": token, "saved_text": texto}).encode()
    requisicao = urllib.request.Request(
        ENDPOINT,
        data=dados,
        headers={
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_SEGUNDOS) as resposta:
            corpo = resposta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"O invertexto respondeu com erro HTTP {e.code}."
    except urllib.error.URLError as e:
        return False, f"Não foi possível alcançar o invertexto: {e.reason}"
    except Exception as e:  # rede/timeout/SSL — não vale derrubar a rota
        return False, f"Falha ao enviar para o invertexto: {e}"

    try:
        resposta_json = json.loads(corpo)
    except json.JSONDecodeError:
        return False, "Resposta inesperada do invertexto."

    if resposta_json.get("status") == "ok":
        return True, "Relatório enviado para o invertexto!"

    return False, f"O invertexto recusou o envio: {resposta_json.get('status', 'motivo desconhecido')}"
