"""Testes das funções puras de unificação (services/unification.py)."""

import pandas as pd
import pytest

from autoavaria.services.unification import (
    extrair_codigo_barras_de_detalhes,
    extrair_peso_de_valor,
    extrair_quantidade_de_observacao,
    normalizar_texto,
    unificar_itens_avarias,
    unificar_itens_uso_interno,
)


class TestNormalizarTexto:
    def test_remove_acentos_e_maiusculas(self):
        assert normalizar_texto("Maçã Vermelha") == "maca vermelha"

    def test_valores_vazios(self):
        assert normalizar_texto("") == ""
        assert normalizar_texto("-") == ""
        assert normalizar_texto(None) == ""


class TestExtrairPesoDeValor:
    @pytest.mark.parametrize(
        "valor,esperado",
        [
            ("1,5kg", 1.5),
            ("0.530kg", 0.530),
            ("500g", 0.5),
            ("350 g", 0.35),
            ("46", 46.0),  # sem unidade -> assume kg (comportamento legado)
            ("N/A", None),
            ("", None),
            ("-", None),
        ],
    )
    def test_conversao(self, valor, esperado):
        resultado = extrair_peso_de_valor(valor)
        if esperado is None:
            assert resultado is None
        else:
            assert resultado == pytest.approx(esperado)

    def test_gramas_nao_e_contado_como_quilos(self):
        """Regressão: '350g' não pode virar 350.0 (seria 1000x o valor real)."""
        assert extrair_peso_de_valor("350g") == pytest.approx(0.35)
        assert extrair_peso_de_valor("350g") != 350.0


class TestExtrairQuantidadeDeObservacao:
    def test_nenhuma_conta_como_um(self):
        assert extrair_quantidade_de_observacao("Nenhuma") == 1.0

    def test_numero_extraido(self):
        assert extrair_quantidade_de_observacao("46 unidades") == 46.0

    def test_soma_multiplos_numeros(self):
        assert extrair_quantidade_de_observacao("2 caixas de 10") == 12.0

    def test_sem_numero_conta_como_um(self):
        assert extrair_quantidade_de_observacao("texto qualquer") == 1.0


class TestExtrairCodigoBarrasDeDetalhes:
    def test_extrai_codigo(self):
        assert extrair_codigo_barras_de_detalhes("Marca: X | Cód. Barras: 123456") == "123456"

    def test_sem_codigo_retorna_na(self):
        assert extrair_codigo_barras_de_detalhes("Marca: X") == "N/A"
        assert extrair_codigo_barras_de_detalhes("") == "N/A"


class TestUnificarItensAvarias:
    def test_agrupa_por_produto_e_soma_peso_em_kg(self):
        df = pd.DataFrame(
            [
                {"Produto": "Tomate", "Peso": "1kg", "Observação da Mensagem": "-", "Caminho da Imagem": "a.jpg"},
                {"Produto": "TOMATE", "Peso": "500g", "Observação da Mensagem": "-", "Caminho da Imagem": "b.jpg"},
                {"Produto": "Alface", "Peso": "N/A", "Observação da Mensagem": "-", "Caminho da Imagem": "c.jpg"},
            ]
        )
        resultado, auditoria = unificar_itens_avarias(df)

        tomate = resultado[resultado["Produto"] == "TOMATE"].iloc[0]
        # 1kg + 500g deve ser 1.5kg, não 501kg
        assert "1,500 kg" in tomate["Quantidade Total"]
        assert tomate["Qtd_Registros_Consolidados"] == 2

        alface = resultado[resultado["Produto"] == "ALFACE"].iloc[0]
        assert alface["Quantidade Total"] == "1 un"

    def test_dataframe_vazio(self):
        df = pd.DataFrame(columns=["Produto", "Peso"])
        resultado, auditoria = unificar_itens_avarias(df)
        assert resultado.empty
        assert auditoria == {}

    def test_colunas_ausentes_retorna_copia(self):
        df = pd.DataFrame([{"Outra Coluna": 1}])
        resultado, auditoria = unificar_itens_avarias(df)
        assert len(resultado) == 1
        assert auditoria == {}


