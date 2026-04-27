window.DashboardView = {
  render: function() {
    var container = document.createElement('div');

    var heading = document.createElement('h2');
    heading.textContent = 'Dashboard';
    heading.style.cssText = 'margin:0 0 var(--sp-6,24px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    var loading = document.createElement('div');
    loading.id = 'dash-loading';
    loading.style.cssText = 'display:flex;align-items:center;gap:8px;padding:var(--sp-6,24px);color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);';
    loading.innerHTML = '<div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading telemetry...';
    container.appendChild(loading);

    var grid = document.createElement('div');
    grid.id = 'dash-grid';
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:var(--sp-4,16px);margin-bottom:var(--sp-6,24px);';
    container.appendChild(grid);

    var actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-6,24px);flex-wrap:wrap;';

    var compactBtn = document.createElement('button');
    compactBtn.textContent = 'Run Compaction';
    compactBtn.style.cssText = 'padding:8px 16px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    compactBtn.addEventListener('mouseenter', function() { compactBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; compactBtn.style.color = 'var(--fg-1,#C9D1D9)'; });
    compactBtn.addEventListener('mouseleave', function() { compactBtn.style.borderColor = 'var(--border,#30363D)'; compactBtn.style.color = 'var(--fg-2,#8B949E)'; });
    compactBtn.addEventListener('click', function() {
      window.ToastComponent.show('Compaction initiated', 'info');
    });
    actions.appendChild(compactBtn);

    var reloadBtn = document.createElement('button');
    reloadBtn.textContent = 'Reload Config';
    reloadBtn.style.cssText = 'padding:8px 16px;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-2,#8B949E);cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:border-color 120ms,color 120ms;';
    reloadBtn.addEventListener('mouseenter', function() { reloadBtn.style.borderColor = 'var(--intent-factual,#58A6FF)'; reloadBtn.style.color = 'var(--fg-1,#C9D1D9)'; });
    reloadBtn.addEventListener('mouseleave', function() { reloadBtn.style.borderColor = 'var(--border,#30363D)'; reloadBtn.style.color = 'var(--fg-2,#8B949E)'; });
    reloadBtn.addEventListener('click', function() {
      window.ToastComponent.show('Configuration reloaded', 'success');
      window.DashboardView.load();
    });
    actions.appendChild(reloadBtn);

    container.appendChild(actions);

    var telemetryHeading = document.createElement('h3');
    telemetryHeading.textContent = 'Telemetry';
    telemetryHeading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-lg,18px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(telemetryHeading);

    var telemetryGrid = document.createElement('div');
    telemetryGrid.id = 'dash-telemetry';
    telemetryGrid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:var(--sp-4,16px);margin-bottom:var(--sp-6,24px);';
    container.appendChild(telemetryGrid);

    var intentHeading = document.createElement('h4');
    intentHeading.textContent = 'Top Intents';
    intentHeading.style.cssText = 'margin:0 0 var(--sp-3,12px);font-size:var(--text-base,14px);font-weight:var(--fw-semibold,600);text-transform:uppercase;letter-spacing:var(--ls-label,0.04em);color:var(--fg-2,#8B949E);';
    container.appendChild(intentHeading);

    var intentChart = document.createElement('div');
    intentChart.id = 'dash-intents';
    intentChart.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);margin-bottom:var(--sp-6,24px);';
    container.appendChild(intentChart);

    this.load();
    return container;
  },

  makeTile: function(title, items) {
    var tile = document.createElement('div');
    tile.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);';

    var heading = document.createElement('div');
    heading.textContent = title;
    heading.style.cssText = 'font-size:var(--text-xs,11px);font-weight:var(--fw-semibold,600);text-transform:uppercase;letter-spacing:var(--ls-label,0.04em);color:var(--fg-2,#8B949E);margin-bottom:var(--sp-3,12px);';
    tile.appendChild(heading);

    items.forEach(function(item) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:4px 0;font-size:var(--text-sm,12px);';
      var labelSpan = document.createElement('span');
      labelSpan.textContent = item.label;
      labelSpan.style.cssText = 'color:var(--fg-2,#8B949E);font-family:var(--font-mono);';
      row.appendChild(labelSpan);
      var valSpan = document.createElement('span');
      valSpan.textContent = item.value;
      valSpan.style.cssText = 'color:var(--fg-1,#C9D1D9);font-weight:var(--fw-medium,500);';
      row.appendChild(valSpan);
      tile.appendChild(row);
    });

    return tile;
  },

  load: function() {
    var self = this;
    var grid = document.getElementById('dash-grid');
    var telemetryGrid = document.getElementById('dash-telemetry');
    var intentChart = document.getElementById('dash-intents');
    var loading = document.getElementById('dash-loading');

    if (!grid) return;

    grid.innerHTML = '<div style="grid-column:1/-1;padding:var(--sp-6,24px);color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);display:flex;align-items:center;gap:8px;"><div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading stats...</div>';

    Promise.all([
      window.API.get('/api/health').catch(function() { return null; }),
      window.API.get('/api/stats').catch(function() { return {}; }),
      window.API.get('/api/telemetry').catch(function() { return {}; })
    ]).then(function(results) {
      var health = results[0];
      var stats = results[1];
      var telemetry = results[2];

      window.store.set('stats', stats);
      window.store.set('health', health);
      window.store.set('telemetry', telemetry);

      if (loading) loading.style.display = 'none';

      var tiles = [];

      tiles.push(self.makeTile('Storage', [
        { label: 'notes', value: (stats.total_notes || 0).toLocaleString() },
        { label: 'entities', value: (stats.total_entities || 0).toLocaleString() },
        { label: 'db size', value: stats.db_size || '---' }
      ]));

      tiles.push(self.makeTile('LLM', [
        { label: 'provider', value: health ? (health.llm_provider || '---') : '---' },
        { label: 'model', value: health ? (health.llm_model || '---') : '---' },
        { label: 'local backend', value: health ? (health.llm_local_backend || '---') : '---' }
      ]));

      tiles.push(self.makeTile('Embedding', [
        { label: 'provider', value: health ? (health.embedding_provider || '---') : '---' },
        { label: 'model', value: health ? (health.embedding_model || '---') : '---' },
        { label: 'dimensions', value: health ? (health.embedding_dimensions || '---').toString() : '---' }
      ]));

      tiles.push(self.makeTile('Queue', [
        { label: 'depth', value: (stats.queue_depth || 0).toString() },
        { label: 'status', value: health && health.queue_status ? health.queue_status : 'idle' }
      ]));

      grid.innerHTML = '';
      tiles.forEach(function(t) { grid.appendChild(t); });

      self.renderTelemetry(telemetryGrid, telemetry);
      self.renderIntents(intentChart, telemetry);

      // Re-render header with new stats
      var headerRoot = document.getElementById('header-root');
      if (headerRoot) {
        headerRoot.innerHTML = '';
        headerRoot.appendChild(window.HeaderComponent.render());
      }
    }).catch(function(err) {
      if (loading) loading.style.display = 'none';
      grid.innerHTML = '';
      var errorCard = document.createElement('div');
      errorCard.style.cssText = 'grid-column:1/-1;background:var(--bg-surface,#161B22);border:1px solid var(--danger,#F85149);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);color:var(--danger,#F85149);font-size:var(--text-sm,12px);font-family:var(--font-mono);';
      errorCard.textContent = 'Failed to load dashboard data: ' + err.message;
      grid.appendChild(errorCard);

      if (telemetryGrid) telemetryGrid.innerHTML = '';
      if (intentChart) intentChart.innerHTML = '<div style="color:var(--fg-3,#484F58);font-size:var(--text-sm,12px);font-family:var(--font-mono);">intent data unavailable</div>';
    });
  },

  renderTelemetry: function(container, telemetry) {
    if (!container) return;
    if (!telemetry || (telemetry.queries_today === undefined && telemetry.total_queries === undefined)) {
      container.innerHTML = '<div style="grid-column:1/-1;color:var(--fg-3,#484F58);padding:var(--sp-4,16px);font-size:var(--text-sm,12px);font-family:var(--font-mono);">telemetry data unavailable</div>';
      return;
    }

    container.innerHTML = '';

    var items = [
      { label: 'queries today', value: (telemetry.queries_today || telemetry.total_queries || 0).toLocaleString() },
      { label: 'syntheses today', value: (telemetry.syntheses_today || telemetry.synthesis_count || 0).toLocaleString() },
      { label: 'avg latency', value: telemetry.avg_latency_ms ? telemetry.avg_latency_ms + 'ms' : '---' }
    ];

    items.forEach(function(item) {
      var tile = document.createElement('div');
      tile.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);text-align:center;';

      var val = document.createElement('div');
      val.textContent = item.value;
      val.style.cssText = 'font-size:var(--text-xl,20px);font-weight:var(--fw-bold,700);color:var(--fg-1,#C9D1D9);margin-bottom:4px;';
      tile.appendChild(val);

      var lbl = document.createElement('div');
      lbl.textContent = item.label;
      lbl.style.cssText = 'font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);text-transform:uppercase;letter-spacing:var(--ls-label,0.04em);';
      tile.appendChild(lbl);

      container.appendChild(tile);
    });
  },

  renderIntents: function(container, telemetry) {
    if (!container) return;
    var intents = telemetry.top_intents || [];
    if (!Array.isArray(intents)) {
      intents = Object.keys(intents).map(function(name) {
        return { name: name, count: intents[name] };
      });
    }
    if (!intents.length) {
      container.innerHTML = '<div style="color:var(--fg-3,#484F58);font-size:var(--text-sm,12px);font-family:var(--font-mono);">no intent data yet</div>';
      return;
    }

    container.innerHTML = '';

    var maxVal = 0;
    intents.forEach(function(i) { if (i.count > maxVal) maxVal = i.count; });
    if (maxVal === 0) maxVal = 1;

    intents.forEach(function(intent) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:var(--sp-3,12px);margin-bottom:8px;';

      var label = document.createElement('span');
      label.textContent = intent.name || intent.intent || 'unknown';
      label.style.cssText = 'width:100px;font-size:var(--text-sm,12px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);text-align:right;flex-shrink:0;';
      row.appendChild(label);

      var barWrap = document.createElement('div');
      barWrap.style.cssText = 'flex:1;height:16px;background:var(--bg-surface-hi,#21262D);border-radius:var(--r-sm,6px);overflow:hidden;';

      var bar = document.createElement('div');
      var pct = (intent.count / maxVal) * 100;
      bar.style.cssText = 'height:100%;width:' + pct + '%;background:var(--signal-neon,#00FFA3);border-radius:var(--r-sm,6px);transition:width 400ms;opacity:0.8;';
      barWrap.appendChild(bar);
      row.appendChild(barWrap);

      var count = document.createElement('span');
      count.textContent = intent.count;
      count.style.cssText = 'width:40px;font-size:var(--text-sm,12px);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);flex-shrink:0;';
      row.appendChild(count);

      container.appendChild(row);
    });
  }
};
