"""
Blueprint compartilhado por todos os módulos de rotas web.

Cada módulo em ``autoavaria.routes`` importa ``web_bp`` daqui (geralmente
como ``from .blueprint import web_bp as app``) e registra suas rotas nele
como efeito colateral da importação. Isolar o Blueprint neste módulo (em vez
de deixá-lo em ``web.py``) evita import circular entre os módulos de rotas.
"""

from flask import Blueprint

web_bp = Blueprint("web", __name__)
