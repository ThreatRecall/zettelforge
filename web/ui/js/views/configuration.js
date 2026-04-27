window.ConfigurationView = (function() {
  'use strict';

  // Known enum fields rendered as <select>. Keyed by dotted path.
  // When the live value is not in the option list, it is added so we never
  // silently drop an admin-set value.
  var ENUMS = {
    'backend':                    ['sqlite', 'lance'],
    'embedding.provider':         ['fastembed', 'ollama'],
    'llm.provider':               ['ollama', 'local', 'mock', 'litellm'],
    'llm.local_backend':          ['llama-cpp-python', 'onnxruntime-genai'],
    'logging.level':              ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
    'synthesis.default_format':   ['direct_answer', 'synthesized_brief'],
    'governance.pii.action':      ['log', 'redact', 'block']
  };

  // Dotted leaf paths the server flags as restart-required. The defaults
  // below mirror _RESTART_REQUIRED_FIELDS in web/app.py and are used until
  // GET /api/config/meta returns the authoritative server-side set on first
  // load. Hardcoded fallbacks survive an offline server and the server set
  // wins to prevent UI/server drift.
  var RESTART_PATHS = {
    'backend': true,
    'embedding.provider': true,
    'embedding.url': true,
    'llm.provider': true,
    'llm.model': true,
    'llm.url': true,
    'storage.data_dir': true,
    'logging.log_file': true,
    'logging.level': true
  };

  // Display order + grouping for known sections. Keys not listed here fall
  // through to an "Other" group at the bottom so nothing is hidden.
  var GROUPS = [
    { name: 'Core',                       sections: ['backend', 'storage', 'web'] },
    { name: 'LLM',                        sections: ['llm', 'llm_ner'] },
    { name: 'Embedding',                  sections: ['embedding'] },
    { name: 'Extraction & Retrieval',     sections: ['extraction', 'retrieval'] },
    { name: 'Synthesis',                  sections: ['synthesis'] },
    { name: 'Governance',                 sections: ['governance'] },
    { name: 'Storage Maintenance',        sections: ['lance', 'cache'] },
    { name: 'Logging',                    sections: ['logging'] },
    { name: 'Enterprise & Integrations',  sections: ['enterprise', 'opencti', 'typedb'] }
  ];

  var DESCRIPTIONS = {
    'backend':                            'Storage backend (sqlite or lance)',
    'storage.data_dir':                   'Data storage directory path',
    'embedding.provider':                 'Embedding service provider',
    'embedding.model':                    'Embedding model identifier',
    'embedding.url':                      'Ollama URL (used when provider=ollama)',
    'embedding.dimensions':               'Vector dimension count',
    'llm.provider':                       'LLM backend provider',
    'llm.model':                          'Model identifier',
    'llm.url':                            'Provider URL (used by ollama/local)',
    'llm.api_key':                        'API key (env-resolved; redacted)',
    'llm.temperature':                    'Sampling temperature (0.0 - 2.0)',
    'llm.timeout':                        'Per-call timeout in seconds',
    'llm.max_retries':                    'Max retries on transient failures',
    'llm.local_backend':                  'In-process backend when provider=local',
    'logging.level':                      'Log verbosity',
    'logging.log_file':                   'Log output file path',
    'logging.log_to_stdout':              'Mirror logs to stdout',
    'governance.enabled':                 'Enforce governance policies',
    'governance.min_content_length':      'Minimum accepted content length',
    'governance.pii.enabled':             'Run Presidio PII detection',
    'governance.pii.action':              'PII handling: log, redact, or block',
    'governance.limits.max_content_length': 'Max content body size in bytes',
    'governance.limits.recall_timeout_seconds': 'Recall timeout in seconds',
    'retrieval.default_k':                'Default top-K results',
    'retrieval.similarity_threshold':     'Minimum similarity score',
    'synthesis.default_format':           'Default synthesis output format',
    'synthesis.max_context_tokens':       'Max tokens packed into a synthesis prompt',
    'web.enabled':                        'Serve the web management interface',
    'web.host':                           'Bind host for the web interface',
    'web.port':                           'Bind port for the web interface',
    'opencti.url':                        'OpenCTI instance URL',
    'opencti.token':                      'OpenCTI API token (redacted)',
    'opencti.sync_interval':              'OpenCTI sync interval (seconds; 0 disables)',
    'enterprise.license_key':             'Enterprise license key (redacted)'
  };

  function isSecretKey(name) {
    var n = (name || '').toLowerCase();
    return n.indexOf('api_key') !== -1 ||
           n.indexOf('password') !== -1 ||
           n.indexOf('secret') !== -1 ||
           n.indexOf('token') !== -1 ||
           n.indexOf('license_key') !== -1;
  }

  // Walk nested config to produce a list of {path, value} leaves in order.
  function flattenLeaves(obj, prefix, out) {
    out = out || [];
    Object.keys(obj || {}).forEach(function(k) {
      var v = obj[k];
      var path = prefix ? prefix + '.' + k : k;
      if (v && typeof v === 'object' && !Array.isArray(v)) {
        flattenLeaves(v, path, out);
      } else {
        out.push({ path: path, value: v });
      }
    });
    return out;
  }

  // Build a nested object payload from a flat {dotted.path: value} map so the
  // server-side _apply_yaml() handler receives the structure it expects.
  function buildNestedPayload(changes) {
    var out = {};
    Object.keys(changes).forEach(function(path) {
      var parts = path.split('.');
      var cursor = out;
      for (var i = 0; i < parts.length - 1; i++) {
        var key = parts[i];
        if (typeof cursor[key] !== 'object' || cursor[key] === null) {
          cursor[key] = {};
        }
        cursor = cursor[key];
      }
      cursor[parts[parts.length - 1]] = changes[path];
    });
    return out;
  }

  function coerce(originalValue, raw) {
    if (typeof originalValue === 'number') {
      var trimmed = typeof raw === 'string' ? raw.trim() : raw;
      // Empty / unparseable input reverts to the original value rather than
      // silently coercing to 0, which would overwrite a real numeric setting.
      if (trimmed === '' || trimmed === null || trimmed === undefined) return originalValue;
      var n = parseFloat(trimmed);
      return isNaN(n) ? originalValue : n;
    }
    if (typeof originalValue === 'boolean') {
      return raw === true || raw === 'true';
    }
    return raw;
  }

  function el(tag, css, text) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ── Public view ─────────────────────────────────────────────────────────────

  var View = {
    _config: null,
    _changes: {},
    _activeTab: 'flags',
    _editorContent: '',

    render: function() {
      var self = this;
      var container = el('div', 'max-width:960px;');
      container.id = 'configuration-view';

      var heading = el('h2', 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);', 'Configuration');
      container.appendChild(heading);

      var subhead = el('div', 'margin:-8px 0 var(--sp-4,16px);font-size:var(--text-xs,11px);color:var(--fg-3,#484F58);font-family:var(--font-mono);', 'Edit settings live. Restart-flagged fields take effect on next process start.');
      container.appendChild(subhead);

      var tabBar = el('div', 'display:flex;gap:6px;margin-bottom:var(--sp-4,16px);');
      tabBar.id = 'config-tabs';
      var tabs = [{ id: 'flags', label: 'Settings' }, { id: 'yaml', label: 'YAML Editor' }];

      tabs.forEach(function(t) {
        var active = self._activeTab === t.id;
        var btn = el('button',
          'padding:8px 16px;background:' + (active ? 'var(--bg-surface-hi,#21262D)' : 'transparent') +
          ';border:1px solid ' + (active ? 'var(--border-focus,#58A6FF)' : 'var(--border,#30363D)') +
          ';border-radius:var(--r-sm,6px);color:' + (active ? 'var(--fg-1,#C9D1D9)' : 'var(--fg-2,#8B949E)') +
          ';cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:color 120ms,background 120ms,border-color 120ms;',
          t.label);
        if (!active) {
          btn.addEventListener('mouseenter', function() { btn.style.color = 'var(--fg-1,#C9D1D9)'; });
          btn.addEventListener('mouseleave', function() { btn.style.color = 'var(--fg-2,#8B949E)'; });
        }
        btn.addEventListener('click', function() {
          if (self._activeTab === t.id) return;
          self._activeTab = t.id;
          var fresh = self.render();
          if (container.parentNode) container.parentNode.replaceChild(fresh, container);
        });
        tabBar.appendChild(btn);
      });
      container.appendChild(tabBar);

      var content = el('div');
      content.id = 'config-content';
      container.appendChild(content);

      content.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:var(--sp-8,32px);gap:8px;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading configuration...</div>';

      if (this._activeTab === 'flags') {
        this.loadFlags(content);
      } else {
        this.loadYamlEditor(content);
      }

      return container;
    },

    loadFlags: function(contentEl) {
      var self = this;
      // Fetch config + meta in parallel; meta failure is non-fatal — fall back
      // to the hardcoded RESTART_PATHS defaults.
      Promise.all([
        window.API.get('/api/config'),
        window.API.get('/api/config/meta').catch(function() { return null; })
      ]).then(function(results) {
        var config = results[0];
        var meta = results[1];
        if (meta && Array.isArray(meta.restart_required_fields)) {
          var fresh = {};
          meta.restart_required_fields.forEach(function(p) { fresh[p] = true; });
          RESTART_PATHS = fresh;
        }
        self._config = config;
        self._changes = {};
        self.renderFlags(contentEl, config);
      }).catch(function(err) {
        contentEl.innerHTML = '';
        contentEl.appendChild(el('div',
          'padding:var(--sp-4,16px);background:var(--bg-surface,#161B22);border:1px solid var(--danger,#F85149);border-radius:var(--r-md,8px);color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);',
          'Failed to load configuration: ' + (err.message || 'unknown error')));
      });
    },

    renderFlags: function(container, config) {
      var self = this;
      container.innerHTML = '';

      var leaves = flattenLeaves(config);
      if (leaves.length === 0) {
        container.appendChild(el('div',
          'padding:var(--sp-6,24px);text-align:center;color:var(--fg-3,#484F58);font-size:var(--text-sm,12px);font-family:var(--font-mono);',
          'No configuration data available'));
        return;
      }

      // Bucket leaves by top-level section
      var bySection = {};
      leaves.forEach(function(leaf) {
        var section = leaf.path.indexOf('.') === -1 ? leaf.path : leaf.path.split('.')[0];
        if (!bySection[section]) bySection[section] = [];
        bySection[section].push(leaf);
      });

      var rendered = {};
      GROUPS.forEach(function(group) {
        var groupLeaves = [];
        group.sections.forEach(function(s) {
          if (bySection[s]) {
            groupLeaves = groupLeaves.concat(bySection[s]);
            rendered[s] = true;
          }
        });
        if (groupLeaves.length === 0) return;
        container.appendChild(self.renderGroupCard(group.name, groupLeaves));
      });

      // Catch-all for unmapped sections so nothing gets dropped silently.
      var leftovers = [];
      Object.keys(bySection).forEach(function(s) {
        if (!rendered[s]) leftovers = leftovers.concat(bySection[s]);
      });
      if (leftovers.length > 0) {
        container.appendChild(self.renderGroupCard('Other', leftovers));
      }

      // Apply control row
      container.appendChild(self.renderApplyRow());

      // Result area
      var resultArea = el('div', 'margin-top:var(--sp-3,12px);');
      resultArea.id = 'config-result';
      container.appendChild(resultArea);
    },

    renderGroupCard: function(title, leaves) {
      var self = this;
      var card = el('div', 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);');
      var heading = el('h3', 'margin:0 0 var(--sp-3,12px);font-size:var(--text-base,14px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);', title);
      card.appendChild(heading);

      leaves.forEach(function(leaf, idx) {
        card.appendChild(self.renderRow(leaf, idx === leaves.length - 1));
      });
      return card;
    },

    renderRow: function(leaf, isLast) {
      var self = this;
      var path = leaf.path;
      var value = leaf.value;

      var row = el('div',
        'display:flex;justify-content:space-between;align-items:center;gap:12px;padding:8px 0;' +
        (isLast ? '' : 'border-bottom:1px solid var(--border,#30363D);'));

      var labelDiv = el('div', 'flex:1;min-width:0;');
      var name = el('div', 'font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--fg-1,#C9D1D9);word-break:break-all;', path);
      labelDiv.appendChild(name);

      var hint = DESCRIPTIONS[path];
      if (hint) {
        labelDiv.appendChild(el('div', 'font-size:10px;color:var(--fg-3,#484F58);margin-top:2px;', hint));
      }
      if (RESTART_PATHS[path]) {
        var badge = el('span',
          'display:inline-block;margin-top:4px;padding:1px 6px;border-radius:var(--r-pill,9999px);font-size:10px;font-family:var(--font-mono);background:var(--tier-c-bg,#3A2A0F);color:var(--warning,#D29922);',
          'restart required');
        labelDiv.appendChild(badge);
      }
      row.appendChild(labelDiv);

      var controlDiv = el('div', 'flex-shrink:0;');
      controlDiv.appendChild(self.renderControl(path, value));
      row.appendChild(controlDiv);
      return row;
    },

    renderControl: function(path, value) {
      var self = this;

      if (isSecretKey(path)) {
        var secret = el('span',
          'font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--fg-3,#484F58);padding:4px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);display:inline-block;',
          '***');
        secret.title = 'Secrets are redacted server-side. Edit via env vars or YAML editor.';
        return secret;
      }

      // Dropdown for known enum paths
      if (ENUMS[path]) {
        var options = ENUMS[path].slice();
        var current = String(value);
        if (current && options.indexOf(current) === -1) {
          options.unshift(current);
        }
        var select = document.createElement('select');
        select.style.cssText = 'min-width:180px;padding:5px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-mono);outline:none;cursor:pointer;';
        options.forEach(function(opt) {
          var optEl = document.createElement('option');
          optEl.value = opt;
          optEl.textContent = opt;
          if (opt === current) optEl.selected = true;
          select.appendChild(optEl);
        });
        select.addEventListener('change', function() {
          if (this.value === current) {
            delete self._changes[path];
          } else {
            self._changes[path] = this.value;
          }
          self.updateApplyButton();
        });
        return select;
      }

      if (typeof value === 'boolean') {
        var label = el('label', 'display:flex;align-items:center;gap:6px;cursor:pointer;');
        var toggle = document.createElement('input');
        toggle.type = 'checkbox';
        toggle.checked = value;
        toggle.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);cursor:pointer;';
        var stateText = el('span', 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);min-width:54px;text-align:right;', value ? 'enabled' : 'disabled');
        toggle.addEventListener('change', function() {
          stateText.textContent = this.checked ? 'enabled' : 'disabled';
          if (this.checked === value) {
            delete self._changes[path];
          } else {
            self._changes[path] = this.checked;
          }
          self.updateApplyButton();
        });
        label.appendChild(toggle);
        label.appendChild(stateText);
        return label;
      }

      if (Array.isArray(value)) {
        var arrInput = document.createElement('input');
        arrInput.type = 'text';
        arrInput.value = value.join(', ');
        arrInput.style.cssText = 'width:220px;padding:5px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-mono);outline:none;';
        arrInput.placeholder = 'comma-separated';
        arrInput.addEventListener('change', function() {
          var parts = this.value.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
          var same = parts.length === value.length && parts.every(function(p, i) { return p === value[i]; });
          if (same) delete self._changes[path];
          else self._changes[path] = parts;
          self.updateApplyButton();
        });
        return arrInput;
      }

      var input = document.createElement('input');
      input.type = (typeof value === 'number') ? 'number' : 'text';
      if (typeof value === 'number' && !Number.isInteger(value)) {
        input.step = 'any';
      }
      input.value = (value === null || value === undefined) ? '' : String(value);
      input.style.cssText = 'width:200px;padding:5px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-mono);outline:none;text-align:right;';
      input.addEventListener('change', function() {
        var coerced = coerce(value, this.value);
        if (coerced === value) {
          delete self._changes[path];
        } else {
          self._changes[path] = coerced;
        }
        self.updateApplyButton();
      });
      return input;
    },

    renderApplyRow: function() {
      var self = this;
      var row = el('div', 'display:flex;gap:var(--sp-3,12px);align-items:center;margin-top:var(--sp-4,16px);');
      row.id = 'config-apply-row';

      var apply = el('button', 'padding:8px 20px;background:#238636;border:none;border-radius:var(--r-sm,6px);color:#fff;cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:background 120ms,opacity 120ms;', 'Apply Changes');
      apply.id = 'config-apply-btn';
      apply.addEventListener('mouseenter', function() { if (!apply.disabled) apply.style.background = '#2EA043'; });
      apply.addEventListener('mouseleave', function() { apply.style.background = '#238636'; });
      apply.addEventListener('click', function() { self.applyChanges(); });

      var revert = el('button', 'padding:8px 16px;background:transparent;border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:color 120ms,border-color 120ms;', 'Revert');
      revert.id = 'config-revert-btn';
      revert.addEventListener('mouseenter', function() { revert.style.color = 'var(--fg-1,#C9D1D9)'; revert.style.borderColor = 'var(--fg-2,#8B949E)'; });
      revert.addEventListener('mouseleave', function() { revert.style.color = 'var(--fg-2,#8B949E)'; revert.style.borderColor = 'var(--border,#30363D)'; });
      revert.addEventListener('click', function() { self.revertChanges(); });

      var pending = el('span', 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);');
      pending.id = 'config-pending-count';

      row.appendChild(apply);
      row.appendChild(revert);
      row.appendChild(pending);

      // Initial state
      setTimeout(function() { self.updateApplyButton(); }, 0);
      return row;
    },

    updateApplyButton: function() {
      var btn = document.getElementById('config-apply-btn');
      var revert = document.getElementById('config-revert-btn');
      var pending = document.getElementById('config-pending-count');
      var count = Object.keys(this._changes).length;
      var disabled = count === 0;

      if (btn) {
        btn.disabled = disabled;
        btn.style.opacity = disabled ? '0.4' : '1';
        btn.style.cursor = disabled ? 'default' : 'pointer';
      }
      if (revert) {
        revert.disabled = disabled;
        revert.style.opacity = disabled ? '0.4' : '1';
        revert.style.cursor = disabled ? 'default' : 'pointer';
      }
      if (pending) {
        if (count === 0) {
          pending.textContent = '';
        } else {
          var restartCount = Object.keys(this._changes).filter(function(k) { return RESTART_PATHS[k]; }).length;
          var msg = count + ' pending change' + (count === 1 ? '' : 's');
          if (restartCount > 0) msg += ' (' + restartCount + ' need restart)';
          pending.textContent = msg;
        }
      }
    },

    revertChanges: function() {
      var contentEl = document.getElementById('config-content');
      if (!contentEl) return;
      this._changes = {};
      this.renderFlags(contentEl, this._config);
      window.ToastComponent.show('Reverted to last loaded values', 'info');
    },

    applyChanges: function() {
      var self = this;
      var btn = document.getElementById('config-apply-btn');
      var resultArea = document.getElementById('config-result');
      if (!resultArea) return;

      var changes = this._changes;
      if (Object.keys(changes).length === 0) {
        window.ToastComponent.show('No changes to apply', 'info');
        return;
      }

      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Applying...';
      }

      resultArea.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px 0;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Applying configuration changes...</div>';

      var payload = buildNestedPayload(changes);

      window.API.put('/api/config', payload).then(function(data) {
        // Clear pending changes and reload from server so the form reflects
        // truth (server may coerce or reject silently for unknown leaves).
        self._changes = {};
        if (btn) btn.textContent = 'Apply Changes';
        self.renderResult(resultArea, data);
        window.ToastComponent.show('Configuration applied', 'success');

        // Refresh flags from /api/config so toggles/dropdowns show new state
        var contentEl = document.getElementById('config-content');
        if (contentEl) self.loadFlags(contentEl);
      }).catch(function(err) {
        if (btn) {
          btn.disabled = false;
          btn.textContent = 'Apply Changes';
          btn.style.opacity = '1';
        }
        resultArea.innerHTML = '';
        resultArea.appendChild(el('div',
          'padding:12px;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);background:var(--bg-input,#0D1117);border:1px solid var(--danger,#F85149);border-radius:var(--r-sm,6px);',
          'Failed to apply: ' + (err.message || 'unknown error')));
        window.ToastComponent.show('Apply failed: ' + (err.message || 'unknown'), 'error');
      });
    },

    renderResult: function(area, data) {
      area.innerHTML = '';
      var box = el('div', 'background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);');

      if (data.applied && data.applied.length) {
        box.appendChild(el('div', 'margin-bottom:6px;font-size:var(--text-xs,11px);color:var(--success,#3FB950);font-family:var(--font-mono);font-weight:600;', 'Applied:'));
        data.applied.forEach(function(k) {
          box.appendChild(el('div', 'padding:2px 0;font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--success,#3FB950);', '✓ ' + k));
        });
      }
      if (data.pending_restart && data.pending_restart.length) {
        var head = el('div', 'margin-top:8px;margin-bottom:4px;');
        head.appendChild(el('span', 'font-size:var(--text-xs,11px);color:var(--warning,#D29922);font-family:var(--font-mono);font-weight:600;', 'Pending Restart:'));
        head.appendChild(el('span', 'display:inline-block;margin-left:6px;padding:1px 6px;border-radius:var(--r-pill,9999px);font-size:10px;font-family:var(--font-mono);background:var(--tier-c-bg,#3A2A0F);color:var(--warning,#D29922);', 'restart required'));
        box.appendChild(head);
        data.pending_restart.forEach(function(k) {
          box.appendChild(el('div', 'padding:2px 0;font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--warning,#D29922);', '⚠ ' + k));
        });
      }
      if ((!data.applied || !data.applied.length) && (!data.pending_restart || !data.pending_restart.length)) {
        box.appendChild(el('div', 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);', 'Server accepted the request but reported no leaf-level changes.'));
      }
      area.appendChild(box);
    },

    // ── YAML editor (unchanged behavior, refactored for clarity) ──────────────

    loadYamlEditor: function(contentEl) {
      var self = this;
      window.API.get('/api/config').then(function(config) {
        self._config = config;
        self._editorContent = self.configToYaml(config);
        self.renderYamlEditor(contentEl);
      }).catch(function(err) {
        contentEl.innerHTML = '';
        contentEl.appendChild(el('div',
          'padding:var(--sp-4,16px);background:var(--bg-surface,#161B22);border:1px solid var(--danger,#F85149);border-radius:var(--r-md,8px);color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);',
          'Failed to load configuration: ' + (err.message || 'unknown error')));
      });
    },

    configToYaml: function(config, indent) {
      indent = indent || '';
      var yaml = '';
      var self = this;
      Object.keys(config || {}).forEach(function(k) {
        var v = config[k];
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          yaml += indent + k + ':\n';
          yaml += self.configToYaml(v, indent + '  ');
        } else if (Array.isArray(v)) {
          yaml += indent + k + ':\n';
          v.forEach(function(item) { yaml += indent + '  - ' + item + '\n'; });
        } else if (typeof v === 'boolean') {
          yaml += indent + k + ': ' + (v ? 'true' : 'false') + '\n';
        } else if (typeof v === 'number') {
          yaml += indent + k + ': ' + v + '\n';
        } else if (v === null) {
          yaml += indent + k + ': null\n';
        } else {
          var s = String(v);
          if (isSecretKey(k)) s = '***';
          if (s.indexOf('#') !== -1 || s.indexOf(':') !== -1 || s === '') {
            // Escape backslashes BEFORE quotes so a literal `\` in the value
            // isn't turned into a YAML escape sequence and a value like
            // `foo\"bar` doesn't terminate the scalar early.
            yaml += indent + k + ': "' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"\n';
          } else {
            yaml += indent + k + ': ' + s + '\n';
          }
        }
      });
      return yaml;
    },

    renderYamlEditor: function(container) {
      var self = this;
      container.innerHTML = '';

      var warn = el('div', 'background:rgba(210,153,34,0.08);border:1px solid var(--warning,#D29922);border-radius:var(--r-sm,6px);padding:8px 12px;font-size:var(--text-xs,11px);color:var(--warning,#D29922);font-family:var(--font-mono);margin-bottom:var(--sp-3,12px);display:flex;align-items:center;gap:8px;');
      warn.appendChild(el('span', 'flex-shrink:0;', '⚠'));
      warn.appendChild(el('span', '', 'Some changes require a restart. Secrets shown as "***" are redacted and not editable here.'));
      container.appendChild(warn);

      var editor = document.createElement('textarea');
      editor.id = 'config-yaml-editor';
      editor.value = this._editorContent;
      editor.style.cssText = 'width:100%;min-height:400px;padding:var(--sp-4,16px);background:#0D1117;border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-mono);resize:vertical;outline:none;box-sizing:border-box;tab-size:2;line-height:1.5;';
      editor.addEventListener('input', function() { self._editorContent = this.value; });
      container.appendChild(editor);

      var actions = el('div', 'display:flex;gap:var(--sp-2,8px);margin-top:var(--sp-3,12px);');
      var apply = el('button', 'padding:8px 20px;background:#238636;border:none;border-radius:var(--r-sm,6px);color:#fff;cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:background 120ms;', 'Apply');
      apply.id = 'config-yaml-apply-btn';
      apply.addEventListener('mouseenter', function() { if (!apply.disabled) apply.style.background = '#2EA043'; });
      apply.addEventListener('mouseleave', function() { apply.style.background = '#238636'; });
      apply.addEventListener('click', function() { self.applyYaml(); });
      actions.appendChild(apply);

      var reset = el('button', 'padding:8px 20px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;', 'Reset to Server');
      reset.addEventListener('mouseenter', function() { reset.style.borderColor = 'var(--danger,#F85149)'; reset.style.color = 'var(--fg-1,#C9D1D9)'; });
      reset.addEventListener('mouseleave', function() { reset.style.borderColor = 'var(--border,#30363D)'; reset.style.color = 'var(--fg-2,#8B949E)'; });
      reset.addEventListener('click', function() { self.resetYaml(); });
      actions.appendChild(reset);

      container.appendChild(actions);

      var resultArea = el('div', 'margin-top:var(--sp-3,12px);');
      resultArea.id = 'config-yaml-result';
      container.appendChild(resultArea);
    },

    applyYaml: function() {
      var self = this;
      var btn = document.getElementById('config-yaml-apply-btn');
      var resultArea = document.getElementById('config-yaml-result');
      if (!resultArea) return;

      if (btn) { btn.disabled = true; btn.textContent = 'Applying...'; }
      resultArea.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px 0;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Applying YAML configuration...</div>';

      var payload = parseFlatYaml(this._editorContent);

      window.API.put('/api/config', payload).then(function(data) {
        if (btn) { btn.disabled = false; btn.textContent = 'Apply'; }
        self.renderResult(resultArea, data);
        window.ToastComponent.show('YAML configuration applied', 'success');
      }).catch(function(err) {
        if (btn) { btn.disabled = false; btn.textContent = 'Apply'; }
        resultArea.innerHTML = '';
        resultArea.appendChild(el('div',
          'padding:12px;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);background:var(--bg-input,#0D1117);border:1px solid var(--danger,#F85149);border-radius:var(--r-sm,6px);',
          'Failed to apply: ' + (err.message || 'unknown error')));
        window.ToastComponent.show('Apply failed: ' + (err.message || 'unknown'), 'error');
      });
    },

    resetYaml: function() {
      var self = this;
      var resultArea = document.getElementById('config-yaml-result');
      var editor = document.getElementById('config-yaml-editor');
      if (editor) editor.value = 'Loading configuration...';

      window.API.get('/api/config').then(function(config) {
        self._config = config;
        self._editorContent = self.configToYaml(config);
        if (editor) editor.value = self._editorContent;
        if (resultArea) {
          resultArea.innerHTML = '';
          resultArea.appendChild(el('div', 'padding:12px;color:var(--success,#3FB950);font-size:var(--text-xs,11px);font-family:var(--font-mono);', 'Configuration reset to current server state'));
        }
        window.ToastComponent.show('Reset to server state', 'info');
      }).catch(function(err) {
        if (resultArea) {
          resultArea.innerHTML = '';
          resultArea.appendChild(el('div', 'padding:12px;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);', 'Failed to fetch config: ' + (err.message || 'unknown error')));
        }
      });
    }
  };

  // Minimal indented-YAML parser sufficient for the editor's two-level layout.
  // Produces a nested object so it round-trips cleanly through PUT /api/config.
  function parseFlatYaml(text) {
    var root = {};
    var stack = [{ indent: -1, obj: root }];
    text.split('\n').forEach(function(line) {
      var stripped = line.replace(/\s+$/, '');
      if (!stripped || /^\s*#/.test(stripped)) return;
      var indent = line.search(/\S/);
      if (indent === -1) return;

      // List item under the previous parent
      var listMatch = stripped.match(/^\s*-\s+(.*)$/);
      if (listMatch) {
        while (stack.length > 1 && stack[stack.length - 1].indent >= indent) stack.pop();
        var frame = stack[stack.length - 1];
        // Case A: this frame was opened by `key:` with empty value, optimistically
        // initialized to {}. The first child is a list item, so convert {} → [].
        if (frame.parentObj && frame.parentKey && !frame.lastKey) {
          if (!Array.isArray(frame.parentObj[frame.parentKey])) {
            frame.parentObj[frame.parentKey] = [];
            frame.obj = frame.parentObj[frame.parentKey];
          }
          frame.obj.push(coerceYamlScalar(listMatch[1]));
          return;
        }
        // Case B: list items belong to the previous mapping key in this frame.
        if (frame.lastKey) {
          if (!Array.isArray(frame.obj[frame.lastKey])) frame.obj[frame.lastKey] = [];
          frame.obj[frame.lastKey].push(coerceYamlScalar(listMatch[1]));
        }
        return;
      }

      var kvMatch = stripped.match(/^\s*([^:#]+?)\s*:\s*(.*)$/);
      if (!kvMatch) return;
      var key = kvMatch[1].trim();
      var value = kvMatch[2];

      while (stack.length > 1 && stack[stack.length - 1].indent >= indent) stack.pop();
      var ctx = stack[stack.length - 1];

      if (value === '') {
        ctx.obj[key] = {};
        ctx.lastKey = key;
        // parentObj/parentKey let a `- item` first-child convert this {} into []
        // so YAML lists round-trip correctly. lastKey starts null so the list
        // handler can distinguish "deferred container" from "real mapping".
        stack.push({
          indent: indent,
          obj: ctx.obj[key],
          parentObj: ctx.obj,
          parentKey: key,
          lastKey: null
        });
      } else {
        // Skip redacted secret placeholders so we never PUT '***' back.
        if (value.replace(/['"]/g, '').trim() === '***' && isSecretKey(key)) return;
        ctx.obj[key] = coerceYamlScalar(value);
        ctx.lastKey = key;
      }
    });
    return root;
  }

  function coerceYamlScalar(raw) {
    var v = raw.trim();
    if (v === 'true') return true;
    if (v === 'false') return false;
    if (v === 'null' || v === '~' || v === '') return null;
    if (/^-?\d+$/.test(v)) return parseInt(v, 10);
    if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v);
    if ((v.charAt(0) === '"' && v.charAt(v.length - 1) === '"') ||
        (v.charAt(0) === "'" && v.charAt(v.length - 1) === "'")) {
      return v.slice(1, -1);
    }
    return v;
  }

  // Test/debug hooks — exposed but not part of the user-facing API surface.
  View._buildNestedPayload = buildNestedPayload;
  View._flattenLeaves = flattenLeaves;
  View._parseFlatYaml = parseFlatYaml;
  View._ENUMS = ENUMS;
  View._RESTART_PATHS = RESTART_PATHS;

  return View;
})();
