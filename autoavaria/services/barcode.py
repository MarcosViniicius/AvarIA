"""
LEITURA DE CÓDIGO DE BARRAS (sem IA)

Decodifica os códigos de barras das fotos usando `zxing-cpp` + `opencv`.
Nenhum modelo de IA, nenhuma chamada de rede, nenhum binário externo — só
processamento de imagem local.

Dois tipos de código aparecem nas fotos deste projeto:

1. **EAN-13 comum** (produto industrializado, aba "Uso Interno")
   Ex.: ``7897274410245`` — identifica o produto no catálogo.

2. **EAN-13 de balança / peso variável** (etiqueta impressa na loja, aba
   "Avarias"). O primeiro dígito é ``2`` e o restante carrega o código
   interno do produto (PLU) e o valor total em centavos::

       2 | 00140 | 000516 | 7
       ^     ^        ^     ^
       |     |        |     └─ dígito verificador
       |     |        └─ total em centavos = R$ 5,16
       |     └─ PLU (código interno do produto)
       └─ prefixo de peso variável

   O peso NÃO está no código — ele se obtém dividindo o total pelo preço
   por quilo do produto (ver `services/catalogo.py`).

Vantagem sobre a IA: o EAN-13 tem dígito verificador, então um código lido
ou está matematicamente correto ou é rejeitado. Não existe "alucinar" um
dígito, que é o erro que a IA comete com mais frequência.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

# ================================
# DEPENDÊNCIAS OPCIONAIS
# ================================
# Importadas de forma tolerante: se não estiverem instaladas, o modo "sem IA"
# fica indisponível mas o resto da aplicação (incluindo o modo IA) continua
# funcionando normalmente.

try:
    import cv2
    import numpy as np

    _CV2_DISPONIVEL = True
except ImportError:  # pragma: no cover - depende do ambiente
    _CV2_DISPONIVEL = False

try:
    import zxingcpp

    _ZXING_DISPONIVEL = True
except ImportError:  # pragma: no cover - depende do ambiente
    _ZXING_DISPONIVEL = False


LEITURA_DISPONIVEL = _CV2_DISPONIVEL and _ZXING_DISPONIVEL

MENSAGEM_INDISPONIVEL = (
    "Leitura de código de barras indisponível. Instale as dependências com: "
    "pip install zxing-cpp opencv-python-headless"
)

# Tamanho máximo do maior lado antes de processar. Fotos de celular passam de
# 3000px, o que deixa o detector lento sem ganho de precisão.
MAX_LADO = 1600


@dataclass
class CodigoLido:
    """Um código de barras decodificado com sucesso."""

    texto: str
    formato: str
    estrategia: str  # qual pré-processamento conseguiu ler (útil para diagnóstico)

    @property
    def eh_balanca(self) -> bool:
        return eh_etiqueta_balanca(self.texto)


# ================================
# VALIDAÇÃO E INTERPRETAÇÃO
# ================================


def ean13_valido(codigo: str) -> bool:
    """Confere o dígito verificador de um EAN-13.

    É esta checagem que torna a leitura por código de barras mais confiável
    que a leitura por IA: um dígito trocado quase sempre quebra o DV e o
    código é descartado em vez de entrar errado no relatório.
    """
    codigo = str(codigo).strip()
    if len(codigo) != 13 or not codigo.isdigit():
        return False
    soma = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(codigo[:12]))
    digito_esperado = (10 - soma % 10) % 10
    return digito_esperado == int(codigo[12])


def eh_etiqueta_balanca(codigo: str) -> bool:
    """Indica se o código é de etiqueta de balança (peso variável, prefixo 2)."""
    codigo = str(codigo).strip()
    return len(codigo) == 13 and codigo.isdigit() and codigo[0] == "2"


def interpretar_etiqueta_balanca(codigo: str) -> Optional[Tuple[str, float]]:
    """Extrai (PLU, total em reais) de um código de balança.

    Retorna ``None`` se o código não for uma etiqueta de balança válida.
    """
    codigo = str(codigo).strip()
    if not eh_etiqueta_balanca(codigo) or not ean13_valido(codigo):
        return None
    plu = codigo[1:6]
    total_reais = int(codigo[6:12]) / 100.0
    return plu, total_reais


def calcular_peso(total_reais: float, preco_por_kg: float) -> Optional[float]:
    """Calcula o peso em kg a partir do total da etiqueta e do preço por quilo."""
    if not preco_por_kg or preco_por_kg <= 0:
        return None
    return round(total_reais / preco_por_kg, 3)


# ================================
# PRÉ-PROCESSAMENTO E LEITURA
# ================================


def _variantes(cinza):
    """Gera variantes de pré-processamento, da mais barata para a mais cara.

    A ordem importa: a maioria das fotos é lida já na primeira variante, e
    as seguintes só rodam quando a anterior falha.
    """
    yield "original", cinza

    # Contraste local — resolve foto escura ou com reflexo na etiqueta.
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    yield "contraste", clahe.apply(cinza)

    # Ampliação — resolve código pequeno no quadro (foto tirada de longe).
    yield "ampliada", cv2.resize(cinza, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Nitidez — resolve foco levemente errado.
    borrado = cv2.GaussianBlur(cinza, (0, 0), 3)
    yield "nitidez", cv2.addWeighted(cinza, 1.5, borrado, -0.5, 0)

    # Rotações — foto deitada.
    yield "rot90", cv2.rotate(cinza, cv2.ROTATE_90_CLOCKWISE)
    yield "rot270", cv2.rotate(cinza, cv2.ROTATE_90_COUNTERCLOCKWISE)


def _ladrilhos(cinza, n: int = 3, sobreposicao: float = 0.25):
    """Divide a imagem em ladrilhos sobrepostos e amplia cada um.

    Último recurso, para quando o código ocupa uma fração pequena da foto:
    isolar o pedaço e ampliar costuma tornar as barras legíveis. É a
    estratégia mais cara, por isso só roda depois que todas as outras falham.
    """
    altura, largura = cinza.shape
    passo_y, passo_x = altura // n, largura // n
    margem_y, margem_x = int(passo_y * sobreposicao), int(passo_x * sobreposicao)

    for i in range(n):
        for j in range(n):
            y0 = max(0, i * passo_y - margem_y)
            y1 = min(altura, (i + 1) * passo_y + margem_y)
            x0 = max(0, j * passo_x - margem_x)
            x1 = min(largura, (j + 1) * passo_x + margem_x)
            recorte = cinza[y0:y1, x0:x1]
            if recorte.size == 0:
                continue
            yield f"ladrilho{i}{j}", cv2.resize(
                recorte, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC
            )


def _decodificar(matriz, estrategia: str) -> List[CodigoLido]:
    """Roda o decodificador numa matriz já pré-processada."""
    try:
        resultados = zxingcpp.read_barcodes(matriz)
    except Exception:
        return []

    lidos = []
    for r in resultados:
        texto = (r.text or "").strip()
        # Só aceitamos EAN-13 com dígito verificador válido. Outros formatos
        # (DataBar, Code128 de lote/validade) aparecem em algumas embalagens
        # mas não identificam o produto — entram como ruído se aceitos.
        if ean13_valido(texto):
            lidos.append(CodigoLido(texto=texto, formato=str(r.format), estrategia=estrategia))
    return lidos


def ler_imagem(caminho: str, tentar_ladrilhos: bool = True) -> List[CodigoLido]:
    """Lê todos os códigos de barras válidos de uma imagem.

    Retorna lista vazia se nada for lido — o chamador decide o que fazer
    (mandar para a IA, no modo híbrido, ou marcar como erro no modo sem IA).
    """
    if not LEITURA_DISPONIVEL:
        raise RuntimeError(MENSAGEM_INDISPONIVEL)

    imagem = cv2.imread(caminho)
    if imagem is None:
        return []

    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)

    # Reduz fotos gigantes de celular: mesma taxa de acerto, bem mais rápido.
    altura, largura = cinza.shape
    if max(altura, largura) > MAX_LADO:
        escala = MAX_LADO / max(altura, largura)
        cinza = cv2.resize(cinza, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)

    for estrategia, matriz in _variantes(cinza):
        lidos = _decodificar(matriz, estrategia)
        if lidos:
            return _sem_duplicatas(lidos)

    if tentar_ladrilhos:
        encontrados: List[CodigoLido] = []
        for estrategia, matriz in _ladrilhos(cinza):
            encontrados.extend(_decodificar(matriz, estrategia))
        if encontrados:
            return _sem_duplicatas(encontrados)

    return []


def _sem_duplicatas(lidos: List[CodigoLido]) -> List[CodigoLido]:
    """Remove códigos repetidos preservando a ordem de leitura.

    O mesmo código costuma ser detectado por mais de um ladrilho, já que os
    ladrilhos se sobrepõem de propósito.
    """
    vistos = set()
    unicos = []
    for codigo in lidos:
        if codigo.texto not in vistos:
            vistos.add(codigo.texto)
            unicos.append(codigo)
    return unicos
