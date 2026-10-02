"""
Funções puras de unificação de produtos (Avarias / Uso Interno): agrupar
itens equivalentes, extrair peso/quantidade/código de barras a partir dos
campos do relatório e consolidar em uma única linha por produto.

Vivem em services/ (não em routes/) porque são usadas tanto pela rota
`/api/unificar_relatorio` (routes/unificacao.py) quanto por outros serviços
que não deveriam depender de código de rotas: a exportação escopada por
execução (services/execucao_export.py), a migração de campos
(services/campo_migration.py) e os agregados do banco (services/db.py).
"""

import re
import unicodedata

import pandas as pd


def normalizar_texto(texto):
    """Normaliza texto para comparação (remove acentos, maiúsculas, espaços extras)."""
    if pd.isna(texto) or texto == "" or texto == "-":
        return ""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(char for char in texto if unicodedata.category(char) != 'Mn')
    return texto


def extrair_quantidade_unidade(texto):
    """Extrai quantidade numérica e unidade de uma string.

    Exemplos:
        "2 kg" -> (2.0, "kg")
        "1,5 kg" -> (1.5, "kg")
        "3.5kg" -> (3.5, "kg")
        "500g" -> (500.0, "g")
        "2 unidades" -> (2.0, "unidades")
    """
    if pd.isna(texto) or texto == "" or texto == "-":
        return None, None

    texto = str(texto).strip()

    padroes = [
        r'([\d]+[,.]?[\d]*)\s*(kg|g|l|ml|unidade|unidades|un|und|caixa|caixas|pacote|pacotes|lata|latas)',
        r'([\d]+[,.]?[\d]*)\s*([a-zA-Z]+)',
    ]

    for padrao in padroes:
        match = re.search(padrao, texto.lower())
        if match:
            try:
                quantidade_str = match.group(1).replace(',', '.')
                quantidade = float(quantidade_str)
                unidade = match.group(2).strip()
                return quantidade, unidade
            except ValueError:
                continue

    return None, None


def extrair_peso_de_valor(peso_valor):
    """Extrai o peso em QUILOGRAMAS a partir do valor bruto da coluna 'Peso'.

    Ex: '1,5kg' -> 1.5, '500g' -> 0.5, '350 g' -> 0.35, 'N/A' -> None.
    Se nenhuma unidade for reconhecida no texto, assume quilogramas.

    Importante: a IA registra o peso na unidade que aparece na etiqueta, que
    varia entre 'kg' e 'g' item a item — sem essa conversão, somar pesos de
    itens em gramas junto com itens em quilogramas (na unificação) resultava
    em totais até 1000x maiores que o real.
    """
    if pd.isna(peso_valor) or peso_valor == "" or peso_valor == "-":
        return None

    texto = str(peso_valor).strip()
    if "n/a" in texto.lower():
        return None

    match = re.search(r"([\d]+[.,]?[\d]*)\s*(kg|g)?", texto, re.IGNORECASE)
    if not match:
        return None
    try:
        numero = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    unidade = (match.group(2) or "kg").lower()
    return numero / 1000.0 if unidade == "g" else numero


def extrair_quantidade_de_observacao(observacao):
    """Extrai quantidade numérica do campo 'Observação da Mensagem' para USO INTERNO.

    Regras:
    - Se houver números (ex: "2" ou "46 unid"), extrair e somar
    - Se for "Nenhuma", retornar 1
    - Se não houver números, retornar 1
    """
    if pd.isna(observacao) or observacao == "" or observacao == "-":
        return 1.0

    observacao_str = str(observacao).strip()

    if observacao_str.lower() == "nenhuma":
        return 1.0

    padrao = r'(\d+)(?:\s*(?:unid|unidade|unidades|un|und))?'
    matches = re.findall(padrao, observacao_str.lower())

    if matches:
        return sum(float(m) for m in matches)

    return 1.0


def extrair_codigo_barras_de_detalhes(detalhes):
    """Extrai código de barras do texto combinado legado 'Marca: X | Cód. Barras: Y'.

    Usado apenas para migrar dados antigos (services/campo_migration.py) —
    hoje o código de barras já vem numa coluna própria.
    """
    if pd.isna(detalhes) or detalhes == "" or detalhes == "-":
        return "N/A"

    detalhes_str = str(detalhes).strip()

    if 'barras' not in detalhes_str.lower():
        return "N/A"

    padrao = r'c[oó]d\.?\s*barras\s*:\s*([\d]+)'
    match = re.search(padrao, detalhes_str.lower())

    if match:
        return match.group(1)

    return "N/A"


