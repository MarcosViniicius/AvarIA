/**
 * Acoes da pagina /relatorio: unificacao, exportacao e reanalise de erros.
 *
 * Mantido separado de historico-execucao.js de proposito: as duas paginas
 * tem funcoes com o MESMO NOME e comportamentos DIFERENTES (ex.:
 * iniciarReanalise aqui reprocessa so os erros; la reprocessa a execucao
 * inteira criando versao). Unificar criaria colisao de globais.
 *
 * Estrutura: blocos DOMContentLoaded de nivel superior (o script usa `defer`,
 * entao todos disparam antes do evento). Nao aninhar um dentro do outro:
 * um listener registrado durante o dispatch do evento nunca dispara.
 */
// ========================================
// MODAL DE UNIFICAÇÃO - FUNÇÕES
// ========================================

let modalUnificacao = null;
let downloadUrl = null;
let unificacionContenido = '';

// Inicializar modal de unificação
document.addEventListener('DOMContentLoaded', function() {
  console.log('🔧 Inicializando modal de unificação...');
  const modalElement = document.getElementById('unificacaoModal');
  if (modalElement) {
    console.log('✅ Elemento do modal de unificação encontrado');
    // Garantir que bootstrap está disponível
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      modalUnificacao = new bootstrap.Modal(modalElement);
      console.log('✅ Modal de unificação criado com sucesso');
    } else {
      console.warn('⚠️ Bootstrap não disponível para criar modal de unificação');
    }
  } else {
    console.warn('⚠️ Elemento unificacaoModal não encontrado');
  }
  
  // Event listener para botão iniciar unificação
  const btnIniciar = document.getElementById('btnIniciarUnificacao');
  if (btnIniciar) {
    btnIniciar.addEventListener('click', iniciarUnificacao);
    console.log('✅ Event listener adicionado ao botão Iniciar Unificação');
  } else {
    console.warn('⚠️ Botão Iniciar Unificação não encontrado');
  }
  
  // Event listener para botão de download
  const btnDownload = document.getElementById('btnDownloadUnificado');
  if (btnDownload) {
    btnDownload.addEventListener('click', function() {
      if (downloadUrl) {
        window.location.href = downloadUrl;
      }
    });
    console.log('✅ Event listener adicionado ao botão Download');
  } else {
    console.warn('⚠️ Botão Download não encontrado');
  }
});

window.abrirModalUnificacao = async function() {
  console.log('🔄 Tentando abrir modal de unificação...');
  
  // Garantir que o modal está inicializado
  if (!modalUnificacao) {
    console.log('⚠️ Modal não inicializado, tentando criar...');
    const modalElement = document.getElementById('unificacaoModal');
    if (modalElement && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      modalUnificacao = new bootstrap.Modal(modalElement);
      console.log('✅ Modal criado com sucesso');
    } else {
      console.error('❌ Não foi possível criar o modal:', { 
        modalElement: !!modalElement, 
        bootstrap: typeof bootstrap !== 'undefined',
        Modal: typeof bootstrap !== 'undefined' ? !!bootstrap.Modal : false
      });
      alert('Modal de unificação não está disponível. Por favor, recarregue a página.');
      return;
    }
  }
  
  console.log('✅ Modal disponível, resetando estados...');
  
  // Resetar estados
  const explicacao = document.getElementById('unificacaoExplicacao');
  const processando = document.getElementById('unificacaoProcessando');
  const resultado = document.getElementById('unificacaoResultado');
  const erro = document.getElementById('unificacaoErro');
  const btnIniciar = document.getElementById('btnIniciarUnificacao');
  const btnCancelar = document.getElementById('btnCancelarUnificacao');
  const btnFechar = document.getElementById('btnFecharUnificacao');
  
  if (explicacao) explicacao.classList.remove('d-none');
  if (processando) processando.classList.add('d-none');
  if (resultado) resultado.classList.add('d-none');
  if (erro) erro.classList.add('d-none');
  if (btnIniciar) btnIniciar.classList.remove('d-none');
  if (btnCancelar) btnCancelar.disabled = false;
  if (btnFechar) btnFechar.disabled = false;
  
  console.log('✅ Abrindo modal e carregando opções...');
  modalUnificacao.show();
  
  // Carregar opções de seções e colunas
  await carregarOpcoesUnificacao();
};

