/**
 * Edicao de dados do relatorio (pagina /editar_dados).
 *
 * Saida do inline de templates/editar_dados.html - mantido como arquivo
 * proprio para poder ser testado e cacheado pelo navegador. Os alertas
 * usam o showAlert global de static/js/main.js (carregado antes).
 */
/*
 * MELHORIAS IMPLEMENTADAS - EDIÇÃO DE DADOS:
 *
 * 1. CORREÇÃO DO BUG DE EDIÇÃO:
 *    - Corrigido problema onde cliques em células editavam apenas a primeira tabela
 *    - Adicionada identificação correta da tabela ativa através do contexto DOM
 *    - Melhorada busca de elementos usando seletores específicos de aba
 *
 * 2. FUNCIONALIDADE DE MOVER ITENS ENTRE TABELAS:
 *    - Adicionado dropdown de ações com opções para mover itens
 *    - Implementada rota /mover_item no backend para transferir dados
 *    - Adaptação automática de campos ao mover entre diferentes tipos de planilha
 *    - Confirmação antes de mover e feedback visual durante operação
 *
 * 3. MELHORIAS DE UX:
 *    - Feedback visual melhorado com estados de loading
 *    - Mensagens informativas sobre funcionalidades
 *    - Animações suaves para remoção de linhas
 *    - Tooltips e ícones informativos
 */

let currentEditElement = null;
let currentSheet = null;
let currentLineId = null;

// Editar campo individual
function editarCampo(element) {
  currentEditElement = element;
  const tr = element.closest("tr");
  currentSheet = tr.getAttribute("data-sheet");
  currentLineId = parseInt(tr.getAttribute("data-linha"));

  const fieldName = element.getAttribute("data-field");
  const currentValue = element.getAttribute("data-original");

  console.log("🔧 Editando campo:", {
    sheet: currentSheet,
    linha: currentLineId,
    campo: fieldName,
    valor: currentValue,
  });

  document.getElementById("editFieldName").value = fieldName;
  document.getElementById("editFieldValue").value = currentValue;

  exibirImagemNoModal(
    tr,
    "editImagePreviewContainer",
    "editImagePreview",
    "editImagePreviewVazio"
  );

  const modal = new bootstrap.Modal(document.getElementById("editModal"));
  modal.show();
}

// Mostra a imagem do produto (se houver) dentro de um modal de edição,
// reaproveitando o botão "Ver" já renderizado na linha da tabela.
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

// Salvar edição
function salvarEdicao() {
  const fieldName = document.getElementById("editFieldName").value;
  const newValue = document.getElementById("editFieldValue").value;

  if (!currentSheet || currentLineId === null) {
    showAlert("danger", "Erro: dados de edição não encontrados");
    return;
  }

  // Mostrar loading
  const saveBtn = document.querySelector("#editModal .btn-primary");
  const originalText = saveBtn.innerHTML;
  saveBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Salvando...';
  saveBtn.disabled = true;

  fetch("/salvar_edicao", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sheet_name: currentSheet,
      linha_id: parseInt(currentLineId),
      campo: fieldName,
      novo_valor: newValue,
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        // Atualizar visualmente
        if (currentEditElement) {
          currentEditElement.textContent = newValue || "-";
          currentEditElement.setAttribute("data-original", newValue);
        }

        showAlert("success", data.message);
        bootstrap.Modal.getInstance(
          document.getElementById("editModal")
        ).hide();
      } else {
        showAlert("danger", data.message);
      }
    })
    .catch((error) => {
      console.error("Erro ao salvar:", error);
      showAlert("danger", "Erro ao salvar: " + error.message);
    })
    .finally(() => {
      // Restaurar botão
      saveBtn.innerHTML = originalText;
      saveBtn.disabled = false;
    });
}

