import hashlib
import os
import zipfile
import tarfile
import gzip
import shutil
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
# py7zr é opcional - se não estiver disponível, arquivos .7z não serão suportados
try:
    import py7zr
    PY7ZR_DISPONIVEL = True
except ImportError:
    PY7ZR_DISPONIVEL = False
    
try:
    import rarfile
    RARFILE_DISPONIVEL = True
except ImportError:
    RARFILE_DISPONIVEL = False

import tempfile

# Configurar logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _hash(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _hash_arquivo(caminho) -> str:
    with open(caminho, "rb") as f:
        return _hash(f.read())


def nome_para_gravar(
    pastas,
    nome: str,
    dados: bytes,
    forcar: bool = False,
    nomes_processados=None,
) -> Optional[str]:
    """Decide o nome com que gravar `dados` (conteúdo do arquivo) em
    `pastas[0]` (a primeira pasta é sempre onde o arquivo será gravado; as
    demais entram só como pastas adicionais a checar por colisão de nome).

    `pastas` aceita uma única pasta ou uma lista delas - checar mais de uma
    pasta importa quando existe uma pasta de arquivamento separada da pasta
    de pendentes: sem checar as duas, reenviar uma imagem DIFERENTE com o
    mesmo nome de uma já arquivada seria salvo sem sufixo e, como esse nome
    já está no log de processados, seria ignorado como "já processado" sem
    nunca ser analisado.

    `nomes_processados`: conjunto (ou iterável) de nomes que JÁ constam no
    log de processados (log_mestre.txt). A imagem arquivada é RECOMPRIMIDA
    ao ser movida para imagens_processadas/ (ver image_archive.py), então o
    hash do arquivo guardado difere do original: comparar conteúdo para
    decidir "é o mesmo arquivo?" falha justamente no caso mais comum -
    reenviar o mesmo lote depois de processado. Como o pipeline identifica
    "já processado" pelo NOME (não pelo conteúdo), um nome nesta lista nunca
    deve ganhar sufixo: o sufixo criaria um nome inédito (`IMG-x_2.jpg`) que
    entra na fila e é analisado (e cobrado) de novo. Sem `forcar`, devolve
    None (é o mesmo arquivo já processado); com `forcar=True` o sufixo é
    aplicado de propósito, porque o usuário pediu para reprocessar.

    - Sem colisão de nome em nenhuma pasta: devolve `nome` como está.
    - Colisão, mas o CONTEÚDO já existente é byte-a-byte igual a `dados`
      (em qualquer uma das pastas): devolve None — é literalmente o mesmo
      arquivo, gravar de novo só duplicaria a imagem e, junto, a linha dela
      no relatório. É o caso de reenviar o mesmo lote pra testar de novo (o
      pipeline decide "já processado" pelo nome, então sem essa checagem
      cada reenvio virava um arquivo novo com sufixo e era processado - e
      contado - de novo).
    - Colisão com conteúdo DIFERENTE: devolve um nome com sufixo numérico,
      preservando os arquivos sem sobrescrever nada.

    `forcar=True` desativa a checagem de "mesmo conteúdo" (e a de
    `nomes_processados`) - toda colisão de nome ganha sufixo, mesmo que o
    conteúdo já exista. Usado pelo checkbox "Forçar reprocessamento" da tela
    de Upload, para quando o usuário quer reanalisar de propósito um lote já
    enviado antes.

    Usado tanto no upload direto (routes/upload.py) quanto na extração de
    arquivos compactados abaixo.
    """
    lista_pastas = [Path(pastas)] if isinstance(pastas, (str, Path)) else [Path(p) for p in pastas]
    processados = set() if nomes_processados is None else set(nomes_processados)

    # Nome já processado (está no log): o arquivo em disco pode diferir byte a
    # byte do original por causa da recompressão do arquivamento, mas é o
    # MESMO arquivo aos olhos do pipeline. Sem forcar, não grava nada.
    if not forcar and nome in processados:
        return None

    base, extensao = os.path.splitext(nome)
    candidato_nome = nome
    contador = 2
    while True:
        colide_com_conteudo_diferente = False
        for pasta in lista_pastas:
            caminho = pasta / candidato_nome
            if not caminho.exists():
                continue
            if not forcar and _hash_arquivo(caminho) == _hash(dados):
                return None
            colide_com_conteudo_diferente = True

        if not colide_com_conteudo_diferente:
            return candidato_nome

        candidato_nome = f"{base}_{contador}{extensao}"
        contador += 1


