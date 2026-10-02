"""Configuração compartilhada dos testes: expõe o pacote (na raiz do projeto)
e fornece um banco SQLite temporário isolado (nunca toca em
database/avariaia.db real)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redireciona o banco para um arquivo temporário e cria o schema."""
    from avariaia.services import db

    db_path = tmp_path / "teste.db"
    monkeypatch.setattr(db, "DATABASE_DIR", tmp_path)
    monkeypatch.setattr(db, "DATABASE_FILE", db_path)
    db.init_db()
    return db
