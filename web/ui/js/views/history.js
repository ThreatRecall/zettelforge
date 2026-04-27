window.HistoryView = {
  _allHistory: [],
  _filtered: [],
  _expandedRow: null,

  render: function() {
    var container = document.createElement('div');
    container.id = 'history-view';
    container.style.cssText = 'max-width:960px;';

    var heading = document.createElement('h2');
    heading.textContent = 'Query History';
    heading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    // Filter bar
    var filterBar = document.createElement('div');
    filterBar.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);align-items:center;flex-wrap:wrap;';

    var dateLabel = document.createElement('span');
    dateLabel.textContent = 'Date:';
    dateLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    filterBar.appendChild(dateLabel);

    var dateSelect = document.createElement('select');
    dateSelect.id = 'history-date';
    dateSelect.style.cssText = 'padding:6px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    ['All', 'Today', '7 days', '30 days'].forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d.toLowerCase();
      opt.textContent = d;
      dateSelect.appendChild(opt);
    });
    var self = this;
    dateSelect.addEventListener('change', function() { self.applyFilters(); });
    filterBar.appendChild(dateSelect);

    var countSpan = document.createElement('span');
    countSpan.id = 'history-count';
    countSpan.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);white-space:nowrap;';
    countSpan.textContent = '0 entries';
    filterBar.appendChild(countSpan);

    var exportBtn = document.createElement('button');
    exportBtn.textContent = 'Export JSON';
    exportBtn.style.cssText = 'margin-left:auto;padding:6px 14px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-xs,11px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    exportBtn.addEventListener('mouseenter', function() { exportBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; exportBtn.style.color = 'var(--fg-1,#C9D1D9)'; });
    exportBtn.addEventListener('mouseleave', function() { exportBtn.style.borderColor = 'var(--border,#30363D)'; exportBtn.style.color = 'var(--fg-2,#8B949E)'; });
    exportBtn.addEventListener('click', function() { window.HistoryView.exportJSON(); });
    filterBar.appendChild(exportBtn);

    container.appendChild(filterBar);

    // Table
    var tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);overflow:hidden;margin-bottom:var(--sp-4,16px);';

    var table = document.createElement('table');
    table.id = 'history-table';
    table.style.cssText = 'width:100%;border-collapse:collapse;font-size:var(--text-xs,11px);font-family:var(--font-mono);';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    headerRow.style.cssText = 'background:var(--bg-input,#0D1117);';

    ['Timestamp', 'Type', 'Query', 'Latency', 'Results', 'Intent'].forEach(function(h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:8px 12px;text-align:left;font-weight:600;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);white-space:nowrap;';
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    tbody.id = 'history-body';
    table.appendChild(tbody);

    tableWrap.appendChild(table);
    container.appendChild(tableWrap);

    // Detail panel
    var detailPanel = document.createElement('div');
    detailPanel.id = 'history-detail';
    detailPanel.style.cssText = 'display:none;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';
    container.appendChild(detailPanel);

    this.load();
    return container;
  },

  getTypeColor: function(eventType) {
    var et = (eventType || '').toLowerCase();
    if (et === 'recall' || eventType === 'recall') return '#58A6FF';
    if (et === 'synthesis' || eventType === 'synthesis') return '#A371F7';
    if (et === 'remember' || eventType === 'remember') return '#3FB950';
    return '#8B949E';
  },

  load: function() {
    var self = this;
    var tbody = document.getElementById('history-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="6" style="padding:24px;text-align:center;color:var(--fg-2,#8B949E);"><div style="display:flex;align-items:center;justify-content:center;gap:8px;"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading history...</div></td></tr>';

    window.API.get('/api/history').then(function(data) {
      self._allHistory = data || [];
      self.applyFilters();
    }).catch(function(err) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:24px;text-align:center;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);">Failed to load history: ' + (err.message || 'unknown error') + '</td></tr>';
    });
  },

  applyFilters: function() {
    var dateSelect = document.getElementById('history-date');
    var tbody = document.getElementById('history-body');
    if (!tbody) return;

    var dateFilter = dateSelect ? dateSelect.value : 'all';
    var now = new Date();
    var cutoff = null;

    if (dateFilter === 'today') {
      cutoff = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    } else if (dateFilter === '7 days') {
      cutoff = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    } else if (dateFilter === '30 days') {
      cutoff = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    }

    this._filtered = this._allHistory.filter(function(h) {
      if (!cutoff) return true;
      var ts = new Date(h.timestamp || h.created_at);
      return ts >= cutoff;
    });

    var countSpan = document.getElementById('history-count');
    if (countSpan) countSpan.textContent = this._filtered.length + ' entries';

    this.renderRows();
  },

  renderRows: function() {
    var tbody = document.getElementById('history-body');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (this._filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:24px;text-align:center;color:var(--fg-3,#484F58);">No query history found</td></tr>';
      return;
    }

    var self = this;
    var fragment = document.createDocumentFragment();

    this._filtered.forEach(function(entry, idx) {
      var row = document.createElement('tr');
      row.setAttribute('data-history-idx', idx);
      row.style.cssText = 'cursor:pointer;transition:background 120ms;';
      row.addEventListener('click', function() { window.HistoryView.expandRow(idx); });
      row.addEventListener('mouseenter', function() { row.style.background = 'var(--bg-surface-hi,#21262D)'; });
      row.addEventListener('mouseleave', function() { row.style.background = ''; });

      // Timestamp
      var tsTd = document.createElement('td');
      var ts = entry.timestamp || entry.created_at || '';
      tsTd.textContent = ts.length > 19 ? ts.slice(0, 19).replace('T', ' ') : ts;
      tsTd.style.cssText = 'padding:6px 12px;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);white-space:nowrap;';
      row.appendChild(tsTd);

      // Type badge
      var typeTd = document.createElement('td');
      typeTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);';
      var typeBadge = document.createElement('span');
      var eventType = entry.event_type || entry.type || 'recall';
      typeBadge.textContent = eventType.charAt(0).toUpperCase() + eventType.slice(1);
      var eColor = self.getTypeColor(eventType);
      typeBadge.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);font-weight:600;background:var(--bg-surface-hi,#21262D);color:' + eColor + ';';
      typeTd.appendChild(typeBadge);
      row.appendChild(typeTd);

      // Query text
      var qTd = document.createElement('td');
      qTd.textContent = entry.query || '---';
      qTd.style.cssText = 'padding:6px 12px;color:var(--fg-1,#C9D1D9);border-bottom:1px solid var(--border,#30363D);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(qTd);

      // Latency
      var latTd = document.createElement('td');
      var lat = entry.duration_ms !== undefined ? entry.duration_ms + 'ms' : '---';
      latTd.textContent = lat;
      latTd.style.cssText = 'padding:6px 12px;color:var(--fg-1,#C9D1D9);border-bottom:1px solid var(--border,#30363D);white-space:nowrap;';
      row.appendChild(latTd);

      // Result count
      var resTd = document.createElement('td');
      resTd.textContent = entry.result_count !== undefined ? entry.result_count.toString() : '---';
      resTd.style.cssText = 'padding:6px 12px;color:var(--fg-1,#C9D1D9);border-bottom:1px solid var(--border,#30363D);text-align:center;';
      row.appendChild(resTd);

      // Intent
      var intentTd = document.createElement('td');
      intentTd.textContent = entry.intent || '---';
      intentTd.style.cssText = 'padding:6px 12px;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(intentTd);

      fragment.appendChild(row);
    });

    tbody.appendChild(fragment);
  },

  expandRow: function(idx) {
    var entry = this._filtered[idx];
    if (!entry) return;

    var panel = document.getElementById('history-detail');
    if (!panel) return;

    if (this._expandedRow === idx) {
      panel.style.display = 'none';
      this._expandedRow = null;
      return;
    }

    this._expandedRow = idx;

    var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3,12px);">';
    html += '<div style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);text-transform:uppercase;letter-spacing:0.04em;">Query Detail</div>';
    html += '<button id="history-detail-close" style="background:none;border:none;color:var(--fg-2,#8B949E);cursor:pointer;font-size:14px;padding:2px;">x</button>';
    html += '</div>';

    html += '<div style="margin-bottom:var(--sp-3,12px);">';
    if (entry.query) {
      html += '<div style="font-size:var(--text-base,14px);font-weight:500;color:var(--fg-1,#C9D1D9);margin-bottom:6px;">' + entry.query + '</div>';
    }

    var eventType = entry.event_type || entry.type || '';
    var eColor = this.getTypeColor(eventType);
    html += '<div style="display:flex;gap:var(--sp-3,12px);flex-wrap:wrap;font-size:var(--text-xs,11px);font-family:var(--font-mono);color:var(--fg-2,#8B949E);">';
    html += '<span>Type: <span style="color:' + eColor + ';">' + (eventType || '---') + '</span></span>';
    if (entry.duration_ms !== undefined) html += '<span>Latency: <span style="color:var(--fg-1,#C9D1D9);">' + entry.duration_ms + 'ms</span></span>';
    if (entry.result_count !== undefined) html += '<span>Results: <span style="color:var(--fg-1,#C9D1D9);">' + entry.result_count + '</span></span>';
    if (entry.actor) html += '<span>Actor: <span style="color:var(--fg-1,#C9D1D9);">' + entry.actor + '</span></span>';
    html += '</div>';
    html += '</div>';

    // Re-run query button
    if (entry.query) {
      html += '<div style="margin-bottom:var(--sp-3,12px);">';
      html += '<button id="history-rerun" style="padding:6px 14px;background:var(--bg-surface,#161B22);border:1px solid var(--intent-factual,#58A6FF);border-radius:var(--r-sm,6px);color:var(--intent-factual,#58A6FF);cursor:pointer;font-size:var(--text-xs,11px);font-family:var(--font-mono);transition:background 120ms,color 120ms;">Re-run Query</button>';
      html += '</div>';
    }

    // Full data
    html += '<pre style="margin:0;font-family:var(--font-mono);font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);white-space:pre-wrap;word-break:break-all;background:var(--bg-input,#0D1117);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);max-height:250px;overflow-y:auto;">' + JSON.stringify(entry, null, 2) + '</pre>';

    panel.innerHTML = html;
    panel.style.display = 'block';

    var closeBtn = document.getElementById('history-detail-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function() {
        panel.style.display = 'none';
        window.HistoryView._expandedRow = null;
      });
    }

    var rerunBtn = document.getElementById('history-rerun');
    if (rerunBtn) {
      rerunBtn.addEventListener('mouseenter', function() { rerunBtn.style.background = 'var(--bg-surface-hi,#21262D)'; });
      rerunBtn.addEventListener('mouseleave', function() { rerunBtn.style.background = ''; });
      rerunBtn.addEventListener('click', function() {
        if (entry.query) {
          window.location.hash = '#search';
        }
      });
    }
  },

  exportJSON: function() {
    var data = this._filtered.length > 0 ? this._filtered : this._allHistory;
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'zettelforge-history-' + new Date().toISOString().slice(0, 10) + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    window.ToastComponent.show('Exported ' + data.length + ' history entries', 'success');
  }
};
