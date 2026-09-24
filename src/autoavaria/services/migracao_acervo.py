"""
MIGRAÇÃO DO ACERVO (nomes antigos -> acervo com nome físico opaco)

Move o acervo que já existe para o modelo de `services/arquivos.py`:

- cada arquivo em `imagens_para_analisar` / `imagens_processadas` ganha um
  nome físico aleatório (uuid) e um registro no banco com o nome original;
- arquivos cujo nome já está no log de processados vão para 'arquivadas';
  os demais ficam 'pendentes';
- é IDEMPOTENTE: rodar duas vezes não duplica nem renomeia de novo (arquivos
  que já têm registro são ignorados).

Por que migrar: o nome-em-disco era a identidade, então reenviar o mesmo lote
colidia (`IMG-x_2.jpg`) e o dedup por hash falhava (a versão arquivada é
recomprimida). Com o acervo, a identidade é o `nome_original` no banco e o
físico é opaco.
"""

import os
from typing import Dict, List, Optional

from ..core.paths import ARCHIVE_FOLDER, UPLOAD_FOLDER
from . import arquivos as acervo

EXTENSOES = (".png", ".jpg", ".jpeg")


def _log_processados() -> set:
    try:
        from .extraction_pipeline import carregar_logs

        return carregar_logs()
    except Exception:
        return set()


def migrar(pasta_pendentes=None, pasta_arquivadas=None, aplicar: bool = True) -> Dict[str, object]:
    """Migra o acervo em disco para o modelo de metadados.

    A pasta lógica de cada arquivo é PRESERVADA da origem: o que está em
    `imagens_para_analisar` fica 'pendentes' e o que está em
    `imagens_processadas` fica 'arquivadas'. Não inferimos pelo log porque uma
    imagem com erro fica em pendentes de propósito (para a reanálise achá-la),
    mesmo constando como processada.

    `aplicar=False` só relata o que faria (dry-run). Devolve um resumo com os
    nomes migrados, pulados e erros.
    """
    pasta_pendentes = pasta_pendentes or UPLOAD_FOLDER
    pasta_arquivadas = pasta_arquivadas or ARCHIVE_FOLDER

    migrados: List[Dict[str, str]] = []
    pulados: List[str] = []
    erros: List[Dict[str, str]] = []

    # Arquivos já conhecidos pelo acervo (por nome original) não são tocados.
    try:
        ja_migrados = {r["nome_original"] for r in acervo.listar()}
    except Exception:
        ja_migrados = set()

    for pasta_real, pasta_logica in (
        (pasta_pendentes, acervo.PASTA_PENDENTES),
        (pasta_arquivadas, acervo.PASTA_ARQUIVADAS),
    ):
        pasta_real = str(pasta_real)
        if not os.path.isdir(pasta_real):
            continue

        for nome in sorted(os.listdir(pasta_real)):
            if not nome.lower().endswith(EXTENSOES):
                continue
            if nome in ja_migrados:
                pulados.append(nome)
                continue

            caminho_antigo = os.path.join(pasta_real, nome)
            # Preserva a pasta de ORIGEM: um arquivo que está fisicamente em
            # 'pendentes' continua pendente, mesmo que já conste no log. Isso
            # mantém as imagens com erro disponíveis para reanálise (elas ficam
            # na pasta de pendentes de propósito - ver extraction_pipeline).
            destino = pasta_logica

            if not aplicar:
                migrados.append({"nome_original": nome, "pasta": destino, "dry_run": "1"})
                continue

            try:
                with open(caminho_antigo, "rb") as f:
                    dados = f.read()
                registro = acervo.registrar(nome, dados=dados, pasta=destino)
                if registro is None:
                    # Conteúdo idêntico já registrado (duplicata legítima):
                    # apaga a cópia antiga para não confundir a varredura.
                    try:
                        os.remove(caminho_antigo)
                    except OSError:
                        pass
                    pulados.append(nome)
                    continue
                # Só remove o antigo depois que o novo está gravado.
                try:
                    os.remove(caminho_antigo)
                except OSError:
                    pass
                migrados.append({
                    "nome_original": nome,
                    "nome_fisico": registro["nome_fisico"],
                    "pasta": destino,
                })
            except Exception as e:
                erros.append({"arquivo": nome, "erro": str(e)})

    return {
        "migrados": migrados,
        "total_migrados": len(migrados),
        "pulados": pulados,
        "total_pulados": len(pulados),
        "erros": erros,
    }