// Excluir linha
function excluirLinha(sheetName, linhaId) {
  if (
    !confirm(
      "Tem certeza que deseja excluir esta linha? Esta ação não pode ser desfeita."
    )
  ) {
    return;
  }

  // Encontrar o botão que foi clicado na tabela correta
  const sanitizedSheetName = sheetName.replace(/ /g, "-").toLowerCase();
  const deleteBtn = document.querySelector(
    `#${sanitizedSheetName} button[data-sheet="${sheetName}"][data-linha="${linhaId}"].btn-excluir-linha`
  );
  const originalContent = deleteBtn ? deleteBtn.innerHTML : null;

  if (deleteBtn) {
    deleteBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
    deleteBtn.disabled = true;
  }

  fetch("/excluir_linha", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sheet_name: sheetName,
      linha_id: parseInt(linhaId),
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        // Remover linha da tabela com animação
        const row = document.querySelector(
          `#${sanitizedSheetName} tr[data-linha="${linhaId}"]`
        );
        if (row) {
          row.style.transition = "opacity 0.3s";
          row.style.opacity = "0";
          setTimeout(() => row.remove(), 300);
        }
        showAlert("success", data.message);
      } else {
        showAlert("danger", data.message);
        // Restaurar botão em caso de erro
        if (deleteBtn && originalContent) {
          deleteBtn.innerHTML = originalContent;
          deleteBtn.disabled = false;
        }
      }
    })
    .catch((error) => {
      console.error("Erro ao excluir:", error);
      showAlert("danger", "Erro ao excluir: " + error.message);
      // Restaurar botão em caso de erro
      if (deleteBtn && originalContent) {
        deleteBtn.innerHTML = originalContent;
        deleteBtn.disabled = false;
      }
    });
}

// Mover item entre tabelas
function moverItem(sheetOrigem, sheetDestino, linhaId) {
  console.log("🔄 Movendo item:", {
    origem: sheetOrigem,
    destino: sheetDestino,
    linha: linhaId,
  });

  if (
    !confirm(
      `Tem certeza que deseja mover este item de "${sheetOrigem}" para "${sheetDestino}"?`
    )
  ) {
    return;
  }

  // Mostrar loading no link
  const moveLink = document.querySelector(
    `a[data-sheet-origem="${sheetOrigem}"][data-sheet-destino="${sheetDestino}"][data-linha="${linhaId}"]`
  );
  const originalText = moveLink ? moveLink.innerHTML : null;

  if (moveLink) {
    moveLink.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Movendo...';
    moveLink.classList.add("disabled");
  }

  fetch("/mover_item", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sheet_origem: sheetOrigem,
      sheet_destino: sheetDestino,
      linha_id: parseInt(linhaId),
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        showAlert("success", data.message);
        // Recarregar página para atualizar as tabelas
        setTimeout(() => location.reload(), 1500);
      } else {
        showAlert("danger", data.message);
        // Restaurar link em caso de erro
        if (moveLink && originalText) {
          moveLink.innerHTML = originalText;
          moveLink.classList.remove("disabled");
        }
      }
    })
    .catch((error) => {
      console.error("Erro ao mover item:", error);
      showAlert("danger", "Erro ao mover item: " + error.message);
      // Restaurar link em caso de erro
      if (moveLink && originalText) {
        moveLink.innerHTML = originalText;
        moveLink.classList.remove("disabled");
      }
    });
}

// Adicionar nova linha
function adicionarLinha(sheetName) {
  currentSheet = sheetName;

  // Pegar colunas da tabela
  const table = document.getElementById(
    `table-${sheetName.replace(/ /g, "-").toLowerCase()}`
  );
  const headers = Array.from(table.querySelectorAll("thead th"))
    .map((th) => th.textContent.trim())
    .filter((header) => header !== "#" && header !== "Ações");

  // Gerar campos do formulário
  let formHtml = "";
  headers.forEach((header) => {
    if (
      !header.includes("Ver Imagem") &&
      !header.includes("Caminho da Imagem")
    ) {
      const isRequired = ["Produto", "Arquivo"].includes(header);
      formHtml += `
      <div class="mb-3">
        <label class="form-label">
          ${header} ${isRequired ? '<span class="text-danger">*</span>' : ""}
        </label>
        <input 
          type="text" 
          class="form-control" 
          name="${header}" 
          placeholder="Digite ${header.toLowerCase()}"
          ${isRequired ? "required" : ""}
        >
        <div class="invalid-feedback">
          Este campo é obrigatório
        </div>
      </div>
    `;
    }
  });

  document.getElementById("addFormFields").innerHTML = formHtml;

  // Nova linha ainda não tem imagem associada
  const imagemContainer = document.getElementById("addModalImagePreviewContainer");
  if (imagemContainer) imagemContainer.style.display = "none";

  const modal = new bootstrap.Modal(document.getElementById("addModal"));
  modal.show();
}

