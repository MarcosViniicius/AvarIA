import os
from datetime import timedelta


def load_flask_settings() -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "sua_chave_secreta_aqui_mude_em_producao"),
        # O limite individual é aplicado pela rota de upload; o limite do
        # request permite vários arquivos de até 50 MiB no mesmo lote.
        "MAX_CONTENT_LENGTH": 200 * 1024 * 1024,
        "SEND_FILE_MAX_AGE_DEFAULT": timedelta(hours=1),
    }
