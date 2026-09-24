/* configuracoes.js - Configuracoes: modelos por provedor, testes, backup.
   Extraido de configuracoes.html (era <script> inline: sem cache,
   bloqueava o parse). Carregado com defer + static_v. */
// Configurações de modelos por provedor (apenas com suporte a visão/imagens)
const MODELOS_POR_PROVEDOR = {
  'gemini': [
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-3-flash'
  ],
  'openai': [
    'gpt-4o',
    'gpt-4o-mini',
    'gpt-4-turbo',
    'gpt-4-vision-preview'
  ],
  'claude': [
    'claude-3-5-sonnet-20241022',
    'claude-3-5-haiku-20241022',
    'claude-3-opus-20240229',
    'claude-3-sonnet-20240229',
    'claude-3-haiku-20240307'
  ],
  'openrouter': [
    'anthropic/claude-3.5-sonnet',
    'google/gemini-pro-1.5',
    'openai/gpt-4o',
    'openai/gpt-4-turbo',
    'meta-llama/llama-3.2-90b-vision',
    'qwen/qwen-2-vl-72b'
  ]
};

document.addEventListener('DOMContentLoaded', function() {
  const apiProvider = document.getElementById('apiProvider');
  const apiModel = document.getElementById('apiModel');
  const configApiForm = document.getElementById('configApiForm');
  const configAdvancedForm = document.getElementById('configAdvancedForm');

  // Atualizar modelos quando provedor mudar - busca dinâmica via API
  async function atualizarModelos() {
    const provider = apiProvider.value;
    
    // Mostrar loading
    apiModel.innerHTML = '<option value="">Carregando modelos...</option>';
    apiModel.disabled = true;
    
    try {
      // Buscar modelos disponíveis da API em tempo real
      const response = await fetch(`/api/listar_modelos/${provider}`);
      const data = await response.json();
      
      if (data.success && data.modelos && data.modelos.length > 0) {
        // Limpar e popular com modelos reais
        apiModel.innerHTML = '';
        data.modelos.forEach(modelo => {
          const option = document.createElement('option');
          option.value = modelo;
          option.textContent = modelo;
          apiModel.appendChild(option);
        });
        
        // Tentar manter seleção anterior ou selecionar primeiro
        const modeloAtualSelecionado = apiModel.getAttribute('data-selected-model');
        if (modeloAtualSelecionado && data.modelos.includes(modeloAtualSelecionado)) {
          apiModel.value = modeloAtualSelecionado;
        } else if (data.modelos.length > 0) {
          apiModel.value = data.modelos[0];
        }
      } else {
        // Fallback para lista estática em caso de erro
        const modelos = MODELOS_POR_PROVEDOR[provider] || [];
        apiModel.innerHTML = '';
        modelos.forEach(modelo => {
          const option = document.createElement('option');
          option.value = modelo;
          option.textContent = modelo;
          apiModel.appendChild(option);
        });
        
        if (modelos.length > 0) {
          apiModel.value = modelos[0];
        }
      }
    } catch (error) {
      console.error('Erro ao buscar modelos:', error);
      
      // Fallback para lista estática
      const modelos = MODELOS_POR_PROVEDOR[provider] || [];
      apiModel.innerHTML = '';
      modelos.forEach(modelo => {
        const option = document.createElement('option');
        option.value = modelo;
        option.textContent = modelo;
        apiModel.appendChild(option);
      });
      
      if (modelos.length > 0) {
        apiModel.value = modelos[0];
      }
    } finally {
      apiModel.disabled = false;
    }
  }

  // Mostrar/ocultar campos de API
  function toggleApiFields() {
    const provider = apiProvider.value;
    
    // Ocultar todos
    document.querySelectorAll('.api-key-group').forEach(el => {
      el.style.display = 'none';
    });
    
    // Mostrar o relevante
    if (provider === 'gemini') {
      document.getElementById('geminiKeyGroup').style.display = 'block';
    } else if (provider === 'openai') {
      document.getElementById('openaiKeyGroup').style.display = 'block';
    } else if (provider === 'claude') {
      document.getElementById('claudeKeyGroup').style.display = 'block';
    } else if (provider === 'openrouter') {
      document.getElementById('openrouterKeyGroup').style.display = 'block';
    }
  }

  // Event listeners
  apiProvider.addEventListener('change', function() {
    atualizarModelos();
    toggleApiFields();
  });

  // Inicializar
  atualizarModelos();
  toggleApiFields();

  // Salvar configurações da API
  configApiForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const formData = {
      api: {
        provider: apiProvider.value,
        modelo_selecionado: apiModel.value,
        gemini_api_key: document.getElementById('geminiApiKey').value,
        openai_api_key: document.getElementById('openaiApiKey').value,
        anthropic_api_key: document.getElementById('anthropicApiKey').value,
        openrouter_api_key: document.getElementById('openrouterApiKey').value
      }
    };

    salvarConfiguracao(formData);
  });

  // Salvar configurações avançadas
  configAdvancedForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const formData = {
      processamento: {
        modo_extracao: document.getElementById('modoExtracao').value,
        temperatura: parseFloat(document.getElementById('temperatura').value),
        max_tokens: parseInt(document.getElementById('maxTokens').value),
        timeout: parseInt(document.getElementById('timeout').value),
        tamanho_lote: parseInt(document.getElementById('tamanhoLote').value),
        max_workers: parseInt(document.getElementById('maxWorkers').value),
        request_delay: parseFloat(document.getElementById('requestDelay').value)
      }
    };

    salvarConfiguracao(formData);
  });

  // Função comum para salvar
  function salvarConfiguracao(data) {
    fetch('/salvar_configuracao', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        showAlert('success', '✅ ' + data.message);
      } else {
        showAlert('danger', '❌ ' + data.message);
      }
    })
    .catch(error => {
      showAlert('danger', '❌ Erro ao salvar: ' + error);
    });
  }

  // Limpar dados
  document.querySelectorAll('.clear-data-btn').forEach(button => {
    button.addEventListener('click', function() {
      const tipo = this.getAttribute('data-type');
      let confirmMsg = `Tem certeza que deseja limpar ${tipo}? Esta ação não pode ser desfeita.`;
      if (tipo === 'relatorio') {
        confirmMsg = 'Isso vai APAGAR o relatório Excel atual (Avarias, Uso Interno e Erros de Análise) - ' +
          'sem backup automático. Se ainda precisa dos dados, cancele e baixe o relatório primeiro ' +
          '(botão "Baixar Excel" na aba Relatório). Continuar mesmo assim?';
      } else if (tipo === 'imagens') {
        confirmMsg = 'Tem certeza que deseja apagar TODAS as imagens? ' +
          'Itens antigos no Histórico que referenciam essas imagens vão perder o botão "Ver Imagem" para sempre. ' +
          'Esta ação não pode ser desfeita.';
      } else if (tipo === 'reprocessar_tudo') {
        confirmMsg = 'Isso apaga as imagens da pasta e o histórico de processamento (log_mestre.txt), ' +
          'deixando tudo pronto para enviar e processar do zero. ' +
          'O relatório Excel e o Histórico NÃO são apagados. Continuar?';
      } else if (tipo === 'exportacoes') {
        confirmMsg = 'Isso vai apagar exportações antigas em resultados/, mantendo só as 30 mais recentes de cada tipo. Continuar?';
      }

      if (confirm(confirmMsg)) {
        fetch('/limpar_dados', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({tipo: tipo})
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            showAlert('success', '✅ ' + data.message);
            setTimeout(() => location.reload(), 1500);
          } else {
            showAlert('danger', '❌ ' + data.message);
          }
        })
        .catch(error => {
          showAlert('danger', '❌ Erro: ' + error);
        });
      }
    });
  });
});

// Toggle visibilidade de senha
function togglePasswordVisibility(inputId) {
  const input = document.getElementById(inputId);
  const button = input.nextElementSibling;
  const icon = button.querySelector('i');
  
  if (input.type === 'password') {
    input.type = 'text';
    icon.classList.remove('bi-eye');
    icon.classList.add('bi-eye-slash');
  } else {
    input.type = 'password';
    icon.classList.remove('bi-eye-slash');
    icon.classList.add('bi-eye');
  }
}


// Criar backup
function criarBackup() {
  window.location.href = '/download_relatorio';
  showAlert('info', 'ℹ️ Fazendo backup do relatório...');
}

// Função para mostrar alertas
function showAlert(type, message) {
  const alertDiv = document.createElement('div');
  alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3`;
  alertDiv.style.zIndex = '9999';
  alertDiv.style.minWidth = '300px';
  alertDiv.innerHTML = `
    ${message}
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  `;
  document.body.appendChild(alertDiv);
  setTimeout(() => alertDiv.remove(), 5000);
}
