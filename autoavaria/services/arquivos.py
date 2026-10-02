"""
ARMAZENAMENTO DE ARQUIVOS (metadados no banco, bytes no disco)

Modelo híbrido: o SQLite guarda a IDENTIDADE do arquivo (nome original, nome
físico, hash, tamanho, pasta) e o conteúdo continua em disco. Isso dá o que o
nome-em-disco sozinho não dava:

- **Sem colisão de nome.** O arquivo físico usa um nome aleatório
  (`uuid4().hex` + extensão). Reenviar `IMG-x.jpg` gera um físico novo
  (`a3f9....jpg`) em vez de `IMG-x_2.jpg`; o nome original fica preservado como
  dado, então a UI continua mostrando o nome que o usuário reconhece.
- **Dedup por conteúdo de verdade.** `hash_sha256` é a chave de "já tenho este
  arquivo?". A recompressão do arquivamento muda o hash do arquivo em disco
  (ver image_archive.py), e era por isso que o dedup por conteúdo falhava e o
  mesmo lote era reprocessado; aqui o hash é do conteúdo ORIGINAL, gravado no
  momento do upload e nunca recalculado a partir da versão recomprimida.
- **Mover de pasta não quebra vínculo.** O vínculo é o `id`; o caminho físico
  é derivado de `pasta` + `nome_fisico`, então arquivar (pendentes ->
  arquivadas) não invalida nenhum link.

O nome físico nunca é exibido ao usuário; para isso existe `nome_original`.
"""

import hashlib
import os
import re
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from ..core.paths import ARCHIVE_FOLDER, UPLOAD_FOLDER

PASTA_PENDENTES = "pendentes"
PASTA_ARQUIVADAS = "arquivadas"

_EXTENSOES_PERMITIDAS = {".jpg", ".jpeg", ".png", ".txt", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}


def _db():
    """Import tardio para evitar ciclo (db importa services, e este módulo é
    usado pelo db na migração)."""
    from . import db as db_service

    return db_service


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pasta_de(pasta: str) -> Path:
    """Resolve a pasta lógica ('pendentes'|'arquivadas') para o caminho real."""
    return UPLOAD_FOLDER if pasta == PASTA_PENDENTES else ARCHIVE_FOLDER


def hash_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def hash_arquivo(caminho: Union[str, Path]) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _nome_fisico(extensao: str) -> str:
    """Nome opaco e único. A extensão é mantida porque o botão 'Ver Imagem' e
    o navegador dependem dela para reconhecer o formato."""
    extensao = extensao if extensao.startswith(".") else f".{extensao}"
    return f"{uuid.uuid4().hex}{extensao.lower()}"


def registrar(
    nome_original: str,
    dados: Optional[bytes] = None,
    caminho_origem: Optional[Union[str, Path]] = None,
    pasta: str = PASTA_PENDENTES,
    executar_migracao_pastas: bool = True,
    forcar: bool = False,
) -> Optional[Dict[str, Any]]:
    """Grava um arquivo novo (ou registra um que já esteja em disco).

    Informe `dados` (bytes) OU `caminho_origem` (arquivo já existente, que será
    lido). Devolve o registro criado, ou None se o CONTEÚDO já existir (dedup).

    `forcar=True` ignora a checagem de conteúdo idêntico - grava mesmo assim,
    com um nome físico novo. É o "Forçar reprocessamento" do upload, quando o
    usuário quer reanalisar de propósito um lote já enviado.

    `executar_migracao_pastas=False` só registra os metadados e presume que o
    arquivo físico já está no lugar (usado pela migração de acervo antigo).
    """
    if dados is None and caminho_origem is None:
        raise ValueError("Informe 'dados' ou 'caminho_origem'")

    if dados is None:
        with open(caminho_origem, "rb") as f:
            dados = f.read()

    nome_original = os.path.basename(str(nome_original)).strip()
    if not nome_original:
        raise ValueError("Nome de arquivo vazio")

    digest = hash_bytes(dados)
    if not forcar:
        existente = buscar_por_hash(digest)
        if existente is not None:
            # Fantasma: o registro existe mas os bytes foram apagados por fora
            # (ex.: "Limpar imagens" anterior a este tratamento). Deixar isso
            # bloquearia o reenvio do mesmo arquivo para sempre — remove o
            # registro órfão e segue com a gravação nova.
            if Path(caminho_de(existente)).exists():
                return None  # conteúdo idêntico já armazenado
            remover(existente["id"], apagar_fisico=False)

    extensao = os.path.splitext(nome_original)[1].lower() or ".bin"
    nome_fisico = _nome_fisico(extensao)
    destino_dir = pasta_de(pasta)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / nome_fisico

    # Tenta um nome físico novo se, por absurdo, o uuid colidir.
    while destino.exists():
        nome_fisico = _nome_fisico(extensao)
        destino = destino_dir / nome_fisico

    if not executar_migracao_pastas:
        # Migração: o físico pode já existir no destino; não reescreve.
        if not destino.exists():
            with open(destino, "wb") as f:
                f.write(dados)
    else:
        with open(destino, "wb") as f:
            f.write(dados)

    return _inserir(nome_original, nome_fisico, pasta, digest, len(dados), extensao)


def _inserir(nome_original, nome_fisico, pasta, digest, tamanho, extensao) -> Dict[str, Any]:
    db = _db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO arquivos
                   (nome_original, nome_fisico, pasta, extensao, tipo_mime,
                    tamanho, hash_sha256, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                nome_original, nome_fisico, pasta, extensao,
                _mime(extensao), tamanho, digest, _now(),
            ),
        )
        arquivo_id = cursor.lastrowid
    return {
        "id": arquivo_id,
        "nome_original": nome_original,
        "nome_fisico": nome_fisico,
        "pasta": pasta,
        "caminho": str(pasta_de(pasta) / nome_fisico),
        "tamanho": tamanho,
        "hash_sha256": digest,
    }


