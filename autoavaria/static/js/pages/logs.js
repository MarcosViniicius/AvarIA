/* logs.js - Logs: polling, auto-scroll, filtros.
   Extraido de logs.html (era <script> inline: sem cache,
   bloqueava o parse). Carregado com defer + static_v. */
  let autoScroll = true;
  let logCount = 0;
  let updateInterval;
  const logsExibidos = new Set(); // evita reexibir a mesma linha a cada polling

  // Logs carregam nomes de arquivos/produtos do banco: escapar antes de
  // interpolar em innerHTML (um nome com markup executaria na página).
  function escapeHtml(texto) {
    return String(texto).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Elementos
    const logConsole = document.getElementById("logConsole");
    const toggleAutoScrollBtn = document.getElementById("toggleAutoScroll");
    const autoScrollStatus = document.getElementById("autoScrollStatus");
    const clearLogsBtn = document.getElementById("clearLogs");
    const progressBar = document.getElementById("progressBar");
    const progressText = document.getElementById("progressText");
    const statusIcon = document.getElementById("statusIcon");
    const statusText = document.getElementById("statusText");
    const statusTime = document.getElementById("statusTime");
    const logCountEl = document.getElementById("logCount");
    const toggleLogsDetalhadosInput = document.getElementById("toggleLogsDetalhados");

    // Configurar botões
    toggleLogsDetalhadosInput.addEventListener("change", alternarLogsDetalhados);

    toggleAutoScrollBtn.addEventListener("click", function () {
      autoScroll = !autoScroll;
      autoScrollStatus.textContent = autoScroll ? "ON" : "OFF";
      this.className = autoScroll
        ? "btn btn-outline-secondary me-2"
        : "btn btn-outline-warning me-2";
    });

    clearLogsBtn.addEventListener("click", function () {
      logConsole.innerHTML =
        '<div class="text-muted"><i class="bi bi-info-circle me-2"></i>Logs limpos...</div>';
      logCount = 0;
      logsExibidos.clear();
      updateLogCount();
    });

    // Alternar logs detalhados - usa a rota dedicada (não a de configurações
    // gerais, que trafega a chave de API e não é necessária aqui).
    async function alternarLogsDetalhados() {
      const checkbox = document.getElementById("toggleLogsDetalhados");
      const ativo = checkbox.checked;

      try {
        const response = await fetch("/api/configuracoes/logs_detalhados", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ativo }),
        });
        if (!response.ok) {
          throw new Error("Erro ao salvar configuração");
        }

        logConsole.innerHTML = `<div class="text-success"><i class="bi bi-check-circle me-2"></i>${
          ativo ? "✅ Logs detalhados da aplicação ativados" : "📋 Logs simplificados ativados"
        }</div>`;
        logCount = 0;
        updateLogCount();
      } catch (error) {
        console.error("Erro ao alternar logs detalhados:", error);
        checkbox.checked = !ativo; // Reverter checkbox
        logConsole.innerHTML = `<div class="text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Erro ao alternar logs: ${error.message}</div>`;
      }
    }

    // Carregar estado dos logs detalhados
    async function carregarEstadoLogsDetalhados() {
      try {
        const response = await fetch("/api/configuracoes/logs_detalhados");
        const { ativo } = await response.json();
        document.getElementById("toggleLogsDetalhados").checked = !!ativo;
      } catch (error) {
        console.error("Erro ao carregar configuração:", error);
      }
    }

    // Função para atualizar logs
    function updateLogs() {
      fetch("/api/logs")
        .then((response) => response.json())
        .then((data) => {
          updateStatus(data.progresso, data.processamento_ativo);
          updateLogDisplay(data.logs);
        })
        .catch((error) => {
          console.error("Erro ao buscar logs:", error);
          addLogEntry(
            "erro",
            new Date().toLocaleTimeString(),
            "Erro de conexão com servidor"
          );
        });
    }

    // Atualizar status do processamento
    function updateStatus(progresso, ativo) {
      const progress = progresso.progresso || 0;
      const status = progresso.status || "Aguardando";

      // Atualizar barra de progresso
      progressBar.style.width = progress + "%";
      progressBar.setAttribute("aria-valuenow", progress);
      progressText.textContent = progress + "%";

      // Atualizar cor da barra
      progressBar.className = "progress-bar progress-bar-striped";
      if (ativo) {
        progressBar.classList.add("progress-bar-animated");
        if (progress >= 100) {
          progressBar.classList.add("bg-success");
        } else {
          progressBar.classList.add("bg-primary");
        }
      } else {
        if (progress >= 100) {
          progressBar.classList.add("bg-success");
        } else if (progress > 0) {
          progressBar.classList.add("bg-warning");
        } else {
          progressBar.classList.add("bg-secondary");
        }
      }

      // Atualizar ícone de status
      if (ativo) {
        statusIcon.innerHTML =
          '<i class="bi bi-gear-fill text-primary fs-3 spin"></i>';
      } else if (progress >= 100) {
        statusIcon.innerHTML =
          '<i class="bi bi-check-circle-fill text-success fs-3"></i>';
      } else {
        statusIcon.innerHTML = '<i class="bi bi-clock text-warning fs-3"></i>';
      }

      // Atualizar texto de status
      statusText.textContent = status;
      statusTime.textContent =
        "Última atualização: " + new Date().toLocaleTimeString();
    }

    // Atualizar display de logs
    function updateLogDisplay(logs) {
      if (!logs || logs.length === 0) return;

      // Limpar console se necessário
      if (logCount === 0) {
        logConsole.innerHTML = "";
      }

      // Adicionar apenas logs ainda não exibidos - a API sempre retorna as
      // últimas N linhas do arquivo, então sem essa checagem a mesma linha
      // seria duplicada no console a cada polling (a cada 2s)
      logs.forEach((log) => {
        const chave = `${log.tipo}::${log.mensagem}`;
        if (logsExibidos.has(chave)) {
          return;
        }
        logsExibidos.add(chave);
        addLogEntry(log.tipo, log.timestamp, log.mensagem);
      });

      updateLogCount();
    }

    // Adicionar entrada de log. As linhas vindas do arquivo já trazem o
    // próprio timestamp no texto; removemos para não duplicar com o span.
    function addLogEntry(tipo, timestamp, mensagem) {
      const logEntry = document.createElement("div");
      logEntry.className = `log-entry log-${tipo}`;

      const texto = String(mensagem).replace(
        /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\s*[-–]?\s*/,
        ""
      );

      logEntry.innerHTML = `
      <span class="log-timestamp">[${escapeHtml(timestamp)}]</span>
      <span class="ms-2">${escapeHtml(texto)}</span>
    `;

      logConsole.appendChild(logEntry);
      logCount++;

      // Auto-scroll se ativado
      if (autoScroll) {
        logConsole.scrollTop = logConsole.scrollHeight;
      }
    }

    // Atualizar contador de logs
    function updateLogCount() {
      logCountEl.textContent = logCount + " linhas";
    }

    // Iniciar atualizações automáticas
    function startUpdates() {
      updateLogs(); // Primeira busca
      updateInterval = setInterval(updateLogs, 2000); // A cada 2 segundos
    }

    // Parar atualizações
    function stopUpdates() {
      if (updateInterval) {
        clearInterval(updateInterval);
      }
    }

    // Iniciar
    carregarEstadoLogsDetalhados();
    startUpdates();

    // Limpar intervalo quando sair da página
    window.addEventListener("beforeunload", stopUpdates);
  });