// Carregar opções de seções e colunas para unificação
async function carregarOpcoesUnificacao() {
  try {
    console.log('📡 Carregando opções de unificação...');
    const response = await fetch('/api/opcoes_unificacao');
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('📊 Opções recebidas:', data);
    
    // Preencher seções
    const secoesContainer = document.getElementById('secoesUnificacao');
    secoesContainer.innerHTML = '';
    
    data.secoes.forEach(secao => {
      const div = document.createElement('div');
      div.className = 'form-check';
      div.innerHTML = `
        <input class="form-check-input secao-checkbox-unificacao" type="checkbox" 
               value="${secao}" id="secao_unif_${secao.replace(/\s+/g, '_')}" checked>
        <label class="form-check-label" for="secao_unif_${secao.replace(/\s+/g, '_')}">
          ${secao}
        </label>
      `;
      
      // Event listener para mostrar/ocultar colunas
      const checkbox = div.querySelector('input');
      checkbox.addEventListener('change', function() {
        atualizarColunasUnificacao(data.colunas_por_secao);
      });
      
      secoesContainer.appendChild(div);
    });
    
    // Preencher colunas por seção
    atualizarColunasUnificacao(data.colunas_por_secao);
    
    console.log('✅ Opções de unificação carregadas com sucesso');
  } catch (error) {
    console.error('❌ Erro ao carregar opções de unificação:', error);
    alert('Erro ao carregar opções de unificação: ' + error.message);
  }
}

// Atualizar colunas baseado nas seções selecionadas
function atualizarColunasUnificacao(colunasPorSecao) {
  const colunasContainer = document.getElementById('colunasUnificacao');
  colunasContainer.innerHTML = '';
  
  // Obter seções selecionadas
  const secoesSelecionadas = Array.from(document.querySelectorAll('.secao-checkbox-unificacao:checked'))
    .map(cb => cb.value);
  
  if (secoesSelecionadas.length === 0) {
    colunasContainer.innerHTML = '<div class="text-center text-muted"><small>Selecione pelo menos uma seção</small></div>';
    return;
  }
  
  for (const secao of secoesSelecionadas) {
    const colunas = colunasPorSecao[secao];
    if (!colunas) continue;
    
    const secaoDiv = document.createElement('div');
    secaoDiv.id = `colunas_unif_${secao.replace(/\s+/g, '_')}`;
    secaoDiv.className = 'mb-3';
    secaoDiv.innerHTML = `<h6 class="mb-2">${secao}</h6>`;
    
    const colunasGrid = document.createElement('div');
    colunasGrid.className = 'row';
    
    colunas.forEach(coluna => {
      const div = document.createElement('div');
      div.className = 'col-md-6';
      
      // Verificar se é coluna de caminho ou imagem - desmarcar por padrão
      const colunaLower = coluna.toLowerCase();
      const isImagemOuCaminho = colunaLower.includes('caminho') || 
                                colunaLower.includes('imagem') ||
                                colunaLower.includes('path') ||
                                colunaLower.includes('image') ||
                                colunaLower.includes('ver imagem');
      
      div.innerHTML = `
        <div class="form-check">
          <input class="form-check-input coluna-checkbox-unificacao" type="checkbox" 
                 value="${coluna}" data-secao="${secao}" 
                 id="col_unif_${secao.replace(/\s+/g, '_')}_${coluna.replace(/\s+/g, '_')}" 
                 ${isImagemOuCaminho ? '' : 'checked'}>
          <label class="form-check-label" for="col_unif_${secao.replace(/\s+/g, '_')}_${coluna.replace(/\s+/g, '_')}">
            ${coluna}
          </label>
        </div>
      `;
      colunasGrid.appendChild(div);
    });
    
    secaoDiv.appendChild(colunasGrid);
    colunasContainer.appendChild(secaoDiv);
  }
}

// Funções de seleção de seções e colunas para unificação
window.selecionarTodasSecoesUnificacao = function(selecionar) {
  try {
    console.log('selecionarTodasSecoesUnificacao:', selecionar);
    document.querySelectorAll('.secao-checkbox-unificacao').forEach(cb => {
      cb.checked = selecionar;
      cb.dispatchEvent(new Event('change'));
    });
  } catch (error) {
    console.error('Erro em selecionarTodasSecoesUnificacao:', error);
  }
};

window.selecionarTodasColunasUnificacao = function(selecionar) {
  try {
    console.log('selecionarTodasColunasUnificacao:', selecionar);
    document.querySelectorAll('.coluna-checkbox-unificacao').forEach(cb => {
      cb.checked = selecionar;
    });
  } catch (error) {
    console.error('Erro em selecionarTodasColunasUnificacao:', error);
  }
};

