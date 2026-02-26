import os
from datetime import timedelta


def load_flask_settings() -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "sua_chave_secreta_aqui_mude_em_producao"),
        "MAX_CONTENT_LENGTH": 50 * 1024 * 1024,
        "SEND_FILE_MAX_AGE_DEFAULT": timedelta(hours=1),
    }
