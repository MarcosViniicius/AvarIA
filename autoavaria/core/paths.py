import os
from pathlib import Path

# Este arquivo é autoavaria/core/paths.py:
#   parents[0] = core/            parents[1] = autoavaria/ (o pacote)
#   parents[2] = raiz do projeto  (onde vivem config/, database/, results...)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

if "VERCEL" in os.environ:
    DATA_ROOT = Path("/tmp")
else:
    DATA_ROOT = PROJECT_ROOT

UPLOAD_FOLDER = DATA_ROOT / "imagens_para_analisar"
ARCHIVE_FOLDER = DATA_ROOT / "imagens_processadas"
RESULTADOS_DIR = DATA_ROOT / "resultados"
LOGS_DIR = DATA_ROOT / "logs"
CONFIG_DIR = DATA_ROOT / "config"
DATABASE_DIR = DATA_ROOT / "database"

ARQUIVO_SAIDA_EXCEL = RESULTADOS_DIR / "Relatorio_Mestre_Produtos.xlsx"
LOG_CONSUMO_FILE = LOGS_DIR / "log_consumo_tokens.txt"
LOG_PROCESSADOS_FILE = LOGS_DIR / "log_mestre.txt"
CONFIG_FILE = CONFIG_DIR / "config.json"
DATABASE_FILE = DATABASE_DIR / "autoavaria.db"

def ensure_directories() -> None:
    for path in [UPLOAD_FOLDER, ARCHIVE_FOLDER, RESULTADOS_DIR, LOGS_DIR, CONFIG_DIR, DATABASE_DIR]:
        path.mkdir(parents=True, exist_ok=True)
