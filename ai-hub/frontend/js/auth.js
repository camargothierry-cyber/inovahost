/* Tela de login / cadastro. */
(function () {
  const viewAuth = document.getElementById('view-auth');
  const viewApp = document.getElementById('view-app');
  const tabs = document.querySelectorAll('.auth-tab');
  const formLogin = document.getElementById('form-login');
  const formRegister = document.getElementById('form-register');
  const errorEl = document.getElementById('auth-error');

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('is-active'));
      tab.classList.add('is-active');
      const isLogin = tab.dataset.tab === 'login';
      formLogin.classList.toggle('hidden', !isLogin);
      formRegister.classList.toggle('hidden', isLogin);
      hideError();
    });
  });

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }
  function hideError() {
    errorEl.classList.add('hidden');
  }
  function setSubmitting(form, submitting) {
    const btn = form.querySelector('button[type=submit]');
    btn.disabled = submitting;
    btn.textContent = submitting ? 'Aguarde...' : (form === formLogin ? 'Entrar' : 'Criar conta');
  }

  formLogin.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();
    const fd = new FormData(formLogin);
    setSubmitting(formLogin, true);
    try {
      const user = await API.login(fd.get('username'), fd.get('password'));
      window.AIHub.boot(user);
    } catch (err) {
      showError(err.message);
    } finally {
      setSubmitting(formLogin, false);
    }
  });

  formRegister.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideError();
    const fd = new FormData(formRegister);
    setSubmitting(formRegister, true);
    try {
      const user = await API.register(fd.get('username'), fd.get('password'));
      window.AIHub.boot(user);
    } catch (err) {
      showError(err.message);
    } finally {
      setSubmitting(formRegister, false);
    }
  });

  // fundo decorativo: uma pequena rede de nós, sugerindo sinal/conexão
  function drawAuthBg() {
    const svg = document.getElementById('auth-nodes');
    if (!svg) return;
    const cols = 9, rows = 7, w = 1200, h = 800;
    const pts = [];
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        pts.push([
          (i + 0.5) * (w / cols) + (Math.random() - 0.5) * 44,
          (j + 0.5) * (h / rows) + (Math.random() - 0.5) * 44,
        ]);
      }
    }
    let lines = '';
    pts.forEach((p, idx) => {
      if (Math.random() < 0.3 && pts[idx + rows]) {
        const t = pts[idx + rows];
        lines += `<line class="auth-node" x1="${p[0]}" y1="${p[1]}" x2="${t[0]}" y2="${t[1]}" />`;
      }
      if (Math.random() < 0.3 && (idx + 1) % rows !== 0 && pts[idx + 1]) {
        const t = pts[idx + 1];
        lines += `<line class="auth-node" x1="${p[0]}" y1="${p[1]}" x2="${t[0]}" y2="${t[1]}" />`;
      }
    });
    const dots = pts.map((p) => `<circle class="auth-node-dot" cx="${p[0]}" cy="${p[1]}" r="1.6" />`).join('');
    svg.innerHTML = lines + dots;
  }
  drawAuthBg();

  window.AIHub = window.AIHub || {};
  window.AIHub.showAuth = function (message) {
    viewApp.classList.add('hidden');
    viewAuth.classList.remove('hidden');
    if (message) showError(message);
  };

  // sessão já ativa? entra direto na aplicação
  API.me().then((user) => window.AIHub.boot(user)).catch(() => window.AIHub.showAuth());
})();
