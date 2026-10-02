"""
Estatísticas e resultados recentes usados pelo dashboard (`/`, `/api/stats`).

Importa os caminhos diretamente de ``avariaia.core.paths`` (em vez de
``avariaia.routes.context``) para não criar uma dependência de services ->
routes.
"""

import os
from datetime import datetime

import pandas as pd

from ..core.paths import (
    UPLOAD_FOLDER as UPLOAD_FOLDER_PATH,
    LOG_PROCESSADOS_FILE as LOG_PROCESSADOS_FILE_PATH,
    LOG_CONSUMO_FILE as LOG_CONSUMO_FILE_PATH,
    ARCHIVE_FOLDER as ARCHIVE_FOLDER_PATH,
)

DIRETORIO_IMAGENS = str(UPLOAD_FOLDER_PATH)
LOG_PROCESSADOS_FILE = str(LOG_PROCESSADOS_FILE_PATH)
LOG_CONSUMO_FILE = str(LOG_CONSUMO_FILE_PATH)
ARCHIVE_FOLDER = str(ARCHIVE_FOLDER_PATH)
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")


def _nomes_do_acervo():
    """(nomes_pendentes, nomes_arquivados) do acervo, ou (None, None) sem uso.

    Devolve None quando o acervo ainda não tem registros, sinalizando a quem
    chamou que deve varrer o disco (instalação não migrada). O nome devolvido é
    o ORIGINAL, que é a identidade exibida e comparada com o log.
    """
    try:
        from . import arquivos as acervo

        registros = acervo.listar()
        if not registros:
            return None, None
        pendentes = {
            r["nome_original"] for r in registros
            if r["pasta"] == acervo.PASTA_PENDENTES
            and r["nome_original"].lower().endswith(EXTENSOES_IMAGEM)
        }
        arquivados = {
            r["nome_original"] for r in registros
            if r["pasta"] == acervo.PASTA_ARQUIVADAS
            and r["nome_original"].lower().endswith(EXTENSOES_IMAGEM)
        }
        return pendentes, arquivados
    except Exception:
        return None, None


def carregar_logs_processados():
    """Nomes de arquivos já processados.

    Delega para o pipeline (fonte única do cálculo: banco + arquivo). Antes
    havia DUAS implementações quase idênticas — uma aqui, uma em
    `extraction_pipeline.carregar_logs` — que podiam divergir sobre o que
    conta como processado.

    Passa o PRÓPRIO LOG_PROCESSADOS_FILE: os testes trocam esse caminho via
    monkeypatch, e o pipeline resolveria para o arquivo de produção se lesse a
    constante dele.
    """
    try:
        from .extraction_pipeline import carregar_logs

        return carregar_logs(arquivo_log=LOG_PROCESSADOS_FILE)
    except Exception:
        return _carregar_logs_processados_do_arquivo()


