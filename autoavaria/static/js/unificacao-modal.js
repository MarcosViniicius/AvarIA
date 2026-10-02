/**
 * MODAL DE UNIFICAÇÃO (módulo único)
 *
 * Antes existiam DUAS implementações da mesma coisa: `relatorio-acoes.js`
 * (unificação do relatório mestre) e `historico-execucao.js` (unificação de
 * uma execução), cada uma com seus próprios ids e sua própria função
 * `abrirModalUnificacao`. Os modais eram cópias quase idênticas e a manutenção
 * exigia lembrar de mexer nos dois — deu errado mais de uma vez.
 *
 * Agora há um módulo e uma parcial (`_modal_unificacao.html`). O que diferencia
 * as telas vem de `window.UNIFICACAO`:
 *
 *   window.UNIFICACAO = {
 *     escopo: 'mestre' | 'execucao',
 *     runId: 25,            // só no escopo 'execucao'
 *     comSelecao: true,     // mostra seletor de seções/colunas
 *     invertextoUrl: '...',
 *   }
 *
 * Rota de unificação:
 *   mestre   -> POST /api/unificar_relatorio        {formato, secoes, colunas}
 *   execucao -> POST /historico/execucao/<id>/unificar {formato}
 *
 * Rota de envio ao invertexto:
 *   mestre   -> POST /api/enviar_invertexto
 *   execucao -> POST /historico/execucao/<id>/enviar_invertexto
 */

