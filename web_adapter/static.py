"""Static HTML/CSS/JS for the Local Lucy web adapter.

The page is intentionally dependency-free: no React, Vue, build system, or
external CDN. It uses vanilla JS and a small amount of inline CSS.
"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Lucy</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #1e293b;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --danger: #f87171;
      --success: #34d399;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    header {
      padding: 1rem;
      background: var(--panel);
      border-bottom: 1px solid #334155;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
    }
    header h1 { margin: 0; font-size: 1.25rem; }
    #status {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.875rem;
      color: var(--muted);
    }
    #status-dot { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--danger); }
    #status-dot.ok { background: var(--success); }
    main { flex: 1; max-width: 800px; width: 100%; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: 1rem; }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      align-items: center;
    }
    label { font-size: 0.875rem; color: var(--muted); }
    select, button {
      padding: 0.5rem 0.75rem;
      border-radius: 0.375rem;
      border: 1px solid #334155;
      background: var(--panel);
      color: var(--text);
      font-size: 0.95rem;
    }
    button {
      background: var(--accent);
      color: #0f172a;
      border-color: var(--accent);
      font-weight: 600;
      cursor: pointer;
    }
    button:hover:not(:disabled) { background: var(--accent-hover); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    textarea {
      width: 100%;
      min-height: 6rem;
      resize: vertical;
      padding: 0.75rem;
      border-radius: 0.5rem;
      border: 1px solid #334155;
      background: var(--panel);
      color: var(--text);
      font-size: 1rem;
      line-height: 1.5;
    }
    .toolbar { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
    #answer-panel {
      background: var(--panel);
      border-radius: 0.5rem;
      padding: 1rem;
      white-space: pre-wrap;
      line-height: 1.6;
      min-height: 4rem;
    }
    #answer-panel:empty::before { content: "Lucy's answer will appear here..."; color: var(--muted); }
    .meta { font-size: 0.8rem; color: var(--muted); margin-top: 0.5rem; }
    #error {
      display: none;
      padding: 0.75rem;
      border-radius: 0.375rem;
      background: rgba(248, 113, 113, 0.15);
      border: 1px solid var(--danger);
      color: var(--danger);
      white-space: pre-wrap;
    }
    .spinner {
      display: none;
      width: 1rem;
      height: 1rem;
      border: 2px solid rgba(255,255,255,0.2);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    footer { padding: 1rem; text-align: center; font-size: 0.8rem; color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <h1>Local Lucy</h1>
    <div id="status"><span id="status-dot"></span><span id="status-text">Checking...</span></div>
  </header>

  <main>
    <div class="controls">
      <label for="model-select">Model:</label>
      <select id="model-select" aria-label="Select model">
        <option value="">Use active default</option>
      </select>
      <span id="active-model" class="meta"></span>
    </div>

    <textarea id="question" placeholder="Ask Local Lucy anything... (Shift+Enter for new line)" aria-label="Question"></textarea>

    <div class="toolbar">
      <button id="send-btn" type="button">Send</button>
      <div class="spinner" id="spinner" aria-label="Loading"></div>
      <button id="clear-btn" type="button">New conversation</button>
      <button id="copy-btn" type="button" disabled>Copy answer</button>
    </div>

    <div id="error" role="alert"></div>

    <div id="answer-panel" aria-live="polite"></div>
    <div id="meta" class="meta"></div>
  </main>

  <footer>Private Local Lucy web interface. Do not expose to the public internet.</footer>

  <script>
    const questionEl = document.getElementById('question');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const copyBtn = document.getElementById('copy-btn');
    const answerPanel = document.getElementById('answer-panel');
    const metaEl = document.getElementById('meta');
    const errorEl = document.getElementById('error');
    const spinner = document.getElementById('spinner');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const modelSelect = document.getElementById('model-select');
    const activeModelEl = document.getElementById('active-model');

    const fetchOpts = { credentials: 'include', headers: { 'Accept': 'application/json' } };

    function showError(msg) {
      errorEl.textContent = msg;
      errorEl.style.display = 'block';
    }
    function clearError() {
      errorEl.textContent = '';
      errorEl.style.display = 'none';
    }
    function setBusy(busy) {
      sendBtn.disabled = busy;
      questionEl.disabled = busy;
      spinner.style.display = busy ? 'inline-block' : 'none';
    }

    async function loadStatus() {
      try {
        const res = await fetch('/api/status', fetchOpts);
        if (res.status === 401) { throw new Error('Authentication required. Please reload the page and log in.'); }
        if (!res.ok) { throw new Error('Status check failed: ' + res.status); }
        const data = await res.json();
        if (data.ok) {
          statusDot.classList.add('ok');
          statusText.textContent = data.available ? 'Lucy ready' : 'Lucy unavailable';
          activeModelEl.textContent = 'Active default: ' + (data.active_model || 'unknown');
        } else {
          throw new Error(data.error || 'Lucy unavailable');
        }
      } catch (err) {
        statusText.textContent = err.message;
        statusDot.classList.remove('ok');
        showError(err.message);
      }
    }

    async function loadModels() {
      try {
        const res = await fetch('/api/models', fetchOpts);
        if (!res.ok) { return; }
        const data = await res.json();
        const current = modelSelect.value;
        // keep the default option
        modelSelect.innerHTML = '<option value="">Use active default</option>';
        (data.models || []).forEach(m => {
          const opt = document.createElement('option');
          opt.value = m;
          opt.textContent = m;
          if (m === current) { opt.selected = true; }
          modelSelect.appendChild(opt);
        });
      } catch (err) {
        // non-fatal
      }
    }

    async function sendQuestion() {
      const question = questionEl.value.trim();
      if (!question) {
        showError('Please enter a question.');
        return;
      }
      clearError();
      setBusy(true);
      answerPanel.textContent = '';
      metaEl.textContent = '';
      copyBtn.disabled = true;

      const payload = { question };
      const model = modelSelect.value;
      if (model) { payload.model = model; }

      try {
        const res = await fetch('/api/ask', {
          ...fetchOpts,
          method: 'POST',
          headers: { ...fetchOpts.headers, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (res.status === 401) { throw new Error('Authentication required. Please reload the page and log in.'); }
        let data;
        try { data = await res.json(); } catch (_) { data = { ok: false, error: 'Invalid response from server.' }; }
        if (!res.ok || !data.ok) {
          throw new Error(data.error || ('Request failed: ' + res.status));
        }
        answerPanel.textContent = data.answer || '(no answer)';
        const parts = [];
        if (data.route) { parts.push('route: ' + data.route); }
        if (data.provider) { parts.push('provider: ' + data.provider); }
        if (data.model) { parts.push('model: ' + data.model); }
        if (data.elapsed_ms) { parts.push('time: ' + data.elapsed_ms + 'ms'); }
        metaEl.textContent = parts.join(' \u2022 ');
        copyBtn.disabled = false;
      } catch (err) {
        showError(err.message);
      } finally {
        setBusy(false);
      }
    }

    sendBtn.addEventListener('click', sendQuestion);
    questionEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuestion();
      }
    });
    clearBtn.addEventListener('click', () => {
      questionEl.value = '';
      answerPanel.textContent = '';
      metaEl.textContent = '';
      clearError();
      copyBtn.disabled = true;
      questionEl.focus();
    });
    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(answerPanel.textContent);
        copyBtn.textContent = 'Copied';
        setTimeout(() => copyBtn.textContent = 'Copy answer', 1500);
      } catch (_) {
        copyBtn.textContent = 'Copy failed';
      }
    });

    loadStatus();
    loadModels();
  </script>
</body>
</html>
"""
