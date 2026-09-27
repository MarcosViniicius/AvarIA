/* dashboard.js - Dashboard: modo de extracao, stats/auto-refresh, progresso.
   Extraido de index.html (era <script> inline: sem cache,
   bloqueava o parse). Carregado com defer + static_v. */
  document.addEventListener("DOMContentLoaded", function () {
    // Bind botões de processamento
    const processBtn = document.getElementById("processBtn");
    const refreshBtn = document.getElementById("refreshBtn");

    if (processBtn) {
      processBtn.addEventListener("click", iniciarProcessamento);
    }
    if (refreshBtn) {
      // não passar atualizarStats direto: addEventListener chamaria com o
      // Event do clique como 1º argumento, que o parametro `silencioso`
      // interpretaria como truthy e silenciaria o clique manual também.
      refreshBtn.addEventListener("click", () => atualizarStats(false));
    }

    // Rótulos do modo de extração, para o "Estado do sistema" mostrar o modo
    // em vigor em vez de só o valor cru ("sem_ia").
    const ROTULOS_MODO = {
      ia: "Somente IA",
      hibrido: "Híbrido (código + IA)",
      sem_ia: "Sem IA (só código)",
    };

    // Pré-selecionar o modo salvo em Configurações, para o seletor refletir
    // o padrão do usuário em vez de sempre voltar para "Somente IA".
    const modoSelect = document.getElementById("modoExtracaoSelect");
    if (modoSelect) {
      fetch("/api/configuracoes")
        .then((r) => r.json())
        .then((config) => {
          const modoSalvo = config.processamento?.modo_extracao;
          if (modoSalvo) modoSelect.value = modoSalvo;
          atualizarRotuloModo();
        })
        .catch(() => {}); // mantém o padrão do <select> se a leitura falhar

      // Mantém o rótulo do estado sincronizado com o seletor.
      modoSelect.addEventListener("change", atualizarRotuloModo);
    }

    function atualizarRotuloModo() {
      const el = document.getElementById("modoAtualRotulo");
      if (!el || !modoSelect) return;
      el.textContent = ROTULOS_MODO[modoSelect.value] || modoSelect.value;
    }
    atualizarRotuloModo();

    function iniciarProcessamento() {
      const modo_extracao = modoSelect ? modoSelect.value : undefined;
      fetch("/processar", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ modo_extracao }),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            showAlert("success", data.message);
            monitorarProgresso();
          } else {
            showAlert("danger", data.message);
          }
        })
        .catch((error) => {
          showAlert("danger", "Erro ao iniciar processamento: " + error);
        });
    }

    // silencioso=true (usado pelo auto-refresh de 30s) não mostra o toast de
    // sucesso nem o spinner do botão - só o clique manual precisa desse
    // feedback. Sem essa distinção, o usuário recebia um alerta verde a cada
    // 30s sem ter pedido nada, o que treina a ignorar alertas (inclusive os
    // de erro de verdade).
    function atualizarStats(silencioso) {
      const originalText = refreshBtn.innerHTML;
      if (!silencioso) {
        refreshBtn.innerHTML =
          '<i class="bi bi-arrow-clockwise spin"></i> Atualizando...';
        refreshBtn.disabled = true;
      }

      fetch("/api/stats")
        .then((response) => response.json())
        .then((stats) => {
          document.getElementById("totalImagens").textContent =
            stats.imagens_total;
          document.getElementById("imagensProcessadas").textContent =
            stats.imagens_processadas;
          document.getElementById("imagensPendentes").textContent =
            stats.imagens_pendentes;
          document.getElementById("tokensHoje").textContent =
            stats.tokens_consumidos_hoje.toLocaleString();
          document.getElementById("ultimoProcessamento").textContent =
            stats.ultimo_processamento;

          // Barra de progresso do lote atual
          const barra = document.getElementById("progressoBarra");
          const resumo = document.getElementById("progressoResumo");
          const total = stats.imagens_total || 0;
          const feitas = stats.imagens_processadas || 0;
          const pct = total > 0 ? (feitas / total) * 100 : 0;
          if (barra) {
            barra.style.width = pct.toFixed(1) + "%";
            barra.setAttribute("aria-valuenow", pct.toFixed(0));
          }
          if (resumo) {
            resumo.textContent = total
              ? `${feitas} de ${total} imagens analisadas`
              : "Nenhuma imagem enviada ainda";
          }

          if (!silencioso) {
            showAlert("success", "Estatísticas atualizadas!");
          }
        })
        .catch((error) => {
          if (!silencioso) {
            showAlert("danger", "Erro ao atualizar: " + error);
          }
        })
        .finally(() => {
          if (!silencioso) {
            refreshBtn.innerHTML = originalText;
            refreshBtn.disabled = false;
          }
        });
    }

    // Auto-refresh silencioso a cada 30 segundos
    setInterval(() => atualizarStats(true), 30000);

    // A abertura do modal de imagem é tratada por static/js/image-modal.js
    // (delegação única, compartilhada com as outras telas).
  });