async function iniciarUnificacao() {
  console.log('🚀 Iniciando processo de unificação...');
  try {
    // Verificar se todos os elementos necessários existem
    const elementos = {
      explicacao: document.getElementById('unificacaoExplicacao'),
      processando: document.getElementById('unificacaoProcessando'),
      resultado: document.getElementById('unificacaoResultado'),
      erro: document.getElementById('unificacaoErro'),
      btnIniciar: document.getElementById('btnIniciarUnificacao'),
      btnCancelar: document.getElementById('btnCancelarUnificacao'),
      btnFechar: document.getElementById('btnFecharUnificacao')
    };
    
    // Verificar se todos os elementos foram encontrados
    for (const [nome, elemento] of Object.entries(elementos)) {
      if (!elemento) {
        console.error(`❌ Elemento não encontrado: ${nome}`);
        alert('Erro: Elementos do modal não encontrados. Por favor, recarregue a página.');
        return;
      }
    }
    
    console.log('✅ Todos os elementos encontrados, coletando seleções...');
    
    // Obter formato selecionado
    const formatoSelecionado = document.querySelector('input[name="formatoUnificacao"]:checked')?.value || 'xlsx';
    console.log('📋 Formato selecionado:', formatoSelecionado);
    
    // Obter seções selecionadas
    const secoesSelecionadas = Array.from(document.querySelectorAll('.secao-checkbox-unificacao:checked'))
      .map(cb => cb.value);
    
    console.log('📑 Seções selecionadas:', secoesSelecionadas);
    
    if (secoesSelecionadas.length === 0) {
      alert('Selecione pelo menos uma seção para unificar!');
      return;
    }
    
    // Obter colunas selecionadas por seção
    const colunasPorSecao = {};
    secoesSelecionadas.forEach(secao => {
      const colunas = Array.from(document.querySelectorAll(`.coluna-checkbox-unificacao[data-secao="${secao}"]:checked`))
        .map(cb => cb.value);
      if (colunas.length > 0) {
        colunasPorSecao[secao] = colunas;
      }
    });
    
    console.log('📊 Colunas por seção:', colunasPorSecao);
    
    // Mudar para estado de processamento
    elementos.explicacao.classList.add('d-none');
    elementos.processando.classList.remove('d-none');
    elementos.resultado.classList.add('d-none');
    elementos.erro.classList.add('d-none');
    elementos.btnIniciar.classList.add('d-none');
    elementos.btnCancelar.disabled = true;
    elementos.btnFechar.disabled = true;
    
    console.log('📡 Enviando requisição para API de unificação...');
    
    // Preparar payload
    const payload = {
      formato: formatoSelecionado,
      secoes: secoesSelecionadas,
      colunas: colunasPorSecao
    };
    
    console.log('📦 Payload:', payload);
    
    // Chamar API de unificação
    const response = await fetch('/api/unificar_relatorio', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
    
    console.log('📥 Resposta recebida, status:', response.status);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('📊 Dados recebidos:', data);
    
    if (data.success) {
      console.log('✅ Unificação concluída com sucesso!');
      // Mostrar resultado de sucesso
      elementos.processando.classList.add('d-none');
      elementos.resultado.classList.remove('d-none');
      
      const mensagemElement = document.getElementById('unificacaoResultadoMensagem');
      if (mensagemElement) {
        mensagemElement.textContent = data.message;
      }
      
      // Guardar URL de download
      downloadUrl = data.download_url;
      console.log('💾 URL de download salva:', downloadUrl);
      
      // Guardar contenido generado para visualizar/copiar
      unificacionContenido = data.contenido || '';
      const vistaPreviaEl = document.getElementById('unificacaoVistaPrevia');
      if (vistaPreviaEl) vistaPreviaEl.value = unificacionContenido;
      const btnExpandirOk = document.getElementById('btnExpandirUnificado');
      const btnCopiarOk = document.getElementById('btnCopiarUnificado');
      const areaOk = document.getElementById('unificacaoAreaVistaPrevia');
      if (btnExpandirOk) btnExpandirOk.style.display = 'inline-block';
      if (btnCopiarOk) btnCopiarOk.style.display = 'inline-block';
      if (areaOk) {
        areaOk.classList.add('d-none');
        areaOk.style.display = 'none';
      }
      if (btnExpandirOk) btnExpandirOk.innerHTML = '<i class="bi bi-eye me-1"></i>Expandir para visualizar';
      elementos.btnFechar.disabled = false;
    } else {
      console.error('❌ Erro na unificação:', data.message);
      // Mostrar erro
      mostrarErroUnificacao(data.message || 'Erro desconhecido ao processar unificação.');
    }
    
  } catch (error) {
    console.error('❌ Erro ao iniciar unificação:', error);
    mostrarErroUnificacao('Erro de comunicação com o servidor: ' + error.message);
  }
}

function mostrarErroUnificacao(mensagem) {
  document.getElementById('unificacaoProcessando').classList.add('d-none');
  document.getElementById('unificacaoErro').classList.remove('d-none');
  document.getElementById('unificacaoErroMensagem').textContent = mensagem;
  document.getElementById('btnCancelarUnificacao').disabled = false;
  document.getElementById('btnFecharUnificacao').disabled = false;
}

// Expandir/recolher a vista previa do conteúdo unificado
document.addEventListener('DOMContentLoaded', function() {
  const btnExpandir = document.getElementById('btnExpandirUnificado');
  if (btnExpandir) {
    btnExpandir.addEventListener('click', function() {
      const area = document.getElementById('unificacaoAreaVistaPrevia');
      if (!area) return;
      const oculta = area.classList.contains('d-none') || area.style.display === 'none';
      area.classList.toggle('d-none', !oculta);
      area.style.display = oculta ? 'block' : 'none';
      btnExpandir.innerHTML = oculta
        ? '<i class="bi bi-eye-slash me-1"></i>Recolher'
        : '<i class="bi bi-eye me-1"></i>Expandir para visualizar';
    });
  }
  const btnCopiar = document.getElementById('btnCopiarUnificado');
  if (btnCopiar) {
    btnCopiar.addEventListener('click', function() {
      const campo = document.getElementById('unificacaoVistaPrevia');
      const texto = (campo && campo.value) || unificacionContenido;
      if (!texto) {
        alert('Nada para copiar: o conteúdo unificado está vazio.');
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(function() {
          const anterior = btnCopiar.innerHTML;
          btnCopiar.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copiado!';
          setTimeout(function() { btnCopiar.innerHTML = anterior; }, 1500);
        }).catch(function() {
          copiarFallback(texto, btnCopiar);
        });
      } else {
        copiarFallback(texto, btnCopiar);
      }
    });
  }
  function copiarFallback(texto, btn) {
    const area = document.createElement('textarea');
    area.value = texto;
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand('copy');
      const anterior = btn.innerHTML;
      btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Copiado!';
      setTimeout(function() { btn.innerHTML = anterior; }, 1500);
    } catch (e) {
      alert('Não foi possível copiar automaticamente. Selecione o texto manualmente.');
    }
    document.body.removeChild(area);
  }
});

