"""
Limpeza de exportações antigas em resultados/.

Cada exportação (Excel/TXT de uma execução do Histórico, relatório
unificado) gera um arquivo novo e nunca apaga os anteriores — com o tempo
isso acumula. Este módulo mantém só os N mais recentes de cada tipo,
mantendo o índice no banco (unified_reports) consistente com o que
realmente existe em disco.
"""

import re
from pathlib import Path
from typing import Dict

from . import db

_PADROES = {
    "unificados": re.compile(r"^Relatorio_Unificado_.*\.(xlsx|txt)$"),
    "execucoes": re.compile(r"^Historico_Execucao_.*\.(xlsx|txt)$"),
}


def limpar_exportacoes_antigas(resultados_dir: Path, manter: int = 30) -> Dict[str, int]:
    """Remove exportações antigas, mantendo as `manter` mais recentes de cada tipo.

    Returns:
        dict com a quantidade de arquivos removidos por tipo.
    """
    removidos = {"unificados": 0, "execucoes": 0}

    if not resultados_dir.exists():
        return removidos

    arquivos_removidos_unificados = []

    for tipo, padrao in _PADROES.items():
        candidatos = [f for f in resultados_dir.iterdir() if f.is_file() and padrao.match(f.name)]
        candidatos.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        for arquivo in candidatos[manter:]:
            try:
                arquivo.unlink()
                removidos[tipo] += 1
                if tipo == "unificados":
                    arquivos_removidos_unificados.append(arquivo.name)
            except OSError as e:
                print(f"⚠️ Não foi possível remover {arquivo.name}: {e}")

    if arquivos_removidos_unificados:
        db.remover_relatorios_unificados_por_arquivo(arquivos_removidos_unificados)

    return removidos