def _extrair_membro(dados_origem, caminho_relativo: str, pasta_destino, pasta_arquivo=None, forcar: bool = False, nomes_processados=None) -> None:
    """Grava um membro de arquivo compactado em `pasta_destino`, usando
    `nome_para_gravar` para nunca sobrescrever um arquivo diferente, e nunca
    duplicar um arquivo idêntico. `dados_origem` é um file-like aberto para
    leitura binária (ex.: retorno de `ZipFile.open()`/`TarFile.extractfile()`).

    `pasta_arquivo`, se informado, também é verificada na decisão do nome -
    é a pasta onde imagens processadas com sucesso são arquivadas (ver
    services/image_archive.py); sem checá-la aqui, extrair de novo um arquivo
    compactado com um nome que já foi processado e arquivado poderia salvar
    uma imagem diferente sem sufixo e ela ser ignorada como "já processada".

    `nomes_processados`, se informado, é repassado a `nome_para_gravar`: os
    nomes ali já foram analisados e não devem gerar sufixo (ver docstring de
    `nome_para_gravar`).
    """
    nome_membro = str(caminho_relativo)
    caminho_posix = PurePosixPath(nome_membro.replace("\\", "/"))
    caminho_windows = PureWindowsPath(nome_membro)
    if (
        caminho_posix.is_absolute()
        or caminho_windows.is_absolute()
        or caminho_windows.drive
        or ".." in caminho_posix.parts
        or not caminho_posix.parts
    ):
        raise ValueError(f"Caminho inseguro dentro do arquivo compactado: {nome_membro}")

    caminho_relativo = Path(*[parte for parte in caminho_posix.parts if parte not in ("", ".")])
    raiz_destino = Path(pasta_destino).resolve()
    pasta_membro = (raiz_destino / caminho_relativo.parent).resolve()
    destino_membro = (pasta_membro / caminho_relativo.name).resolve()
    try:
        pasta_membro.relative_to(raiz_destino)
        destino_membro.relative_to(raiz_destino)
    except ValueError as e:
        raise ValueError(f"Caminho escapa da pasta de destino: {nome_membro}") from e

    pasta_membro.mkdir(parents=True, exist_ok=True)
    with dados_origem as entrada:
        dados = entrada.read()
    pastas_colisao = [pasta_membro, pasta_arquivo] if pasta_arquivo else [pasta_membro]
    nome_final = nome_para_gravar(
        pastas_colisao, caminho_relativo.name, dados,
        forcar=forcar, nomes_processados=nomes_processados,
    )
    if nome_final is None:
        return  # conteúdo idêntico já extraído antes - não duplicar
    with open(pasta_membro / nome_final, "wb") as saida:
        saida.write(dados)


