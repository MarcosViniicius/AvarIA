"""
ARQUIVAMENTO DE IMAGENS PROCESSADAS

Move imagens já processadas com sucesso para fora da pasta de pendentes
(imagens_para_analisar/) e as recomprime para ocupar menos espaço, mantendo
nome e extensão exatos - o botão "Ver Imagem" e o Excel/banco resolvem a
imagem só pelo nome de arquivo, então trocar extensão ou formato quebraria
links já salvos.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Union

from PIL import Image

from ..core.paths import ARCHIVE_FOLDER

logger = logging.getLogger(__name__)

MAX_DIMENSAO_PX = 1600
JPEG_QUALITY = 70
_EXTENSOES_JPEG = (".jpg", ".jpeg")


def arquivar_imagem(
    nome_arquivo: str,
    pasta_origem: Union[str, Path],
    pasta_destino: Optional[Union[str, Path]] = None,
) -> bool:
    """Move `nome_arquivo` de `pasta_origem` para `pasta_destino` (padrão
    ARCHIVE_FOLDER), recomprimindo para reduzir espaço em disco.

    - .jpg/.jpeg: reduz dimensão (máx. 1600px no maior lado) e qualidade.
    - .png: só reotimiza (optimize=True), sem redimensionar nem trocar formato.

    Se a recompressão falhar por qualquer motivo (imagem corrompida, modo não
    suportado etc.), cai para uma cópia simples do arquivo original - nunca
    perde a imagem, nunca derruba o pipeline por causa disso.

    Só remove o arquivo original depois que o destino existe de fato no disco
    (mesma garantia de "grava antes de marcar" usada no resto do pipeline).

    Retorna True se a imagem foi arquivada, False se não havia nada para
    arquivar (arquivo de origem inexistente) ou se a gravação no destino
    falhou (nesse caso o original é mantido intocado).
    """
    origem = Path(pasta_origem) / nome_arquivo
    if not origem.exists():
        return False

    destino_dir = Path(pasta_destino) if pasta_destino is not None else ARCHIVE_FOLDER
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / nome_arquivo
    destino_tmp = destino.with_name(destino.name + ".tmp")

    try:
        _recomprimir(origem, destino_tmp)
    except Exception as e:
        logger.warning(f"⚠️ Falha ao recomprimir '{nome_arquivo}', arquivando sem recompressão: {e}")
        try:
            _copiar_sem_alterar(origem, destino_tmp)
        except Exception as e2:
            logger.error(f"❌ Falha ao arquivar '{nome_arquivo}': {e2}")
            if destino_tmp.exists():
                _remover_silenciosamente(destino_tmp)
            return False

    try:
        os.replace(destino_tmp, destino)
    except OSError as e:
        logger.error(f"❌ Falha ao mover '{nome_arquivo}' para o destino final: {e}")
        _remover_silenciosamente(destino_tmp)
        return False

    try:
        os.remove(origem)
    except OSError as e:
        # Destino já está gravado com sucesso; não remover a origem só deixa
        # uma cópia extra para trás, não é um estado inconsistente.
        logger.warning(f"⚠️ Não foi possível remover o original '{nome_arquivo}' após arquivar: {e}")

    return True


def _recomprimir(origem: Path, destino_tmp: Path) -> None:
    extensao = origem.suffix.lower()
    with Image.open(origem) as img:
        if extensao in _EXTENSOES_JPEG:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((MAX_DIMENSAO_PX, MAX_DIMENSAO_PX))
            img.save(destino_tmp, "JPEG", quality=JPEG_QUALITY, optimize=True)
        elif extensao == ".png":
            img.save(destino_tmp, "PNG", optimize=True)
        else:
            raise ValueError(f"Extensão não suportada para recompressão: {extensao}")


def _copiar_sem_alterar(origem: Path, destino_tmp: Path) -> None:
    import shutil

    shutil.copy2(origem, destino_tmp)


def _remover_silenciosamente(caminho: Path) -> None:
    try:
        os.remove(caminho)
    except OSError:
        pass