// Salvar edição completa
function salvarEdicaoCompleta() {
  const formData = {};
  const inputs = document.querySelectorAll("#addFormFields input");
  let hasEmptyFields = false;

  inputs.forEach((input) => {
    formData[input.name] = input.value;
    if (!input.value.trim() && input.hasAttribute("required")) {
      hasEmptyFields = true;
      input.classList.add("is-invalid");
    } else {
      input.classList.remove("is-invalid");
    }
  });

  if (hasEmptyFields) {
    showAlert("warning", "Por favor, preencha todos os campos obrigatórios");
    return;
  }

  if (!currentSheet || currentLineId === null) {
    showAlert("danger", "Erro: dados de edição não encontrados");
    return;
  }

  // Mostrar loading
  const saveBtn = document.querySelector("#addModal .btn-success");
  const originalText = saveBtn.innerHTML;
  saveBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Salvando...';
  saveBtn.disabled = true;

  fetch("/salvar_edicao_completa", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sheet_name: currentSheet,
      linha_id: parseInt(currentLineId),
      dados_linha: formData,
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        showAlert("success", data.message);
        bootstrap.Modal.getInstance(
          document.getElementById("addModal")
        ).hide();

        // Atualizar linha na tabela específica
        const sanitizedSheetName = currentSheet
          .replace(/ /g, "-")
          .toLowerCase();
        const row = document.querySelector(
          `#${sanitizedSheetName} tr[data-linha="${currentLineId}"]`
        );
        if (row) {
          // Encontrar células editáveis e atualizar
          const editableFields = row.querySelectorAll(".editable-field");
          editableFields.forEach((field) => {
            const fieldName = field.getAttribute("data-field");
            if (formData[fieldName] !== undefined) {
              field.textContent = formData[fieldName] || "-";
              field.setAttribute("data-original", formData[fieldName] || "");
            }
          });
        }

        // Restaurar modal para estado de adicionar
        resetAddModal();
      } else {
        showAlert("danger", data.message);
      }
    })
    .catch((error) => {
      console.error("Erro ao salvar edição completa:", error);
      showAlert("danger", "Erro ao salvar: " + error.message);
    })
    .finally(() => {
      // Restaurar botão
      saveBtn.innerHTML = originalText;
      saveBtn.disabled = false;
    });
}

// Resetar modal para estado de adicionar
function resetAddModal() {
  const modalTitle = document.querySelector("#addModal .modal-title");
  const saveBtn = document.querySelector("#addModal .btn-success");

  modalTitle.innerHTML =
    '<i class="bi bi-plus-lg me-2"></i>Adicionar Nova Linha';
  saveBtn.innerHTML = '<i class="bi bi-plus-lg"></i> Adicionar';
  saveBtn.setAttribute("onclick", "salvarNovaLinha()");

  const imagemContainer = document.getElementById("addModalImagePreviewContainer");
  if (imagemContainer) imagemContainer.style.display = "none";
}

// Salvar nova linha
function salvarNovaLinha() {
  const formData = {};
  const inputs = document.querySelectorAll("#addFormFields input");
  let hasEmptyFields = false;

  inputs.forEach((input) => {
    formData[input.name] = input.value;
    if (!input.value.trim() && input.hasAttribute("required")) {
      hasEmptyFields = true;
      input.classList.add("is-invalid");
    } else {
      input.classList.remove("is-invalid");
    }
  });

  if (hasEmptyFields) {
    showAlert("warning", "Por favor, preencha todos os campos obrigatórios");
    return;
  }

  // Mostrar loading
  const saveBtn = document.querySelector("#addModal .btn-success");
  const originalText = saveBtn.innerHTML;
  saveBtn.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Adicionando...';
  saveBtn.disabled = true;

  fetch("/adicionar_linha", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sheet_name: currentSheet,
      dados_linha: formData,
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        showAlert("success", data.message);
        bootstrap.Modal.getInstance(
          document.getElementById("addModal")
        ).hide();
        // Recarregar página para mostrar nova linha
        setTimeout(() => location.reload(), 1500);
      } else {
        showAlert("danger", data.message);
      }
    })
    .catch((error) => {
      console.error("Erro ao adicionar:", error);
      showAlert("danger", "Erro ao adicionar: " + error.message);
    })
    .finally(() => {
      // Restaurar botão
      saveBtn.innerHTML = originalText;
      saveBtn.disabled = false;
    });
}

