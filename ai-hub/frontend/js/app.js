/* Lógica principal do AI Hub: colunas de chat, ponte multi-IA e administração de agentes. */
(function () {
  const state = {
    user: null,
    agents: [],
    agentsBySlug: {},
    columns: new Map(), // slug -> { node, ... }
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    if (!text) return '';
    let out = escapeHtml(text);
    out = out.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="code-block"><code>${code}</code></pre>`);
    out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    out = out.replace(/\n/g, '<br>');
    return out;
  }

  function scrollToBottom(el) {
    requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
  }

  function formatDate(sqlTimestamp) {
    try {
      const d = new Date(sqlTimestamp.replace(' ', 'T') + 'Z');
      return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' +
        d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ''; }
  }

  // ------------------------------------------------------------------
  // Boot
  // ------------------------------------------------------------------
  window.AIHub = window.AIHub || {};
  window.AIHub.boot = async function (user) {
    state.user = user;
    document.getElementById('view-auth').classList.add('hidden');
    document.getElementById('view-app').classList.remove('hidden');
    document.getElementById('user-name').textContent = user.username;
    document.getElementById('user-avatar').textContent = user.username.slice(0, 2).toUpperCase();
    document.getElementById('admin-section').classList.toggle('hidden', !user.is_admin);

    await loadAgents();
    renderSidebarAgents();

    let toOpen = [];
    try { toOpen = JSON.parse(localStorage.getItem('aihub_open_columns') || '[]'); } catch (e) { toOpen = []; }
    toOpen = toOpen.filter((s) => s === '__bridge__' || state.agentsBySlug[s]);
    if (!toOpen.length && state.agents.length) toOpen = [state.agents[0].slug];
    toOpen.forEach((slug) => (slug === '__bridge__' ? createBridgeColumn() : createColumn(state.agentsBySlug[slug])));
    renderSidebarAgents();
  };

  async function loadAgents() {
    state.agents = await API.listAgents();
    state.agentsBySlug = {};
    state.agents.forEach((a) => { state.agentsBySlug[a.slug] = a; });
  }

  document.getElementById('logout-btn').addEventListener('click', async () => {
    try { await API.logout(); } catch (e) { /* segue o baile */ }
    state.columns.clear();
    document.getElementById('columns').innerHTML = '';
    localStorage.removeItem('aihub_open_columns');
    window.AIHub.showAuth();
  });

  // ------------------------------------------------------------------
  // Sidebar (mobile) toggle
  // ------------------------------------------------------------------
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('sidebar-scrim');
  document.getElementById('sidebar-toggle').addEventListener('click', () => {
    sidebar.classList.add('is-open');
    scrim.classList.remove('hidden');
  });
  function closeSidebarOnMobile() {
    sidebar.classList.remove('is-open');
    scrim.classList.add('hidden');
  }
  scrim.addEventListener('click', closeSidebarOnMobile);

  // ------------------------------------------------------------------
  // Sidebar: lista de agentes
  // ------------------------------------------------------------------
  function renderSidebarAgents() {
    const list = document.getElementById('agent-list');
    list.innerHTML = '';
    state.agents.forEach((agent) => {
      const btn = document.createElement('button');
      btn.className = 'agent-item' + (state.columns.has(agent.slug) ? ' is-open' : '');
      btn.style.setProperty('--agent-c', agent.color);
      btn.innerHTML = `<span class="agent-item-dot"></span><span class="agent-item-name">${escapeHtml(agent.display_name)}</span>` +
        (agent.has_api_key ? '' : '<span class="agent-item-badge">sem chave</span>');
      btn.addEventListener('click', () => {
        if (state.columns.has(agent.slug)) focusColumn(agent.slug);
        else { createColumn(agent); persistOpenColumns(); renderSidebarAgents(); }
        closeSidebarOnMobile();
      });
      list.appendChild(btn);
    });
  }

  document.getElementById('open-bridge').addEventListener('click', () => {
    if (state.columns.has('__bridge__')) focusColumn('__bridge__');
    else { createBridgeColumn(); persistOpenColumns(); }
    closeSidebarOnMobile();
  });

  function focusColumn(slug) {
    const col = state.columns.get(slug);
    if (col) col.node.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
  }

  function closeColumn(slug) {
    const col = state.columns.get(slug);
    if (!col) return;
    col.node.remove();
    state.columns.delete(slug);
    persistOpenColumns();
    renderSidebarAgents();
  }

  function persistOpenColumns() {
    localStorage.setItem('aihub_open_columns', JSON.stringify(Array.from(state.columns.keys())));
  }

  // ------------------------------------------------------------------
  // Mensagens (elementos compartilhados por chat único e ponte)
  // ------------------------------------------------------------------
  function createMessageEl(role, opts = {}) {
    const div = document.createElement('div');
    div.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-agent') + (opts.isError ? ' msg-error' : '');
    if (opts.agentColor) div.style.setProperty('--agent-c', opts.agentColor);

    let html = '';
    if (opts.speaker) html += `<span class="msg-speaker">${escapeHtml(opts.speaker)}</span>`;
    if (opts.reasoning) {
      html += `<details class="msg-reasoning"><summary>ver raciocínio</summary><div class="msg-reasoning-body">${renderMarkdown(opts.reasoning)}</div></details>`;
    }
    html += '<div class="msg-bubble">';
    if (opts.imageDataUrl) html += `<img class="msg-image" src="${opts.imageDataUrl}" alt="imagem enviada">`;
    html += `<span class="msg-content">${renderMarkdown(opts.content || '')}</span></div>`;
    div.innerHTML = html;
    return div;
  }

  function updateStreamingBubble(el, content, reasoning) {
    let html = '';
    if (reasoning) {
      const stillThinking = !content;
      html += `<details class="msg-reasoning"${stillThinking ? ' open' : ''}><summary>${stillThinking ? 'pensando…' : 'ver raciocínio'}</summary><div class="msg-reasoning-body">${renderMarkdown(reasoning)}</div></details>`;
    }
    if (content) {
      html += `<div class="msg-bubble"><span class="msg-content">${renderMarkdown(content)}</span></div>`;
    } else if (!reasoning) {
      html += '<div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    }
    el.innerHTML = html;
  }

  function renderHistoryList(container, convos, onSelect) {
    if (!convos.length) {
      container.innerHTML = '<div class="history-empty">Nenhuma conversa ainda</div>';
      return;
    }
    container.innerHTML = '';
    convos.forEach((c) => {
      const item = document.createElement('div');
      item.className = 'history-item';
      item.innerHTML = `<span class="history-item-title">${escapeHtml(c.title)}</span><span class="history-item-date">${formatDate(c.created_at)}</span><span class="icon-btn history-item-del">×</span>`;
      item.querySelector('.history-item-title').addEventListener('click', () => onSelect(c.id));
      item.querySelector('.history-item-date').addEventListener('click', () => onSelect(c.id));
      item.querySelector('.history-item-del').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('Apagar esta conversa? Essa ação não pode ser desfeita.')) return;
        try { await API.deleteConversation(c.id); item.remove(); } catch (err) { alert(err.message); }
      });
      container.appendChild(item);
    });
  }

  function closeAllHistoryDropdowns() {
    $$('.history-dropdown').forEach((d) => d.classList.add('hidden'));
  }

  // ------------------------------------------------------------------
  // Coluna de chat com um único agente
  // ------------------------------------------------------------------
  function createColumn(agent) {
    if (state.columns.has(agent.slug)) return state.columns.get(agent.slug);
    const node = document.getElementById('tpl-column').content.firstElementChild.cloneNode(true);
    node.dataset.slug = agent.slug;
    node.style.setProperty('--agent-c', agent.color);
    node.querySelector('.column-name').textContent = agent.display_name;
    node.querySelector('.column-model').textContent = agent.model;

    const messagesEl = node.querySelector('.messages');
    const form = node.querySelector('.composer');
    const textarea = node.querySelector('.composer-input');
    const sendBtn = node.querySelector('.send-btn');
    const attachBtn = node.querySelector('.attach-btn');
    const fileInput = node.querySelector('.file-input');
    const imagePreview = node.querySelector('.image-preview');
    const historyDropdown = node.querySelector('.history-dropdown');

    if (agent.supports_vision) attachBtn.classList.remove('hidden');

    const col = { slug: agent.slug, agent, node, messagesEl, conversationId: null, pendingImage: null };

    textarea.addEventListener('input', () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });
    textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = textarea.value.trim();
      if (!text || sendBtn.disabled) return;
      const img = col.pendingImage;
      textarea.value = '';
      textarea.style.height = 'auto';
      clearImagePreview();
      sendMessage(col, text, img);
    });

    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      const file = fileInput.files[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) { alert('Imagem muito grande (máximo 5MB).'); fileInput.value = ''; return; }
      const reader = new FileReader();
      reader.onload = () => {
        col.pendingImage = reader.result;
        imagePreview.innerHTML = `<img src="${reader.result}" alt=""><span class="image-preview-remove">×</span>`;
        imagePreview.classList.remove('hidden');
        imagePreview.querySelector('.image-preview-remove').addEventListener('click', clearImagePreview);
      };
      reader.readAsDataURL(file);
    });
    function clearImagePreview() {
      col.pendingImage = null;
      imagePreview.innerHTML = '';
      imagePreview.classList.add('hidden');
      fileInput.value = '';
    }

    node.querySelector('[data-action="close"]').addEventListener('click', () => closeColumn(agent.slug));
    node.querySelector('[data-action="new"]').addEventListener('click', () => {
      col.conversationId = null;
      messagesEl.innerHTML = '';
      historyDropdown.classList.add('hidden');
    });
    node.querySelector('[data-action="history"]').addEventListener('click', async () => {
      const willOpen = historyDropdown.classList.contains('hidden');
      closeAllHistoryDropdowns();
      if (!willOpen) return;
      historyDropdown.classList.remove('hidden');
      historyDropdown.innerHTML = '<div class="history-empty">Carregando…</div>';
      try {
        const convos = await API.listConversations({ agent_slug: agent.slug, mode: 'single' });
        renderHistoryList(historyDropdown, convos, async (id) => {
          historyDropdown.classList.add('hidden');
          await loadConversationIntoColumn(col, id);
        });
      } catch (err) {
        historyDropdown.innerHTML = '<div class="history-empty">Erro ao carregar histórico</div>';
      }
    });

    state.columns.set(agent.slug, col);
    document.getElementById('columns').appendChild(node);
    scrollToBottom(messagesEl);
    return col;
  }

  async function loadConversationIntoColumn(col, convId) {
    const data = await API.getConversationMessages(convId);
    col.conversationId = convId;
    col.messagesEl.innerHTML = '';
    data.messages.forEach((m) => {
      if (m.role === 'user') {
        col.messagesEl.appendChild(createMessageEl('user', { content: m.content, imageDataUrl: m.image_data_url }));
      } else {
        col.messagesEl.appendChild(createMessageEl('agent', {
          content: m.content, reasoning: m.reasoning, agentColor: col.agent.color,
          isError: m.content.startsWith('[erro'),
        }));
      }
    });
    scrollToBottom(col.messagesEl);
  }

  async function sendMessage(col, text, imageDataUrl) {
    const sendBtn = col.node.querySelector('.send-btn');
    const textarea = col.node.querySelector('.composer-input');

    col.messagesEl.appendChild(createMessageEl('user', { content: text, imageDataUrl }));
    const agentEl = createMessageEl('agent', {});
    agentEl.style.setProperty('--agent-c', col.agent.color);
    col.messagesEl.appendChild(agentEl);
    scrollToBottom(col.messagesEl);

    let content = '', reasoning = '';
    sendBtn.disabled = true;
    textarea.disabled = true;

    await API.streamChat(col.slug, { conversation_id: col.conversationId, message: text, image_data_url: imageDataUrl }, {
      onEvent(evt) {
        if (evt.type === 'content') {
          content += evt.text;
          updateStreamingBubble(agentEl, content, reasoning);
          scrollToBottom(col.messagesEl);
        } else if (evt.type === 'reasoning') {
          reasoning += evt.text;
          updateStreamingBubble(agentEl, content, reasoning);
        } else if (evt.type === 'error') {
          agentEl.classList.add('msg-error');
          agentEl.innerHTML = `<div class="msg-bubble">${escapeHtml(evt.text)}</div>`;
        } else if (evt.type === 'done') {
          col.conversationId = evt.conversation_id;
        }
      },
      onError(msg) {
        agentEl.classList.add('msg-error');
        agentEl.innerHTML = `<div class="msg-bubble">${escapeHtml(msg)}</div>`;
      },
    });

    sendBtn.disabled = false;
    textarea.disabled = false;
    textarea.focus();
  }

  // ------------------------------------------------------------------
  // Coluna da Ponte multi-IA
  // ------------------------------------------------------------------
  function createBridgeColumn() {
    if (state.columns.has('__bridge__')) return state.columns.get('__bridge__');
    const node = document.getElementById('tpl-bridge-column').content.firstElementChild.cloneNode(true);

    const pickerEl = node.querySelector('.bridge-agent-picker');
    const topicEl = node.querySelector('.bridge-topic');
    const roundsEl = node.querySelector('.bridge-rounds');
    const roundsValueEl = node.querySelector('.bridge-rounds-value');
    const startBtn = node.querySelector('.bridge-start-btn');
    const setupEl = node.querySelector('.bridge-setup');
    const patchbayEl = node.querySelector('.bridge-patchbay');
    const transcriptEl = node.querySelector('.bridge-transcript');
    const historyDropdown = node.querySelector('.history-dropdown');

    const selected = new Set();
    state.agents.forEach((agent) => {
      const chip = document.createElement('div');
      chip.className = 'bridge-chip';
      chip.style.setProperty('--agent-c', agent.color);
      chip.innerHTML = `<span class="agent-item-dot"></span>${escapeHtml(agent.display_name)}`;
      chip.addEventListener('click', () => {
        if (selected.has(agent.slug)) { selected.delete(agent.slug); chip.classList.remove('is-selected'); }
        else { selected.add(agent.slug); chip.classList.add('is-selected'); }
      });
      pickerEl.appendChild(chip);
    });

    roundsEl.addEventListener('input', () => { roundsValueEl.textContent = roundsEl.value; });

    const col = { slug: '__bridge__', node, conversationId: null };

    async function runBridge(slugs, topic, rounds) {
      setupEl.classList.add('hidden');
      patchbayEl.classList.remove('hidden');
      transcriptEl.innerHTML = '';
      renderPatchbay(patchbayEl, slugs.map((s) => state.agentsBySlug[s]).filter(Boolean));
      transcriptEl.appendChild(createMessageEl('user', { content: topic, speaker: state.user.username }));
      scrollToBottom(transcriptEl);

      startBtn.disabled = true;
      await API.streamBridge({ agent_slugs: slugs, topic, rounds }, {
        onEvent(evt) {
          if (evt.type === 'start') {
            col.conversationId = evt.conversation_id;
          } else if (evt.type === 'turn') {
            setPatchbayActive(patchbayEl, evt.agent_slug);
            transcriptEl.appendChild(createMessageEl('agent', {
              content: evt.content, agentColor: evt.color, speaker: evt.display_name,
              isError: evt.content.startsWith('[erro'),
            }));
            scrollToBottom(transcriptEl);
          } else if (evt.type === 'done') {
            setPatchbayActive(patchbayEl, null);
          }
        },
        onError(msg) {
          transcriptEl.appendChild(createMessageEl('agent', { content: msg, isError: true }));
        },
      });
      startBtn.disabled = false;
    }

    startBtn.addEventListener('click', () => {
      const slugs = Array.from(selected);
      const topic = topicEl.value.trim();
      if (slugs.length < 2) { alert('Selecione ao menos 2 agentes para a ponte.'); return; }
      if (!topic) { alert('Escreva um tópico para os agentes discutirem.'); return; }
      runBridge(slugs, topic, parseInt(roundsEl.value, 10));
    });

    node.querySelector('[data-action="close"]').addEventListener('click', () => closeColumn('__bridge__'));
    node.querySelector('[data-action="new"]').addEventListener('click', () => {
      col.conversationId = null;
      setupEl.classList.remove('hidden');
      patchbayEl.classList.add('hidden');
      transcriptEl.innerHTML = '';
      historyDropdown.classList.add('hidden');
    });
    node.querySelector('[data-action="history"]').addEventListener('click', async () => {
      const willOpen = historyDropdown.classList.contains('hidden');
      closeAllHistoryDropdowns();
      if (!willOpen) return;
      historyDropdown.classList.remove('hidden');
      historyDropdown.innerHTML = '<div class="history-empty">Carregando…</div>';
      try {
        const convos = await API.listConversations({ mode: 'bridge' });
        renderHistoryList(historyDropdown, convos, async (id) => {
          historyDropdown.classList.add('hidden');
          const data = await API.getConversationMessages(id);
          col.conversationId = id;
          setupEl.classList.add('hidden');
          patchbayEl.classList.remove('hidden');
          renderPatchbay(patchbayEl, data.conversation.agent_slugs.map((s) => state.agentsBySlug[s]).filter(Boolean));
          transcriptEl.innerHTML = '';
          data.messages.forEach((m) => {
            if (m.role === 'user') {
              transcriptEl.appendChild(createMessageEl('user', { content: m.content, speaker: state.user.username }));
            } else {
              const a = state.agentsBySlug[m.agent_slug];
              transcriptEl.appendChild(createMessageEl('agent', {
                content: m.content, agentColor: a ? a.color : null,
                speaker: a ? a.display_name : m.agent_slug, isError: m.content.startsWith('[erro'),
              }));
            }
          });
          scrollToBottom(transcriptEl);
        });
      } catch (err) {
        historyDropdown.innerHTML = '<div class="history-empty">Erro ao carregar histórico</div>';
      }
    });

    state.columns.set('__bridge__', col);
    document.getElementById('columns').appendChild(node);
    return col;
  }

  function renderPatchbay(container, agents) {
    const w = Math.max(220, agents.length * 100), h = 96, nodeY = 50, radius = 16;
    const spacing = w / (agents.length + 1);
    const positions = agents.map((a, i) => ({ x: spacing * (i + 1), y: nodeY, agent: a }));

    let svg = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">`;
    for (let i = 0; i < positions.length - 1; i++) {
      const a = positions[i], b = positions[i + 1];
      const midY = nodeY - 28;
      svg += `<path class="patch-cable" data-pair="${a.agent.slug}|${b.agent.slug}" stroke="${a.agent.color}" d="M${a.x},${a.y} Q${(a.x + b.x) / 2},${midY} ${b.x},${b.y}"></path>`;
    }
    positions.forEach((p) => {
      svg += `<circle class="patch-node-ring" cx="${p.x}" cy="${p.y}" r="${radius}" stroke="${p.agent.color}"></circle>`;
      svg += `<circle cx="${p.x}" cy="${p.y}" r="${radius - 5}" fill="${p.agent.color}" opacity="0.85"></circle>`;
      svg += `<text class="patch-label" x="${p.x}" y="${p.y + radius + 14}">${escapeHtml(p.agent.display_name)}</text>`;
    });
    svg += '</svg>';
    container.innerHTML = svg;
  }

  function setPatchbayActive(container, activeSlug) {
    $$('.patch-cable', container).forEach((c) => {
      const pair = c.dataset.pair.split('|');
      c.classList.toggle('is-active', !!activeSlug && pair.includes(activeSlug));
    });
  }

  // ------------------------------------------------------------------
  // Administração de agentes
  // ------------------------------------------------------------------
  const adminModal = document.getElementById('admin-modal');
  document.getElementById('open-admin').addEventListener('click', () => {
    adminModal.classList.remove('hidden');
    renderAdminAgentList();
    closeSidebarOnMobile();
  });
  $$('[data-close-modal]').forEach((btn) => btn.addEventListener('click', () => adminModal.classList.add('hidden')));
  adminModal.addEventListener('click', (e) => { if (e.target === adminModal) adminModal.classList.add('hidden'); });

  function renderAdminAgentList() {
    const container = document.getElementById('admin-agent-table');
    container.innerHTML = '';
    state.agents.forEach((agent) => {
      const row = document.createElement('div');
      row.className = 'admin-agent-row';
      row.innerHTML = `
        <span class="agent-item-dot" style="--agent-c:${agent.color}"></span>
        <div class="admin-agent-info">
          <strong>${escapeHtml(agent.display_name)}</strong>
          <span>${escapeHtml(agent.model)}${agent.has_api_key ? '' : ' · sem chave configurada'}</span>
        </div>
        <button class="icon-btn admin-del-btn" title="Remover">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>`;
      row.querySelector('.admin-del-btn').addEventListener('click', async () => {
        if (!confirm(`Remover o agente "${agent.display_name}"? O histórico já salvo não é apagado.`)) return;
        try {
          await API.deleteAgent(agent.slug);
          closeColumn(agent.slug);
          await loadAgents();
          renderAdminAgentList();
          renderSidebarAgents();
        } catch (err) { alert(err.message); }
      });
      container.appendChild(row);
    });
  }

  document.getElementById('form-new-agent').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      slug: String(fd.get('slug') || '').trim().toLowerCase(),
      display_name: String(fd.get('display_name') || '').trim(),
      model: String(fd.get('model') || '').trim(),
      base_url: String(fd.get('base_url') || '').trim() || null,
      api_key: String(fd.get('api_key') || '').trim(),
      supports_vision: fd.get('supports_vision') === 'on',
      color: fd.get('color') || '#8B8FA3',
      temperature: parseFloat(fd.get('temperature')) || 1.0,
      top_p: parseFloat(fd.get('top_p')) || 1.0,
      max_tokens: parseInt(fd.get('max_tokens'), 10) || 8192,
    };
    try {
      await API.createAgent(payload);
      e.target.reset();
      await loadAgents();
      renderAdminAgentList();
      renderSidebarAgents();
    } catch (err) {
      alert(err.message);
    }
  });
})();
