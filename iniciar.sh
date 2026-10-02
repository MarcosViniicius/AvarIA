#!/usr/bin/env bash
#
# AvarIA - inicia o sistema (Linux e macOS).
# Uso: ./iniciar.sh   (ou dê dois cliques em "Iniciar AvarIA.command" no macOS)

set -e
cd "$(dirname "$0")"

# Saída em UTF-8 (acentos corretos no console e nos logs).
export PYTHONUTF8=1

echo
echo "  AvarIA - as perdas da loja à vista"
echo "  =================================="
echo

if [ ! -f "app.py" ]; then
  echo "[ERRO] Este script precisa estar na pasta do projeto (onde fica o app.py)."
  exit 1
fi

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[ERRO] Python 3 não encontrado."
  echo "       Instale em https://www.python.org/downloads/ e rode de novo."
  exit 1
fi

PRIMEIRA=0
if [ ! -x "venv/bin/python" ]; then
  PRIMEIRA=1
  echo "Criando o ambiente virtual..."
  "$PYTHON" -m venv venv
fi

if [ "$PRIMEIRA" -eq 1 ]; then
  echo "Instalando as dependências (pode demorar alguns minutos na primeira vez)..."
  venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
else
  echo "Conferindo as dependências..."
  venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

echo
echo "Iniciando o sistema em http://localhost:5000 ..."
if [ -z "${AVARIA_SEM_BROWSER:-}" ]; then
  (
    sleep 5
    xdg-open "http://localhost:5000" >/dev/null 2>&1 ||
      open "http://localhost:5000" >/dev/null 2>&1 || true
  ) &
fi

echo
echo "  O navegador vai abrir sozinho. Se não abrir, acesse:"
echo "  http://localhost:5000"
echo
echo "  Para encerrar: pressione Ctrl+C."
echo

exec venv/bin/python app.py
