"""
Caminhos e constantes compartilhados pelos módulos de rotas web.

Mantém os mesmos nomes e valores (como strings) que existiam originalmente
no topo de ``routes/web.py``, para que os demais módulos de rotas continuem
se comportando exatamente da mesma forma depois da divisão em arquivos
menores.
"""

import os

from autoavaria.core.paths import (
    DATA_ROOT,
    UPLOAD_FOLDER as UPLOAD_FOLDER_PATH,
    ARCHIVE_FOLDER as ARCHIVE_FOLDER_PATH,
    ARQUIVO_SAIDA_EXCEL as ARQUIVO_SAIDA_EXCEL_PATH,
    LOG_CONSUMO_FILE as LOG_CONSUMO_FILE_PATH,
    LOG_PROCESSADOS_FILE as LOG_PROCESSADOS_FILE_PATH,
    CONFIG_FILE as CONFIG_FILE_PATH,
)

BASE_PATH = str(DATA_ROOT)

# Configurações básicas adaptadas para ambiente
UPLOAD_FOLDER = str(UPLOAD_FOLDER_PATH)
ARCHIVE_FOLDER = str(ARCHIVE_FOLDER_PATH)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "txt", "zip", "rar", "7z", "tar", "gz", "bz2", "tgz"}
EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")
DIRETORIO_IMAGENS = UPLOAD_FOLDER
ARQUIVO_SAIDA_EXCEL = str(ARQUIVO_SAIDA_EXCEL_PATH)
LOG_CONSUMO_FILE = str(LOG_CONSUMO_FILE_PATH)
LOG_PROCESSADOS_FILE = str(LOG_PROCESSADOS_FILE_PATH)
CONFIG_FILE = str(CONFIG_FILE_PATH)

# Garantir que os diretórios existam
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ARCHIVE_FOLDER, exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, "resultados"), exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, "logs"), exist_ok=True)
os.makedirs(os.path.join(BASE_PATH, "config"), exist_ok=True)