def unificar_itens_avarias(df):
    """Unifica itens de AVARIAS agrupando por Produto e somando pesos.

    Regras:
    - Chave de Agrupamento: Nome do Produto (normalizado)
    - Extrai o valor numérico da coluna 'Peso' e soma
    - Se peso for 'N/A' ou inexistente, contar como 1 unidade
    - Saída: NOME DO PRODUTO | QUANTIDADE TOTAL (kg ou un)

    Returns:
        tuple: (df_unificado, auditoria_dict)
    """
    if df.empty:
        return df.copy(), {}

    if "Produto" not in df.columns or "Peso" not in df.columns:
        return df.copy(), {}

    grupos = {}

    for idx, row in df.iterrows():
        produto = row.get("Produto", "")
        peso_valor = row.get("Peso", "")

        produto_norm = normalizar_texto(produto)
        if not produto_norm:
            continue

        peso = extrair_peso_de_valor(peso_valor)
        quantidade_linha = _quantidade_da_linha(row) or 1

        if produto_norm not in grupos:
            grupos[produto_norm] = {
                "produto_original": produto.strip().upper(),
                "quantidade_kg": 0.0,
                "quantidade_un": 0,
                "registros": []
            }

        if peso is not None and peso > 0:
            grupos[produto_norm]["quantidade_kg"] += peso
        else:
            grupos[produto_norm]["quantidade_un"] += quantidade_linha

        grupos[produto_norm]["registros"].append({
            "index": idx,
            "registro_completo": row.to_dict(),
            "peso_extraido": peso
        })

    registros_unificados = []
    auditoria = {}

    for produto_norm in sorted(grupos.keys()):
        info = grupos[produto_norm]
        registro_base = info["registros"][0]["registro_completo"].copy()

        if info["quantidade_kg"] > 0:
            quantidade_formatada = f"{info['quantidade_kg']:.3f} kg".replace('.', ',')
        else:
            quantidade_formatada = f"{info['quantidade_un']} un"

        registro_base["Produto"] = info["produto_original"]
        registro_base["Quantidade Total"] = quantidade_formatada
        registro_base["Qtd_Registros_Consolidados"] = len(info["registros"])

        registros_unificados.append(registro_base)

        chave_auditoria = f"{info['produto_original']} ({quantidade_formatada})"
        auditoria[chave_auditoria] = info["registros"]

    if registros_unificados:
        df_unificado = pd.DataFrame(registros_unificados)
        colunas = ["Produto", "Quantidade Total"]
        colunas += [c for c in df_unificado.columns if c not in colunas]
        df_unificado = df_unificado[colunas]
    else:
        df_unificado = df.copy()

    return df_unificado, auditoria


_CODIGOS_INVALIDOS = {"", "n/a", "na", "-", "none", "null", "nan", "nenhum", "nenhuma"}


def _quantidade_da_linha(row):
    """Lê a quantidade já associada ao item, quando disponível."""
    valor = row.get("Quantidade")
    if pd.isna(valor) or str(valor).strip() in ("", "-"):
        return None
    try:
        quantidade = int(float(str(valor).replace(",", ".")))
    except (TypeError, ValueError, OverflowError):
        return None
    return quantidade if quantidade > 0 else None


def _codigo_barras_valido(valor) -> bool:
    """True se `valor` é um código de barras utilizável como chave de unificação."""
    if pd.isna(valor):
        return False
    return str(valor).strip().lower() not in _CODIGOS_INVALIDOS


