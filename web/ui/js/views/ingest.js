window.IngestView = {
  _state: {
    content: '',
    domain: 'cti',
    source_type: 'manual',
    evolve: true,
    loading: false,
    result: null,
    error: null
  },

  render: function() {
    var container = document.createElement('div');
    container.id = 'ingest-view';
    container.style.cssText = 'max-width:960px;';

    var heading = document.createElement('h2');
    heading.textContent = 'Ingest Threat Intelligence';
    heading.style.cssText = 'margin:0 0 var(--sp-6,24px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    // Single entry section
    var singleCard = document.createElement('div');
    singleCard.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';

    var singleTitle = document.createElement('h3');
    singleTitle.textContent = 'Single Entry';
    singleTitle.style.cssText = 'margin:0 0 var(--sp-3,12px);font-size:var(--text-base,14px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    singleCard.appendChild(singleTitle);

    // Textarea
    var textarea = document.createElement('textarea');
    textarea.id = 'ingest-textarea';
    textarea.placeholder = 'Paste CTI content, report text, YARA rule, Sigma rule, or CVE detail...';
    textarea.value = this._state.content;
    textarea.style.cssText = 'width:100%;min-height:180px;padding:12px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-base,14px);font-family:var(--font-sans);resize:vertical;outline:none;box-sizing:border-box;transition:border-color 120ms;';
    textarea.addEventListener('focus', function() { textarea.style.borderColor = 'var(--border-focus,#58A6FF)'; });
    textarea.addEventListener('blur', function() { textarea.style.borderColor = ''; });
    textarea.addEventListener('input', function() {
      window.IngestView._state.content = this.value;
    });
    singleCard.appendChild(textarea);

    // Metadata row
    var metaRow = document.createElement('div');
    metaRow.style.cssText = 'display:flex;gap:var(--sp-3,12px);margin-top:var(--sp-3,12px);align-items:flex-end;flex-wrap:wrap;';

    var domainGroup = document.createElement('div');
    domainGroup.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
    var domainLabel = document.createElement('label');
    domainLabel.textContent = 'Domain';
    domainLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.04em;';
    domainGroup.appendChild(domainLabel);
    var domainSelect = document.createElement('select');
    domainSelect.id = 'ingest-domain';
    domainSelect.value = this._state.domain;
    domainSelect.style.cssText = 'padding:6px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    ['cti', 'sigma', 'yara', 'report', 'general'].forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d.charAt(0).toUpperCase() + d.slice(1);
      domainSelect.appendChild(opt);
    });
    domainSelect.addEventListener('change', function() {
      window.IngestView._state.domain = this.value;
    });
    domainGroup.appendChild(domainSelect);
    metaRow.appendChild(domainGroup);

    var sourceGroup = document.createElement('div');
    sourceGroup.style.cssText = 'display:flex;flex-direction:column;gap:4px;';
    var sourceLabel = document.createElement('label');
    sourceLabel.textContent = 'Source Type';
    sourceLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.04em;';
    sourceGroup.appendChild(sourceLabel);
    var sourceSelect = document.createElement('select');
    sourceSelect.id = 'ingest-source-type';
    sourceSelect.value = this._state.source_type;
    sourceSelect.style.cssText = 'padding:6px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    ['manual', 'report', 'feed', 'api'].forEach(function(s) {
      var opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s.charAt(0).toUpperCase() + s.slice(1);
      sourceSelect.appendChild(opt);
    });
    sourceSelect.addEventListener('change', function() {
      window.IngestView._state.source_type = this.value;
    });
    sourceGroup.appendChild(sourceSelect);
    metaRow.appendChild(sourceGroup);

    // Evolve toggle
    var evolveGroup = document.createElement('div');
    evolveGroup.style.cssText = 'display:flex;align-items:center;gap:6px;padding-bottom:4px;';
    var evolveCheck = document.createElement('input');
    evolveCheck.type = 'checkbox';
    evolveCheck.id = 'ingest-evolve';
    evolveCheck.checked = this._state.evolve;
    evolveCheck.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);';
    evolveCheck.addEventListener('change', function() {
      window.IngestView._state.evolve = this.checked;
    });
    evolveGroup.appendChild(evolveCheck);
    var evolveLabel = document.createElement('label');
    evolveLabel.htmlFor = 'ingest-evolve';
    evolveLabel.textContent = 'Auto-evolve (extract entities & relationships)';
    evolveLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);cursor:pointer;';
    evolveGroup.appendChild(evolveLabel);
    metaRow.appendChild(evolveGroup);

    singleCard.appendChild(metaRow);

    // Submit button
    var submitBtn = document.createElement('button');
    submitBtn.id = 'ingest-submit';
    submitBtn.textContent = 'Store in Memory';
    submitBtn.style.cssText = 'margin-top:var(--sp-3,12px);padding:8px 20px;background:#238636;border:none;border-radius:var(--r-sm,6px);color:#fff;cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:background 120ms;';
    submitBtn.addEventListener('mouseenter', function() { if (!submitBtn.disabled) submitBtn.style.background = '#2EA043'; });
    submitBtn.addEventListener('mouseleave', function() { if (!submitBtn.disabled) submitBtn.style.background = '#238636'; });
    submitBtn.addEventListener('click', function() { window.IngestView.submitSingle(); });
    singleCard.appendChild(submitBtn);

    // Result area
    var resultArea = document.createElement('div');
    resultArea.id = 'ingest-result';
    resultArea.style.cssText = 'margin-top:var(--sp-3,12px);';
    singleCard.appendChild(resultArea);

    container.appendChild(singleCard);

    // Bulk section
    var bulkCard = document.createElement('div');
    bulkCard.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';

    var bulkTitle = document.createElement('h3');
    bulkTitle.textContent = 'Bulk Ingest';
    bulkTitle.style.cssText = 'margin:0 0 var(--sp-3,12px);font-size:var(--text-base,14px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    bulkCard.appendChild(bulkTitle);

    var bulkTa = document.createElement('textarea');
    bulkTa.id = 'ingest-bulk-textarea';
    bulkTa.placeholder = 'One item per line. For JSON items, place each object on its own line.\nExample:\nAPT29 used a new backdoor variant in recent campaigns\nCVE-2024-1234 is a critical RCE in Apache Log4j';
    bulkTa.style.cssText = 'width:100%;min-height:120px;padding:12px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-base,14px);font-family:var(--font-sans);resize:vertical;outline:none;box-sizing:border-box;';
    bulkCard.appendChild(bulkTa);

    var bulkBtn = document.createElement('button');
    bulkBtn.id = 'ingest-bulk-btn';
    bulkBtn.textContent = 'Bulk Ingest';
    bulkBtn.style.cssText = 'margin-top:var(--sp-2,8px);padding:8px 20px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    bulkBtn.addEventListener('mouseenter', function() { if (!bulkBtn.disabled) { bulkBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; bulkBtn.style.color = 'var(--fg-1,#C9D1D9)'; } });
    bulkBtn.addEventListener('mouseleave', function() { if (!bulkBtn.disabled) { bulkBtn.style.borderColor = 'var(--border,#30363D)'; bulkBtn.style.color = 'var(--fg-2,#8B949E)'; } });
    bulkBtn.addEventListener('click', function() { window.IngestView.submitBulk(); });
    bulkCard.appendChild(bulkBtn);

    var bulkResult = document.createElement('div');
    bulkResult.id = 'ingest-bulk-result';
    bulkResult.style.cssText = 'margin-top:var(--sp-3,12px);';
    bulkCard.appendChild(bulkResult);

    container.appendChild(bulkCard);

    // File upload section
    var uploadCard = document.createElement('div');
    uploadCard.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';

    var uploadTitle = document.createElement('h3');
    uploadTitle.textContent = 'Upload File';
    uploadTitle.style.cssText = 'margin:0 0 var(--sp-3,12px);font-size:var(--text-base,14px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    uploadCard.appendChild(uploadTitle);

    var dropZone = document.createElement('div');
    dropZone.id = 'ingest-dropzone';
    dropZone.style.cssText = 'border:2px dashed var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-8,32px);text-align:center;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:border-color 120ms,background 120ms;cursor:pointer;';
    dropZone.textContent = 'Drop .txt, .md, or .json files here, or click to browse';

    dropZone.addEventListener('dragover', function(e) {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--signal-neon,#00FFA3)';
      dropZone.style.background = 'rgba(0,255,163,0.03)';
    });
    dropZone.addEventListener('dragleave', function() {
      dropZone.style.borderColor = 'var(--border,#30363D)';
      dropZone.style.background = '';
    });
    dropZone.addEventListener('drop', function(e) {
      e.preventDefault();
      dropZone.style.borderColor = 'var(--border,#30363D)';
      dropZone.style.background = '';
      var files = e.dataTransfer.files;
      if (files.length > 0) {
        window.IngestView.handleFile(files[0]);
      }
    });
    dropZone.addEventListener('click', function() {
      var fileInput = document.getElementById('ingest-file-input');
      if (fileInput) fileInput.click();
    });

    uploadCard.appendChild(dropZone);

    var fileInput = document.createElement('input');
    fileInput.id = 'ingest-file-input';
    fileInput.type = 'file';
    fileInput.accept = '.txt,.md,.json';
    fileInput.style.cssText = 'display:none;';
    fileInput.addEventListener('change', function(e) {
      if (e.target.files.length > 0) {
        window.IngestView.handleFile(e.target.files[0]);
      }
    });
    uploadCard.appendChild(fileInput);

    var uploadStatus = document.createElement('div');
    uploadStatus.id = 'ingest-upload-status';
    uploadStatus.style.cssText = 'margin-top:var(--sp-2,8px);font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    uploadCard.appendChild(uploadStatus);

    container.appendChild(uploadCard);

    return container;
  },

  handleFile: function(file) {
    var validExts = ['.txt', '.md', '.json'];
    var ext = '.' + file.name.split('.').pop().toLowerCase();
    if (validExts.indexOf(ext) === -1) {
      var statusEl = document.getElementById('ingest-upload-status');
      if (statusEl) statusEl.textContent = 'Invalid file type. Accepted: .txt, .md, .json';
      return;
    }

    var reader = new FileReader();
    var statusEl = document.getElementById('ingest-upload-status');
    if (statusEl) statusEl.textContent = 'Reading ' + file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)...';

    reader.onload = function(e) {
      var content = e.target.result;
      var textarea = document.getElementById('ingest-textarea');
      if (textarea) {
        textarea.value = content;
        window.IngestView._state.content = content;
      }
      if (statusEl) statusEl.textContent = 'Loaded ' + file.name + ' into content field';
    };

    reader.onerror = function() {
      if (statusEl) statusEl.textContent = 'Error reading file';
    };

    reader.readAsText(file);
  },

  submitSingle: function() {
    var content = this._state.content.trim();
    if (!content) {
      window.ToastComponent.show('Please enter content to ingest', 'info');
      return;
    }

    this._state.loading = true;
    this._state.error = null;
    this._state.result = null;

    var btn = document.getElementById('ingest-submit');
    var resultArea = document.getElementById('ingest-result');
    if (btn) {
      btn.disabled = true;
      btn.style.background = 'var(--fg-3,#484F58)';
      btn.textContent = 'Storing...';
    }
    if (resultArea) {
      resultArea.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px 0;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Processing content...</div>';
    }

    var self = this;

    window.API.post('/api/remember', {
      content: content,
      domain: this._state.domain,
      source_type: this._state.source_type,
      evolve: this._state.evolve
    }).then(function(data) {
      self._state.loading = false;
      self._state.result = data;
      self._state.content = '';
      var ta = document.getElementById('ingest-textarea');
      if (ta) ta.value = '';

      if (btn) {
        btn.disabled = false;
        btn.style.background = '#238636';
        btn.textContent = 'Store in Memory';
      }

      self.renderResult(data, resultArea);
      window.ToastComponent.show('Content stored successfully', 'success');
    }).catch(function(err) {
      self._state.loading = false;
      self._state.error = err.message;
      if (btn) {
        btn.disabled = false;
        btn.style.background = '#238636';
        btn.textContent = 'Store in Memory';
      }
      if (resultArea) {
        resultArea.innerHTML = '<div style="padding:12px;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);background:var(--bg-input,#0D1117);border:1px solid var(--danger,#F85149);border-radius:var(--r-sm,6px);">Failed to store: ' + (err.message || 'unknown error') + '</div>';
      }
      window.ToastComponent.show('Store failed: ' + err.message, 'error');
    });
  },

  renderResult: function(data, container) {
    if (!container) return;
    if (!data) {
      container.innerHTML = '';
      return;
    }

    var html = '<div style="background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">';
    html += '<span style="font-size:var(--text-xs,11px);color:var(--success,#3FB950);font-family:var(--font-mono);font-weight:600;text-transform:uppercase;letter-spacing:0.04em;">Stored Successfully</span>';
    if (data.latency_ms) {
      html += '<span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);">' + data.latency_ms + 'ms</span>';
    }
    html += '</div>';

    if (data.note_id) {
      html += '<div style="margin-bottom:4px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Note ID:</span> <span style="font-size:var(--text-xs,11px);color:var(--intent-factual,#58A6FF);font-family:var(--font-mono);">' + data.note_id + '</span></div>';
    }

    if (data.status) {
      html += '<div style="margin-bottom:4px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Status:</span> <span style="font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);">' + data.status + '</span></div>';
    }

    if (data.entities && data.entities.length) {
      html += '<div style="margin-bottom:4px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Entities extracted:</span></div>';
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">';
      data.entities.forEach(function(e) {
        var entityName = typeof e === 'string' ? e : (e.name || e.label || e);
        var entityType = typeof e === 'object' ? (e.type || '') : '';
        html += '<span style="display:inline-block;padding:2px 8px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);background:var(--bg-surface-hi,#21262D);color:var(--intent-factual,#58A6FF);">' + entityName + (entityType ? ' (' + entityType + ')' : '') + '</span>';
      });
      html += '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
  },

  submitBulk: function() {
    var ta = document.getElementById('ingest-bulk-textarea');
    var resultEl = document.getElementById('ingest-bulk-result');
    if (!ta) return;

    var raw = ta.value.trim();
    if (!raw) {
      window.ToastComponent.show('Please enter items to bulk ingest', 'info');
      return;
    }

    var lines = raw.split('\n').map(function(l) { return l.trim(); }).filter(function(l) { return l.length > 0; });
    var items = lines.map(function(line) {
      // Try to parse as JSON
      var obj = null;
      try { obj = JSON.parse(line); } catch(e) {}
      if (obj && obj.content) return obj;
      return { content: line, source_type: 'manual', domain: 'general', evolve: true };
    });

    var btn = document.getElementById('ingest-bulk-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Ingesting ' + items.length + ' items...';
      btn.style.color = 'var(--fg-3,#484F58)';
    }

    if (resultEl) {
      resultEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:12px 0;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Processing ' + items.length + ' items...</div>';
    }

    var self = this;
    window.API.post('/api/ingest', { items: items }).then(function(data) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Bulk Ingest';
        btn.style.color = 'var(--fg-2,#8B949E)';
      }

      if (resultEl) {
        var html = '<div style="background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);">';
        html += '<div style="display:flex;gap:var(--sp-3,12px);margin-bottom:6px;">';
        html += '<span style="font-size:var(--text-xs,11px);color:var(--success,#3FB950);font-family:var(--font-mono);">Total: ' + (data.total || 0) + '</span>';
        html += '<span style="font-size:var(--text-xs,11px);color:var(--success,#3FB950);font-family:var(--font-mono);">Succeeded: ' + (data.succeeded || 0) + '</span>';
        html += '<span style="font-size:var(--text-xs,11px);color:var(--danger,#F85149);font-family:var(--font-mono);">Failed: ' + (data.failed || 0) + '</span>';
        html += '</div>';

        if (data.results && data.results.length) {
          data.results.forEach(function(r) {
            var statusColor = r.status === 'success' ? 'var(--success,#3FB950)' : 'var(--danger,#F85149)';
            html += '<div style="padding:4px 0;font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--fg-1,#C9D1D9);">';
            html += '<span style="color:' + statusColor + ';">[' + (r.status || '?') + ']</span> ';
            if (r.note_id) html += '<span style="color:var(--intent-factual,#58A6FF);">' + r.note_id + '</span> ';
            html += '<span style="color:var(--fg-2,#8B949E);">' + (r.message || '') + '</span>';
            html += '</div>';
          });
        }

        html += '</div>';
        resultEl.innerHTML = html;
      }

      window.ToastComponent.show('Bulk ingest complete: ' + (data.succeeded || 0) + ' succeeded, ' + (data.failed || 0) + ' failed', data.failed > 0 ? 'warning' : 'success');
    }).catch(function(err) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Bulk Ingest';
        btn.style.color = 'var(--fg-2,#8B949E)';
      }
      if (resultEl) {
        resultEl.innerHTML = '<div style="padding:12px;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);background:var(--bg-input,#0D1117);border:1px solid var(--danger,#F85149);border-radius:var(--r-sm,6px);">Bulk ingest failed: ' + (err.message || 'unknown error') + '</div>';
      }
      window.ToastComponent.show('Bulk ingest failed: ' + err.message, 'error');
    });
  }
};
