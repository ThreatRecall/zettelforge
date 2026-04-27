window.LogsView = {
  _logs: [],
  _filtered: [],
  _autoRefresh: false,
  _refreshTimer: null,
  _expandedRow: null,

  render: function() {
    var container = document.createElement('div');
    container.id = 'logs-view';
    container.style.cssText = 'max-width:960px;';

    var heading = document.createElement('h2');
    heading.textContent = 'Logs & Telemetry';
    heading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    // Filter bar
    var filterBar = document.createElement('div');
    filterBar.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);align-items:center;flex-wrap:wrap;';

    var levelLabel = document.createElement('span');
    levelLabel.textContent = 'Level:';
    levelLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    filterBar.appendChild(levelLabel);

    var levelSelect = document.createElement('select');
    levelSelect.id = 'logs-level';
    levelSelect.style.cssText = 'padding:6px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR'].forEach(function(l) {
      var opt = document.createElement('option');
      opt.value = l;
      opt.textContent = l;
      levelSelect.appendChild(opt);
    });
    levelSelect.addEventListener('change', function() { window.LogsView.applyFilters(); });
    filterBar.appendChild(levelSelect);

    var searchInput = document.createElement('input');
    searchInput.id = 'logs-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search messages...';
    searchInput.style.cssText = 'flex:1;min-width:150px;padding:6px 10px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    searchInput.addEventListener('input', function() { window.LogsView.applyFilters(); });
    filterBar.appendChild(searchInput);

    var countSpan = document.createElement('span');
    countSpan.id = 'logs-count';
    countSpan.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);white-space:nowrap;';
    countSpan.textContent = '0 entries';
    filterBar.appendChild(countSpan);

    var autoLabel = document.createElement('label');
    autoLabel.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);cursor:pointer;';

    var autoCheck = document.createElement('input');
    autoCheck.type = 'checkbox';
    autoCheck.id = 'logs-autorefresh';
    autoCheck.checked = false;
    autoCheck.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);';
    autoCheck.addEventListener('change', function() {
      window.LogsView._autoRefresh = this.checked;
      if (this.checked) {
        window.LogsView.startAutoRefresh();
      } else {
        window.LogsView.stopAutoRefresh();
      }
    });
    autoLabel.appendChild(autoCheck);
    autoLabel.appendChild(document.createTextNode('Auto-refresh (3s)'));
    filterBar.appendChild(autoLabel);

    container.appendChild(filterBar);

    // Table wrapper
    var tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);overflow:hidden;margin-bottom:var(--sp-4,16px);';

    var table = document.createElement('table');
    table.id = 'logs-table';
    table.style.cssText = 'width:100%;border-collapse:collapse;font-size:var(--text-xs,11px);font-family:var(--font-mono);';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    headerRow.style.cssText = 'background:var(--bg-input,#0D1117);';

    ['Timestamp', 'Level', 'Logger', 'Message'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:8px 12px;text-align:left;font-weight:600;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);';
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    tbody.id = 'logs-body';
    table.appendChild(tbody);

    tableWrap.appendChild(table);
    container.appendChild(tableWrap);

    // Detail panel (for expanded row)
    var detailPanel = document.createElement('div');
    detailPanel.id = 'logs-detail';
    detailPanel.style.cssText = 'display:none;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';
    container.appendChild(detailPanel);

    this.load();
    return container;
  },

  getLevelColor: function(level) {
    var map = { DEBUG: '#8B949E', INFO: '#58A6FF', WARNING: '#D29922', ERROR: '#F85149' };
    return map[level] || '#8B949E';
  },

  load: function() {
    var self = this;
    var tbody = document.getElementById('logs-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="4" style="padding:24px;text-align:center;color:var(--fg-2,#8B949E);"><div style="display:flex;align-items:center;justify-content:center;gap:8px;"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading logs...</div></td></tr>';

    window.API.get('/api/logs?lines=200').then(function(data) {
      self._logs = data.logs || [];
      self.applyFilters();
    }).catch(function(err) {
      tbody.innerHTML = '<tr><td colspan="4" style="padding:24px;text-align:center;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);">Failed to load logs: ' + (err.message || 'unknown error') + '</td></tr>';
    });
  },

  applyFilters: function() {
    var levelSelect = document.getElementById('logs-level');
    var searchInput = document.getElementById('logs-search');
    var tbody = document.getElementById('logs-body');
    var countSpan = document.getElementById('logs-count');

    if (!tbody) return;

    var levelFilter = levelSelect ? levelSelect.value : 'ALL';
    var textFilter = searchInput ? searchInput.value.toLowerCase() : '';

    var self = this;
    this._filtered = this._logs.filter(function(log) {
      if (levelFilter !== 'ALL' && (log.level || '').toUpperCase() !== levelFilter) return false;
      if (textFilter) {
        var msg = (log.message || log.msg || '').toLowerCase();
        var logger = (log.logger || '').toLowerCase();
        if (msg.indexOf(textFilter) === -1 && logger.indexOf(textFilter) === -1) return false;
      }
      return true;
    });

    if (countSpan) {
      countSpan.textContent = this._filtered.length + ' entries (of ' + this._logs.length + ')';
    }

    tbody.innerHTML = '';

    if (this._filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="padding:24px;text-align:center;color:var(--fg-3,#484F58);">No matching log entries</td></tr>';
      return;
    }

    var fragment = document.createDocumentFragment();
    this._filtered.forEach(function(log, idx) {
      var row = document.createElement('tr');
      row.style.cssText = 'cursor:pointer;transition:background 120ms;';
      row.setAttribute('data-log-idx', idx);
      row.addEventListener('click', function() { window.LogsView.expandRow(idx); });
      row.addEventListener('mouseenter', function() { row.style.background = 'var(--bg-surface-hi,#21262D)'; });
      row.addEventListener('mouseleave', function() { row.style.background = ''; });

      var ts = document.createElement('td');
      ts.textContent = log.timestamp || '---';
      ts.style.cssText = 'padding:6px 12px;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);white-space:nowrap;';
      row.appendChild(ts);

      var levelTd = document.createElement('td');
      levelTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);';
      var badge = document.createElement('span');
      var lvl = (log.level || 'INFO').toUpperCase();
      badge.textContent = lvl;
      badge.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);font-weight:600;background:var(--bg-surface-hi,#21262D);color:' + self.getLevelColor(lvl) + ';';
      levelTd.appendChild(badge);
      row.appendChild(levelTd);

      var loggerTd = document.createElement('td');
      loggerTd.textContent = log.logger || '---';
      loggerTd.style.cssText = 'padding:6px 12px;color:var(--intent-factual,#58A6FF);border-bottom:1px solid var(--border,#30363D);white-space:nowrap;max-width:200px;overflow:hidden;text-overflow:ellipsis;';
      row.appendChild(loggerTd);

      var msgTd = document.createElement('td');
      msgTd.textContent = log.message || log.msg || '---';
      msgTd.style.cssText = 'padding:6px 12px;color:var(--fg-1,#C9D1D9);border-bottom:1px solid var(--border,#30363D);max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(msgTd);

      fragment.appendChild(row);
    });

    tbody.appendChild(fragment);
  },

  expandRow: function(idx) {
    var log = this._filtered[idx];
    if (!log) return;

    var panel = document.getElementById('logs-detail');
    if (!panel) return;

    if (this._expandedRow === idx) {
      panel.style.display = 'none';
      this._expandedRow = null;
      return;
    }

    this._expandedRow = idx;

    var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3,12px);">';
    html += '<div style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);text-transform:uppercase;letter-spacing:0.04em;">Log Entry Detail</div>';
    html += '<button id="logs-detail-close" style="background:none;border:none;color:var(--fg-2,#8B949E);cursor:pointer;font-size:14px;padding:2px;">x</button>';
    html += '</div>';

    html += '<pre style="margin:0;font-family:var(--font-mono);font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);white-space:pre-wrap;word-break:break-all;background:var(--bg-surface,#161B22);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);max-height:300px;overflow-y:auto;">' + JSON.stringify(log, null, 2) + '</pre>';

    panel.innerHTML = html;
    panel.style.display = 'block';

    var closeBtn = document.getElementById('logs-detail-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function() {
        panel.style.display = 'none';
        window.LogsView._expandedRow = null;
      });
    }
  },

  startAutoRefresh: function() {
    var self = this;
    this.stopAutoRefresh();
    this._refreshTimer = setInterval(function() {
      window.API.get('/api/logs?lines=200').then(function(data) {
        self._logs = data.logs || [];
        self.applyFilters();
      }).catch(function() {});
    }, 3000);
  },

  stopAutoRefresh: function() {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  }
};