// ========================================
// FIM MODAL DE UNIFICAÇÃO
// ========================================

// ========================================
// REANÁLISE SELETIVA (um tipo, vários ou todos)
// ========================================
// Sem execução vinculada (relatório via Excel), tudo passa pelo mestre.
// Com execução (caso normal), todos/categoria criam nova versão versionada
// e só as imagens marcadas vão pelo mestre.

function abasVisiveisRelatorio() {
  const abas = new Set();
  document.querySelectorAll('.reanalise-check[data-categoria]').forEach((cb) => {
    if (cb.getAttribute('data-categoria')) abas.add(cb.getAttribute('data-categoria'));
  });
  return Array.from(abas);
}

function acompanharReanaliseExecucao() {
  const intervalo = setInterval(() => {
    fetch('/status')
      .then((r) => r.json())
      .then((data) => {
        const terminou =
          (data.resultado && typeof data.resultado.run_id !== 'undefined') ||
          (data.status || '').includes('Erro');
        if (!terminou) return;
        clearInterval(intervalo);
        const novoRunId = data.resultado && data.resultado.run_id;
        alert('Reanálise concluída! Abrindo a nova versão.');
        window.location.href = novoRunId ? `/historico/execucao/${novoRunId}` : window.location.href;
      })
      .catch(() => clearInterval(intervalo));
  }, 2000);
}

function acompanharReanaliseMestre() {
  if (!window.ReanaliseSelecao) {
    alert('Módulo de reanálise não carregado. Recarregue a página.');
    return;
  }
  alert('Reanálise iniciada! A página será recarregada ao concluir.');
  window.ReanaliseSelecao.acompanhar({
    onConcluido: function () {
      alert('Reanálise concluída!');
      window.location.reload();
    },
    onErro: function (erro) {
      alert('Erro na reanálise: ' + erro);
    },
  });
}