_MIMES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".txt": "text/plain",
    ".zip": "application/zip", ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed", ".tar": "application/x-tar",
    ".gz": "application/gzip", ".bz2": "application/x-bzip2",
}


def _mime(extensao: str) -> str:
    return _MIMES.get(extensao.lower(), "application/octet-stream")


def buscar_por_hash(digest: str) -> Optional[Dict[str, Any]]:
    db = _db()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM arquivos WHERE hash_sha256 = ? LIMIT 1", (digest,)
        ).fetchone()
    return _para_dict(row) if row else None


def buscar_por_nome_original(nome: str) -> List[Dict[str, Any]]:
    db = _db()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM arquivos WHERE nome_original = ? ORDER BY id", (nome,)
        ).fetchall()
    return [_para_dict(r) for r in rows]


def buscar_por_nome_com_fallback(nome: str) -> List[Dict[str, Any]]:
    """Como `buscar_por_nome_original`, mas cai para o nome-base se preciso.

    Item antigo pode referenciar `IMG-x_2.jpg` enquanto o acervo guardou só
    `IMG-x.jpg` (as cópias `_N` eram conteúdo idêntico e a migração as
    descartou). Como o `_N` só existe por causa de colisão de nome — nunca foi
    uma imagem diferente —, resolver para o original é correto e evita que
    links que já funcionavam fiquem quebrados.
    """
    registros = buscar_por_nome_original(nome)
    if registros:
        return registros

    base, extensao = os.path.splitext(nome)
    sem_sufixo = re.sub(r"_\d+$", "", base)
    if sem_sufixo and sem_sufixo != base:
        return buscar_por_nome_original(f"{sem_sufixo}{extensao}")
    return []


def obter(arquivo_id: int) -> Optional[Dict[str, Any]]:
    db = _db()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM arquivos WHERE id = ?", (arquivo_id,)).fetchone()
    return _para_dict(row) if row else None


def listar(pasta: Optional[str] = None) -> List[Dict[str, Any]]:
    db = _db()
    with db.get_connection() as conn:
        if pasta:
            rows = conn.execute(
                "SELECT * FROM arquivos WHERE pasta = ? ORDER BY id", (pasta,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM arquivos ORDER BY id").fetchall()
    return [_para_dict(r) for r in rows]


def mover(arquivo_id: int, pasta_destino: str) -> bool:
    """Move o arquivo físico entre pendentes/arquivadas e atualiza o metadado.

    Só move o físico depois que o destino existe (grava-antes-de-marcar).
    """
    if pasta_destino not in (PASTA_PENDENTES, PASTA_ARQUIVADAS):
        raise ValueError(f"Pasta inválida: {pasta_destino}")

    registro = obter(arquivo_id)
    if not registro:
        return False
    if registro["pasta"] == pasta_destino:
        return True

    origem = pasta_de(registro["pasta"]) / registro["nome_fisico"]
    destino_dir = pasta_de(pasta_destino)
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / registro["nome_fisico"]

    if origem.exists() and not destino.exists():
        os.replace(origem, destino)

    db = _db()
    with db.get_connection() as conn:
        conn.execute("UPDATE arquivos SET pasta = ? WHERE id = ?", (pasta_destino, arquivo_id))
    return True


def atualizar_caminho_fisico(nome_original: str, novo_nome_fisico: str, pasta: str) -> int:
    """Renomeia o metadado de todas as linhas com este nome original.

    Usado pela migração: o arquivo físico passa a ser o nome opaco, e qualquer
    referência antiga por nome precisa continuar resolvendo.
    """
    db = _db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE arquivos SET nome_fisico = ?, pasta = ? WHERE nome_original = ?",
            (novo_nome_fisico, pasta, nome_original),
        )
        return cursor.rowcount


def caminho_de(registro: Dict[str, Any]) -> str:
    """Caminho absoluto do arquivo físico de um registro."""
    return str(pasta_de(registro["pasta"]) / registro["nome_fisico"])


def limpar(pasta: Optional[str] = None) -> int:
    """Remove registros do acervo (os bytes são apagados por quem chama).

    `pasta=None` limpa tudo (usado quando as duas pastas são esvaziadas);
    com uma pasta, limpa só os registros dela — assim os links das imagens
    arquivadas continuam resolvendo mesmo depois de um "reprocessar tudo".
    """
    db = _db()
    with db.get_connection() as conn:
        if pasta:
            cursor = conn.execute("DELETE FROM arquivos WHERE pasta = ?", (pasta,))
        else:
            cursor = conn.execute("DELETE FROM arquivos")
        return cursor.rowcount


def remover(arquivo_id: int, apagar_fisico: bool = True) -> bool:
    registro = obter(arquivo_id)
    if not registro:
        return False
    if apagar_fisico:
        caminho = Path(caminho_de(registro))
        if caminho.exists():
            try:
                caminho.unlink()
            except OSError:
                pass
    db = _db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM arquivos WHERE id = ?", (arquivo_id,))
    return True


def _para_dict(row) -> Dict[str, Any]:
    dados = dict(row)
    dados.setdefault("caminho", str(pasta_de(dados.get("pasta", PASTA_PENDENTES)) / dados.get("nome_fisico", "")))
    return dados
