/* Camada de acesso à API do backend. */
const API = {
  async request(path, options = {}) {
    let resp;
    try {
      resp = await fetch(path, {
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      });
    } catch (e) {
      throw new Error('Não foi possível conectar ao servidor.');
    }
    if (!resp.ok) {
      let detail = `Erro (${resp.status})`;
      try { const data = await resp.json(); detail = data.detail || detail; } catch (e) { /* corpo vazio */ }
      const err = new Error(detail);
      err.status = resp.status;
      throw err;
    }
    if (resp.status === 204) return null;
    return resp.json();
  },

  register(username, password) {
    return this.request('/api/auth/register', { method: 'POST', body: JSON.stringify({ username, password }) });
  },
  login(username, password) {
    return this.request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
  },
  logout() {
    return this.request('/api/auth/logout', { method: 'POST' });
  },
  me() {
    return this.request('/api/auth/me');
  },

  listAgents() {
    return this.request('/api/agents');
  },
  createAgent(payload) {
    return this.request('/api/agents', { method: 'POST', body: JSON.stringify(payload) });
  },
  updateAgent(slug, payload) {
    return this.request(`/api/agents/${encodeURIComponent(slug)}`, { method: 'PUT', body: JSON.stringify(payload) });
  },
  deleteAgent(slug) {
    return this.request(`/api/agents/${encodeURIComponent(slug)}`, { method: 'DELETE' });
  },

  listConversations(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/api/conversations${qs ? '?' + qs : ''}`);
  },
  getConversationMessages(id) {
    return this.request(`/api/conversations/${id}/messages`);
  },
  deleteConversation(id) {
    return this.request(`/api/conversations/${id}`, { method: 'DELETE' });
  },

  streamChat(slug, body, handlers) {
    return this._stream(`/api/agents/${encodeURIComponent(slug)}/chat`, body, handlers);
  },
  streamBridge(body, handlers) {
    return this._stream('/api/bridge/start', body, handlers);
  },

  async _stream(path, body, { onEvent, onError }) {
    let resp;
    try {
      resp = await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (e) {
      onError && onError('Não foi possível conectar ao servidor.');
      return;
    }
    if (!resp.ok) {
      let detail = `Erro (${resp.status})`;
      try { const data = await resp.json(); detail = data.detail || detail; } catch (e) { /* corpo vazio */ }
      onError && onError(detail);
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;
        try {
          onEvent && onEvent(JSON.parse(jsonStr));
        } catch (e) { /* fragmento incompleto, ignora */ }
      }
    }
  },
};