async function reanalisarRelatorio(escopo) {
  try {
    if (!window.ReanaliseSelecao) {
      alert('Módulo de reanálise não carregado. Recarregue a página.');
      return;
    }
    const execId = window.ULTIMA_EXECUCAO_ID || null;

    if (escopo === 'selecionados') {
      const imgs = window.ReanaliseSelecao.selecionados()
        .map((s) => s.imagem)
        .filter((v) => v && v !== 'N/A' && v !== '-' && v !== 'nan');
      if (!imgs.length) {
        alert('Marque pelo menos uma imagem na tabela para reanalisar.');
        return;
      }
      if (!window.ReanaliseSelecao.confirmarEscopo(imgs.length + ' imagem(ns) marcada(s)')) return;
      await window.ReanaliseSelecao.post('/api/reanalisar_mestre', { imagens: imgs });
      acompanharReanaliseMestre();
      return;
    }

    const categorias = escopo === 'todos' ? null : [escopo];
    const rotulo = escopo === 'todos' ? 'todas as imagens desta exibição' : 'a categoria ' + escopo;
    if (execId) {
      if (!confirm('Isso vai rodar a análise de novo em ' + rotulo + ' e criar uma nova versão. Continuar?')) return;
      await window.ReanaliseSelecao.post(
        `/historico/execucao/${execId}/reanalisar`, categorias ? { categorias } : {}
      );
      alert('Reanálise iniciada! Abrindo a nova versão ao concluir.');
      acompanharReanaliseExecucao();
    } else {
      const cats = categorias || abasVisiveisRelatorio();
      if (!cats.length) {
        alert('Nada para reanalisar: nenhuma aba com itens.');
        return;
      }
      if (!window.ReanaliseSelecao.confirmarEscopo(rotulo)) return;
      await window.ReanaliseSelecao.post('/api/reanalisar_mestre', { categorias: cats });
      acompanharReanaliseMestre();
    }
  } catch (error) {
    console.error('Erro na reanálise:', error);
    alert('Erro: ' + error.message);
  }
}

document.addEventListener('DOMContentLoaded', function () {
  const btnTodos = document.getElementById('btnReanalisarRelatorio');
  if (btnTodos) {
    btnTodos.addEventListener('click', function () {
      reanalisarRelatorio('todos');
    });
  }
  document.querySelectorAll('[data-reanalise-rel]').forEach((el) => {
    el.addEventListener('click', function (ev) {
      ev.preventDefault();
      reanalisarRelatorio(el.getAttribute('data-reanalise-rel'));
    });
  });
  const atualizarContador = function () {
    const total = document.querySelectorAll('.reanalise-check:checked').length;
    const contador = document.getElementById('reanaliseRelContador');
    if (contador) contador.textContent = total;
  };
  document.querySelectorAll('.reanalise-check-all').forEach((todos) => {
    todos.addEventListener('change', function () {
      const tabela = todos.closest('table');
      if (tabela) {
        tabela.querySelectorAll('.reanalise-check').forEach((cb) => {
          cb.checked = todos.checked;
        });
      }
      atualizarContador();
    });
  });
  document.querySelectorAll('.reanalise-check').forEach((cb) => {
    cb.addEventListener('change', atualizarContador);
  });
});

// ========================================
// FIM REANÁLISE SELETIVA
// ========================================

// ========================================
// MODAL DE REANÁLISE
// ========================================

