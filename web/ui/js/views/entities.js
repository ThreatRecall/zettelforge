window.EntitiesView = {
  _allEntities: [],
  _filtered: [],
  _page: 0,
  _pageSize: 25,
  _sortKey: null,
  _sortAsc: true,
  _expandedRow: null,

  render: function() {
    var container = document.createElement('div');
    container.id = 'entities-view';
    container.style.cssText = 'max-width:960px;';

    var heading = document.createElement('h2');
    heading.textContent = 'Entities';
    heading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    // Filter bar
    var filterBar = document.createElement('div');
    filterBar.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);align-items:center;flex-wrap:wrap;';

    var typeLabel = document.createElement('span');
    typeLabel.textContent = 'Type:';
    typeLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    filterBar.appendChild(typeLabel);

    var typeSelect = document.createElement('select');
    typeSelect.id = 'entities-type';
    typeSelect.style.cssText = 'padding:6px 8px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    var typeOpts = ['ALL', 'actor', 'cve', 'tool', 'campaign', 'malware', 'indicator', 'report', 'unknown'];
    var self = this;
    typeOpts.forEach(function(t) {
      var opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    });
    typeSelect.addEventListener('change', function() { self._page = 0; self.applyFilters(); });
    filterBar.appendChild(typeSelect);

    var tierLabel = document.createElement('span');
    tierLabel.textContent = 'Tier:';
    tierLabel.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    filterBar.appendChild(tierLabel);

    var tierA = document.createElement('label');
    tierA.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:var(--text-xs,11px);color:var(--tier-a-fg,#3FB950);cursor:pointer;';
    var cbA = document.createElement('input');
    cbA.type = 'checkbox';
    cbA.checked = true;
    cbA.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);';
    cbA.addEventListener('change', function() { self._page = 0; self.applyFilters(); });
    tierA.appendChild(cbA);
    tierA.appendChild(document.createTextNode('A'));
    filterBar.appendChild(tierA);

    var tierB = document.createElement('label');
    tierB.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:var(--text-xs,11px);color:var(--tier-b-fg,#A371F7);cursor:pointer;padding-left:8px;';
    var cbB = document.createElement('input');
    cbB.type = 'checkbox';
    cbB.checked = true;
    cbB.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);';
    cbB.addEventListener('change', function() { self._page = 0; self.applyFilters(); });
    tierB.appendChild(cbB);
    tierB.appendChild(document.createTextNode('B'));
    filterBar.appendChild(tierB);

    var tierC = document.createElement('label');
    tierC.style.cssText = 'display:flex;align-items:center;gap:4px;font-size:var(--text-xs,11px);color:var(--tier-c-fg,#D29922);cursor:pointer;padding-left:8px;';
    var cbC = document.createElement('input');
    cbC.type = 'checkbox';
    cbC.checked = true;
    cbC.style.cssText = 'accent-color:var(--signal-neon,#00FFA3);';
    cbC.addEventListener('change', function() { self._page = 0; self.applyFilters(); });
    tierC.appendChild(cbC);
    tierC.appendChild(document.createTextNode('C'));
    filterBar.appendChild(tierC);

    var searchInput = document.createElement('input');
    searchInput.id = 'entities-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search entities...';
    searchInput.style.cssText = 'flex:1;min-width:150px;padding:6px 10px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-xs,11px);font-family:var(--font-sans);outline:none;';
    searchInput.addEventListener('input', function() { self._page = 0; self.applyFilters(); });
    filterBar.appendChild(searchInput);

    var countSpan = document.createElement('span');
    countSpan.id = 'entities-count';
    countSpan.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);white-space:nowrap;';
    countSpan.textContent = '0 entities';
    filterBar.appendChild(countSpan);

    container.appendChild(filterBar);

    // Table
    var tableWrap = document.createElement('div');
    tableWrap.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);overflow:hidden;margin-bottom:var(--sp-4,16px);';

    var table = document.createElement('table');
    table.id = 'entities-table';
    table.style.cssText = 'width:100%;border-collapse:collapse;font-size:var(--text-xs,11px);';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    headerRow.style.cssText = 'background:var(--bg-input,#0D1117);';

    var columns = [
      { key: 'name', label: 'Name' },
      { key: 'type', label: 'Type' },
      { key: 'tier', label: 'Tier' },
      { key: 'confidence', label: 'Confidence' },
      { key: 'aliases', label: 'Aliases' }
    ];

    columns.forEach(function(col) {
      var th = document.createElement('th');
      th.textContent = col.label;
      th.style.cssText = 'padding:8px 12px;text-align:left;font-weight:600;color:var(--fg-2,#8B949E);border-bottom:1px solid var(--border,#30363D);cursor:pointer;transition:color 120ms;white-space:nowrap;';
      th.addEventListener('click', function() {
        if (self._sortKey === col.key) {
          self._sortAsc = !self._sortAsc;
        } else {
          self._sortKey = col.key;
          self._sortAsc = true;
        }
        self.sortAndRender();
      });
      th.addEventListener('mouseenter', function() { th.style.color = 'var(--fg-1,#C9D1D9)'; });
      th.addEventListener('mouseleave', function() { th.style.color = 'var(--fg-2,#8B949E)'; });

      if (self._sortKey === col.key) {
        th.textContent = col.label + (self._sortAsc ? ' \u25B2' : ' \u25BC');
      }
      headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    tbody.id = 'entities-body';
    table.appendChild(tbody);

    tableWrap.appendChild(table);
    container.appendChild(tableWrap);

    // Pagination
    var pagination = document.createElement('div');
    pagination.id = 'entities-pagination';
    pagination.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:var(--sp-3,12px);padding:var(--sp-3,12px) 0;margin-bottom:var(--sp-6,24px);';

    var prevBtn = document.createElement('button');
    prevBtn.id = 'entities-prev';
    prevBtn.textContent = 'Previous';
    prevBtn.style.cssText = 'padding:6px 14px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-xs,11px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    prevBtn.addEventListener('mouseenter', function() { prevBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; prevBtn.style.color = 'var(--fg-1,#C9D1D9)'; });
    prevBtn.addEventListener('mouseleave', function() { prevBtn.style.borderColor = 'var(--border,#30363D)'; prevBtn.style.color = 'var(--fg-2,#8B949E)'; });
    prevBtn.addEventListener('click', function() {
      if (self._page > 0) { self._page--; self.renderPage(); }
    });
    pagination.appendChild(prevBtn);

    var pageInfo = document.createElement('span');
    pageInfo.id = 'entities-page-info';
    pageInfo.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
    pageInfo.textContent = 'Page 1 of 1';
    pagination.appendChild(pageInfo);

    var nextBtn = document.createElement('button');
    nextBtn.id = 'entities-next';
    nextBtn.textContent = 'Next';
    nextBtn.style.cssText = 'padding:6px 14px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-xs,11px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    nextBtn.addEventListener('mouseenter', function() { nextBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; nextBtn.style.color = 'var(--fg-1,#C9D1D9)'; });
    nextBtn.addEventListener('mouseleave', function() { nextBtn.style.borderColor = 'var(--border,#30363D)'; nextBtn.style.color = 'var(--fg-2,#8B949E)'; });
    nextBtn.addEventListener('click', function() {
      var totalPages = Math.ceil(self._filtered.length / self._pageSize);
      if (self._page < totalPages - 1) { self._page++; self.renderPage(); }
    });
    pagination.appendChild(nextBtn);

    container.appendChild(pagination);

    // Expanded detail panel
    var detailPanel = document.createElement('div');
    detailPanel.id = 'entities-detail';
    detailPanel.style.cssText = 'display:none;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-4,16px);';
    container.appendChild(detailPanel);

    this.load();
    return container;
  },

  load: function() {
    var self = this;
    var tbody = document.getElementById('entities-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--fg-2,#8B949E);"><div style="display:flex;align-items:center;justify-content:center;gap:8px;"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading entities...</div></td></tr>';

    window.API.get('/api/entities?offset=0&limit=500').then(function(data) {
      self._allEntities = data.entities || [];
      self.applyFilters();
    }).catch(function(err) {
      tbody.innerHTML = '<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);">Failed to load entities: ' + (err.message || 'unknown error') + '</td></tr>';
    });
  },

  applyFilters: function() {
    var typeSelect = document.getElementById('entities-type');
    var searchInput = document.getElementById('entities-search');
    var tbody = document.getElementById('entities-body');
    if (!tbody) return;

    var typeFilter = typeSelect ? typeSelect.value : 'ALL';
    var textFilter = searchInput ? searchInput.value.toLowerCase() : '';

    var tierFilters = {};
    var tierCheckboxes = document.querySelectorAll('#entities-view input[type="checkbox"]');
    tierCheckboxes.forEach(function(cb) {
      var parentLabel = cb.parentElement;
      if (parentLabel) {
        var tierChar = parentLabel.textContent.trim();
        if (tierChar) tierFilters[tierChar.toLowerCase()] = cb.checked;
      }
    });

    this._filtered = this._allEntities.filter(function(e) {
      if (typeFilter !== 'ALL' && (e.type || '').toLowerCase() !== typeFilter.toLowerCase()) return false;
      if (textFilter) {
        var name = (e.name || '').toLowerCase();
        var id = (e.id || '').toLowerCase();
        var aliases = (e.aliases || []).join(' ').toLowerCase();
        if (name.indexOf(textFilter) === -1 && id.indexOf(textFilter) === -1 && aliases.indexOf(textFilter) === -1) return false;
      }
      var t = (e.tier || 'b').toLowerCase();
      if (tierFilters[t] === false) return false;
      return true;
    });

    var countSpan = document.getElementById('entities-count');
    if (countSpan) countSpan.textContent = this._filtered.length + ' entities';

    this._page = 0;
    this.sortAndRender();
  },

  sortAndRender: function() {
    var key = this._sortKey;
    var asc = this._sortAsc;

    if (key) {
      this._filtered.sort(function(a, b) {
        var va = a[key];
        var vb = b[key];
        if (va === undefined || va === null) va = '';
        if (vb === undefined || vb === null) vb = '';
        if (typeof va === 'number') return asc ? va - vb : vb - va;
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        return asc ? (va < vb ? -1 : va > vb ? 1 : 0) : (va < vb ? 1 : va > vb ? -1 : 0);
      });
    }

    this.renderPage();
    this.updateSortHeaders();
  },

  updateSortHeaders: function() {
    var thead = document.querySelector('#entities-table thead tr');
    if (!thead) return;
    var headers = thead.querySelectorAll('th');
    var columns = ['name', 'type', 'tier', 'confidence', 'aliases'];
    headers.forEach(function(th, idx) {
      var col = columns[idx];
      if (!col) return;
      var base = col.charAt(0).toUpperCase() + col.slice(1);
      if (window.EntitiesView._sortKey === col) {
        th.textContent = base + (window.EntitiesView._sortAsc ? ' \u25B2' : ' \u25BC');
      } else {
        th.textContent = base;
      }
    });
  },

  renderPage: function() {
    var tbody = document.getElementById('entities-body');
    var pageInfo = document.getElementById('entities-page-info');
    var prevBtn = document.getElementById('entities-prev');
    var nextBtn = document.getElementById('entities-next');
    if (!tbody) return;

    var totalPages = Math.ceil(this._filtered.length / this._pageSize) || 1;
    if (this._page >= totalPages) this._page = totalPages - 1;
    if (this._page < 0) this._page = 0;

    var start = this._page * this._pageSize;
    var end = Math.min(start + this._pageSize, this._filtered.length);
    var pageItems = this._filtered.slice(start, end);

    if (pageInfo) pageInfo.textContent = 'Page ' + (this._page + 1) + ' of ' + totalPages + ' (' + this._filtered.length + ' total)';
    if (prevBtn) prevBtn.style.opacity = this._page <= 0 ? '0.4' : '1';
    if (nextBtn) nextBtn.style.opacity = this._page >= totalPages - 1 ? '0.4' : '1';

    tbody.innerHTML = '';

    if (pageItems.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--fg-3,#484F58);">No entities found</td></tr>';
      return;
    }

    var self = this;
    var fragment = document.createDocumentFragment();
    var baseIdx = start;

    pageItems.forEach(function(entity, idx) {
      var row = document.createElement('tr');
      var globalIdx = baseIdx + idx;
      row.setAttribute('data-entity-idx', globalIdx);
      row.style.cssText = 'cursor:pointer;transition:background 120ms;';
      row.addEventListener('click', function() { window.EntitiesView.expandRow(globalIdx); });
      row.addEventListener('mouseenter', function() { row.style.background = 'var(--bg-surface-hi,#21262D)'; });
      row.addEventListener('mouseleave', function() { row.style.background = ''; });

      // Name (mono, blue)
      var nameTd = document.createElement('td');
      nameTd.textContent = entity.name || entity.id || 'unknown';
      nameTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);color:var(--intent-factual,#58A6FF);font-family:var(--font-mono);font-size:13px;';
      row.appendChild(nameTd);

      // Type badge
      var typeTd = document.createElement('td');
      typeTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);';
      var typeBadge = document.createElement('span');
      var typeColor = '#8B949E';
      if (entity.type === 'actor') typeColor = '#58A6FF';
      else if (entity.type === 'cve') typeColor = '#F85149';
      else if (entity.type === 'tool') typeColor = '#A371F7';
      else if (entity.type === 'campaign') typeColor = '#D29922';
      typeBadge.textContent = entity.type || 'unknown';
      typeBadge.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);background:var(--bg-surface-hi,#21262D);color:' + typeColor + ';';
      typeTd.appendChild(typeBadge);
      row.appendChild(typeTd);

      // Tier pill
      var tierTd = document.createElement('td');
      tierTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);';
      var tierPill = document.createElement('span');
      var tier = (entity.tier || 'b').toLowerCase();
      var tierColors = { a: 'var(--tier-a-fg,#3FB950)', b: 'var(--tier-b-fg,#A371F7)', c: 'var(--tier-c-fg,#D29922)' };
      var tierBgs = { a: 'var(--tier-a-bg,#1A472A)', b: 'var(--tier-b-bg,#2A1A47)', c: 'var(--tier-c-bg,#3A2A0F)' };
      tierPill.textContent = tier.toUpperCase();
      tierPill.style.cssText = 'display:inline-block;padding:1px 6px;border-radius:var(--r-pill,9999px);font-size:11px;font-family:var(--font-mono);color:' + (tierColors[tier] || 'var(--tier-b-fg,#A371F7)') + ';background:' + (tierBgs[tier] || 'var(--tier-b-bg,#2A1A47)') + ';';
      tierTd.appendChild(tierPill);
      row.appendChild(tierTd);

      // Confidence
      var confTd = document.createElement('td');
      var conf = entity.confidence !== undefined ? (typeof entity.confidence === 'number' ? Math.round(entity.confidence * 100) + '%' : entity.confidence) : '---';
      confTd.textContent = conf;
      confTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);';
      row.appendChild(confTd);

      // Aliases
      var aliasTd = document.createElement('td');
      var aliases = entity.aliases || [];
      aliasTd.textContent = aliases.slice(0, 3).join(', ') + (aliases.length > 3 ? ' +' + (aliases.length - 3) : '') || '---';
      aliasTd.style.cssText = 'padding:6px 12px;border-bottom:1px solid var(--border,#30363D);color:var(--fg-2,#8B949E);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      row.appendChild(aliasTd);

      fragment.appendChild(row);
    });

    tbody.appendChild(fragment);
  },

  expandRow: function(idx) {
    var entity = this._filtered[idx];
    if (!entity) return;

    var panel = document.getElementById('entities-detail');
    if (!panel) return;

    if (this._expandedRow === idx) {
      panel.style.display = 'none';
      this._expandedRow = null;
      return;
    }

    this._expandedRow = idx;

    var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3,12px);">';
    html += '<div style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);text-transform:uppercase;letter-spacing:0.04em;">Entity Detail</div>';
    html += '<button id="entities-detail-close" style="background:none;border:none;color:var(--fg-2,#8B949E);cursor:pointer;font-size:14px;padding:2px;">x</button>';
    html += '</div>';

    html += '<div style="font-size:var(--text-base,14px);font-weight:600;color:var(--intent-factual,#58A6FF);font-family:var(--font-mono);margin-bottom:var(--sp-3,12px);">' + (entity.name || entity.id) + '</div>';

    html += '<pre style="margin:0 0 var(--sp-3,12px);font-family:var(--font-mono);font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);white-space:pre-wrap;word-break:break-all;background:var(--bg-input,#0D1117);border-radius:var(--r-sm,6px);padding:var(--sp-3,12px);max-height:250px;overflow-y:auto;">' + JSON.stringify(entity, null, 2) + '</pre>';

    html += '<a href="#knowledge-graph" style="font-size:var(--text-xs,11px);color:var(--intent-factual,#58A6FF);font-family:var(--font-mono);">View in Knowledge Graph \u2192</a>';

    panel.innerHTML = html;
    panel.style.display = 'block';

    var closeBtn = document.getElementById('entities-detail-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function() {
        panel.style.display = 'none';
        window.EntitiesView._expandedRow = null;
      });
    }
  }
};
