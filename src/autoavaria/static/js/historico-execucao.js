/**
 * Acoes da pagina de detalhe de uma execucao do historico.
 *
 * Depende de window.RUN_ID, injetado pelo template ANTES deste arquivo:
 *   <script>window.RUN_ID = {{ execucao.id }};</script>
 */
document.addEventListener("DOMContentLoaded", function () {
  const RUN_ID = window.RUN_ID;
  if (RUN_ID == null) {
    console.error("window.RUN_ID nao foi definido pelo template");
    return;
  }
  window.apiUrl = (path) => `/historico/execucao/${RUN_ID}${path}`;
  const apiUrl = window.apiUrl;

  function mostrarAlerta(tipo, mensagem) {
    const container = document.querySelector("main.container") || document.body;
    const alerta = document.createElement("div");
    alerta.className = `alert alert-${tipo} alert-dismissible fade show`;
    alerta.innerHTML = `${mensagem}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    container.prepend(alerta);
    setTimeout(() => alerta.remove(), 5000);
  }

  // Mostra a imagem do produto (se houver) dentro de um modal de edição.
  function exibirImagemNoModal(row, containerId, imgId, vazioId) {
    const container = document.getElementById(containerId);
    const img = document.getElementById(imgId);
    const vazio = vazioId ? document.getElementById(vazioId) : null;
    if (!container || !img) return;

    const botaoImagem = row ? row.querySelector(".view-image-btn") : null;
    const imagePath = botaoImagem ? botaoImagem.getAttribute("data-image") : null;

    if (imagePath) {
      img.src = imagePath;
      container.style.display = "block";
      if (vazio) vazio.style.display = "none";
    } else {
      container.style.display = "none";
      img.src = "";
      if (vazio) vazio.style.display = "block";
    }
  }

  // ===================== EDIÇÃO DE CAMPO ÚNICO =====================
  let currentItemId = null;
  let currentCategoria = null;
  let currentEditElement = null;

  function editarCampo(element) {
    currentEditElement = element;
    const tr = element.closest("tr");
    currentCategoria = tr.getAttribute("data-categoria");
    currentItemId = parseInt(tr.getAttribute("data-linha"));

    const fieldName = element.getAttribute("data-field");
    const currentValue = element.getAttribute("data-original");

    document.getElementById("editFieldName").value = fieldName;
    document.getElementById("editFieldValue").value = currentValue;

    exibirImagemNoModal(tr, "editImagePreviewContainer", "editImagePreview", "editImagePreviewVazio");

    new bootstrap.Modal(document.getElementById("editModal")).show();
  }

  function salvarEdicao() {
    const fieldName = document.getElementById("editFieldName").value;
    const newValue = document.getElementById("editFieldValue").value;

    if (currentItemId === null) {
      mostrarAlerta("danger", "Erro: item não identificado");
      return;
    }

    fetch(apiUrl("/item/editar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: currentItemId, campo: fieldName, novo_valor: newValue }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          if (currentEditElement) {
            currentEditElement.textContent = newValue || "-";
            currentEditElement.setAttribute("data-original", newValue);
          }
          bootstrap.Modal.getInstance(document.getElementById("editModal")).hide();
          mostrarAlerta("success", data.message);
        } else {
          mostrarAlerta("danger", data.message);
        }
      })
      .catch((err) => mostrarAlerta("danger", "Erro de comunicação: " + err.message));
  }

  // ===================== ADICIONAR / EDITAR LINHA COMPLETA =====================
  let modoAddModal = "adicionar"; // "adicionar" | "editar"

  function camposDaCategoria(categoria) {
    const tabelaId = `${categoria.replace(/ /g, "-").toLowerCase()}-table`;
    const table = document.getElementById(tabelaId);
    if (!table) return [];
    return Array.from(table.querySelectorAll("thead th"))
      .map((th) => th.textContent.trim())
      .filter((h) => h && h !== "Ações" && !h.includes("Ver Imagem") && !h.includes("Caminho da Imagem"));
  }

  function montarFormulario(campos, valores) {
    let html = "";
    campos.forEach((campo) => {
      const valor = (valores && valores[campo]) || "";
      html += `
        <div class="mb-3">
          <label class="form-label">${campo}</label>
          <input type="text" class="form-control" name="${campo}" value="${valor.replace(/"/g, "&quot;")}" placeholder="Digite ${campo.toLowerCase()}">
        </div>
      `;
    });
    return html;
  }

  function adicionarItem(categoria) {
    modoAddModal = "adicionar";
    currentCategoria = categoria;
    currentItemId = null;

    const campos = camposDaCategoria(categoria);
    document.getElementById("addFormFields").innerHTML = montarFormulario(campos, {});
    document.getElementById("addModalTitle").innerHTML = `<i class="bi bi-plus-lg me-2"></i>Adicionar Item - ${categoria}`;
    document.getElementById("addModalSaveBtn").innerHTML = '<i class="bi bi-plus-lg"></i> Adicionar';

    const imagemContainer = document.getElementById("addModalImagePreviewContainer");
    if (imagemContainer) imagemContainer.style.display = "none";

    new bootstrap.Modal(document.getElementById("addModal")).show();
  }

  function editarLinha(categoria, itemId) {
    modoAddModal = "editar";
    currentCategoria = categoria;
    currentItemId = itemId;

    const sanitized = categoria.replace(/ /g, "-").toLowerCase();
    const row = document.querySelector(`#${sanitized} tr[data-linha="${itemId}"]`);
    if (!row) {
      mostrarAlerta("danger", "Item não encontrado na tabela");
      return;
    }

    const campos = camposDaCategoria(categoria);
    const valores = {};
    campos.forEach((campo) => {
      const span = row.querySelector(`.editable-field[data-field="${campo}"]`);
      valores[campo] = span ? span.getAttribute("data-original") : "";
    });

    document.getElementById("addFormFields").innerHTML = montarFormulario(campos, valores);
    document.getElementById("addModalTitle").innerHTML = `<i class="bi bi-pencil-square me-2"></i>Editar Item - ${categoria}`;
    document.getElementById("addModalSaveBtn").innerHTML = '<i class="bi bi-check-lg"></i> Salvar Alterações';

    exibirImagemNoModal(row, "addModalImagePreviewContainer", "addModalImagePreview");

    new bootstrap.Modal(document.getElementById("addModal")).show();
  }

  function salvarNovoItem() {
    const inputs = document.querySelectorAll("#addFormFields input");
    const dados = {};
    inputs.forEach((input) => (dados[input.name] = input.value));

    const endpoint = modoAddModal === "adicionar" ? "/item/adicionar" : "/item/editar_completo";
    const body =
      modoAddModal === "adicionar"
        ? { categoria: currentCategoria, dados_linha: dados }
        : { item_id: currentItemId, dados_linha: dados };

    fetch(apiUrl(endpoint), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          bootstrap.Modal.getInstance(document.getElementById("addModal")).hide();
          mostrarAlerta("success", data.message);
          setTimeout(() => window.location.reload(), 600);
        } else {
          mostrarAlerta("danger", data.message);
        }
      })
      .catch((err) => mostrarAlerta("danger", "Erro de comunicação: " + err.message));
  }

  document.getElementById("addModal").addEventListener("hidden.bs.modal", function () {
    document.getElementById("addFormFields").innerHTML = "";
    const imagemContainer = document.getElementById("addModalImagePreviewContainer");
    if (imagemContainer) imagemContainer.style.display = "none";
  });

  // ===================== EXCLUIR / MOVER =====================
  function excluirItem(categoria, itemId) {
    if (!confirm("Tem certeza que deseja excluir este item? Esta ação não pode ser desfeita.")) return;

    fetch(apiUrl("/item/excluir"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          mostrarAlerta("success", data.message);
          setTimeout(() => window.location.reload(), 600);
        } else {
          mostrarAlerta("danger", data.message);
        }
      })
      .catch((err) => mostrarAlerta("danger", "Erro de comunicação: " + err.message));
  }

  function moverItem(event, categoriaOrigem, categoriaDestino, itemId) {
    event.preventDefault();
    if (!confirm(`Mover este item de "${categoriaOrigem}" para "${categoriaDestino}"?`)) return;

    fetch(apiUrl("/item/mover"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, categoria_destino: categoriaDestino }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          mostrarAlerta("success", data.message);
          setTimeout(() => window.location.reload(), 600);
        } else {
          mostrarAlerta("danger", data.message);
        }
      })
      .catch((err) => mostrarAlerta("danger", "Erro de comunicação: " + err.message));
  }

  // ===================== UNIFICAÇÃO ESCOPADA =====================
  function abrirModalUnificacao() {
    document.getElementById("unificacaoExplicacao").classList.remove("d-none");
    document.getElementById("unificacaoProcessando").classList.add("d-none");
    document.getElementById("unificacaoResultado").classList.add("d-none");
    document.getElementById("unificacaoErro").classList.add("d-none");
    document.getElementById("btnIniciarUnificacaoExec").classList.remove("d-none");
    new bootstrap.Modal(document.getElementById("unificacaoModal")).show();
  }

  function iniciarUnificacaoExecucao() {
    const formato = document.querySelector('input[name="formatoUnificacaoExecucao"]:checked').value;

    document.getElementById("unificacaoExplicacao").classList.add("d-none");
    document.getElementById("unificacaoProcessando").classList.remove("d-none");
    document.getElementById("btnIniciarUnificacaoExec").classList.add("d-none");

    fetch(apiUrl("/unificar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formato }),
    })
      .then((r) => r.json())
      .then((data) => {
        document.getElementById("unificacaoProcessando").classList.add("d-none");
        if (data.success) {
          document.getElementById("unificacaoResultado").classList.remove("d-none");
          document.getElementById("unificacaoResultadoMensagem").textContent = data.message;
          document.getElementById("btnDownloadUnificadoExec").href = data.download_url;
          const contenido = data.contenido || "";
          const area = document.getElementById("unificacaoAreaVistaPreviaExec");
          const ta = document.getElementById("unificacaoVistaPreviaExec");
          if (ta) ta.value = contenido;
          if (area) area.style.display = "none";
          document.getElementById("btnExpandirUnificadoExec").style.display = "inline-block";
          document.getElementById("btnCopiarUnificadoExec").style.display = "inline-block";
        } else {
          document.getElementById("unificacaoErro").classList.remove("d-none");
          document.getElementById("unificacaoErroMensagem").textContent = data.message || "Erro desconhecido.";
        }
      })
      .catch((err) => {
        document.getElementById("unificacaoProcessando").classList.add("d-none");
        document.getElementById("unificacaoErro").classList.remove("d-none");
        document.getElementById("unificacaoErroMensagem").textContent = "Erro de comunicação: " + err.message;
      });
  }

  // Expandir/recolher a vista previa e copiar o conteúdo unificado.
  // Roda direto (este arquivo inteiro já executa dentro de um
  // DOMContentLoaded): um listener aninhado nunca dispararia.
  (function ligarVistaPreviaUnificado() {
    const btnExpandir = document.getElementById("btnExpandirUnificadoExec");
    if (btnExpandir) {
      btnExpandir.addEventListener("click", function () {
        const area = document.getElementById("unificacaoAreaVistaPreviaExec");
        if (!area) return;
        const oculta = area.classList.contains("d-none") || area.style.display === "none";
        area.classList.toggle("d-none", !oculta);
        area.style.display = oculta ? "block" : "none";
        btnExpandir.innerHTML = oculta
          ? '<i class="bi bi-eye-slash me-1"></i>Recolher'
          : '<i class="bi bi-eye me-1"></i>Expandir para visualizar';
      });
    }
    const btnCopiar = document.getElementById("btnCopiarUnificadoExec");
    if (btnCopiar) {
      btnCopiar.addEventListener("click", function () {
        const campo = document.getElementById("unificacaoVistaPreviaExec");
        const texto = (campo && campo.value) || "";
        if (!texto) {
          alert("Nada para copiar: o conteúdo unificado está vazio.");
          return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(texto).then(function () {
            const anterior = btnCopiar.innerHTML;
            btnCopiar.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copiado!';
            setTimeout(function () { btnCopiar.innerHTML = anterior; }, 1500);
          }).catch(function () {
            copiarFallbackExec(texto, btnCopiar);
          });
        } else {
          copiarFallbackExec(texto, btnCopiar);
        }
      });
    }
    function copiarFallbackExec(texto, btn) {
      const area = document.createElement("textarea");
      area.value = texto;
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy");
        const anterior = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copiado!';
        setTimeout(function () { btn.innerHTML = anterior; }, 1500);
      } catch (e) {
        alert("Não foi possível copiar automaticamente. Selecione o texto manualmente.");
      }
      document.body.removeChild(area);
    }
  })();

  // ===================== REANÁLISE SELETIVA (um / vários / todos) =====================
  // Sem filtros reanalisa tudo (comportamento original). Com item_ids ou
  // categorias, só a seleção vai para a IA; o resto é copiado intacto para
  // a nova versão pelo backend.
  function iniciarReanalise(filtros) {
    const body = filtros || {};
    let rotulo = "todas as imagens desta execução";
    if (body.item_ids && body.item_ids.length) {
      rotulo = body.item_ids.length + " item(ns) marcado(s)";
    } else if (body.categorias && body.categorias.length) {
      rotulo = "a categoria " + body.categorias.join(", ");
    }
    if (
      !confirm(
        "Isso vai rodar a análise de novo em " + rotulo + " e criar uma nova versão dos resultados. Continuar?"
      )
    ) {
      return;
    }

    const btn = document.getElementById("btnReanalisar");
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i class="bi bi-arrow-clockwise spin me-1"></i>Iniciando...';
    }

    fetch(apiUrl("/reanalisar"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) {
          mostrarAlerta("danger", data.message);
          if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reanalisar';
          }
          return;
        }
        mostrarAlerta("success", data.message);
        if (typeof monitorarProgresso === "function") monitorarProgresso();
        aguardarConclusaoDaReanalise();
      })
      .catch((err) => {
        mostrarAlerta("danger", "Erro de comunicação: " + err.message);
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reanalisar';
        }
      });
  }

  function aguardarConclusaoDaReanalise() {
    const intervalo = setInterval(() => {
      fetch("/status")
        .then((r) => r.json())
        .then((data) => {
          const terminou =
            (data.resultado && typeof data.resultado.run_id !== "undefined") ||
            (data.status || "").includes("Erro");
          if (!terminou) return;
          clearInterval(intervalo);
          const novoRunId = data.resultado && data.resultado.run_id;
          setTimeout(() => {
            window.location.href = novoRunId ? `/historico/execucao/${novoRunId}` : window.location.href;
          }, 1500);
        })
        .catch(() => clearInterval(intervalo));
    }, 2000);
  }

  // ===================== DELEGAÇÃO DE EVENTOS =====================
  // Checkboxes de reanálise seletiva: marcar todos da aba + contador.
  document.addEventListener("change", (event) => {
    if (event.target.classList && event.target.classList.contains("reanalise-check-all")) {
      const tabela = event.target.closest("table");
      if (tabela) {
        tabela.querySelectorAll(".reanalise-check").forEach((cb) => {
          cb.checked = event.target.checked;
        });
      }
    }
    if (
      event.target.classList &&
      (event.target.classList.contains("reanalise-check") ||
        event.target.classList.contains("reanalise-check-all"))
    ) {
      const total = document.querySelectorAll(".reanalise-check:checked").length;
      const contador = document.getElementById("reanaliseContador");
      if (contador) contador.textContent = total;
    }
  });

  // Os botões abaixo chamavam funções deste módulo por `onclick` inline no
  // template, o que exige a função no escopo global — e estas são privadas de
  // propósito. A delegação também cobre as linhas criadas depois (após
  // "Adicionar" ou uma edição), que os listeners diretos ignoravam.
  document.addEventListener("click", (event) => {
    const campo = event.target.closest(".editable-field");
    if (campo) {
      event.preventDefault();
      editarCampo(campo);
      return;
    }

    const add = event.target.closest("[data-add-sheet]");
    if (add) {
      event.preventDefault();
      adicionarItem(add.dataset.addSheet);
      return;
    }

    const edit = event.target.closest("[data-edit-sheet]");
    if (edit) {
      event.preventDefault();
      editarLinha(edit.dataset.editSheet, edit.dataset.editLinha);
      return;
    }

    const move = event.target.closest("[data-move-sheet]");
    if (move) {
      event.preventDefault();
      moverItem(event, move.dataset.moveSheet, move.dataset.moveDestino, move.dataset.moveLinha);
      return;
    }

    const del = event.target.closest("[data-del-sheet]");
    if (del) {
      event.preventDefault();
      excluirItem(del.dataset.delSheet, del.dataset.delLinha);
      return;
    }

    if (event.target.closest("#execSalvarEdicaoBtn")) {
      event.preventDefault();
      salvarEdicao();
      return;
    }

    if (event.target.closest("#addModalSaveBtn")) {
      event.preventDefault();
      salvarNovoItem();
      return;
    }

    if (event.target.closest("#btnUnificarExec")) {
      event.preventDefault();
      iniciarUnificacaoExecucao();
      return;
    }

    if (event.target.closest("#btnReanalisar")) {
      event.preventDefault();
      iniciarReanalise({});
      return;
    }

    const escopo = event.target.closest("[data-reanalise-escopo]");
    if (escopo) {
      event.preventDefault();
      const qual = escopo.getAttribute("data-reanalise-escopo");
      if (qual === "todos") {
        iniciarReanalise({});
      } else if (qual === "selecionados") {
        const ids = Array.from(document.querySelectorAll(".reanalise-check:checked"))
          .filter((cb) => !cb.disabled)
          .map((cb) => parseInt(cb.value, 10))
          .filter((n) => Number.isFinite(n));
        if (!ids.length) {
          mostrarAlerta("warning", "Marque pelo menos um item na tabela para reanalisar.");
          return;
        }
        iniciarReanalise({ item_ids: ids });
      } else {
        iniciarReanalise({ categorias: [qual] });
      }
      return;
    }
  });
});