document.addEventListener('DOMContentLoaded', function() {
  console.log('🔧 Inicializando modal de reanálise...');
  const btnReanalisar = document.getElementById('btnReanalisarErros');
  const modalElement = document.getElementById('reanaliseModal');
  const progressBar = document.getElementById('reanaliseProgressBar');
  const statusElement = document.getElementById('reanaliseStatus');
  const detalhesElement = document.getElementById('reanaliseDetalhes');
  const resultadoDiv = document.getElementById('reanaliseResultado');
  const resultadoConteudo = document.getElementById('reanaliseResultadoConteudo');
  const btnFechar = document.getElementById('btnFecharReanalise');
  const btnAtualizar = document.getElementById('btnAtualizarRelatorio');
  
  let progressInterval = null;
  let modalReanalise = null;
  
  // Inicializar modal apenas se existir
  if (modalElement) {
    console.log('✅ Elemento do modal de reanálise encontrado');
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      modalReanalise = new bootstrap.Modal(modalElement);
      console.log('✅ Modal de reanálise criado com sucesso');
    } else {
      console.warn('⚠️ Bootstrap não disponível para criar modal de reanálise');
    }
  } else {
    console.warn('⚠️ Elemento reanaliseModal não encontrado');
  }
  
  // Event listener para botão de reanálise
  if (btnReanalisar) {
    btnReanalisar.addEventListener('click', function() {
      console.log('🔄 Botão de reanálise clicado');
      iniciarReanalise();
    });
  } else {
    console.warn('⚠️ Botão de reanálise não encontrado na página');
  }
  
  // Função para iniciar reanálise
  async function iniciarReanalise() {
    console.log('🚀 Iniciando processo de reanálise...');
    try {
      // Garantir que o modal está inicializado
      if (!modalReanalise && modalElement && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        console.log('⚠️ Modal não estava inicializado, criando...');
        modalReanalise = new bootstrap.Modal(modalElement);
      }
      
      if (!modalReanalise) {
        console.error('❌ Modal de reanálise não disponível');
        alert('Modal de reanálise não está disponível. Por favor, recarregue a página.');
        return;
      }
      
      console.log('✅ Modal disponível, resetando interface...');
      
      // Resetar interface
      if (progressBar) {
        progressBar.style.width = '0%';
        progressBar.textContent = '0%';
      }
      if (statusElement) statusElement.textContent = 'Iniciando reanálise...';
      if (detalhesElement) detalhesElement.textContent = 'Preparando para processar itens com erro...';
      if (resultadoDiv) resultadoDiv.classList.add('d-none');
      if (btnFechar) btnFechar.disabled = true;
      if (btnAtualizar) btnAtualizar.classList.add('d-none');
      
      console.log('✅ Abrindo modal...');
      // Mostrar modal
      modalReanalise.show();
      
      console.log('📡 Enviando requisição para API de reanálise...');
      // Iniciar reanálise
      const response = await fetch('/api/reanalisar_erros', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      console.log('📥 Resposta recebida, status:', response.status);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('📊 Dados recebidos:', data);
      
      if (!data.success) {
        throw new Error(data.message || 'Erro ao iniciar reanálise');
      }
      
      console.log('✅ Reanálise iniciada com sucesso, iniciando monitoramento...');
      // Iniciar monitoramento de progresso
      monitorarProgresso();
      
    } catch (error) {
      console.error('❌ Erro ao iniciar reanálise:', error);
      if (statusElement) statusElement.textContent = 'Erro ao iniciar reanálise';
      if (detalhesElement) detalhesElement.textContent = error.message;
      if (btnFechar) btnFechar.disabled = false;
    }
  }
  
  // Função para monitorar progresso
  function monitorarProgresso() {
    progressInterval = setInterval(async () => {
      try {
        const response = await fetch('/api/progresso_reanalise');
        const data = await response.json();
        
        // Atualizar barra de progresso
        const progresso = data.progresso || 0;
        progressBar.style.width = progresso + '%';
        progressBar.textContent = progresso + '%';
        
        // Atualizar status
        statusElement.textContent = data.status || 'Processando...';
        
        // Atualizar detalhes (últimos logs)
        if (data.logs && data.logs.length > 0) {
          const ultimoLog = data.logs[data.logs.length - 1];
          detalhesElement.textContent = ultimoLog;
        }
        
        // Verificar se concluído
        if (!data.ativo && progresso >= 100) {
          clearInterval(progressInterval);
          progressInterval = null;
          
          // Mostrar resultado
          if (data.resultado) {
            mostrarResultado(data.resultado);
          } else if (data.erro) {
            mostrarErro(data.erro);
          }
          
          btnFechar.disabled = false;
          btnAtualizar.classList.remove('d-none');
        }
        
      } catch (error) {
        console.error('Erro ao monitorar progresso:', error);
        clearInterval(progressInterval);
        progressInterval = null;
        btnFechar.disabled = false;
      }
    }, 2000); // Verificar a cada 2 segundos
  }
  
  // Função para mostrar resultado
  function mostrarResultado(resultado) {
    resultadoDiv.classList.remove('d-none');
    
    const html = `
      <p class="mb-2"><strong>Total de arquivos:</strong> ${resultado.total_arquivos || 0}</p>
      <p class="mb-2 text-success"><strong>✅ Corrigidos:</strong> ${resultado.corrigidos || 0}</p>
      <p class="mb-2 text-warning"><strong>⚠️ Ainda com erro:</strong> ${resultado.ainda_com_erro || 0}</p>
      ${resultado.corrigidos > 0 ? '<p class="mt-3 mb-0"><em>Clique em "Atualizar Relatório" para ver as mudanças.</em></p>' : ''}
    `;
    
    resultadoConteudo.innerHTML = html;
    statusElement.textContent = 'Reanálise concluída!';
    detalhesElement.textContent = `${resultado.corrigidos} itens foram corrigidos com sucesso.`;
  }
  
  // Função para mostrar erro
  function mostrarErro(erro) {
    resultadoDiv.classList.remove('d-none');
    resultadoConteudo.innerHTML = `
      <div class="alert alert-danger mb-0">
        <i class="bi bi-exclamation-triangle me-2"></i>
        <strong>Erro:</strong> ${erro}
      </div>
    `;
    statusElement.textContent = 'Erro na reanálise';
  }
  
  // Event listener para botão atualizar
  if (btnAtualizar) {
    btnAtualizar.addEventListener('click', function() {
      window.location.reload();
    });
  }
  
  // Event listener para fechar modal
  if (btnFechar) {
    btnFechar.addEventListener('click', function() {
      if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
      }
      if (modalReanalise) {
        modalReanalise.hide();
      }
    });
  }
  
  // Limpar interval quando modal é fechado
  if (modalElement) {
    modalElement.addEventListener('hidden.bs.modal', function() {
      if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
      }
    });
  }
});