// Exportar tabela
function exportarTabela(tableId) {
  const table = document.getElementById(`table-${tableId}`);
  let csv = [];

  // Headers
  const headers = Array.from(table.querySelectorAll("thead th"))
    .map((th) => th.textContent.trim())
    .filter((header) => header !== "Ações");
  csv.push(headers.join(","));

  // Rows
  const rows = table.querySelectorAll("tbody tr");
  rows.forEach((row) => {
    const cells = Array.from(row.querySelectorAll("td"))
      .slice(0, -1) // Remove última coluna (ações)
      .map((td) => td.textContent.trim());
    csv.push(cells.join(","));
  });

  // Download
  const csvContent = csv.join("\n");
  const blob = new Blob(["\ufeff" + csvContent], { type: "text/csv;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${tableId}.csv`;
  a.click();
  window.URL.revokeObjectURL(url);
}

// Alertas: usa o showAlert global (static/js/main.js), que já é carregado
// antes deste arquivo. Havia aqui um fallback próprio, morto na prática
// (o global sempre existe) e que ainda criava um #alert-container com
// z-index arbitrário por cima dos modais.

// Adicionar event listeners quando o documento estiver pronto
document.addEventListener("DOMContentLoaded", function () {
  // Event listeners para botões de editar linha
  document.querySelectorAll(".btn-editar-linha").forEach((button) => {
    button.addEventListener("click", function () {
      const sheetName = this.getAttribute("data-sheet");
      const linhaId = this.getAttribute("data-linha");
      editarLinha(sheetName, linhaId);
    });
  });

  // Delegação: campos editáveis, botão salvar do modal e botão salvar do
  // formulário de nova linha. Antes eram `onclick="..."` inline no template,
  // que só funciona se a função estiver no escopo global — e as funções deste
  // módulo são privadas de propósito. A delegação também cobre as linhas
  // criadas depois (após "Adicionar"), que os listeners diretos ignoravam.
  document.addEventListener("click", (event) => {
    const campo = event.target.closest(".editable-field");
    if (campo) {
      event.preventDefault();
      editarCampo(campo);
      return;
    }
    if (event.target.closest("#editarSalvarBtn")) {
      event.preventDefault();
      salvarEdicao();
      return;
    }
    if (event.target.closest("#addModalSaveBtn")) {
      event.preventDefault();
      salvarNovaLinha();
    }
  });

  // Event listeners para botões de excluir linha
  document.querySelectorAll(".btn-excluir-linha").forEach((button) => {
    button.addEventListener("click", function () {
      const sheetName = this.getAttribute("data-sheet");
      const linhaId = this.getAttribute("data-linha");
      excluirLinha(sheetName, linhaId);
    });
  });

  // Event listeners para botões de adicionar linha
  document.querySelectorAll(".btn-adicionar-linha").forEach((button) => {
    button.addEventListener("click", function () {
      const sheetName = this.getAttribute("data-sheet");
      adicionarLinha(sheetName);
    });
  });

  // Event listeners para botões de exportar tabela
  document.querySelectorAll(".btn-exportar-tabela").forEach((button) => {
    button.addEventListener("click", function () {
      const tableId = this.getAttribute("data-table-id");
      exportarTabela(tableId);
    });
  });

  // Event listeners para links de mover item
  document.querySelectorAll(".mover-item").forEach((link) => {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      const sheetOrigem = this.getAttribute("data-sheet-origem");
      const sheetDestino = this.getAttribute("data-sheet-destino");
      const linhaId = this.getAttribute("data-linha");
      moverItem(sheetOrigem, sheetDestino, linhaId);
    });
  });

  // Event listener para resetar modal quando fechado
  const addModal = document.getElementById("addModal");
  if (addModal) {
    addModal.addEventListener("hidden.bs.modal", function () {
      resetAddModal();
      // Limpar formulário
      const inputs = document.querySelectorAll("#addFormFields input");
      inputs.forEach((input) => {
        input.value = "";
        input.classList.remove("is-invalid");
      });
    });
  }
});

