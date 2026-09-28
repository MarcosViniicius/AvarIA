"""
GERENCIADOR DE ERROS E REANÁLISE

Rastreia os itens que caíram na categoria "Erros de Análise" e apoia o fluxo de
reanálise (usado por services/extraction_pipeline.py).

Antes lia e gravava a aba "Erros de Análise" do Excel mestre. Agora o SQLite é a
fonte da verdade: os itens vêm de `report_items` (via db.listar_erros_por_arquivo)
e "erro corrigido" é uma remoção no banco, com recálculo das contagens da
execução. O Excel virou um export sob demanda (ver services/mestre.py).

A classe manteve a MESMA interface de propósito — o pipeline usa estes métodos e
não precisa saber de onde o dado vem. O único ponto que continua em arquivo é o
log de reanálise, que é registro textual e não dado de negócio.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.paths import LOGS_DIR
from . import db


class GerenciadorErros:
    """Rastreia e apoia a reanálise dos itens com erro."""

    def __init__(self, arquivo_excel: Optional[str] = None):
        # O parâmetro é mantido por compatibilidade de assinatura (quem chamava
        # passava o caminho do Excel). O dado agora vive no banco.
        self.arquivo_excel = arquivo_excel

    def obter_erros_pendentes(self) -> List[Dict[str, Any]]:
        """Itens com erro, no formato das telas, mais recentes primeiro.

        Deduplica por arquivo: o mesmo arquivo pode ter erro em mais de uma
        execução, e reanalisar a mesma imagem duas vezes seria desperdício.
        Fica a linha da versão mais recente de cada arquivo.
        """
        try:
            vistos = set()
            erros: List[Dict[str, Any]] = []
            for item in db.listar_erros_por_arquivo():
                arquivo = item.get("produto")
                if not arquivo or arquivo in vistos:
                    continue
                vistos.add(arquivo)
                erros.append(
                    {
                        "Arquivo": arquivo,
                        "Detalhes do Erro": item.get("detalhes"),
                        "Observação da Mensagem": item.get("observacao_mensagem"),
                        "Caminho da Imagem": item.get("caminho_imagem"),
                        "Ver Imagem": item.get("caminho_imagem"),
                        "status_reanalise": "pendente",
                        "tentativas_reanalise": 0,
                    }
                )
            return erros
        except Exception as e:
            print(f"⚠️ Erro ao obter erros pendentes: {e}")
            return []

    def contar_erros_pendentes(self) -> int:
        return len(self.obter_erros_pendentes())

    def obter_arquivos_com_erro(self) -> List[str]:
        """Nomes de arquivo distintos que estão com erro pendente."""
        return [erro["Arquivo"] for erro in self.obter_erros_pendentes() if erro.get("Arquivo")]

    def marcar_erro_como_reprocessado(self, nome_arquivo: str, sucesso: bool = True) -> None:
        """Registra o resultado da reanálise de um arquivo.

        - sucesso: o erro sai do banco (foi corrigido);
        - falha: o detalhe ganha a marca da tentativa, para o histórico.
        """
        try:
            if sucesso:
                removidos = db.excluir_erros_do_arquivo(nome_arquivo)
                if removidos:
                    print(f"✅ Erro de '{nome_arquivo}' resolvido e removido do histórico")
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.anotar_tentativa_reanalise(
                    nome_arquivo, f" [Reanalise em {timestamp} - Falhou novamente]"
                )
        except Exception as e:
            print(f"⚠️ Erro ao marcar erro como reprocessado: {e}")

    def adicionar_ao_log_reanalise(
        self, nome_arquivo: str, status: str, detalhes: Optional[str] = None
    ) -> None:
        """Registra a reanálise num log de texto (registro, não dado de negócio)."""
        log_file = LOGS_DIR / "log_reanalise.txt"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            linha = f"{timestamp} | {nome_arquivo} | {status}"
            if detalhes:
                linha += f" | {detalhes}"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        except Exception as e:
            print(f"⚠️ Erro ao adicionar ao log de reanálise: {e}")

    def gerar_resumo_erros(self) -> Dict[str, Any]:
        """Estatísticas dos erros pendentes, agrupadas por tipo."""
        erros = self.obter_erros_pendentes()
        if not erros:
            return {"total": 0, "tipos": {}, "arquivos": []}

        tipos: Dict[str, int] = {}
        for erro in erros:
            detalhes = str(erro.get("Detalhes do Erro") or "Erro desconhecido")
            if "JSON" in detalhes or "json" in detalhes:
                tipo = "Erro de parsing JSON"
            elif "API" in detalhes or "timeout" in detalhes.lower():
                tipo = "Erro de API"
            elif "Falha" in detalhes:
                tipo = "Falha na análise"
            else:
                tipo = "Outro"
            tipos[tipo] = tipos.get(tipo, 0) + 1

        return {
            "total": len(erros),
            "tipos": tipos,
            "arquivos": [erro.get("Arquivo") for erro in erros],
        }


def criar_gerenciador(arquivo_excel: Optional[str] = None) -> GerenciadorErros:
    """Cria o gerenciador. O parâmetro é aceito por compatibilidade e ignorado."""
    return GerenciadorErros(arquivo_excel)