// ========================================
// MODAL DE EXPORTAÇÃO - FUNÇÕES GLOBAIS
// ========================================

let formatoExportacao = 'excel';
let modalExportacao = null;

// Inicializar modal quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function() {
  try {
    const modalElement = document.getElementById('exportacaoModal');
    if (modalElement) {
      modalExportacao = new bootstrap.Modal(modalElement);
      console.log('Modal de exportação inicializado com sucesso');
    } else {
      console.error('Elemento exportacaoModal não encontrado no DOM');
    }
  } catch (error) {
    console.error('Erro ao inicializar modal de exportação:', error);
  }
});

window.abrirModalExportacao = function(formato) {
  try {
    console.log('abrirModalExportacao chamado com formato:', formato);
    
    if (!modalExportacao) {
      // Tentar inicializar se ainda não foi
      const modalElement = document.getElementById('exportacaoModal');
      if (modalElement) {
        modalExportacao = new bootstrap.Modal(modalElement);
      } else {
        alert('Erro: Modal de exportação não está disponível. Recarregue a página.');
        console.error('Modal de exportação não inicializado');
        return;
      }
    }
    
    formatoExportacao = formato;
    const tituloElement = document.getElementById('tituloModalExportacao');
    if (tituloElement) {
      tituloElement.textContent = `Exportar Relatório - ${formato.toUpperCase()}`;
    } else {
      console.error('Elemento tituloModalExportacao não encontrado');
    }
    
    // Carregar seções e colunas disponíveis
    carregarOpcoesExportacao();
    modalExportacao.show();
    
  } catch (error) {
    console.error('Erro em abrirModalExportacao:', error);
    alert('Ocorreu um erro ao abrir o modal de exportação: ' + error.message);
  }
};

