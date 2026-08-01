"""
MOTORES DE EXTRAÇÃO (IA / sem IA / híbrido)

Camada acima do provedor de IA. Todos os motores devolvem resultados no
**mesmo formato** que a IA sempre devolveu, de modo que o resto do pipeline
(`processar_resultado_arquivo`, Excel, banco, telas) funciona sem saber qual
motor produziu o dado::

    {
      "IMG-1234.jpg": {
        "tipo": "Avaria" | "Uso Interno" | "Erro",
        "itens": [{"produto": ..., "peso": ..., "marca": ...,
                   "codigo_barras": ..., "quantidade": ...}],
      }
    }

Os três motores:

* ``MotorIA`` — o comportamento atual, sem alteração nenhuma. Só delega para
  `ai_extraction.extrair_dados_de_lote`.
* ``MotorCodigoBarras`` — 100% local, custo zero. Lê o código de barras e
  traduz pelo catálogo. O que não conseguir resolver vira "Erro" e aparece na
  aba de erros para revisão manual.
* ``MotorHibrido`` — lê o código de barras primeiro e manda para a IA só o
  que sobrou. Reduz muito o custo e ainda **ensina o catálogo** com o que a
  IA descobre, de forma que o modo sem IA melhora a cada execução.
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from . import ai_extraction, barcode, catalogo
from .ai import AIProvider
from .conversa import ContextoImagem

MODO_IA = "ia"
MODO_SEM_IA = "sem_ia"
MODO_HIBRIDO = "hibrido"

MODOS_DISPONIVEIS = {
    MODO_IA: "Somente IA",
    MODO_SEM_IA: "Sem IA (código de barras)",
    MODO_HIBRIDO: "Híbrido (código de barras + IA no que faltar)",
}


def _formatar_peso(peso_kg: float) -> str:
    """Formata peso no mesmo padrão já usado no relatório (ex.: '0,738kg')."""
    return f"{peso_kg:.3f}".replace(".", ",") + "kg"


def _quantidade_do_contexto(contexto: Optional[ContextoImagem]) -> int:
    if contexto is None or contexto.quantidade is None:
        return 1
    return contexto.quantidade


class MotorExtracao(ABC):
    """Interface comum dos motores de extração."""

    nome: str = "motor"
    usa_ia: bool = False

    @abstractmethod
    def processar_lote(
        self,
        lote_de_caminhos: List[str],
        contextos: Dict[str, ContextoImagem],
    ) -> Tuple[Dict[str, Any], int]:
        """Processa um lote e devolve (resultados, tokens_consumidos)."""


# ---------------------------------------------------------------------------
# Motor 1 — IA (comportamento atual, intacto)
# ---------------------------------------------------------------------------


class MotorIA(MotorExtracao):
    """Envolve o fluxo de IA existente sem alterar nada do seu comportamento."""

    nome = "IA"
    usa_ia = True

    def __init__(self, provider: AIProvider):
        self.provider = provider

    def processar_lote(self, lote_de_caminhos, contextos):
        mensagens = {img: ctx.texto for img, ctx in contextos.items()}
        resultados, tokens = ai_extraction.extrair_dados_de_lote(
            lote_de_caminhos, self.provider, mensagens
        )
        _aplicar_quantidade(resultados, contextos)
        _aprender_do_resultado(resultados)
        return resultados, tokens


# ---------------------------------------------------------------------------
# Motor 2 — Código de barras (sem IA)
# ---------------------------------------------------------------------------


class MotorCodigoBarras(MotorExtracao):
    """Extração local por código de barras, sem nenhuma chamada de IA."""

    nome = "Código de Barras"
    usa_ia = False

    def processar_lote(self, lote_de_caminhos, contextos):
        resultados: Dict[str, Any] = {}
        for caminho in lote_de_caminhos:
            nome_arquivo = os.path.basename(caminho)
            resultados[nome_arquivo] = self.processar_imagem(
                caminho, contextos.get(nome_arquivo)
            )
        return resultados, 0

    def processar_imagem(
        self, caminho: str, contexto: Optional[ContextoImagem]
    ) -> Dict[str, Any]:
        """Lê uma imagem e monta o resultado no formato do relatório."""
        try:
            codigos = barcode.ler_imagem(caminho)
        except RuntimeError as e:
            return {"tipo": "Erro", "detalhes": str(e)}

        if not codigos:
            return {
                "tipo": "Erro",
                "detalhes": "Nenhum código de barras legível na imagem.",
            }

        quantidade = _quantidade_do_contexto(contexto)
        itens_avaria: List[Dict[str, Any]] = []
        itens_uso: List[Dict[str, Any]] = []

        for codigo in codigos:
            if codigo.eh_balanca:
                item = self._item_de_balanca(codigo.texto, quantidade)
                if item:
                    itens_avaria.append(item)
            else:
                itens_uso.append(self._item_de_ean(codigo.texto, quantidade))

        # Uma foto pode conter etiqueta de balança e código comum; classificamos
        # pela que predominar, mantendo o formato de saída de sempre.
        if itens_avaria and not itens_uso:
            return {"tipo": "Avaria", "itens": itens_avaria}
        if itens_uso and not itens_avaria:
            return {"tipo": "Uso Interno", "itens": itens_uso}
        if itens_avaria and itens_uso:
            return {"tipo": "Avaria", "itens": itens_avaria + itens_uso}

        return {
            "tipo": "Erro",
            "detalhes": "Código lido, mas não foi possível interpretá-lo.",
        }

    def _item_de_balanca(self, codigo: str, quantidade: int) -> Optional[Dict[str, Any]]:
        """Monta um item de avaria a partir de uma etiqueta de balança."""
        interpretado = barcode.interpretar_etiqueta_balanca(codigo)
        if not interpretado:
            return None
        plu, total_reais = interpretado

        entrada = catalogo.buscar(plu) or {}
        produto = entrada.get("produto") or f"PLU {plu}"
        preco_kg = entrada.get("preco_kg")

        peso = "N/A"
        if preco_kg:
            peso_kg = barcode.calcular_peso(total_reais, preco_kg)
            if peso_kg:
                peso = _formatar_peso(peso_kg)

        return {
            "produto": produto,
            "peso": peso,
            "marca": "N/A",
            "codigo_barras": codigo,
            "quantidade": quantidade,
            # Campo interno (não vira coluna de relatório - ver
            # ai_extraction._processar_avaria, que só lê chaves nomeadas):
            # permite ao motor híbrido decidir se esse peso ainda é confiável
            # ou se o preço/kg usado para calculá-lo pode estar desatualizado.
            "_catalogo_atualizado_em": entrada.get("atualizado_em"),
        }

    def _item_de_ean(self, codigo: str, quantidade: int) -> Dict[str, Any]:
        """Monta um item de uso interno a partir de um EAN-13 comum.

        Mesmo sem o produto cadastrado o item é útil: o código de barras é,
        por si só, a identificação precisa do produto — é exatamente o que a
        planilha já registrava como dado principal desta aba.
        """
        entrada = catalogo.buscar(codigo) or {}
        return {
            "produto": entrada.get("produto") or "N/A",
            "marca": entrada.get("marca") or "N/A",
            "codigo_barras": codigo,
            "peso": "N/A",
            "quantidade": quantidade,
        }


# ---------------------------------------------------------------------------
# Motor 3 — Híbrido
# ---------------------------------------------------------------------------


class MotorHibrido(MotorExtracao):
    """Código de barras primeiro; IA só no que não deu para resolver."""

    nome = "Híbrido"
    usa_ia = True

    def __init__(
        self,
        provider: AIProvider,
        dias_para_reverificar: int = catalogo.DIAS_PARA_REVERIFICAR_PADRAO,
    ):
        self.provider = provider
        self.motor_barras = MotorCodigoBarras()
        self.dias_para_reverificar = dias_para_reverificar

    def processar_lote(self, lote_de_caminhos, contextos):
        resultados: Dict[str, Any] = {}
        pendentes: List[str] = []

        for caminho in lote_de_caminhos:
            nome_arquivo = os.path.basename(caminho)
            resultado = self.motor_barras.processar_imagem(
                caminho, contextos.get(nome_arquivo)
            )
            if self._precisa_de_ia(resultado):
                pendentes.append(caminho)
            else:
                resultados[nome_arquivo] = resultado

        tokens = 0
        if pendentes:
            print(
                f"   🤖 {len(pendentes)} de {len(lote_de_caminhos)} imagens "
                f"precisaram de IA (o resto foi resolvido de graça)"
            )
            mensagens = {img: ctx.texto for img, ctx in contextos.items()}
            resultados_ia, tokens = ai_extraction.extrair_dados_de_lote(
                pendentes, self.provider, mensagens
            )
            _aplicar_quantidade(resultados_ia, contextos)
            _aprender_do_resultado(resultados_ia)
            resultados.update(resultados_ia)

        return resultados, tokens

    def _precisa_de_ia(self, resultado: Dict[str, Any]) -> bool:
        """Decide se um resultado local é bom o bastante ou precisa da IA.

        Manda para a IA quando: (a) nada foi lido; (b) é etiqueta de balança
        sem preço/kg cadastrado — não há como calcular o peso localmente, e a
        resposta da IA também ensina o catálogo para resolver sozinho da
        próxima vez; ou (c) o peso foi calculado, mas com um preço/kg que não
        é reconfirmado pela IA há mais de `dias_para_reverificar` dias — sem
        isso, um preço desatualizado (a etiqueta não avisa quando muda) faria
        o peso sair errado silenciosamente para sempre.
        """
        if resultado.get("tipo") == "Erro":
            return True
        for item in resultado.get("itens", []):
            if not barcode.eh_etiqueta_balanca(str(item.get("codigo_barras", ""))):
                continue
            if item.get("peso") in (None, "", "N/A"):
                return True
            if catalogo.esta_desatualizado(
                item.get("_catalogo_atualizado_em"), dias=self.dias_para_reverificar
            ):
                return True
        return False


# ---------------------------------------------------------------------------
# Aprendizado e utilidades compartilhadas
# ---------------------------------------------------------------------------


def _aplicar_quantidade(resultados: Dict[str, Any], contextos: Dict[str, ContextoImagem]) -> None:
    """Preenche a quantidade vinda da conversa nos itens que não a trazem.

    A quantidade só existe no texto da conversa — a IA não tem como inferir
    "7 unidades" de uma foto de um único pacote.
    """
    for nome_arquivo, dados in resultados.items():
        if not isinstance(dados, dict):
            continue
        quantidade = _quantidade_do_contexto(contextos.get(nome_arquivo))
        for item in dados.get("itens", []) or []:
            if isinstance(item, dict) and not item.get("quantidade"):
                item["quantidade"] = quantidade


def _aprender_do_resultado(resultados: Dict[str, Any]) -> None:
    """Alimenta o catálogo com o que a IA descobriu.

    É o que faz o modo híbrido melhorar o modo sem IA com o tempo: cada
    código que a IA identifica passa a ser resolvido localmente depois.
    """
    for dados in resultados.values():
        if not isinstance(dados, dict):
            continue
        categoria = dados.get("tipo") or ""
        for item in dados.get("itens", []) or []:
            if not isinstance(item, dict):
                continue
            codigo = str(item.get("codigo_barras") or "").strip()
            if not barcode.ean13_valido(codigo):
                continue
            try:
                if barcode.eh_etiqueta_balanca(codigo):
                    _aprender_balanca(codigo, item)
                else:
                    catalogo.aprender(
                        codigo=codigo,
                        produto=str(item.get("produto") or ""),
                        marca=str(item.get("marca") or ""),
                        categoria="Uso Interno" if categoria == "Uso Interno" else categoria,
                    )
            except Exception as e:  # nunca deixar o aprendizado quebrar o processamento
                print(f"⚠️ Não foi possível atualizar o catálogo para {codigo}: {e}")


def _aprender_balanca(codigo: str, item: Dict[str, Any]) -> None:
    """Deriva o preço por quilo a partir do total do código e do peso lido pela IA."""
    interpretado = barcode.interpretar_etiqueta_balanca(codigo)
    if not interpretado:
        return
    plu, total_reais = interpretado
    peso_kg = _peso_para_float(item.get("peso"))
    produto = str(item.get("produto") or "")
    if peso_kg:
        catalogo.aprender_preco_kg(plu, produto, total_reais, peso_kg)
    elif produto:
        catalogo.registrar(
            codigo=plu, produto=produto, categoria_padrao="Avarias", tipo="plu", origem="ia"
        )


def _peso_para_float(valor: Any) -> Optional[float]:
    """Converte '0,738kg' / '1.804 kg' / 0.738 em float de quilos."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) or None
    texto = str(valor).strip().lower().replace("kg", "").replace("ks", "").strip()
    texto = texto.replace(",", ".")
    try:
        peso = float(texto)
    except ValueError:
        return None
    return peso if peso > 0 else None