// Editar linha completa
function editarLinha(sheetName, linhaId) {
  console.log("DEBUG editarLinha:", { sheetName, linhaId });

  currentSheet = sheetName;
  currentLineId = linhaId;

  // Encontrar a linha na tabela usando a aba ativa ou específica
  const sanitizedSheetName = sheetName.replace(/ /g, "-").toLowerCase();
  const row = document.querySelector(
    `#${sanitizedSheetName} tr[data-linha="${linhaId}"]`
  );

  if (!row) {
    console.error(
      "Linha não encontrada:",
      linhaId,
      "na tabela:",
      sanitizedSheetName
    );
    showAlert("danger", "Linha não encontrada");
    return;
  }

  // Pegar dados atuais da linha
  const tableId = `table-${sanitizedSheetName}`;
  console.log("DEBUG tableId:", tableId);

  const table = document.getElementById(tableId);
  if (!table) {
    console.error("Tabela não encontrada:", tableId);
    showAlert("danger", "Tabela não encontrada");
    return;
  }

  const headers = Array.from(table.querySelectorAll("thead th"))
    .map((th) => th.textContent.trim())
    .filter((header) => header !== "#" && header !== "Ações");

  console.log("DEBUG headers:", headers);

  // Pegar valores atuais da linha específica
  const currentData = {};
  const cells = row.querySelectorAll("td");
  let cellIndex = 1; // Pular primeira coluna (#)

  console.log("DEBUG cells count:", cells.length);

  headers.forEach((header) => {
    if (
      !header.includes("Ver Imagem") &&
      !header.includes("Caminho da Imagem")
    ) {
      const cell = cells[cellIndex];
      if (cell) {
        const editableField = cell.querySelector(".editable-field");
        if (editableField) {
          currentData[header] =
            editableField.getAttribute("data-original") || "";
        } else {
          const cellText = cell.textContent.trim();
          currentData[header] = cellText === "-" ? "" : cellText;
        }
      }
      cellIndex++;
    } else if (header.includes("Caminho da Imagem")) {
      // Para campos de caminho de imagem, manter valor existente
      const cell = cells[cellIndex];
      if (cell) {
        const cellText = cell.textContent.trim();
        currentData[header] = cellText === "-" ? "" : cellText;
      }
      cellIndex++;
    }
    // Para "Ver Imagem", não incrementar cellIndex pois não há célula correspondente
  });

  console.log("DEBUG currentData:", currentData);

  // Gerar formulário de edição completa
  let formHtml = "";
  headers.forEach((header) => {
    if (
      !header.includes("Ver Imagem") &&
      !header.includes("Caminho da Imagem")
    ) {
      const isRequired = ["Produto", "Arquivo"].includes(header);
      const currentValue = currentData[header] || "";

      formHtml += `
        <div class="mb-3">
          <label class="form-label">
            ${header} ${
        isRequired ? '<span class="text-danger">*</span>' : ""
      }
          </label>
          <input 
            type="text" 
            class="form-control" 
            name="${header}" 
            value="${currentValue}"
            placeholder="Digite ${header.toLowerCase()}"
            ${isRequired ? "required" : ""}
          >
          <div class="invalid-feedback">
            Este campo é obrigatório
          </div>
        </div>
      `;
    }
  });

  // Atualizar modal de adição para ser usado como edição
  document.getElementById("addFormFields").innerHTML = formHtml;

  // Alterar título e botão do modal
  const modalTitle = document.querySelector("#addModal .modal-title");
  const saveBtn = document.querySelector("#addModal .btn-success");

  modalTitle.innerHTML =
    '<i class="bi bi-pencil-square me-2"></i>Editar Linha Completa';
  saveBtn.innerHTML = '<i class="bi bi-check-lg"></i> Salvar Alterações';
  saveBtn.setAttribute("onclick", "salvarEdicaoCompleta()");

  exibirImagemNoModal(row, "addModalImagePreviewContainer", "addModalImagePreview");

  const modal = new bootstrap.Modal(document.getElementById("addModal"));
  modal.show();
}