async function carregarOpcoesExportacao() {
  try {
    console.log('Carregando opções de exportação...');
    const response = await fetch('/api/opcoes_exportacao');
    
    if (!response.ok) {
      throw new Error(`Erro na requisição: ${response.status} ${response.statusText}`);
    }
    
    const data = await response.json();
    console.log('Opções recebidas:', data);
    
    // Preencher seções
    const secoesContainer = document.getElementById('secoesExportacao');
    secoesContainer.innerHTML = '';
    
    data.secoes.forEach(secao => {
      const div = document.createElement('div');
      div.className = 'form-check';
      
      // Verificar se é seção de erros - desmarcar por padrão
      const secaoLower = secao.toLowerCase();
      const isErro = secaoLower.includes('erro') || secaoLower.includes('error');
      
      div.innerHTML = `
        <input class="form-check-input secao-checkbox" type="checkbox" 
               value="${secao}" id="secao_${secao.replace(/\s+/g, '_')}" 
               ${isErro ? '' : 'checked'}>
        <label class="form-check-label" for="secao_${secao.replace(/\s+/g, '_')}">
          ${secao}
        </label>
      `;
      secoesContainer.appendChild(div);
      
      // Adicionar evento para mostrar/ocultar colunas
      div.querySelector('input').addEventListener('change', function() {
        const colunasDiv = document.getElementById(`colunas_${secao.replace(/\s+/g, '_')}`);
        if (colunasDiv) {
          colunasDiv.style.display = this.checked ? 'block' : 'none';
        }
      });
    });
    
    // Preencher colunas por seção
    const colunasContainer = document.getElementById('colunasExportacao');
    colunasContainer.innerHTML = '';
    
    for (const [secao, colunas] of Object.entries(data.colunas_por_secao)) {
      const secaoDiv = document.createElement('div');
      secaoDiv.id = `colunas_${secao.replace(/\s+/g, '_')}`;
      secaoDiv.className = 'mb-3';
      secaoDiv.innerHTML = `<h6 class="mb-2">${secao}</h6>`;
      
      const colunasGrid = document.createElement('div');
      colunasGrid.className = 'row';
      
      colunas.forEach(coluna => {
        const div = document.createElement('div');
        div.className = 'col-md-6';
        
        // Verificar se é coluna de caminho ou imagem - desmarcar por padrão
        const colunaLower = coluna.toLowerCase();
        const isImagemOuCaminho = colunaLower.includes('caminho') || 
                                  colunaLower.includes('imagem') ||
                                  colunaLower.includes('path') ||
                                  colunaLower.includes('image');
        
        div.innerHTML = `
          <div class="form-check">
            <input class="form-check-input coluna-checkbox" type="checkbox" 
                   value="${coluna}" data-secao="${secao}" 
                   id="col_${secao.replace(/\s+/g, '_')}_${coluna.replace(/\s+/g, '_')}" 
                   ${isImagemOuCaminho ? '' : 'checked'}>
            <label class="form-check-label" for="col_${secao.replace(/\s+/g, '_')}_${coluna.replace(/\s+/g, '_')}">
              ${coluna}
            </label>
          </div>
        `;
        colunasGrid.appendChild(div);
      });
      
      secaoDiv.appendChild(colunasGrid);
      colunasContainer.appendChild(secaoDiv);
    }
    
    console.log('Opções de exportação carregadas com sucesso');
  } catch (error) {
    console.error('Erro ao carregar opções:', error);
    alert('Erro ao carregar opções de exportação: ' + error.message);
  }
}

window.selecionarTodasSecoes = function(selecionar) {
  try {
    console.log('selecionarTodasSecoes:', selecionar);
    document.querySelectorAll('.secao-checkbox').forEach(cb => {
      cb.checked = selecionar;
      cb.dispatchEvent(new Event('change'));
    });
  } catch (error) {
    console.error('Erro em selecionarTodasSecoes:', error);
  }
};

window.selecionarTodasColunas = function(selecionar) {
  try {
    console.log('selecionarTodasColunas:', selecionar);
    document.querySelectorAll('.coluna-checkbox').forEach(cb => {
      cb.checked = selecionar;
    });
  } catch (error) {
    console.error('Erro em selecionarTodasColunas:', error);
  }
};

window.realizarExportacao = function() {
  try {
    console.log('realizarExportacao chamada');
    
    // Obter seções selecionadas
    const secoesSelecionadas = Array.from(document.querySelectorAll('.secao-checkbox:checked'))
      .map(cb => cb.value);
    
    console.log('Seções selecionadas:', secoesSelecionadas);
    
    if (secoesSelecionadas.length === 0) {
      alert('Selecione pelo menos uma seção para exportar!');
      return;
    }
    
    // Obter colunas selecionadas por seção
    const colunasPorSecao = {};
    secoesSelecionadas.forEach(secao => {
      const colunas = Array.from(document.querySelectorAll(`.coluna-checkbox[data-secao="${secao}"]:checked`))
        .map(cb => cb.value);
      colunasPorSecao[secao] = colunas;
    });
    
    console.log('Colunas por seção:', colunasPorSecao);
    
    // Construir URL com parâmetros
    const params = new URLSearchParams();
    params.append('secoes', JSON.stringify(secoesSelecionadas));
    params.append('colunas', JSON.stringify(colunasPorSecao));
    
    // Fazer download
    const url = formatoExportacao === 'excel' 
      ? `/download_relatorio?${params.toString()}`
      : `/download_relatorio_txt?${params.toString()}`;
    
    console.log('URL de download:', url);
    window.location.href = url;
    modalExportacao.hide();
    
  } catch (error) {
    console.error('Erro em realizarExportacao:', error);
    alert('Erro ao realizar exportação: ' + error.message);
  }
};

// Capturar erros globais JavaScript
window.addEventListener('error', function(event) {
  console.error('Erro JavaScript global capturado:', {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    error: event.error
  });
});

window.addEventListener('unhandledrejection', function(event) {
  console.error('Promise rejeitada não tratada:', event.reason);
});
