/**
 * Modal de visualização de imagem + dados do item.
 *
 * Antes, cada página (relatorio.min.js, index.html, editar_dados.js,
 * historico-execucao.js) tinha a sua própria cópia desse fluxo, e elas
 * divergiram: o modal de imagem existia em 4 templates com o mesmo id.
 * Aqui a lógica é uma só e lê os dados direto da linha da tabela onde o
 * botão "Ver" está, montando a tabela de detalhes.
 *
 * O modal vive em static/index tabs e é declarado nos templates (para não
 * precisar de fetch de HTML); este módulo só o preenche.
 */
(function () {
  "use strict";

  // Colunas que não viram linha na tabela do modal (a própria ação, e o
  // caminho completo do arquivo, que já aparece no cabeçalho).
  const COLUNAS_IGNORADAS = ["ver imagem", "ações", "caminho da imagem"];

  function normalizar(texto) {
    return (texto || "").replace(/\s+/g, " ").trim();
  }

  /** Lê os pares "rótulo: valor" da linha da tabela onde o botão foi clicado. */
  function extrairDadosDaLinha(btn) {
    const linha = btn.closest("tr");
    const tabela = btn.closest("table");
    if (!linha || !tabela) return [];

    const cabecalhos = Array.from(tabela.querySelectorAll("thead th")).map((th) =>
      normalizar(th.textContent.replace(/[\u2000-\u3300\u2190-\u21FF]/g, ""))
    );

    const celulas = Array.from(linha.children).filter((c) => c.tagName === "TD");
    const lista = [];

    celulas.forEach((td, i) => {
      const rotulo = cabecalhos[i] || "";
      const rotuloLower = rotulo.toLowerCase();
      if (COLUNAS_IGNORADAS.some((c) => rotuloLower.includes(c))) return;

      const texto = normalizar(td.textContent);
      if (!texto || texto === "-") return;

      const item = { rotulo: rotulo || `Coluna ${i + 1}`, valor: texto };

      // Caminho completo do arquivo ocupa várias linhas no celular e é
      // redundante — o nome do arquivo identifica a imagem. O caminho completo
      // continua no title, para quem precisar conferir a pasta.
      if (rotuloLower.includes("caminho")) {
        item.valor = texto.split(/[\\/]/).pop() || texto;
        item.titulo = texto;
      }

      lista.push(item);
    });

    return lista;
  }

  function preencherTabela(container, dados) {
    if (!container) return;
    container.innerHTML = "";

    if (dados.length === 0) {
      const vazio = document.createElement("p");
      vazio.className = "imagem-modal-vazio mb-0";
      vazio.textContent = "Sem dados adicionais para este item.";
      container.appendChild(vazio);
      return;
    }

    const tabela = document.createElement("table");
    tabela.className = "imagem-modal-tabela";

    const tbody = document.createElement("tbody");
    dados.forEach((item) => {
      const tr = document.createElement("tr");

      const th = document.createElement("th");
      th.setAttribute("scope", "row");
      th.textContent = item.rotulo;

      const td = document.createElement("td");
      td.textContent = item.valor;
      td.title = item.titulo || item.valor;

      tr.appendChild(th);
      tr.appendChild(td);
      tbody.appendChild(tr);
    });

    tabela.appendChild(tbody);
    container.appendChild(tabela);
  }

  function abrirModal(btn) {
    const imagePath = btn.getAttribute("data-image");
    if (!imagePath || imagePath === "N/A" || imagePath === "-") {
      if (window.AnalisadorAvarias && window.AnalisadorAvarias.showAlert) {
        window.AnalisadorAvarias.showAlert("warning", "Imagem não disponível para este item.");
      }
      return;
    }

    const modalEl = document.getElementById("imageModal");
    if (!modalEl || typeof bootstrap === "undefined") return;

    const img = document.getElementById("modalImage");
    const erro = document.getElementById("imageLoadError");
    const nomeEl = document.getElementById("imageModalFilename");
    const download = document.getElementById("downloadImageBtn");
    const dadosEl = document.getElementById("imageModalDados");

    const filename = decodeURIComponent(imagePath.split("/").pop() || "Imagem");

    if (nomeEl) {
      nomeEl.textContent = filename;
      nomeEl.title = filename;
    }

    // A tabela é montada a partir da linha; em telas sem tabela (ex.: um
    // botão solto) ela fica com a mensagem de vazio.
    preencherTabela(dadosEl, extrairDadosDaLinha(btn));

    if (erro) erro.classList.add("d-none");
    if (img) {
      img.classList.remove("d-none");
      img.src = imagePath;
      img.alt = filename;
      img.onerror = () => {
        img.classList.add("d-none");
        if (erro) erro.classList.remove("d-none");
      };
    }

    if (download) {
      download.href = imagePath;
      download.download = filename;
    }

    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  // Delegação única: funciona para linhas criadas depois (edição, "Adicionar",
  // filtro de busca e troca de página, que recriam as <tr>).
  document.addEventListener("click", (event) => {
    const btn = event.target.closest(".view-image-btn");
    if (!btn) return;
    event.preventDefault();
    abrirModal(btn);
  });

  window.AnalisadorAvarias = window.AnalisadorAvarias || {};
  window.AnalisadorAvarias.abrirModalImagem = abrirModal;
})();