class TestUnificarItensUsoInterno:
    def test_agrupa_por_codigo_barras_mesmo_com_nomes_iguais(self):
        df = pd.DataFrame(
            [
                {
                    "Produto": "Saco de Lixo",
                    "Código de Barras": "123",
                    "Observação da Mensagem": "2",
                    "Caminho da Imagem": "a.jpg",
                },
                {
                    "Produto": "SACO DE LIXO",
                    "Código de Barras": "123",
                    "Observação da Mensagem": "3",
                    "Caminho da Imagem": "b.jpg",
                },
                {
                    "Produto": "Saco de Lixo",
                    "Código de Barras": "999",
                    "Observação da Mensagem": "Nenhuma",
                    "Caminho da Imagem": "c.jpg",
                },
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)

        linha_123 = resultado[resultado["Código de Barras"] == "123"].iloc[0]
        assert linha_123["Quantidade Total"] == "5"
        assert linha_123["Qtd_Registros_Consolidados"] == 2

        linha_999 = resultado[resultado["Código de Barras"] == "999"].iloc[0]
        assert linha_999["Quantidade Total"] == "1"

    def test_nomes_diferentes_mesmo_codigo_viram_uma_linha_so(self):
        """Caso reportado: descrições diferentes do mesmo produto (mesmo
        código de barras) apareciam como itens separados. Nome do produto
        NUNCA deve ser usado como chave de agrupamento - só o código."""
        df = pd.DataFrame(
            [
                {"Produto": "ABSOLUTO", "Código de Barras": "7897274416391",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "a.jpg"},
                {"Produto": "DETERGENTE ABSOLUTO", "Código de Barras": "7897274416391",
                 "Observação da Mensagem": "2", "Caminho da Imagem": "b.jpg"},
                {"Produto": "LAVA LOUÇAS ABSOLUTO", "Código de Barras": "7897274416391",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "c.jpg"},
                {"Produto": "LAVA-LOUÇAS ABSOLUTO!", "Código de Barras": "7897274416391",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "d.jpg"},
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)

        assert len(resultado) == 1
        linha = resultado.iloc[0]
        assert linha["Código de Barras"] == "7897274416391"
        assert linha["Quantidade Total"] == "5"
        assert linha["Qtd_Registros_Consolidados"] == 4
        # todos os 4 nomes aparecem 1x só - empate resolvido pelo primeiro encontrado
        assert linha["Produto"] == "ABSOLUTO"

    def test_descricao_exibida_e_a_mais_frequente(self):
        df = pd.DataFrame(
            [
                {"Produto": "COPO", "Código de Barras": "7896030893360",
                 "Observação da Mensagem": "2", "Caminho da Imagem": "a.jpg"},
                {"Produto": "COPO TRANSPARENTE", "Código de Barras": "7896030893360",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "b.jpg"},
                {"Produto": "COPO POUP ÁGUA CFT-150 PP TRANSPARENTE", "Código de Barras": "7896030893360",
                 "Observação da Mensagem": "2", "Caminho da Imagem": "c.jpg"},
                {"Produto": "COPO", "Código de Barras": "7896030893360",
                 "Observação da Mensagem": "0", "Caminho da Imagem": "d.jpg"},
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)

        assert len(resultado) == 1
        linha = resultado.iloc[0]
        assert linha["Produto"] == "COPO"  # aparece 2x, mais que qualquer outra descrição
        assert linha["Quantidade Total"] == "5"
        assert linha["Qtd_Registros_Consolidados"] == 4

    def test_nomes_iguais_mas_codigos_diferentes_nunca_se_juntam(self):
        df = pd.DataFrame(
            [
                {"Produto": "COPO", "Código de Barras": "111",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "a.jpg"},
                {"Produto": "COPO", "Código de Barras": "222",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "b.jpg"},
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)
        assert len(resultado) == 2
        assert set(resultado["Código de Barras"]) == {"111", "222"}

    @pytest.mark.parametrize("codigo_vazio", ["N/A", "n/a", "", "-", None, "nenhuma"])
    def test_itens_sem_codigo_valido_nao_sao_unificados_entre_si(self, codigo_vazio):
        """Sem código de barras não há chave confiável - cada item sem código
        permanece em sua própria linha, mesmo com nome idêntico."""
        df = pd.DataFrame(
            [
                {"Produto": "PRODUTO DESCONHECIDO", "Código de Barras": codigo_vazio,
                 "Observação da Mensagem": "1", "Caminho da Imagem": "a.jpg"},
                {"Produto": "PRODUTO DESCONHECIDO", "Código de Barras": codigo_vazio,
                 "Observação da Mensagem": "3", "Caminho da Imagem": "b.jpg"},
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)
        assert len(resultado) == 2  # NÃO vira 1 linha só
        assert set(resultado["Quantidade Total"]) == {"1", "3"}

    def test_codigo_valido_e_codigo_ausente_do_mesmo_produto_nao_se_misturam(self):
        df = pd.DataFrame(
            [
                {"Produto": "ABSOLUTO", "Código de Barras": "7897274416391",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "a.jpg"},
                {"Produto": "ABSOLUTO", "Código de Barras": "N/A",
                 "Observação da Mensagem": "1", "Caminho da Imagem": "b.jpg"},
            ]
        )
        resultado, _ = unificar_itens_uso_interno(df)
        assert len(resultado) == 2
