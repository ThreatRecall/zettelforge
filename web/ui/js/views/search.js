window.SearchView = {
  _state: {
    query: '',
    mode: 'recall',
    format: 'synthesized_brief',
    loading: false,
    results: [],
    synthesis: null,
    status: '',
    error: '',
    rememberValue: ''
  },

  render: function() {
    var container = document.createElement('div');
    container.id = 'search-view';

    // Search bar
    var searchWrap = document.createElement('div');
    searchWrap.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);';

    var input = document.createElement('input');
    input.id = 'search-input';
    input.type = 'text';
    input.placeholder = 'Search threat intelligence... (e.g., What tools does APT28 use?)';
    input.value = this._state.query;
    input.style.cssText = 'flex:1;padding:12px 16px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-md,15px);font-family:var(--font-sans);outline:none;transition:border-color 120ms,box-shadow 120ms;';
    input.addEventListener('focus', function() { input.style.borderColor = 'var(--border-focus,#58A6FF)'; input.style.boxShadow = '0 0 0 3px rgba(88,166,255,0.10)'; });
    input.addEventListener('blur', function() { input.style.borderColor = ''; input.style.boxShadow = ''; });
    input.addEventListener('input', function() {
      window.SearchView._state.query = this.value;
    });
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') window.SearchView.runSearch();
    });
    searchWrap.appendChild(input);

    var btn = document.createElement('button');
    btn.textContent = 'Search';
    btn.style.cssText = 'padding:12px 24px;background:#238636;border:none;border-radius:var(--r-sm,6px);color:#fff;font-size:var(--text-md,15px);cursor:pointer;font-weight:500;font-family:var(--font-sans);transition:background 120ms;';
    btn.addEventListener('mouseenter', function() { btn.style.background = '#2EA043'; });
    btn.addEventListener('mouseleave', function() { btn.style.background = '#238636'; });
    btn.addEventListener('click', function() { window.SearchView.runSearch(); });
    searchWrap.appendChild(btn);

    container.appendChild(searchWrap);

    // Format selector (synthesize mode)
    var formatRow = document.createElement('div');
    formatRow.id = 'format-row';
    formatRow.style.cssText = 'display:' + (this._state.mode === 'synthesize' ? 'flex' : 'none') + ';gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);align-items:center;';

    var formatLabel = document.createElement('span');
    formatLabel.textContent = 'format:';
    formatLabel.style.cssText = 'font-size:var(--text-sm,12px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    formatRow.appendChild(formatLabel);

    var formats = [
      { value: 'direct_answer', label: 'Direct' },
      { value: 'synthesized_brief', label: 'Brief' },
      { value: 'timeline_analysis', label: 'Timeline' },
      { value: 'relationship_map', label: 'Relationships' }
    ];
    var self = this;
    formats.forEach(function(f) {
      var opt = document.createElement('button');
      opt.textContent = f.label;
      var active = self._state.format === f.value;
      opt.style.cssText = 'padding:4px 12px;font-size:var(--text-xs,11px);background:' + (active ? 'var(--bg-surface-hi,#21262D)' : 'transparent') + ';border:1px solid ' + (active ? 'var(--border-focus,#58A6FF)' : 'var(--border,#30363D)') + ';border-radius:var(--r-pill,9999px);color:' + (active ? 'var(--fg-1,#C9D1D9)' : 'var(--fg-2,#8B949E)') + ';cursor:pointer;font-family:var(--font-sans);transition:color 120ms,background 120ms,border-color 120ms;';
      opt.addEventListener('click', function() {
        self._state.format = f.value;
        var btns = document.getElementById('format-row').querySelectorAll('button');
        btns.forEach(function(b, idx) {
          var fmt = formats[idx];
          if (!fmt) return;
          var act = self._state.format === fmt.value;
          b.style.background = act ? 'var(--bg-surface-hi,#21262D)' : 'transparent';
          b.style.borderColor = act ? 'var(--border-focus,#58A6FF)' : 'var(--border,#30363D)';
          b.style.color = act ? 'var(--fg-1,#C9D1D9)' : 'var(--fg-2,#8B949E)';
        });
      });
      formatRow.appendChild(opt);
    });

    container.appendChild(formatRow);

    // Tab bar
    var tabContainer = document.createElement('div');
    tabContainer.id = 'search-tabs';
    var tabs = ['recall', 'synthesize', 'remember'];
    var tabLabels = { recall: 'Recall', synthesize: 'Synthesize', remember: 'Remember' };
    function onTabChange(m) {
      self._state.mode = m;
      var formatRow = document.getElementById('format-row');
      if (formatRow) formatRow.style.display = (m === 'synthesize' ? 'flex' : 'none');

      var rememberPanel = document.getElementById('remember-panel');
      if (rememberPanel) rememberPanel.style.display = (m === 'remember' ? 'block' : 'none');

      // Re-render tabs
      var tabContainer = document.getElementById('search-tabs');
      if (tabContainer) {
        tabContainer.innerHTML = '';
        tabContainer.appendChild(window.TabsComponent.render(m, tabs, tabLabels, onTabChange));
      }
    }
    var tabEl = window.TabsComponent.render(this._state.mode, tabs, tabLabels, onTabChange);
    tabContainer.appendChild(tabEl);
    container.appendChild(tabContainer);

    // Status bar
    var statusBar = document.createElement('div');
    statusBar.id = 'search-status';
    statusBar.style.cssText = 'color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);font-family:var(--font-mono);margin-bottom:var(--sp-4,16px);';
    statusBar.textContent = this._state.status || '';
    container.appendChild(statusBar);

    // Results area
    var resultsArea = document.createElement('div');
    resultsArea.id = 'search-results';
    resultsArea.style.cssText = 'display:flex;flex-direction:column;gap:12px;';
    container.appendChild(resultsArea);

    // Remember panel
    var rememberPanel = document.createElement('div');
    rememberPanel.id = 'remember-panel';
    rememberPanel.style.display = (this._state.mode === 'remember' ? 'block' : 'none');
    rememberPanel.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-6,24px);';

    var ta = document.createElement('textarea');
    ta.id = 'remember-textarea';
    ta.placeholder = 'Paste threat intelligence to store...';
    ta.value = this._state.rememberValue;
    ta.style.cssText = 'width:100%;min-height:100px;padding:12px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-base,14px);resize:vertical;font-family:var(--font-sans);outline:none;box-sizing:border-box;';
    ta.addEventListener('input', function() {
      window.SearchView._state.rememberValue = this.value;
    });
    rememberPanel.appendChild(ta);

    var actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-top:var(--sp-2,8px);';

    var storeBtn = document.createElement('button');
    storeBtn.textContent = 'Store in Memory';
    storeBtn.style.cssText = 'padding:8px 16px;background:#238636;border:none;border-radius:var(--r-sm,6px);color:#fff;cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:background 120ms;';
    storeBtn.addEventListener('mouseenter', function() { storeBtn.style.background = '#2EA043'; });
    storeBtn.addEventListener('mouseleave', function() { storeBtn.style.background = '#238636'; });
    storeBtn.addEventListener('click', function() { window.SearchView.storeNote(); });
    actions.appendChild(storeBtn);

    rememberPanel.appendChild(actions);
    container.appendChild(rememberPanel);

    // Restore results if we had any
    if (this._state.status) {
      this.renderResults();
    }

    return container;
  },

  runSearch: function() {
    var q = this._state.query.trim();
    if (!q) return;
    this._state.loading = true;
    this._state.error = '';
    this._state.synthesis = null;

    var statusEl = document.getElementById('search-status');
    var resultsEl = document.getElementById('search-results');
    if (!resultsEl) return;

    if (statusEl) statusEl.textContent = 'searching...';
    resultsEl.innerHTML = '';
    var spinner = window.SpinnerComponent.render();
    resultsEl.appendChild(spinner);

    var self = this;

    if (this._state.mode === 'synthesize') {
      window.API.post('/api/synthesize', {
        query: q,
        format: this._state.format
      }).then(function(data) {
        self._state.loading = false;
        var synthesis = data.synthesis || data;
        synthesis.format = data.format || self._state.format;
        synthesis.latency_ms = data.latency_ms;
        synthesis.sources_count = data.sources_count || 0;
        self._state.synthesis = synthesis;
        self._state.status = 'synthesis complete \u00B7 ' + (data.latency_ms || '---') + 'ms \u00B7 ' + (data.sources_count || 0) + ' sources';
        self.renderResults();
      }).catch(function(err) {
        self._state.loading = false;
        self._state.error = err.message;
        self.renderResults();
      });
    } else {
      window.API.post('/api/recall', {
        query: q
      }).then(function(data) {
        self._state.loading = false;
        var results = data.results || data.notes || data || [];
        if (Array.isArray(results)) {
          self._state.results = results;
        } else {
          self._state.results = [results];
        }
        self._state.status = self._state.results.length + ' results';
        self.renderResults();
      }).catch(function(err) {
        self._state.loading = false;
        self._state.error = err.message;
        self.renderResults();
      });
    }
  },

  renderResults: function() {
    var statusEl = document.getElementById('search-status');
    var resultsEl = document.getElementById('search-results');
    if (!resultsEl) return;

    resultsEl.innerHTML = '';

    if (this._state.error) {
      var errorCard = document.createElement('div');
      errorCard.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--danger,#F85149);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);';
      errorCard.textContent = this._state.error;
      resultsEl.appendChild(errorCard);
      if (statusEl) statusEl.textContent = 'error: ' + this._state.error;
      return;
    }

    if (this._state.mode === 'synthesize' && this._state.synthesis) {
      var synth = this._state.synthesis;
      var block = document.createElement('div');
      block.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-5,20px);margin-bottom:var(--sp-4,16px);';

      var head = document.createElement('div');
      head.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--sp-3,12px);';

      var title = document.createElement('h3');
      title.textContent = 'Synthesis';
      title.style.cssText = 'color:var(--intent-factual,#58A6FF);font-size:var(--text-lg,18px);font-weight:var(--fw-semibold,600);margin:0;';
      head.appendChild(title);

      var meta = document.createElement('span');
      var sources = synth.sources || synth.source_ids || synth.citations || [];
      var srcCount = synth.sources_count !== undefined ? synth.sources_count : sources.length;
      meta.textContent = (synth.format || this._state.format) + ' \u00B7 ' + (synth.latency_ms || '---') + 'ms \u00B7 ' + srcCount + ' sources';
      meta.style.cssText = 'font-family:var(--font-mono);font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);';
      head.appendChild(meta);
      block.appendChild(head);

      var answer = document.createElement('div');
      answer.textContent = synth.answer || synth.summary || synth.content || (Array.isArray(synth.citations) ? synth.citations.map(function(c) { return c.text || c.id || String(c); }).join('\n') : '') || 'No synthesis content returned.';
      answer.style.cssText = 'font-size:var(--text-base,14px);line-height:var(--lh-relaxed,1.7);color:var(--fg-1,#C9D1D9);white-space:pre-wrap;';
      block.appendChild(answer);

      if (sources && sources.length) {
        var srcSection = document.createElement('div');
        srcSection.style.cssText = 'margin-top:14px;padding-top:12px;border-top:1px solid var(--bg-surface-hi,#21262D);display:flex;gap:var(--sp-2,8px);flex-wrap:wrap;font-family:var(--font-mono);font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);align-items:center;';

        var srcLabel = document.createElement('span');
        srcLabel.textContent = 'sources:';
        srcSection.appendChild(srcLabel);

        sources.forEach(function(s) {
          var src = document.createElement('span');
          src.textContent = typeof s === 'string' ? s : (s.id || s.note_id || s.text || JSON.stringify(s));
          src.style.cssText = 'color:var(--intent-factual,#58A6FF);';
          srcSection.appendChild(src);
        });

        block.appendChild(srcSection);
      }

      resultsEl.appendChild(block);
    }

    if (this._state.mode === 'recall') {
      if (this._state.query && !this._state.loading && this._state.results.length === 0 && !this._state.error) {
        var empty = document.createElement('div');
        empty.style.cssText = 'text-align:center;padding:var(--sp-12,48px);color:var(--fg-3,#484F58);';
        var emptyTitle = document.createElement('h3');
        emptyTitle.textContent = 'No results';
        emptyTitle.style.cssText = 'font-size:var(--text-lg,18px);margin-bottom:var(--sp-2,8px);color:var(--fg-2,#8B949E);font-weight:500;';
        empty.appendChild(emptyTitle);
        var emptySub = document.createElement('p');
        emptySub.textContent = 'Try a different query or a known entity name.';
        emptySub.style.cssText = 'margin:0;font-size:var(--text-base,14px);';
        empty.appendChild(emptySub);
        resultsEl.appendChild(empty);
      } else if (this._state.results.length > 0) {
        var self = this;
        this._state.results.forEach(function(note) {
          resultsEl.appendChild(window.ResultCardComponent.render(note));
        });
      } else if (!this._state.query && !this._state.loading) {
        var empty = document.createElement('div');
        empty.style.cssText = 'text-align:center;padding:var(--sp-12,48px);color:var(--fg-3,#484F58);';
        var emptyTitle = document.createElement('h3');
        emptyTitle.textContent = 'ZettelForge CTI Memory';
        emptyTitle.style.cssText = 'font-size:var(--text-lg,18px);margin-bottom:var(--sp-2,8px);color:var(--fg-2,#8B949E);font-weight:500;';
        empty.appendChild(emptyTitle);
        var emptySub = document.createElement('p');
        emptySub.textContent = 'Search across threat actors, CVEs, tools, campaigns, and reports.';
        emptySub.style.cssText = 'margin:0;font-size:var(--text-base,14px);';
        empty.appendChild(emptySub);
        resultsEl.appendChild(empty);
      }
    }

    // Status
    if (statusEl) {
      statusEl.textContent = this._state.status || '';
    }
  },

  storeNote: function() {
    var content = this._state.rememberValue.trim();
    if (!content) return;

    var self = this;
    window.API.post('/api/remember', {
      content: content,
      domain: 'cti',
      source_type: 'manual',
      evolve: true
    }).then(function(data) {
      self._state.rememberValue = '';
      var ta = document.getElementById('remember-textarea');
      if (ta) ta.value = '';
      window.ToastComponent.show('Stored: ' + (data.note_id || 'ok'), 'success');

      var statusEl = document.getElementById('search-status');
      if (statusEl) statusEl.textContent = 'Stored note successfully';
    }).catch(function(err) {
      window.ToastComponent.show('Store failed: ' + err.message, 'error');
    });
  }
};