def unificar_itens_uso_interno(df):
    """Unifica itens de USO INTERNO exclusivamente pelo Código de Barras.

    Regras:
    - Chave de agrupamento: SOMENTE o Código de Barras — nunca o nome do
      produto. Descrições diferentes do mesmo item (ex.: "ABSOLUTO",
      "DETERGENTE ABSOLUTO", "LAVA-LOUÇAS ABSOLUTO!") têm o mesmo código e
      viram uma linha só; produtos com códigos diferentes NUNCA se juntam,
      mesmo com nomes iguais ou parecidos.
    - Itens sem código de barras válido (N/A, vazio, ausente) não têm chave
      confiável para agrupamento — cada um permanece como linha própria, sem
      unificar nem entre si.
    - Quantidades (extraídas de 'Observação da Mensagem') são somadas por
      código de barras.
    - A descrição exibida é a mais frequente entre os registros daquele
      código; empate é resolvido pela primeira encontrada.
    - Saída: NOME DO PRODUTO | QUANTIDADE TOTAL | CÓDIGO DE BARRAS

    Returns:
        tuple: (df_unificado, auditoria_dict)
    """
    if df.empty:
        return df.copy(), {}

    if "Produto" not in df.columns or "Código de Barras" not in df.columns or "Observação da Mensagem" not in df.columns:
        return df.copy(), {}

    grupos = {}
    proximo_id_sem_codigo = 0

    for idx, row in df.iterrows():
        produto = row.get("Produto", "")
        observacao = row.get("Observação da Mensagem", "")
        codigo_bruto = row.get("Código de Barras", "N/A")

        produto_norm = normalizar_texto(produto)
        if not produto_norm:
            continue

        quantidade = _quantidade_da_linha(row)
        if quantidade is None:
            # Compatibilidade com planilhas antigas sem coluna Quantidade.
            quantidade = extrair_quantidade_de_observacao(observacao)

        if _codigo_barras_valido(codigo_bruto):
            codigo_barras = str(codigo_bruto).strip()
            chave = ("codigo", codigo_barras)
        else:
            # Sem código confiável: não agrupa com nada, nem com outro item
            # também sem código - cada um vira sua própria linha no resultado.
            codigo_barras = "N/A"
            proximo_id_sem_codigo += 1
            chave = ("sem_codigo", proximo_id_sem_codigo)

        if chave not in grupos:
            grupos[chave] = {
                "codigo_barras": codigo_barras,
                "quantidade_total": 0.0,
                "contagem_nomes": {},
                "registros": [],
            }

        grupos[chave]["quantidade_total"] += quantidade
        nome_upper = produto.strip().upper()
        grupos[chave]["contagem_nomes"][nome_upper] = grupos[chave]["contagem_nomes"].get(nome_upper, 0) + 1
        grupos[chave]["registros"].append({
            "index": idx,
            "registro_completo": row.to_dict(),
            "quantidade_extraida": quantidade
        })

    registros_unificados = []
    auditoria = {}

    def chave_ordenacao(chave):
        tipo, valor = chave
        return (1, str(valor)) if tipo == "sem_codigo" else (0, str(valor))

    for chave in sorted(grupos.keys(), key=chave_ordenacao):
        info = grupos[chave]
        registro_base = info["registros"][0]["registro_completo"].copy()

        # Descrição mais frequente; em empate, dict preserva ordem de
        # primeira aparição e max() devolve a primeira encontrada.
        nome_exibido = max(info["contagem_nomes"].items(), key=lambda kv: kv[1])[0]

        quantidade_total = info["quantidade_total"]
        if quantidade_total == int(quantidade_total):
            quantidade_formatada = str(int(quantidade_total))
        else:
            quantidade_formatada = f"{quantidade_total:.2f}".replace('.', ',')

        registro_base["Produto"] = nome_exibido
        registro_base["Quantidade Total"] = quantidade_formatada
        registro_base["Código de Barras"] = info["codigo_barras"]
        registro_base["Qtd_Registros_Consolidados"] = len(info["registros"])

        registros_unificados.append(registro_base)

        chave_auditoria = f"{nome_exibido} - {info['codigo_barras']} ({quantidade_formatada})"
        auditoria[chave_auditoria] = info["registros"]

    if registros_unificados:
        df_unificado = pd.DataFrame(registros_unificados)
        colunas = ["Produto", "Quantidade Total", "Código de Barras"]
        colunas += [c for c in df_unificado.columns if c not in colunas]
        df_unificado = df_unificado[colunas]
    else:
        df_unificado = df.copy()

    return df_unificado, auditoria


def renderizar_secciones_como_texto(secciones) -> str:
    """Convierte un dict {sección: DataFrame} en texto tabular legible.

    Pensado para mostrar en pantalla (después de unificar) todo lo que se
    generó, e que o usuário possa copiar (separado por TAB para que cole bem
    numa hoja de cálculo). Solo incluye seções não vazias.

    Formato por seção:
        NOME DA SEÇÃO
        --------------------
        Cab1\tCab2\t...
        val1\tval2\t...
        (fila vazia entre seções)
    """
    secciones_filtradas = {n: df for n, df in secciones.items() if df is not None and not df.empty}
    if not secciones_filtradas:
        return ""

    bloques = []
    for nombre, df in secciones_filtradas.items():
        lineas = [nombre, "-" * len(str(nombre))]
        df_str = df.astype(object).where(pd.notna(df), "-")
        lineas.append("\t".join(str(col) for col in df_str.columns))
        for _, fila in df_str.iterrows():
            # A saída é destinada a copiar/colar como TSV: tabs e quebras de
            # linha dentro de um campo não devem deslocar colunas/registros.
            valores = [
                str(valor).replace("\t", " ").replace("\r", " ").replace("\n", " / ")
                for valor in fila.tolist()
            ]
            lineas.append("\t".join(valores))
        bloques.append("\n".join(lineas))

    return "\n\n".join(bloques)
