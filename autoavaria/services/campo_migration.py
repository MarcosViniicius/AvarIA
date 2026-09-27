"""
Migração única (idempotente) do campo "Detalhes" combinado (ex: "Peso: 1kg",
"Marca: X | Cód. Barras: Y") para colunas separadas (Peso / Marca / Código de
Barras), tanto no Excel mestre atual quanto nos itens já salvos no banco.

Roda automaticamente na inicialização do app (ver autoavaria/__init__.py) e
não faz nada se os dados já estiverem no formato novo.
"""

import os
import shutil

import pandas as pd

from ..core.paths import ARQUIVO_SAIDA_EXCEL
from .unification import extrair_codigo_barras_de_detalhes
from . import db
from .report_editing import carregar_todas_sheets


def _dividir_detalhes_uso_interno(detalhes):
    """Extrai (marca, codigo_barras) do texto combinado antigo (ex: 'Marca: X | Cód. Barras: Y')."""
    marca = "N/A"
    texto = str(detalhes) if detalhes is not None else ""
    for parte in texto.split("|"):
        parte = parte.strip()
        if parte.lower().startswith("marca:"):
            marca = parte.split(":", 1)[1].strip() or "N/A"
    codigo = extrair_codigo_barras_de_detalhes(detalhes)
    return marca, codigo


def _peso_bruto_de_detalhes(detalhes):
    """Extrai o valor bruto do peso (ex: '1,5kg') a partir de 'Peso: 1,5kg'."""
    texto = str(detalhes) if detalhes is not None else ""
    if "Peso:" in texto:
        return texto.split("Peso:", 1)[1].strip() or "N/A"
    return texto.strip() or "N/A"


def migrar_excel_mestre() -> bool:
    """Separa a coluna 'Detalhes' do Excel mestre em Peso / Marca / Código de Barras, se necessário."""
    if not os.path.exists(ARQUIVO_SAIDA_EXCEL):
        return False

    try:
        sheets = carregar_todas_sheets(ARQUIVO_SAIDA_EXCEL)
    except Exception as e:
        print(f"⚠️ Não foi possível ler o Excel mestre para migração de campos: {e}")
        return False

    alterado = False

    df_avarias = sheets.get("Avarias")
    if df_avarias is not None and "Detalhes" in df_avarias.columns and "Peso" not in df_avarias.columns:
        df_avarias["Peso"] = df_avarias["Detalhes"].apply(_peso_bruto_de_detalhes)
        df_avarias.drop(columns=["Detalhes"], inplace=True)
        colunas = ["Produto", "Peso"] + [c for c in df_avarias.columns if c not in ("Produto", "Peso")]
        sheets["Avarias"] = df_avarias[[c for c in colunas if c in df_avarias.columns]]
        alterado = True

    df_uso = sheets.get("Uso Interno")
    if df_uso is not None and "Detalhes" in df_uso.columns and "Marca" not in df_uso.columns:
        marcas_codigos = df_uso["Detalhes"].apply(_dividir_detalhes_uso_interno)
        df_uso["Marca"] = marcas_codigos.apply(lambda t: t[0])
        df_uso["Código de Barras"] = marcas_codigos.apply(lambda t: t[1])
        df_uso.drop(columns=["Detalhes"], inplace=True)
        colunas = ["Produto", "Marca", "Código de Barras"] + [
            c for c in df_uso.columns if c not in ("Produto", "Marca", "Código de Barras")
        ]
        sheets["Uso Interno"] = df_uso[[c for c in colunas if c in df_uso.columns]]
        alterado = True

    if not alterado:
        return False

    backup_path = f"{ARQUIVO_SAIDA_EXCEL}.antes_migracao_campos.bak"
    try:
        shutil.copy2(ARQUIVO_SAIDA_EXCEL, backup_path)
    except OSError as e:
        print(f"⚠️ Não foi possível criar backup antes da migração de campos: {e}")

    with pd.ExcelWriter(ARQUIVO_SAIDA_EXCEL, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    print("✅ Migração de campos concluída no Excel mestre (Peso / Marca / Código de Barras separados).")
    return True


def migrar_itens_banco() -> int:
    """Preenche peso/marca/codigo_barras nos itens já salvos no banco, a partir do 'detalhes' antigo."""
    with db.get_connection() as conn:
        avarias_pendentes = conn.execute(
            "SELECT id, detalhes FROM report_items WHERE categoria = 'Avarias' AND peso IS NULL AND detalhes IS NOT NULL"
        ).fetchall()
        for row in avarias_pendentes:
            peso = _peso_bruto_de_detalhes(row["detalhes"])
            conn.execute("UPDATE report_items SET peso = ?, detalhes = NULL WHERE id = ?", (peso, row["id"]))

        uso_pendentes = conn.execute(
            "SELECT id, detalhes FROM report_items WHERE categoria = 'Uso Interno' AND marca IS NULL AND detalhes IS NOT NULL"
        ).fetchall()
        for row in uso_pendentes:
            marca, codigo = _dividir_detalhes_uso_interno(row["detalhes"])
            conn.execute(
                "UPDATE report_items SET marca = ?, codigo_barras = ?, detalhes = NULL WHERE id = ?",
                (marca, codigo, row["id"]),
            )

        total = len(avarias_pendentes) + len(uso_pendentes)

    if total:
        print(f"✅ Migração de campos concluída no banco: {total} itens atualizados.")
    return total


def executar_migracao_campos() -> None:
    """Ponto de entrada chamado na inicialização do app. Seguro rodar em toda inicialização."""
    try:
        migrar_excel_mestre()
    except Exception as e:
        print(f"⚠️ Erro na migração de campos do Excel mestre: {e}")
    try:
        migrar_itens_banco()
    except Exception as e:
        print(f"⚠️ Erro na migração de campos do banco: {e}")
