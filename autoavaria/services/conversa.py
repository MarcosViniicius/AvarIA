"""
PARSER DA CONVERSA DO WHATSAPP (contexto de texto, sem IA)

Lê a exportação ``.txt`` da conversa e associa o texto às imagens. É a
terceira fonte de dados do sistema, independente do motor de extração
escolhido (IA, sem IA ou híbrido):

    código de barras → identidade do produto (peso, marca, nome)
    conversa         → QUANTIDADE e observações
    IA               → o que as duas anteriores não resolverem

A quantidade só existe aqui. Uma foto de linguiça com a legenda "7"
significa 7 unidades — não há nada na imagem que indique isso.

Regras de associação implementadas:

1. **Legenda na mesma mensagem** — linhas seguintes sem cabeçalho de
   data/hora fazem parte da mensagem que anexou a imagem.
2. **Comentário posterior** — uma mensagem só de texto logo depois da foto,
   antes de qualquer outra imagem e dentro de uma janela de tempo, é
   tratada como comentário sobre aquela foto. É o caso de alguém responder
   à imagem para dizer algo.
3. **Menção explícita ao arquivo** — uma mensagem que cita o nome do arquivo
   é associada a ele, esteja onde estiver na conversa.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# "01/07/2026 14:29 - Fulano: texto"
_CABECALHO = re.compile(
    r"^(?P<data>\d{2}/\d{2}/\d{4})[,]?\s+(?P<hora>\d{2}:\d{2}(?::\d{2})?)\s*-\s*(?P<resto>.*)$"
)
_AUTOR_E_TEXTO = re.compile(r"^(?P<autor>[^:]{1,60}):\s*(?P<texto>.*)$")
_NOME_IMAGEM = re.compile(r"([\w\-]+\.(?:jpg|jpeg|png))", re.IGNORECASE)
_MARCADOR_ANEXO = re.compile(r"\(arquivo anexado\)|<anexado:", re.IGNORECASE)

# Ruído que o WhatsApp insere e que nunca é conteúdo do usuário.
_RUIDO = (
    "mensagens e ligações são protegidas",
    "esta mensagem foi apagada",
    "mensagem apagada",
    "você criou este grupo",
    "criptografia de ponta a ponta",
)

# Janela para considerar que uma mensagem de texto comenta a foto anterior.
JANELA_COMENTARIO_MINUTOS = 15


@dataclass
class Mensagem:
    data_hora: Optional[datetime]
    autor: str
    texto: str
    imagem: Optional[str] = None

    @property
    def eh_anexo(self) -> bool:
        return self.imagem is not None


@dataclass
class ContextoImagem:
    """Tudo que a conversa diz sobre uma imagem."""

    imagem: str
    textos: List[str] = field(default_factory=list)
    quantidade: Optional[int] = None

    @property
    def texto(self) -> str:
        return "\n".join(t for t in self.textos if t)


# ---------------------------------------------------------------------------
# Leitura e parsing
# ---------------------------------------------------------------------------


def encontrar_arquivo_conversa(diretorio: str) -> Optional[str]:
    """Devolve o caminho do primeiro .txt do diretório, se houver."""
    try:
        for nome in sorted(os.listdir(diretorio)):
            if nome.lower().endswith(".txt"):
                return os.path.join(diretorio, nome)
    except OSError:
        return None
    return None


def _eh_ruido(texto: str) -> bool:
    minusculo = texto.lower()
    return any(r in minusculo for r in _RUIDO)


def parsear_mensagens(caminho_txt: str) -> List[Mensagem]:
    """Converte o arquivo exportado numa lista de mensagens.

    Trata mensagens de várias linhas: só uma linha com cabeçalho de data/hora
    inicia uma mensagem nova; as demais são continuação (a legenda da foto).
    """
    try:
        with open(caminho_txt, "r", encoding="utf-8") as f:
            linhas = f.read().splitlines()
    except OSError as e:
        print(f"⚠️ Não foi possível ler a conversa: {e}")
        return []

    mensagens: List[Mensagem] = []
    for linha in linhas:
        # O WhatsApp insere marcas invisíveis (U+200E) antes do nome do anexo.
        linha = linha.replace("‎", "").replace("‏", "").rstrip()
        if not linha.strip():
            continue

        cabecalho = _CABECALHO.match(linha)
        if not cabecalho:
            # Continuação da mensagem anterior (legenda em outra linha).
            if mensagens:
                mensagens[-1].texto = (mensagens[-1].texto + "\n" + linha.strip()).strip()
            continue

        resto = cabecalho.group("resto").strip()
        if _eh_ruido(resto):
            continue

        autor_match = _AUTOR_E_TEXTO.match(resto)
        if autor_match:
            autor = autor_match.group("autor").strip()
            texto = autor_match.group("texto").strip()
        else:
            # Mensagem de sistema (entrou no grupo, mudou o assunto etc.)
            autor, texto = "", resto

        imagem = None
        if _MARCADOR_ANEXO.search(texto):
            achado = _NOME_IMAGEM.search(texto)
            if achado:
                imagem = achado.group(1)
            texto = ""  # o marcador de anexo em si não é conteúdo

        try:
            data_hora = datetime.strptime(
                f"{cabecalho.group('data')} {cabecalho.group('hora')[:5]}", "%d/%m/%Y %H:%M"
            )
        except ValueError:
            data_hora = None

        mensagens.append(Mensagem(data_hora=data_hora, autor=autor, texto=texto, imagem=imagem))

    return mensagens


# ---------------------------------------------------------------------------
# Associação texto ↔ imagem
# ---------------------------------------------------------------------------


def construir_contextos(mensagens: List[Mensagem]) -> Dict[str, ContextoImagem]:
    """Associa o texto da conversa a cada imagem, aplicando as três regras."""
    contextos: Dict[str, ContextoImagem] = {}

    for i, mensagem in enumerate(mensagens):
        if not mensagem.eh_anexo:
            continue

        contexto = contextos.setdefault(mensagem.imagem, ContextoImagem(imagem=mensagem.imagem))

        # Regra 1: legenda anexada à própria mensagem.
        if mensagem.texto:
            contexto.textos.append(mensagem.texto)

        # Regra 2: mensagens de texto logo em seguida, até aparecer outra
        # imagem. São comentários sobre a foto que acabou de ser enviada.
        for seguinte in mensagens[i + 1 :]:
            if seguinte.eh_anexo:
                break
            if not seguinte.texto:
                continue
            if not _dentro_da_janela(mensagem, seguinte):
                break
            contexto.textos.append(seguinte.texto)

    # Regra 3: menção explícita ao nome do arquivo em qualquer ponto.
    for mensagem in mensagens:
        if mensagem.eh_anexo or not mensagem.texto:
            continue
        for nome in _NOME_IMAGEM.findall(mensagem.texto):
            if nome in contextos and mensagem.texto not in contextos[nome].textos:
                contextos[nome].textos.append(mensagem.texto)

    for contexto in contextos.values():
        contexto.quantidade = extrair_quantidade(contexto.texto)

    return contextos


def _dentro_da_janela(anexo: Mensagem, seguinte: Mensagem) -> bool:
    """Comentário só conta se veio pouco depois da foto."""
    if anexo.data_hora is None or seguinte.data_hora is None:
        return True  # sem timestamp confiável, mantemos a associação
    return seguinte.data_hora - anexo.data_hora <= timedelta(minutes=JANELA_COMENTARIO_MINUTOS)


# ---------------------------------------------------------------------------
# Extração de quantidade
# ---------------------------------------------------------------------------

# Unidades de contagem. Peso (kg/g) e dinheiro NÃO entram aqui de propósito:
# "0,738kg" é peso, não quantidade, e confundir os dois corromperia o relatório.
_UNIDADES = r"(?:un|und|unid|unidades?|pc|pcs|pç|peças?|cx|caixas?|fardos?|pct|pacotes?|sacos?|potes?|garrafas?)"

_PADROES_QUANTIDADE = (
    # "7 unidades", "3 cx", "2 pacotes"
    re.compile(rf"\b(\d{{1,4}})\s*{_UNIDADES}\b", re.IGNORECASE),
    # "x7" ou "7x"
    re.compile(r"\bx\s*(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,4})\s*x\b", re.IGNORECASE),
    # Linha contendo apenas um número — o caso "7" sozinho na legenda.
    re.compile(r"^\s*(\d{1,4})\s*$"),
)


def extrair_quantidade(texto: str) -> Optional[int]:
    """Extrai a quantidade de unidades mencionada no texto.

    Devolve ``None`` quando o texto não indica quantidade — o chamador
    assume 1. Nunca interpreta peso ou preço como quantidade.
    """
    if not texto:
        return None

    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        # Descarta linhas que são claramente peso ou dinheiro.
        if re.search(r"\d\s*(?:kg|g|gramas?|r\$)", linha, re.IGNORECASE):
            continue
        for padrao in _PADROES_QUANTIDADE:
            achado = padrao.search(linha)
            if achado:
                try:
                    valor = int(achado.group(1))
                except (TypeError, ValueError):
                    continue
                if 1 <= valor <= 9999:
                    return valor
    return None


# ---------------------------------------------------------------------------
# API usada pelo pipeline
# ---------------------------------------------------------------------------


def mapear_contextos(diretorio_imagens: str) -> Dict[str, ContextoImagem]:
    """Lê a conversa do diretório e devolve o contexto de cada imagem."""
    caminho = encontrar_arquivo_conversa(diretorio_imagens)
    if not caminho:
        print("ℹ️ Nenhum arquivo .txt de mensagens encontrado para análise de contexto.")
        return {}

    print(f"📄 Arquivo de mensagens encontrado: {os.path.basename(caminho)}")
    mensagens = parsear_mensagens(caminho)
    contextos = construir_contextos(mensagens)

    com_texto = sum(1 for c in contextos.values() if c.texto)
    com_quantidade = sum(1 for c in contextos.values() if c.quantidade)
    print(
        f"✅ Conversa: {len(mensagens)} mensagens, {len(contextos)} imagens citadas, "
        f"{com_texto} com texto associado, {com_quantidade} com quantidade identificada."
    )
    return contextos


def mapear_mensagens_para_imagens(diretorio_imagens: str) -> Dict[str, str]:
    """Compatível com a assinatura antiga: imagem → texto associado.

    Mantida para que o fluxo de IA existente continue funcionando sem
    alteração, agora alimentado pelo parser novo.
    """
    return {img: ctx.texto for img, ctx in mapear_contextos(diretorio_imagens).items() if ctx.texto}