// A visualização de imagem (clique em ".view-image-btn" -> abrir #imageModal)
// é tratada por static/js/relatorio.min.js (setupImageModalOptimizations),
// carregado no fim deste arquivo - a mesma função já usada por
// relatorio.html e historico_execucao.html. Antes havia uma cópia própria
// dessa lógica aqui, divergente das outras duas.

// ========================================
// REANÁLISE SELETIVA DO MESTRE (aba atual / linhas marcadas)
// ========================================
// O relatório geral (Excel) não tem execução: a seleção é por IMAGEM
// (basename do Caminho/Arquivo) via POST /api/reanalisar_mestre, com
// progresso em GET /api/progresso_reanalise.
document.addEventListener("DOMContentLoaded", function () {
  function abaAtiva() {
    const pane = document.querySelector("#sheetTabsContent .tab-pane.active");
    if (!pane) return null;
    const tabela = pane.querySelector("table");
    if (!tabela) return null;
    const primeiraLinha = tabela.querySelector("tbody tr[data-sheet]");
    return primeiraLinha ? primeiraLinha.getAttribute("data-sheet") : null;
  }

  function atualizarContadorMestre() {
    const total = document.querySelectorAll(".reanalise-check:checked").length;
    const contador = document.getElementById("reanaliseMestreContador");
    if (contador) contador.textContent = total;
  }

  document.querySelectorAll(".reanalise-check-all").forEach(function (todos) {
    todos.addEventListener("change", function () {
      const tabela = todos.closest("table");
      if (tabela) {
        tabela.querySelectorAll(".reanalise-check").forEach(function (cb) {
          cb.checked = todos.checked;
        });
      }
      atualizarContadorMestre();
    });
  });
  document.querySelectorAll(".reanalise-check").forEach(function (cb) {
    cb.addEventListener("change", atualizarContadorMestre);
  });

  async function dispararReanaliseMestre(body, rotulo) {
    if (!window.ReanaliseSelecao) {
      alert("Módulo de reanálise não carregado. Recarregue a página.");
      return;
    }
    if (!window.ReanaliseSelecao.confirmarEscopo(rotulo)) return;
    try {
      const data = await window.ReanaliseSelecao.post("/api/reanalisar_mestre", body);
      alert(data.message + " A página será recarregada ao concluir.");
      window.ReanaliseSelecao.acompanhar({
        onConcluido: function () {
          alert("Reanálise concluída!");
          window.location.reload();
        },
        onErro: function (erro) {
          alert("Erro na reanálise: " + erro);
        },
      });
    } catch (e) {
      alert("Erro: " + (e.message || e));
    }
  }

  function reanalisarMarcados() {
    const imgs = window.ReanaliseSelecao
      ? window.ReanaliseSelecao.selecionados().map(function (s) { return s.imagem; })
      : [];
    const validos = imgs.filter(function (v) { return v && v !== "N/A" && v !== "-" && v !== "nan"; });
    if (!validos.length) {
      alert("Marque pelo menos uma linha com imagem para reanalisar.");
      return;
    }
    dispararReanaliseMestre({ imagens: validos }, validos.length + " imagem(ns) marcada(s) do relatório geral");
  }

  function reanalisarAba() {
    const aba = abaAtiva();
    if (!aba) {
      alert("Nenhuma aba ativa para reanalisar.");
      return;
    }
    dispararReanaliseMestre({ categorias: [aba] }, "a aba " + aba + " do relatório geral");
  }

  ["btnReanalisarMestreMarcados", "btnReanalisarMestreMarcadosMenu"].forEach(function (id) {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener("click", function (ev) { ev.preventDefault(); reanalisarMarcados(); });
  });
  const btnAba = document.getElementById("btnReanalisarMestreAba");
  if (btnAba) btnAba.addEventListener("click", function (ev) { ev.preventDefault(); reanalisarAba(); });
});
