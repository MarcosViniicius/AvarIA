import os
import zipfile
import tarfile
import gzip
import shutil
import logging
from pathlib import Path
import py7zr
import rarfile
import tempfile

# Configurar logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ExtratorArquivos:
    def __init__(self, pasta_origem="imagens_para_analisar", pasta_destino=None):
        """
        Inicializa o extrator de arquivos.

        Args:
            pasta_origem (str): Pasta onde estão os arquivos comprimidos
            pasta_destino (str): Pasta onde extrair os arquivos (padrão: mesma pasta)
        """
        self.pasta_origem = Path(pasta_origem)
        self.pasta_destino = Path(pasta_destino) if pasta_destino else self.pasta_origem

        # Formatos suportados e suas respectivas funções de extração
        self.formatos_suportados = {
            ".zip": self._extrair_zip,
            ".rar": self._extrair_rar,
            ".7z": self._extrair_7z,
            ".tar": self._extrair_tar,
            ".tar.gz": self._extrair_tar_gz,
            ".tgz": self._extrair_tar_gz,
            ".tar.bz2": self._extrair_tar_bz2,
            ".gz": self._extrair_gz,
            ".bz2": self._extrair_bz2,
        }

    def _verificar_dependencias(self):
        """Verifica se as dependências necessárias estão instaladas."""
        dependencias = {"py7zr": "py7zr", "rarfile": "rarfile"}

        faltando = []
        for nome, pacote in dependencias.items():
            try:
                __import__(nome)
            except ImportError:
                faltando.append(pacote)

        if faltando:
            logger.warning(f"Dependências faltando: {', '.join(faltando)}")
            logger.info("Instale com: pip install " + " ".join(faltando))

    def _extrair_zip(self, arquivo, pasta_destino):
        """Extrai arquivos ZIP."""
        try:
            with zipfile.ZipFile(arquivo, "r") as zip_ref:
                zip_ref.extractall(pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair ZIP {arquivo}: {e}")
            return False

    def _extrair_rar(self, arquivo, pasta_destino):
        """Extrai arquivos RAR."""
        try:
            with rarfile.RarFile(arquivo, "r") as rar_ref:
                rar_ref.extractall(pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair RAR {arquivo}: {e}")
            return False

    def _extrair_7z(self, arquivo, pasta_destino):
        """Extrai arquivos 7Z."""
        try:
            with py7zr.SevenZipFile(arquivo, mode="r") as z:
                z.extractall(path=pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair 7Z {arquivo}: {e}")
            return False

    def _extrair_tar(self, arquivo, pasta_destino):
        """Extrai arquivos TAR."""
        try:
            with tarfile.open(arquivo, "r") as tar_ref:
                tar_ref.extractall(pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair TAR {arquivo}: {e}")
            return False

    def _extrair_tar_gz(self, arquivo, pasta_destino):
        """Extrai arquivos TAR.GZ ou TGZ."""
        try:
            with tarfile.open(arquivo, "r:gz") as tar_ref:
                tar_ref.extractall(pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair TAR.GZ {arquivo}: {e}")
            return False

    def _extrair_tar_bz2(self, arquivo, pasta_destino):
        """Extrai arquivos TAR.BZ2."""
        try:
            with tarfile.open(arquivo, "r:bz2") as tar_ref:
                tar_ref.extractall(pasta_destino)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair TAR.BZ2 {arquivo}: {e}")
            return False

    def _extrair_gz(self, arquivo, pasta_destino):
        """Extrai arquivos GZ (apenas arquivos únicos)."""
        try:
            nome_arquivo = Path(arquivo).stem
            caminho_destino = pasta_destino / nome_arquivo

            with gzip.open(arquivo, "rb") as f_in:
                with open(caminho_destino, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair GZ {arquivo}: {e}")
            return False

    def _extrair_bz2(self, arquivo, pasta_destino):
        """Extrai arquivos BZ2 (apenas arquivos únicos)."""
        try:
            import bz2

            nome_arquivo = Path(arquivo).stem
            caminho_destino = pasta_destino / nome_arquivo

            with bz2.open(arquivo, "rb") as f_in:
                with open(caminho_destino, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair BZ2 {arquivo}: {e}")
            return False

    def _obter_extensao(self, arquivo):
        """Obtém a extensão do arquivo, considerando extensões duplas."""
        nome = arquivo.name.lower()

        # Verificar extensões duplas primeiro
        extensoes_duplas = [".tar.gz", ".tar.bz2"]
        for ext in extensoes_duplas:
            if nome.endswith(ext):
                return ext

        # Verificar extensões simples
        return arquivo.suffix.lower()

    def excluir_arquivo_compactado(self, arquivo):
        """Exclui o arquivo compactado após a extração."""
        try:
            os.remove(arquivo)
            logger.info(f"Arquivo compactado {arquivo} excluído com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao excluir o arquivo compactado {arquivo}: {e}")

    def _criar_pasta_extracao(self, arquivo):
        """Cria uma pasta específica para extrair o arquivo."""
        nome_pasta = arquivo.stem
        pasta_extracao = self.pasta_destino / nome_pasta
        pasta_extracao.mkdir(exist_ok=True)
        return pasta_extracao

    def listar_arquivos_comprimidos(self):
        """Lista todos os arquivos comprimidos na pasta origem."""
        if not self.pasta_origem.exists():
            logger.error(f"Pasta origem não existe: {self.pasta_origem}")
            return []

        arquivos_comprimidos = []

        for arquivo in self.pasta_origem.iterdir():
            if arquivo.is_file():
                extensao = self._obter_extensao(arquivo)
                if extensao in self.formatos_suportados:
                    arquivos_comprimidos.append(arquivo)

        return arquivos_comprimidos

    def extrair_arquivo(self, arquivo, criar_subpasta=True, remover_original=False):
        """
        Extrai um arquivo específico.

        Args:
            arquivo (Path): Caminho para o arquivo
            criar_subpasta (bool): Se deve criar subpasta para cada arquivo
            remover_original (bool): Se deve remover o arquivo original após extração
        """
        if not arquivo.exists():
            logger.error(f"Arquivo não existe: {arquivo}")
            return False

        extensao = self._obter_extensao(arquivo)

        if extensao not in self.formatos_suportados:
            logger.warning(f"Formato não suportado: {extensao}")
            return False

        # Determinar pasta de destino
        if criar_subpasta:
            pasta_destino = self._criar_pasta_extracao(arquivo)
        else:
            pasta_destino = self.pasta_destino

        logger.info(f"Extraindo {arquivo.name} para {pasta_destino}")

        # Extrair arquivo
        funcao_extracao = self.formatos_suportados[extensao]
        sucesso = funcao_extracao(arquivo, pasta_destino)

        if sucesso:
            logger.info(f"Arquivo {arquivo.name} extraído com sucesso!")

            if remover_original:
                try:
                    arquivo.unlink()
                    logger.info(f"Arquivo original removido: {arquivo.name}")
                except Exception as e:
                    logger.error(
                        f"Erro ao remover arquivo original {arquivo.name}: {e}"
                    )

        return sucesso

    def extrair_todos(self, criar_subpastas=True, remover_originais=False):
        """
        Extrai todos os arquivos comprimidos encontrados.

        Args:
            criar_subpastas (bool): Se deve criar subpasta para cada arquivo
            remover_originais (bool): Se deve remover arquivos originais após extração
        """
        self._verificar_dependencias()

        arquivos_comprimidos = self.listar_arquivos_comprimidos()

        if not arquivos_comprimidos:
            logger.info("Nenhum arquivo comprimido encontrado na pasta.")
            return {}

        logger.info(f"Encontrados {len(arquivos_comprimidos)} arquivos comprimidos")

        # Garantir que a pasta destino existe
        self.pasta_destino.mkdir(parents=True, exist_ok=True)

        resultados = {}

        for arquivo in arquivos_comprimidos:
            sucesso = self.extrair_arquivo(
                arquivo,
                criar_subpasta=criar_subpastas,
                remover_original=remover_originais,
            )
            resultados[arquivo.name] = sucesso

        # Relatório final
        sucessos = sum(1 for v in resultados.values() if v)
        total = len(resultados)

        logger.info(
            f"Extração concluída: {sucessos}/{total} arquivos extraídos com sucesso"
        )

        self.excluir_arquivo_compactado(arquivo)
        

        return resultados


def main():
    """Função principal para executar o extrator."""
    import argparse

    parser = argparse.ArgumentParser(description="Extrator de arquivos comprimidos")
    parser.add_argument(
        "--origem",
        default="imagens_para_analisar",
        help="Pasta origem com arquivos comprimidos",
    )
    parser.add_argument("--destino", help="Pasta destino (padrão: mesma pasta origem)")
    parser.add_argument(
        "--sem-subpastas",
        action="store_true",
        help="Não criar subpastas para cada arquivo",
    )
    parser.add_argument(
        "--remover-originais",
        action="store_true",
        help="Remover arquivos originais após extração",
    )
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Apenas listar arquivos comprimidos encontrados",
    )

    args = parser.parse_args()

    # Criar extrator
    extrator = ExtratorArquivos(args.origem, args.destino)

    if args.listar:
        # Apenas listar arquivos
        arquivos = extrator.listar_arquivos_comprimidos()
        if arquivos:
            print("Arquivos comprimidos encontrados:")
            for arquivo in arquivos:
                print(f"  - {arquivo.name}")
        else:
            print("Nenhum arquivo comprimido encontrado.")
    else:
        # Extrair arquivos
        extrator.extrair_todos(
            criar_subpastas=not args.sem_subpastas,
            remover_originais=args.remover_originais,
        )


if __name__ == "__main__":
    main()