class ExtratorArquivos:
    def __init__(self, pasta_origem="imagens_para_analisar", pasta_destino=None, pasta_arquivo=None, forcar=False, nomes_processados=None):
        """
        Inicializa o extrator de arquivos.

        Args:
            pasta_origem (str): Pasta onde estão os arquivos comprimidos
            pasta_destino (str): Pasta onde extrair os arquivos (padrão: mesma pasta)
            pasta_arquivo (str): Pasta de imagens já processadas/arquivadas,
                verificada também na hora de decidir colisão de nome (ver
                `_extrair_membro`). Opcional - sem ela, só a pasta de destino
                é considerada (comportamento anterior, usado nos testes).
            forcar (bool): Se True, ignora a checagem de conteúdo idêntico -
                toda colisão de nome ganha sufixo numérico (ver
                `nome_para_gravar`). Usado para reprocessar de propósito um
                lote já enviado antes.
            nomes_processados: conjunto de nomes já analisados (log_mestre.txt).
                Um membro com um desses nomes não ganha sufixo - sem isso,
                reenviar um ZIP já processado criaria `IMG-x_2.jpg` e o item
                seria analisado (e cobrado) de novo. Opcional.
        """
        self.pasta_origem = Path(pasta_origem)
        self.pasta_destino = Path(pasta_destino) if pasta_destino else self.pasta_origem
        self.pasta_arquivo = Path(pasta_arquivo) if pasta_arquivo else None
        self.forcar = forcar
        self.nomes_processados = set(nomes_processados) if nomes_processados else set()

        # Formatos suportados e suas respectivas funções de extração
        self.formatos_suportados = {
            ".zip": self._extrair_zip,
            ".tar": self._extrair_tar,
            ".tar.gz": self._extrair_tar_gz,
            ".tgz": self._extrair_tar_gz,
            ".tar.bz2": self._extrair_tar_bz2,
            ".gz": self._extrair_gz,
            ".bz2": self._extrair_bz2,
        }
        
        # Adicionar suporte a RAR se disponível
        if RARFILE_DISPONIVEL:
            self.formatos_suportados[".rar"] = self._extrair_rar
        
        # Adicionar suporte a 7Z se disponível
        if PY7ZR_DISPONIVEL:
            self.formatos_suportados[".7z"] = self._extrair_7z

    def _verificar_dependencias(self):
        """Verifica se as dependências necessárias estão instaladas."""
        dependencias_info = []
        
        if not PY7ZR_DISPONIVEL:
            dependencias_info.append("py7zr (para arquivos .7z)")
        
        if not RARFILE_DISPONIVEL:
            dependencias_info.append("rarfile (para arquivos .rar)")

        if dependencias_info:
            logger.warning(f"Dependências opcionais não instaladas: {', '.join(dependencias_info)}")
            logger.info("Instale com: pip install py7zr rarfile")
            logger.info("Formatos suportados atualmente: " + ", ".join(self.formatos_suportados.keys()))

    def _extrair_zip(self, arquivo, pasta_destino):
        """Extrai arquivos ZIP, membro a membro (nunca sobrescreve - ver `nome_sem_colisao`)."""
        try:
            with zipfile.ZipFile(arquivo, "r") as zip_ref:
                for info in zip_ref.infolist():
                    if info.is_dir():
                        continue
                    _extrair_membro(zip_ref.open(info), info.filename, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair ZIP {arquivo}: {e}")
            return False

    def _extrair_rar(self, arquivo, pasta_destino):
        """Extrai arquivos RAR, membro a membro (nunca sobrescreve - ver `nome_sem_colisao`)."""
        if not RARFILE_DISPONIVEL:
            logger.error(f"rarfile não está instalado. Não é possível extrair {arquivo}")
            return False
        try:
            with rarfile.RarFile(arquivo, "r") as rar_ref:
                for info in rar_ref.infolist():
                    if info.is_dir():
                        continue
                    _extrair_membro(rar_ref.open(info), info.filename, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair RAR {arquivo}: {e}")
            return False

    def _extrair_7z(self, arquivo, pasta_destino):
        """Extrai arquivos 7Z, membro a membro (nunca sobrescreve - ver `nome_sem_colisao`)."""
        if not PY7ZR_DISPONIVEL:
            logger.error(f"py7zr não está instalado. Não é possível extrair {arquivo}")
            return False
        try:
            with py7zr.SevenZipFile(arquivo, mode="r") as z:
                for nome_membro, stream in z.readall().items():
                    _extrair_membro(stream, nome_membro, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair 7Z {arquivo}: {e}")
            return False

    def _extrair_tar(self, arquivo, pasta_destino):
        """Extrai arquivos TAR, membro a membro (nunca sobrescreve - ver `nome_sem_colisao`)."""
        return self._extrair_tar_modo(arquivo, pasta_destino, "r")

    def _extrair_tar_gz(self, arquivo, pasta_destino):
        """Extrai arquivos TAR.GZ ou TGZ, membro a membro."""
        return self._extrair_tar_modo(arquivo, pasta_destino, "r:gz")

    def _extrair_tar_bz2(self, arquivo, pasta_destino):
        """Extrai arquivos TAR.BZ2, membro a membro."""
        return self._extrair_tar_modo(arquivo, pasta_destino, "r:bz2")

    def _extrair_tar_modo(self, arquivo, pasta_destino, modo):
        try:
            with tarfile.open(arquivo, modo) as tar_ref:
                for membro in tar_ref.getmembers():
                    if not membro.isfile():
                        continue
                    origem = tar_ref.extractfile(membro)
                    if origem is None:
                        continue
                    _extrair_membro(origem, membro.name, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair TAR ({modo}) {arquivo}: {e}")
            return False

    def _extrair_gz(self, arquivo, pasta_destino):
        """Extrai arquivos GZ (apenas arquivos únicos), sem sobrescrever."""
        try:
            nome_arquivo = Path(arquivo).stem
            with gzip.open(arquivo, "rb") as f_in:
                _extrair_membro(f_in, nome_arquivo, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
            return True
        except Exception as e:
            logger.error(f"Erro ao extrair GZ {arquivo}: {e}")
            return False

    def _extrair_bz2(self, arquivo, pasta_destino):
        """Extrai arquivos BZ2 (apenas arquivos únicos), sem sobrescrever."""
        try:
            import bz2

            nome_arquivo = Path(arquivo).stem
            with bz2.open(arquivo, "rb") as f_in:
                _extrair_membro(f_in, nome_arquivo, pasta_destino, self.pasta_arquivo, forcar=self.forcar, nomes_processados=self.nomes_processados)
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

        return resultados
