"""
Estado mutável em tempo de execução compartilhado entre os módulos de rotas
web (processamento em background, cancelamento, progresso e buffer de logs
em tempo real).

Os módulos de rotas devem importar este módulo inteiro (``from ..services
import app_state``) e ler/escrever seus atributos (ex.: ``app_state.
processamento_ativo = True``) em vez de importar os nomes diretamente -
assim a semântica de "variável global mutável compartilhada" que o código
original tinha dentro de um único arquivo (``routes/web.py``) é preservada
mesmo agora que o estado é usado por vários módulos diferentes.
"""

import json
import os
import sys
import threading
from datetime import datetime

from ..core.paths import CONFIG_FILE

# Variáveis globais para controle de processamento
processamento_ativo = False
processamento_cancelado = False
progresso_atual = {"progresso": 0, "status": "Aguardando", "logs": []}

# Buffer de logs em tempo real
logs_aplicacao_buffer = []

# Protege logs_aplicacao_buffer contra mutação concorrente - o pipeline roda
# vários workers (ThreadPoolExecutor) imprimindo ao mesmo tempo, então
# append/truncate precisam ser atômicos em relação uns aos outros.
_buffer_lock = threading.Lock()

# Cache local do estado de "logs detalhados" para não abrir e parsear o
# config.json a cada chamada de print() (que pode ser dezenas por segundo
# durante o processamento em lote).
_logs_detalhados_cache = {"valor": False, "mtime": None}
_LOGS_DETALHADOS_CACHE_TTL = 2.0  # segundos


def _logs_detalhados_ativos():
    """Lê `interface.logs_detalhados_aplicacao` do config com cache curto."""
    agora = datetime.now().timestamp()
    if (
        _logs_detalhados_cache["mtime"] is not None
        and agora - _logs_detalhados_cache["mtime"] < _LOGS_DETALHADOS_CACHE_TTL
    ):
        return _logs_detalhados_cache["valor"]

    valor = False
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                valor = bool(config.get("interface", {}).get("logs_detalhados_aplicacao", False))
    except Exception:
        valor = _logs_detalhados_cache["valor"]  # mantém último valor conhecido em caso de erro

    _logs_detalhados_cache["valor"] = valor
    _logs_detalhados_cache["mtime"] = agora
    return valor


def _adicionar_ao_buffer(tipo, mensagem):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _buffer_lock:
        logs_aplicacao_buffer.append({"timestamp": timestamp, "tipo": tipo, "mensagem": mensagem})
        # Manter apenas os últimos 200 logs
        if len(logs_aplicacao_buffer) > 200:
            del logs_aplicacao_buffer[:-200]


def log_aplicacao(mensagem, tipo="info"):
    """Adiciona uma mensagem ao buffer de logs da aplicação."""
    _adicionar_ao_buffer(tipo, mensagem)
    # Sempre imprimir no terminal
    print(mensagem)


# Sistema de captura de prints
class LogCapture:
    """Captura prints e redireciona para o buffer de logs."""
    def __init__(self):
        self.terminal = sys.stdout
        # threading.local: cada thread tem sua própria flag de reentrância,
        # em vez de uma flag de instância compartilhada por todas as threads
        # (que fazia threads concorrentes descartarem silenciosamente as
        # mensagens umas das outras - até 90%+ das linhas se perdiam com
        # vários workers imprimindo ao mesmo tempo).
        self._local = threading.local()

    def write(self, mensagem):
        # Sempre escrever no terminal (com fallback de encoding para Windows)
        try:
            self.terminal.write(mensagem)
        except UnicodeEncodeError:
            encoding = getattr(self.terminal, "encoding", None) or "utf-8"
            safe_msg = mensagem.encode(encoding, errors="replace").decode(encoding, errors="replace")
            self.terminal.write(safe_msg)
        self.terminal.flush()

        # Prevenir recursão infinita (apenas dentro da mesma thread)
        if getattr(self._local, "in_write", False):
            return

        try:
            self._local.in_write = True
            if _logs_detalhados_ativos():
                mensagem_limpa = mensagem.strip()
                if mensagem_limpa:  # Ignorar linhas vazias
                    _adicionar_ao_buffer("aplicacao", mensagem_limpa)
        except Exception:
            pass  # Ignorar erros na captura de logs
        finally:
            self._local.in_write = False

    def flush(self):
        self.terminal.flush()


# Redirecionar stdout para captura de logs
sys.stdout = LogCapture()
