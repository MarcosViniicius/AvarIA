/**
 * Reanálise seletiva: um item, vários ou todos.
 *
 * Helpers compartilhados pelas telas de exibição (Relatório, detalhe da
 * execução no Histórico) e de edição geral (Editar Dados). Cada página
 * marca suas linhas com checkboxes `reanalise-check` e declara a ação com
 * atributos data-*; este módulo só coleta, envia e acompanha.
 *
 * Convenções:
 * - Checkbox de linha: class="reanalise-check" value="<id ou nome>" +
 *   data-categoria="<Aba>" (+ data-imagem="<basename>" quando value é id).
 * - Botão/ação: data-reanalise-url="<POST>" data-reanalise-modo="ids|imagens|categorias"
 *   data-reanalise-categoria="<Aba>" (só modo categorias).
 */
(function () {
  "use strict";

  function selecionados(container) {
    const root = container || document;
    return Array.from(root.querySelectorAll(".reanalise-check:checked"))
      .filter((cb) => !cb.disabled)
      .map((cb) => ({
        valor: cb.value,
        categoria: cb.getAttribute("data-categoria") || "",
        imagem: cb.getAttribute("data-imagem") || cb.value,
      }));
  }

  function contarSelecionados(container) {
    return selecionados(container).length;
  }

  async function post(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error("Resposta inválida do servidor (" + resp.status + ")");
    }
    if (!resp.ok || data.success === false) {
      throw new Error(data.message || data.error || ("HTTP " + resp.status));
    }
    return data;
  }

  // Polling do GET /api/progresso_reanalise até concluir ou falhar.
  function acompanhar(opts) {
    const o = opts || {};
    const intervalo = o.intervaloMs || 2000;
    const timer = setInterval(async () => {
      try {
        const r = await fetch("/api/progresso_reanalise");
        const d = await r.json();
        if (typeof o.onProgresso === "function") o.onProgresso(d);
        if (d.erro) {
          clearInterval(timer);
          if (typeof o.onErro === "function") o.onErro(d.erro);
        } else if (!d.ativo && (d.progresso || 0) >= 100) {
          clearInterval(timer);
          if (typeof o.onConcluido === "function") o.onConcluido(d.resultado || {});
        }
      } catch (e) {
        clearInterval(timer);
        if (typeof o.onErro === "function") o.onErro(String((e && e.message) || e));
      }
    }, intervalo);
    return timer;
  }

  function confirmarEscopo(rotulo) {
    return confirm(
      "Reanalisar " + rotulo + "?\n\n" +
      "A IA vai processar de novo as imagens e os resultados entram como nova versão (histórico) " +
      "ou substituem as linhas no relatório (mestre). Continuar?"
    );
  }

  window.ReanaliseSelecao = {
    selecionados: selecionados,
    contarSelecionados: contarSelecionados,
    post: post,
    acompanhar: acompanhar,
    confirmarEscopo: confirmarEscopo,
  };
})();
