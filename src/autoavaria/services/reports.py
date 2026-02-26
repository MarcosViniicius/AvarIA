"""
GERENCIADOR DE ERROS E REANÁLISE
Módulo isolado para rastreamento e reanálise de itens com erro
Criado em: 24/01/2026
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
import pandas as pd


class GerenciadorErros:
    """Gerencia o rastreamento e reanálise de erros do sistema."""

    def __init__(self, arquivo_excel: str):
        """
        Inicializa o gerenciador de erros.
        
        Args:
            arquivo_excel: Caminho para o arquivo Excel do relatório
        """
        self.arquivo_excel = arquivo_excel
        self.cache_erros = None
        self.cache_timestamp = None

    def obter_erros_pendentes(self) -> List[Dict[str, Any]]:
        """
        Obtém lista de itens com erro do relatório Excel.
        
        Returns:
            Lista de dicionários contendo os erros pendentes
        """
        try:
            if not os.path.exists(self.arquivo_excel):
                return []

            # Carregar apenas a aba de erros
            df_erros = pd.read_excel(
                self.arquivo_excel, 
                sheet_name="Erros de Análise", 
                engine="openpyxl"
            )
            
            if df_erros.empty:
                return []

            # Converter para lista de dicionários
            erros = df_erros.to_dict("records")
            
            # Adicionar flag de reanálise
            for erro in erros:
                erro["status_reanalise"] = "pendente"
                erro["tentativas_reanalise"] = 0
            
            return erros

        except Exception as e:
            print(f"⚠️ Erro ao obter erros pendentes: {e}")
            return []

    def contar_erros_pendentes(self) -> int:
        """
        Conta quantos erros existem no relatório.
        
        Returns:
            Número de erros pendentes
        """
        erros = self.obter_erros_pendentes()
        return len(erros)

    def obter_arquivos_com_erro(self) -> List[str]:
        """
        Obtém lista de nomes de arquivos que tiveram erro.
        
        Returns:
            Lista de nomes de arquivos
        """
        erros = self.obter_erros_pendentes()
        return [erro.get("Arquivo", "") for erro in erros if erro.get("Arquivo")]

    def marcar_erro_como_reprocessado(self, nome_arquivo: str, sucesso: bool = True):
        """
        Marca um erro como reprocessado no Excel.
        
        Args:
            nome_arquivo: Nome do arquivo que foi reprocessado
            sucesso: Se o reprocessamento foi bem-sucedido
        """
        try:
            if not os.path.exists(self.arquivo_excel):
                return

            # Carregar todas as abas
            sheets = pd.read_excel(self.arquivo_excel, sheet_name=None, engine="openpyxl")
            
            if "Erros de Análise" not in sheets:
                return
            
            df_erros = sheets["Erros de Análise"]
            
            if sucesso:
                # Remove o erro da lista se foi reprocessado com sucesso
                df_erros = df_erros[df_erros["Arquivo"] != nome_arquivo]
            else:
                # Atualiza o detalhes do erro com informação de tentativa de reanálise
                mask = df_erros["Arquivo"] == nome_arquivo
                if mask.any():
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    df_erros.loc[mask, "Detalhes do Erro"] = (
                        df_erros.loc[mask, "Detalhes do Erro"] + 
                        f" [Reanalise em {timestamp} - Falhou novamente]"
                    )
            
            # Salvar de volta
            sheets["Erros de Análise"] = df_erros
            
            with pd.ExcelWriter(self.arquivo_excel, engine="openpyxl") as writer:
                for sheet_name, df in sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            print(f"✅ Erro de '{nome_arquivo}' atualizado no relatório")

        except Exception as e:
            print(f"⚠️ Erro ao marcar erro como reprocessado: {e}")

    def adicionar_ao_log_reanalise(
        self, 
        nome_arquivo: str, 
        status: str, 
        detalhes: Optional[str] = None
    ):
        """
        Adiciona entrada no log de reanálises.
        
        Args:
            nome_arquivo: Nome do arquivo reanalisado
            status: Status da reanálise (sucesso/falha)
            detalhes: Detalhes adicionais sobre a reanálise
        """
        log_file = os.path.join(
            os.path.dirname(self.arquivo_excel), 
            "..", 
            "logs", 
            "log_reanalise.txt"
        )
        
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            linha_log = f"{timestamp} | {nome_arquivo} | {status}"
            
            if detalhes:
                linha_log += f" | {detalhes}"
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(linha_log + "\n")
                
        except Exception as e:
            print(f"⚠️ Erro ao adicionar ao log de reanálise: {e}")

    def gerar_resumo_erros(self) -> Dict[str, Any]:
        """
        Gera um resumo dos erros pendentes.
        
        Returns:
            Dicionário com estatísticas de erros
        """
        erros = self.obter_erros_pendentes()
        
        if not erros:
            return {
                "total": 0,
                "tipos": {},
                "arquivos": []
            }
        
        # Analisar tipos de erro
        tipos_erro = {}
        for erro in erros:
            detalhes = erro.get("Detalhes do Erro", "Erro desconhecido")
            
            # Categorizar erros
            if "JSON" in detalhes or "json" in detalhes:
                tipo = "Erro de parsing JSON"
            elif "API" in detalhes or "timeout" in detalhes.lower():
                tipo = "Erro de API"
            elif "Falha" in detalhes:
                tipo = "Falha na análise"
            else:
                tipo = "Outro"
            
            tipos_erro[tipo] = tipos_erro.get(tipo, 0) + 1
        
        return {
            "total": len(erros),
            "tipos": tipos_erro,
            "arquivos": [erro.get("Arquivo") for erro in erros]
        }

    def limpar_cache(self):
        """Limpa o cache de erros."""
        self.cache_erros = None
        self.cache_timestamp = None


# Função auxiliar para uso direto
def criar_gerenciador(arquivo_excel: str = None) -> GerenciadorErros:
    """
    Cria uma instância do gerenciador de erros.
    
    Args:
        arquivo_excel: Caminho opcional para o arquivo Excel. 
                      Se não fornecido, usa o padrão.
    
    Returns:
        Instância do GerenciadorErros
    """
    if arquivo_excel is None:
        arquivo_excel = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resultados",
            "Relatorio_Mestre_Produtos.xlsx"
        )
    
    return GerenciadorErros(arquivo_excel)


if __name__ == "__main__":
    # Teste básico
    print("🧪 Testando Gerenciador de Erros...")
    
    gerenciador = criar_gerenciador()
    resumo = gerenciador.gerar_resumo_erros()
    
    print(f"\n📊 Resumo de Erros:")
    print(f"   Total: {resumo['total']}")
    print(f"   Tipos: {resumo['tipos']}")
    print(f"   Arquivos: {resumo['arquivos'][:5]}...")  # Primeiros 5
