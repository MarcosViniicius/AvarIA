/* upload.js - Upload: selecao/validacao de arquivos, envio, progresso.
   Extraido de upload.html (era <script> inline: sem cache,
   bloqueava o parse). Carregado com defer + static_v. */
  document.addEventListener("DOMContentLoaded", function () {
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    const selectFilesBtn = document.getElementById("selectFilesBtn");
    const fileList = document.getElementById("fileList");
    const fileListContainer = document.getElementById("fileListContainer");
    const clearFilesBtn = document.getElementById("clearFilesBtn");
    const uploadBtn = document.getElementById("uploadBtn");
    const alertContainer = document.getElementById("alertContainer");
    const refreshStatusBtn = document.getElementById("refreshStatusBtn");
    const processarAgoraBtn = document.getElementById("processarAgoraBtn");
    const forcarReprocessamentoCheck = document.getElementById("forcarReprocessamentoCheck");
    const modoExtracaoUpload = document.getElementById("modoExtracaoUpload");

    let selectedFiles = [];
    let modoAlteradoPeloUsuario = false;

    // Nomes de arquivo são dados do usuário: nunca interpolar em innerHTML
    // sem escape (um nome como <img onerror=...> executaria na listagem).
    function escapeHtml(texto) {
      return String(texto).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
      }[c]));
    }

    // Carregar status inicial
    atualizarStatus();
    fetch("/api/configuracoes")
      .then((response) => response.json())
      .then((config) => {
        const modoSalvo = config.processamento?.modo_extracao;
        // Não sobrescrever uma escolha já feita pelo usuário enquanto a
        // resposta da configuração chegava (corrida com o fetch).
        if (modoSalvo && modoExtracaoUpload && !modoAlteradoPeloUsuario)
          modoExtracaoUpload.value = modoSalvo;
      })
      .catch(() => {});

    if (modoExtracaoUpload) {
      modoExtracaoUpload.addEventListener("change", () => {
        modoAlteradoPeloUsuario = true;
      });
    }

    // Event listeners
    selectFilesBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", handleFileSelect);
    clearFilesBtn.addEventListener("click", clearFiles);
    uploadBtn.addEventListener("click", uploadFiles);
    refreshStatusBtn.addEventListener("click", atualizarStatus);
    processarAgoraBtn.addEventListener("click", iniciarProcessamento);

    function iniciarProcessamento() {
      processarAgoraBtn.disabled = true;
      processarAgoraBtn.innerHTML =
        '<i class="bi bi-arrow-clockwise spin me-1"></i>Iniciando...';

      fetch("/processar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          forcar_reprocessamento: forcarReprocessamentoCheck.checked,
          modo_extracao: modoExtracaoUpload ? modoExtracaoUpload.value : undefined,
        }),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            showAlert("success", data.message);
            // monitorarProgresso() é global (static/js/main.js) e abre o
            // mesmo modal de progresso usado no Dashboard.
            monitorarProgresso();
          } else {
            showAlert("danger", data.message);
            processarAgoraBtn.disabled = false;
            processarAgoraBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Processar Agora';
          }
        })
        .catch((error) => {
          showAlert("danger", "Erro ao iniciar processamento: " + error);
          processarAgoraBtn.disabled = false;
          processarAgoraBtn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Processar Agora';
        });
    }

    // Drag and drop
    dropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");

      const files = Array.from(e.dataTransfer.files);
      handleFiles(files);
    });

    function handleFileSelect(e) {
      const files = Array.from(e.target.files);
      handleFiles(files);
    }

    function handleFiles(files) {
      const validFiles = files.filter((file) => {
        if (file.size > 50 * 1024 * 1024) {
          showAlert("warning", `${file.name}: o limite é 50 MB por arquivo.`);
          return false;
        }
        const validTypes = [
          "image/jpeg",
          "image/jpg", 
          "image/png",
          "text/plain",
          "application/zip",
          "application/x-zip-compressed",
          "application/x-rar-compressed",
          "application/x-7z-compressed",
          "application/x-tar",
          "application/gzip",
          "application/x-gzip",
          "application/x-bzip2"
        ];
        const validExtensions = [
          ".jpg", ".jpeg", ".png", ".txt",
          ".zip", ".rar", ".7z", ".tar", 
          ".tar.gz", ".tgz", ".tar.bz2", 
          ".gz", ".bz2"
        ];
        
        const fileName = file.name.toLowerCase();
        const extension = fileName.substring(fileName.lastIndexOf("."));
        
        // Verificar extensões compostas
        const hasValidExtension = validExtensions.some(ext => {
          if (ext.includes('.')) {
            return fileName.endsWith(ext);
          }
          return extension === ext;
        });

        return (
          validTypes.includes(file.type) || hasValidExtension
        );
      });

      if (validFiles.length !== files.length) {
        showAlert(
          "warning",
          `${
            files.length - validFiles.length
          } arquivo(s) ignorado(s) por ter formato inválido.`
        );
      }

      selectedFiles = [...selectedFiles, ...validFiles];
      updateFileList();
    }

    function updateFileList() {
      if (selectedFiles.length === 0) {
        fileList.classList.add("d-none");
        return;
      }

      fileList.classList.remove("d-none");
      fileListContainer.innerHTML = "";

      selectedFiles.forEach((file, index) => {
        const fileItem = document.createElement("div");
        fileItem.className =
          "file-item d-flex justify-content-between align-items-center p-3 border rounded mb-2";

        const fileIcon = getFileIcon(file.type, file.name);
        const fileSize = formatFileSize(file.size);
        const nomeSeguro = escapeHtml(file.name);

        fileItem.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="${fileIcon} me-3"></i>
                    <div>
                        <div class="fw-medium">${nomeSeguro}</div>
                        <small class="text-muted">${fileSize}</small>
                    </div>
                </div>
                <button type="button" class="btn btn-outline-danger btn-sm" onclick="removeFile(${index})">
                    <i class="bi bi-trash"></i>
                </button>
            `;

        fileListContainer.appendChild(fileItem);
      });
    }

    function getFileIcon(type, name) {
      const fileName = name.toLowerCase();
      const extension = fileName.substring(fileName.lastIndexOf("."));

      if (
        type.startsWith("image/") ||
        [".jpg", ".jpeg", ".png"].includes(extension)
      ) {
        return "bi bi-image text-primary";
      } else if (type === "text/plain" || extension === ".txt") {
        return "bi bi-file-text text-info";
      } else if (
        fileName.endsWith(".zip") ||
        fileName.endsWith(".rar") ||
        fileName.endsWith(".7z") ||
        fileName.endsWith(".tar") ||
        fileName.endsWith(".tar.gz") ||
        fileName.endsWith(".tgz") ||
        fileName.endsWith(".tar.bz2") ||
        fileName.endsWith(".gz") ||
        fileName.endsWith(".bz2") ||
        type.includes("zip") ||
        type.includes("rar") ||
        type.includes("7z") ||
        type.includes("tar") ||
        type.includes("gzip") ||
        type.includes("bzip")
      ) {
        return "bi bi-file-zip text-warning";
      }
      return "bi bi-file text-secondary";
    }

    function formatFileSize(bytes) {
      if (bytes === 0) return "0 Bytes";
      const k = 1024;
      const sizes = ["Bytes", "KB", "MB", "GB"];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

    window.removeFile = function (index) {
      selectedFiles.splice(index, 1);
      updateFileList();
    };

    function clearFiles() {
      selectedFiles = [];
      fileInput.value = "";
      updateFileList();
    }

    function uploadFiles() {
      if (selectedFiles.length === 0) {
        showAlert("warning", "Selecione pelo menos um arquivo para enviar.");
        return;
      }

      const tamanhoLote = selectedFiles.reduce((total, file) => total + file.size, 0);
      if (tamanhoLote > 200 * 1024 * 1024) {
        showAlert("warning", "O lote excede o limite total de 200 MB. Remova arquivos ou envie em mais de um lote.");
        return;
      }

      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });
      if (forcarReprocessamentoCheck.checked) {
        formData.append("forcar_reprocessamento", "true");
      }

      // Mostrar progresso
      document.getElementById("dropZoneContent").classList.add("d-none");
      document.getElementById("uploadProgress").classList.remove("d-none");
      uploadBtn.disabled = true;

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/upload_files");
      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.min(99, Math.round((event.loaded / event.total) * 100));
        document.getElementById("uploadProgressBar").style.width = `${percent}%`;
        document.getElementById("uploadStatus").textContent =
          `Enviando ${formatFileSize(event.loaded)} de ${formatFileSize(event.total)} (${percent}%)`;
      });
      xhr.addEventListener("load", () => {
        let data;
        try {
          data = JSON.parse(xhr.responseText);
        } catch (_) {
          data = null;
        }
        document.getElementById("uploadProgressBar").style.width = "100%";
        document.getElementById("uploadStatus").textContent = "Servidor recebeu o envio; verificando arquivos...";
        finishUpload();

        if (xhr.status === 413) {
          showAlert("danger", "O envio ultrapassou o limite total de 200 MB. Divida os arquivos em lotes menores.");
        } else if (!data) {
          showAlert("danger", `O servidor respondeu com erro HTTP ${xhr.status}. Os arquivos foram mantidos na lista para tentar novamente.`);
        } else if (data.success) {
          showAlert(
            data.ignorados_duplicados?.length ? "warning" : "success",
            data.message
          );
          clearFiles();
          atualizarStatus();
        } else {
          showAlert("danger", data.message || "Nenhum arquivo foi enviado.");
        }
      });
      xhr.addEventListener("error", () => {
        finishUpload();
        showAlert("danger", "Falha de conexão durante o envio. A lista foi preservada para tentar novamente.");
      });
      xhr.addEventListener("abort", () => {
        finishUpload();
        showAlert("warning", "Envio cancelado. A lista foi preservada.");
      });
      xhr.send(formData);

      function finishUpload() {
        document.getElementById("dropZoneContent").classList.remove("d-none");
        document.getElementById("uploadProgress").classList.add("d-none");
        uploadBtn.disabled = false;
      }
    }

    function showAlert(type, message) {
      const alertDiv = document.createElement("div");
      alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
      alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

      alertContainer.innerHTML = "";
      alertContainer.appendChild(alertDiv);

      // Auto-remove após 5 segundos
      setTimeout(() => {
        if (alertDiv.parentNode) {
          alertDiv.remove();
        }
      }, 5000);
    }

    function atualizarStatus() {
      fetch("/api/stats")
        .then((response) => response.json())
        .then((stats) => {
          document.getElementById("currentTotal").textContent =
            stats.imagens_total;
          document.getElementById("currentProcessed").textContent =
            stats.imagens_processadas;
          document.getElementById("currentPending").textContent =
            stats.imagens_pendentes;

          processarAgoraBtn.classList.toggle("d-none", !(stats.imagens_pendentes > 0));
        })
        .catch((error) => {
          console.error("Erro ao atualizar status:", error);
        });
    }
  });