def _carregar_logs_processados_do_arquivo():
    """Fallback legado: lê direto o log_mestre.txt."""
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return set()
    try:
        arquivos_processados = set()
        with open(LOG_PROCESSADOS_FILE, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    if " - Processado: " in linha:
                        arquivos_processados.add(linha.split(" - Processado: ")[-1])
                    else:
                        arquivos_processados.add(linha)
        return arquivos_processados
    except IOError as e:
        print(f"⚠️ Erro ao ler log de arquivos processados: {e}")
        return set()


def obter_estatisticas():
    """Obtém estatísticas do sistema."""
    stats = {
        "imagens_total": 0,
        "imagens_processadas": 0,
        "imagens_pendentes": 0,
        "ultimo_processamento": "Nunca",
        "tokens_consumidos_hoje": 0,
        "relatorio_existe": False,
    }

    try:
        # Imagens presentes tanto nas pendentes quanto no arquivo permanente.
        # O pipeline move para ARCHIVE_FOLDER cada imagem analisada com sucesso;
        # olhar só UPLOAD_FOLDER fazia o Dashboard mostrar zero processadas.
        #
        # Fonte: o acervo (services/arquivos.py), onde o nome FÍSICO pode ser
        # opaco; a identidade é o nome original. Cai para a varredura de disco
        # quando não há registros (instalação que ainda não migrou).
        nomes_pendentes, nomes_arquivados = _nomes_do_acervo()
        if nomes_pendentes is None:
            imagens_pendentes_na_pasta = []
            if os.path.exists(DIRETORIO_IMAGENS):
                imagens_pendentes_na_pasta = [
                    f for f in os.listdir(DIRETORIO_IMAGENS) if f.lower().endswith(EXTENSOES_IMAGEM)
                ]
            imagens_arquivadas = []
            if os.path.exists(ARCHIVE_FOLDER):
                imagens_arquivadas = [
                    f for f in os.listdir(ARCHIVE_FOLDER) if f.lower().endswith(EXTENSOES_IMAGEM)
                ]
            nomes_pendentes, nomes_arquivados = set(imagens_pendentes_na_pasta), set(imagens_arquivadas)

        imagens_conhecidas = set(nomes_pendentes) | set(nomes_arquivados)
        stats["imagens_total"] = len(imagens_conhecidas)

        # Não contar nomes antigos do log cujos arquivos já foram removidos.
        processadas_no_log = carregar_logs_processados()
        stats["imagens_processadas"] = sum(
            1 for f in imagens_conhecidas
            if f in processadas_no_log or f in nomes_arquivados
        )
        stats["imagens_pendentes"] = sum(
            1 for f in nomes_pendentes if f not in processadas_no_log
        )

        # Último processamento e tokens de hoje: vêm do banco (fonte primária
        # desde a migração dos logs). O arquivo fica como fallback para
        # instalações que ainda não importaram o histórico.
        ultimo, tokens_hoje = _ultimo_processamento_e_tokens_do_banco()
        if ultimo is None:
            ultimo = _ultimo_processamento_do_arquivo()
        if tokens_hoje is None:
            tokens_hoje = _tokens_de_hoje_do_arquivo()
        stats["ultimo_processamento"] = ultimo or stats["ultimo_processamento"]
        stats["tokens_consumidos_hoje"] = (
            tokens_hoje if tokens_hoje is not None else stats["tokens_consumidos_hoje"]
        )

        # Existe relatório se o BANCO tem itens (fonte da verdade). O .xlsx é
        # export sob demanda e pode não existir sem que isso signifique
        # "sem relatório".
        from . import mestre

        stats["relatorio_existe"] = bool(mestre.contar_por_categoria())

    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")

    return stats


def _ultimo_processamento_e_tokens_do_banco():
    """(ultimo_processamento, tokens_hoje) do SQLite; None onde não houver dado.

    Um `None` em cada campo sinaliza "o banco não tem isso" — quem chama decide
    se cai para o arquivo. Não basta devolver 0/"" senão o fallback nunca roda.
    """
    try:
        from . import db

        ultimo = None
        tokens_hoje = None

        with db.get_connection() as conn:
            linha = conn.execute(
                "SELECT MAX(processado_em) AS ultimo FROM arquivos_processados"
            ).fetchone()
            if linha and linha["ultimo"]:
                ultimo = _formatar_data(linha["ultimo"])

            hoje = datetime.now().strftime("%Y-%m-%d")
            linha = conn.execute(
                """SELECT COALESCE(SUM(tokens), 0) AS total
                   FROM consumo_tokens_log
                   WHERE substr(registrado_em, 1, 10) = ?""",
                (hoje,),
            ).fetchone()
            if linha is not None:
                tokens_hoje = int(linha["total"] or 0)

        return ultimo, tokens_hoje
    except Exception as e:
        print(f"⚠️ Banco indisponível para as estatísticas de log: {e}")
        return None, None


def _formatar_data(valor: str) -> str:
    try:
        return datetime.strptime(valor[:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(valor)


def _ultimo_processamento_do_arquivo():
    if not os.path.exists(LOG_PROCESSADOS_FILE):
        return None
    try:
        return datetime.fromtimestamp(os.path.getmtime(LOG_PROCESSADOS_FILE)).strftime("%d/%m/%Y %H:%M")
    except OSError:
        return None


def _tokens_de_hoje_do_arquivo():
    """Soma os tokens de hoje lendo o log_consumo_tokens.txt (fallback legado)."""
    if not os.path.exists(LOG_CONSUMO_FILE):
        return None
    hoje = datetime.now().strftime("%Y-%m-%d")
    total = 0
    try:
        with open(LOG_CONSUMO_FILE, "r", encoding="utf-8") as f:
            for linha in f.readlines()[-50:]:
                if hoje in linha and "tokens consumidos:" in linha.lower():
                    try:
                        bruto = linha.lower().split("tokens consumidos:")[1].strip()
                        bruto = bruto.split("-")[0].strip().replace(".", "").replace(",", "")
                        total += int(bruto)
                    except (ValueError, IndexError):
                        continue
    except OSError:
        return None
    return total


def obter_resultados_recentes():
    """Últimos itens de cada categoria, para o dashboard.

    Vem da visão mestre do BANCO (services/mestre.py) - a mesma que alimenta o
    relatório e o export. Antes lia o Excel mestre, que podia divergir do banco.
    """
    resultados = {"avarias": [], "uso_interno": [], "erros": []}

    try:
        from . import mestre

        secoes = mestre.obter_secoes_mestre()
        mapa = {
            "Avarias": "avarias",
            "Uso Interno": "uso_interno",
            "Erros de Análise": "erros",
        }
        for categoria, chave in mapa.items():
            info = secoes.get(categoria)
            if not info:
                continue
            # A visão mestre vem da execução mais NOVA para a mais antiga, então
            # os "recentes" são o começo da lista. Reverto para old->new, a mesma
            # ordem que o dashboard assumia quando lia o Excel (o template usa
            # `[-5:]`).
            recentes = list(reversed(info["dados"][:10]))
            resultados[chave] = [
                {k: (v if v not in (None, "") else "-") for k, v in linha.items()}
                for linha in recentes
            ]
    except Exception as e:
        print(f"Erro ao obter resultados recentes: {e}")

    return resultados