(function () {
  "use strict";

  var cfg = window.UNIFICACAO || {};
  var escopo = cfg.escopo || "mestre";
  var invertextoUrl = cfg.invertextoUrl || "https://www.invertexto.com/autoava";

  var el = function (id) { return document.getElementById(id); };

  var modal = null;
  var downloadUrl = null;
  var contenido = "";
  var colunasPorSecao = {};

  function apiUnificar() {
    return escopo === "execucao"
      ? "/historico/execucao/" + cfg.runId + "/unificar"
      : "/api/unificar_relatorio";
  }

  function apiInvertexto() {
    return escopo === "execucao"
      ? "/historico/execucao/" + cfg.runId + "/enviar_invertexto"
      : "/api/enviar_invertexto";
  }

  // ---------------------------------------------------------------------
  // Estados
  // ---------------------------------------------------------------------

  function mostrarEstado(nome) {
    ["unificacaoExplicacao", "unificacaoProcessando", "unificacaoResultado", "unificacaoErro"]
      .forEach(function (id) {
        var no = el(id);
        if (no) no.classList.toggle("d-none", id !== nome);
      });
  }

  function resetar() {
    mostrarEstado("unificacaoExplicacao");
    var status = el("invertextoStatus");
    if (status) status.classList.add("d-none");
    if (el("unificacaoVistaPrevia")) el("unificacaoVistaPrevia").value = "";
    if (el("unificacaoErroMensagem")) el("unificacaoErroMensagem").textContent = "";
  }

  function abrir() {
    if (!modal) {
      var modalEl = el("unificacaoModal");
      if (!modalEl || typeof bootstrap === "undefined" || !bootstrap.Modal) {
        alert("Modal de unificação não está disponível. Recarregue a página.");
        return;
      }
      modal = new bootstrap.Modal(modalEl);
    }
    resetar();
    modal.show();
    if (cfg.comSelecao) carregarOpcoes();
  }

  // ---------------------------------------------------------------------
  // Seleção de seções/colunas (só no escopo 'mestre')
  // ---------------------------------------------------------------------

  function carregarOpcoes() {
    // No escopo de execução, as seções/colunas disponíveis são as daquela
    // execução — não do mestre inteiro.
    var url = "/api/opcoes_unificacao";
    if (escopo === "execucao" && cfg.runId) {
      url += "?run_id=" + encodeURIComponent(cfg.runId);
    }
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.secoes) return;
        colunasPorSecao = data.colunas_por_secao || {};
        renderizarSecoes(data.secoes);
        renderizarColunas();
      })
      .catch(function (e) { console.warn("Falha ao carregar opções de unificação:", e); });
  }

  function secoesSelecionadas() {
    return Array.prototype.map.call(
      document.querySelectorAll(".secao-checkbox-unificacao:checked"),
      function (c) { return c.value; }
    );
  }

  // Corpo enviado às rotas de unificação/invertexto: formato + (quando a tela
  // oferece seleção) as seções e colunas marcadas. Antes o envio ao invertexto
  // mandava um corpo vazio e publicava o relatório inteiro, ignorando o recorte
  // escolhido no modal.
  function montarCorpo() {
    var escolhido = document.querySelector('input[name="formatoUnificacao"]:checked');
    var formato = escolhido ? escolhido.value : "xlsx";

    var corpo = { formato: formato };
    if (cfg.comSelecao) {
      var secoes = secoesSelecionadas();
      if (secoes.length) {
        corpo.secoes = secoes;
        var porSecao = {};
        secoes.forEach(function (secao) {
          var colunas = Array.prototype.map.call(
            document.querySelectorAll('.coluna-checkbox-unificacao[data-secao="' + secao + '"]:checked'),
            function (c) { return c.value; }
          );
          if (colunas.length) porSecao[secao] = colunas;
        });
        corpo.colunas = porSecao;
      }
    }
    return corpo;
  }

  function renderizarSecoes(secoes) {
    var container = el("secoesUnificacao");
    if (!container) return;
    container.innerHTML = "";
    secoes.forEach(function (secao) {
      var div = document.createElement("div");
      div.className = "form-check";
      div.innerHTML =
        '<input class="form-check-input secao-checkbox-unificacao" type="checkbox" ' +
        'value="' + secao + '" id="unif-secao-' + secao.replace(/\s+/g, "_") + '" checked>' +
        '<label class="form-check-label" for="unif-secao-' + secao.replace(/\s+/g, "_") + '">' +
        secao + "</label>";
      container.appendChild(div);
    });
    container.querySelectorAll(".secao-checkbox-unificacao").forEach(function (cb) {
      cb.addEventListener("change", renderizarColunas);
    });
  }

  function renderizarColunas() {
    var container = el("colunasUnificacao");
    if (!container) return;
    container.innerHTML = "";

    var selecionadas = secoesSelecionadas();
    if (!selecionadas.length) {
      container.innerHTML =
        '<div class="text-center text-muted"><small>Selecione uma seção para ver as colunas disponíveis</small></div>';
      return;
    }

    selecionadas.forEach(function (secao) {
      var colunas = colunasPorSecao[secao];
      if (!colunas) return;

      var bloco = document.createElement("div");
      bloco.className = "mb-2";
      var titulo = document.createElement("div");
      titulo.className = "fw-bold small mb-1";
      titulo.textContent = secao;
      bloco.appendChild(titulo);

      var grid = document.createElement("div");
      grid.className = "row g-1";
      colunas.forEach(function (coluna) {
        var col = document.createElement("div");
        col.className = "col-md-6";
        var idCampo = "unif-col-" + secao.replace(/\s+/g, "_") + "-" + coluna.replace(/\s+/g, "_");
        col.innerHTML =
          '<div class="form-check">' +
          '<input class="form-check-input coluna-checkbox-unificacao" type="checkbox" ' +
          'data-secao="' + secao + '" value="' + coluna + '" id="' + idCampo + '" checked>' +
          '<label class="form-check-label small" for="' + idCampo + '">' + coluna + "</label>" +
          "</div>";
        grid.appendChild(col);
      });
      bloco.appendChild(grid);
      container.appendChild(bloco);
    });
  }

  function marcarTodos(seletor, checado) {
    document.querySelectorAll(seletor).forEach(function (cb) { cb.checked = checado; });
  }

  // ---------------------------------------------------------------------
  // Unificação
  // ---------------------------------------------------------------------

  function iniciar() {
    var corpo = montarCorpo();

    mostrarEstado("unificacaoProcessando");
    var btnIniciar = el("btnIniciarUnificacao");
    if (btnIniciar) btnIniciar.disabled = true;

    fetch(apiUnificar(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, dados: j }; }); })
      .then(function (res) {
        if (btnIniciar) btnIniciar.disabled = false;
        if (res.ok && res.dados.success) {
          mostrarResultado(res.dados);
        } else {
          mostrarErro(res.dados.message || "Erro desconhecido ao processar a unificação.");
        }
      })
      .catch(function (err) {
        if (btnIniciar) btnIniciar.disabled = false;
        mostrarErro("Erro de comunicação com o servidor: " + err.message);
      });
  }

  function mostrarResultado(dados) {
    downloadUrl = dados.download_url || null;
    contenido = dados.contenido || "";
    if (el("unificacaoResultadoMensagem")) {
      el("unificacaoResultadoMensagem").textContent = dados.message || "";
    }
    if (el("unificacaoVistaPrevia")) el("unificacaoVistaPrevia").value = contenido;
    var area = el("unificacaoAreaVistaPrevia");
    if (area) area.classList.add("d-none");
    mostrarEstado("unificacaoResultado");
  }

  function mostrarErro(mensagem) {
    if (el("unificacaoErroMensagem")) el("unificacaoErroMensagem").textContent = mensagem;
    mostrarEstado("unificacaoErro");
  }

  // ---------------------------------------------------------------------
  // Vista prévia + copiar
  // ---------------------------------------------------------------------

  function alternarVistaPrevia() {
    var area = el("unificacaoAreaVistaPrevia");
    var btn = el("btnExpandirUnificado");
    if (!area || !btn) return;
    var estavaOculta = area.classList.contains("d-none");
    area.classList.toggle("d-none", !estavaOculta);
    btn.innerHTML = estavaOculta
      ? '<i class="bi bi-eye-slash me-1"></i>Recolher'
      : '<i class="bi bi-eye me-1"></i>Expandir para visualizar';
  }

  function copiarConteudo() {
    var texto = (el("unificacaoVistaPrevia") && el("unificacaoVistaPrevia").value) || contenido;
    if (!texto) {
      alert("Nada para copiar: o conteúdo unificado está vazio.");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texto);
    } else {
      var campo = el("unificacaoVistaPrevia");
      if (campo) { campo.classList.remove("d-none"); campo.select(); }
    }
  }

  // ---------------------------------------------------------------------
  // Invertexto
  // ---------------------------------------------------------------------

  function mostrarStatusInvertexto(url, caracteres) {
    var bloco = el("invertextoStatus");
    if (!bloco) return;
    var alerta = bloco.querySelector(".alert");
    if (alerta) {
      alerta.classList.remove("alert-danger");
      alerta.classList.add("alert-success");
    }
    if (el("invertextoStatusTitulo")) el("invertextoStatusTitulo").textContent = "Relatório publicado no invertexto";
    if (el("invertextoStatusDetalhe")) {
      el("invertextoStatusDetalhe").textContent =
        "Enviado com " + Number(caracteres || 0).toLocaleString("pt-BR") +
        " caracteres. O link abaixo abre o relatório:";
    }
    if (el("invertextoLink")) el("invertextoLink").value = url;
    if (el("btnAbrirInvertexto")) el("btnAbrirInvertexto").setAttribute("href", url);
    bloco.classList.remove("d-none");
  }

  function mostrarErroInvertexto(mensagem) {
    var bloco = el("invertextoStatus");
    if (!bloco) return;
    var alerta = bloco.querySelector(".alert");
    if (alerta) {
      alerta.classList.remove("alert-success");
      alerta.classList.add("alert-danger");
    }
    if (el("invertextoStatusTitulo")) el("invertextoStatusTitulo").textContent = "Não foi possível publicar no invertexto";
    if (el("invertextoStatusDetalhe")) el("invertextoStatusDetalhe").textContent = mensagem;
    if (el("invertextoLink")) el("invertextoLink").value = "";
    if (el("btnAbrirInvertexto")) el("btnAbrirInvertexto").setAttribute("href", "#");
    bloco.classList.remove("d-none");
  }

  function enviarParaInvertexto() {
    var btn = el("btnEnviarInvertexto");
    var confirmado = window.confirm(
      "O relatório será publicado no notepad:\n" + invertextoUrl +
      "\n\nO texto fica PÚBLICO para quem tiver o link (sem senha)." +
      "\nCaminhos de imagem são removidos automaticamente." +
      "\n\nDeseja enviar?"
    );
    if (!confirmado) return;

    var anterior = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Enviando...';
    }

    fetch(apiInvertexto(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(montarCorpo()),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, dados: j }; }); })
      .then(function (res) {
        if (btn) { btn.disabled = false; btn.innerHTML = anterior; }
        if (res.ok && res.dados.success) {
          mostrarStatusInvertexto(res.dados.url || invertextoUrl, res.dados.caracteres);
        } else {
          mostrarErroInvertexto(res.dados.message || "Não foi possível enviar para o invertexto.");
        }
      })
      .catch(function (err) {
        if (btn) { btn.disabled = false; btn.innerHTML = anterior; }
        mostrarErroInvertexto("Erro de comunicação: " + err.message);
      });
  }

  function copiarLink() {
    var campo = el("invertextoLink");
    var texto = (campo && campo.value) || "";
    if (!texto) return;
    var btn = el("btnCopiarLinkInvertexto");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texto).then(function () {
        if (!btn) return;
        var anterior = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check-lg"></i>';
        setTimeout(function () { btn.innerHTML = anterior; }, 1500);
      }).catch(function () { if (campo) campo.select(); });
    } else if (campo) {
      campo.select();
    }
  }

  // ---------------------------------------------------------------------
  // Ligações
  // ---------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    var modalEl = el("unificacaoModal");
    if (!modalEl) return; // página sem o modal (parcial não incluída)

    if (typeof bootstrap !== "undefined" && bootstrap.Modal) {
      modal = new bootstrap.Modal(modalEl);
    }

    // Abrir: por id (ambas as telas usam data-unif-abrir no botão).
    document.querySelectorAll("[data-unif-abrir]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        abrir();
      });
    });

    var btnIniciar = el("btnIniciarUnificacao");
    if (btnIniciar) btnIniciar.addEventListener("click", iniciar);

    var btnDownload = el("btnDownloadUnificado");
    if (btnDownload) {
      btnDownload.addEventListener("click", function () {
        if (downloadUrl) window.location.href = downloadUrl;
      });
    }

    var btnExpandir = el("btnExpandirUnificado");
    if (btnExpandir) btnExpandir.addEventListener("click", alternarVistaPrevia);

    var btnCopiar = el("btnCopiarUnificado");
    if (btnCopiar) btnCopiar.addEventListener("click", copiarConteudo);

    var btnEnviar = el("btnEnviarInvertexto");
    if (btnEnviar) btnEnviar.addEventListener("click", enviarParaInvertexto);

    var btnCopiarLink = el("btnCopiarLinkInvertexto");
    if (btnCopiarLink) btnCopiarLink.addEventListener("click", copiarLink);

    // Seleção em massa (só existem no escopo com seleção).
    document.querySelectorAll("[data-unif-secoes]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        marcarTodos(".secao-checkbox-unificacao", btn.getAttribute("data-unif-secoes") === "todas");
        renderizarColunas();
      });
    });
    document.querySelectorAll("[data-unif-colunas]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var todas = btn.getAttribute("data-unif-colunas") === "todas";
        document.querySelectorAll(".coluna-checkbox-unificacao").forEach(function (cb) {
          // "desmarcar todas" respeita apenas as seções visíveis/selecionadas
          if (cb.offsetParent !== null || todas) cb.checked = todas;
        });
      });
    });
  });
})();
