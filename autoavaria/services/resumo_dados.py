"""
RESUMO DE DADOS PARA A TELA DE CONFIGURAÇÕES (aba "Dados")

Reúne, num único lugar, o estado real dos dados do sistema para a aba "Dados":
o que existe no relatório, quantas execuções, quando rodou e o que dá para
editar. A tela de Configurações antes só tinha botões nessa aba; a ideia aqui é
responder "o que eu tenho?" antes de oferecer "o que eu faço?".

Fonte dos números: a mesma do Histórico (`db.resumo_geral`), para as duas telas
nunca divergirem sobre quanto existe no sistema.
"""

from typing import Any, Dict, Optional

from ..core.paths import ARQUIVO_SAIDA_EXCEL
from . import db


def _iniciais_do_relatorio() -> Dict[str, Any]:
    """Existência, data e contagem por categoria do relatório mestre."""
    existe = ARQUIVO_SAIDA_EXCEL.exists()
    info: Dict[str, Any] = {
        "existe": existe,
        "caminho": str(ARQUIVO_SAIDA_EXCEL),
        "atualizado_em": None,
        "total_itens": 0,
        "por_categoria": {},
    }
    if not existe:
        return info

    try:
        from datetime import datetime

        info["atualizado_em"] = datetime.fromtimestamp(
            ARQUIVO_SAIDA_EXCEL.stat().st_mtime
        ).strftime("%d/%m/%Y %H:%M")
    except OSError:
        pass

    try:
        from .report_editing import carregar_todas_sheets

        sheets = carregar_todas_sheets(str(ARQUIVO_SAIDA_EXCEL))
        por_categoria = {
            nome: len(df) for nome, df in sheets.items() if df is not None and not df.empty
        }
        info["por_categoria"] = por_categoria
        info["total_itens"] = sum(por_categoria.values())
    except Exception as e:
        print(f"⚠️ Não foi possível ler o relatório para o resumo de dados: {e}")

    return info


def obter_resumo_dados() -> Dict[str, Any]:
    """Estado dos dados para a aba "Dados" da tela de Configurações.

    Devolve algo como::

        {
          "relatorio": {"existe": True, "atualizado_em": "...", "por_categoria": {...}},
          "execucoes": {"total": 25, "ultima_em": "...", "ultima_status": "concluido"},
          "tokens": {"total": 123456, "hoje": 456},
          "unificados": 4,
        }
    """
    resumo = {"relatorio": _iniciais_do_relatorio()}

    try:
        geral = db.resumo_geral()
    except Exception as e:
        print(f"⚠️ Não foi possível obter o resumo do banco: {e}")
        geral = {}

    resumo["execucoes"] = {
        "total": geral.get("total_execucoes", 0),
        "ultima_em": None,
        "ultima_status": None,
    }
    resumo["tokens"] = {"total": geral.get("total_tokens", 0), "hoje": 0}
    resumo["unificados"] = geral.get("total_relatorios_unificados", 0)

    # Última execução: a mesma que a tela de Relatório mostra.
    try:
        execucoes = db.listar_execucoes(limite=1)
        if execucoes:
            ultima = execucoes[0]
            resumo["execucoes"]["ultima_em"] = ultima.get("iniciado_em")
            resumo["execucoes"]["ultima_status"] = ultima.get("status")
    except Exception as e:
        print(f"⚠️ Não foi possível obter a última execução: {e}")

    try:
        from .stats import obter_estatisticas

        stats = obter_estatisticas()
        resumo["tokens"]["hoje"] = stats.get("tokens_consumidos_hoje", 0)
        resumo["imagens"] = {
            "total": stats.get("imagens_total", 0),
            "processadas": stats.get("imagens_processadas", 0),
            "pendentes": stats.get("imagens_pendentes", 0),
        }
    except Exception as e:
        print(f"⚠️ Não foi possível obter as estatísticas de imagens: {e}")
        resumo["imagens"] = {"total": 0, "processadas": 0, "pendentes": 0}

    return resumo