# ---------------------------------------------------------------------------
# Fábrica
# ---------------------------------------------------------------------------


def construir_motor(
    modo: str,
    provider: Optional[AIProvider] = None,
    dias_para_reverificar: Optional[int] = None,
) -> MotorExtracao:
    """Cria o motor do modo pedido.

    Faz *fallback* seguro para IA se o modo sem IA for pedido mas as
    dependências de leitura de código de barras não estiverem instaladas.
    """
    modo = (modo or MODO_IA).lower()

    if modo in (MODO_SEM_IA, MODO_HIBRIDO) and not barcode.LEITURA_DISPONIVEL:
        print(f"⚠️ {barcode.MENSAGEM_INDISPONIVEL}")
        if provider is None:
            raise RuntimeError(barcode.MENSAGEM_INDISPONIVEL)
        print("↩️  Voltando para o modo somente IA.")
        modo = MODO_IA

    if modo == MODO_SEM_IA:
        return MotorCodigoBarras()

    if modo == MODO_HIBRIDO:
        if provider is None:
            raise ValueError("O modo híbrido precisa de um provedor de IA configurado.")
        if dias_para_reverificar is None:
            return MotorHibrido(provider)
        return MotorHibrido(provider, dias_para_reverificar=dias_para_reverificar)

    if provider is None:
        raise ValueError("O modo IA precisa de um provedor de IA configurado.")
    return MotorIA(provider)
