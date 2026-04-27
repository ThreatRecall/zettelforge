window.SidebarComponent = {
  NAV_ITEMS: [
    { key: 'dashboard', icon: 'layout-dashboard', label: 'Dashboard' },
    { key: 'search', icon: 'search', label: 'Search' },
    { key: 'knowledge-graph', icon: 'git-graph', label: 'Knowledge Graph' },
    { key: 'logs', icon: 'scroll-text', label: 'Logs & Telemetry' },
    { key: 'ingest', icon: 'upload', label: 'Ingest' },
    { key: 'entities', icon: 'database', label: 'Entities' },
    { key: 'history', icon: 'clock', label: 'History' },
    { key: 'configuration', icon: 'settings', label: 'Configuration' }
  ],
  render: function(activeView) {
    var self = this;
    var sidebar = document.createElement('nav');
    sidebar.style.cssText = 'width:220px;background:var(--graphite-1,#0D0F1C);border-right:1px solid var(--border,#30363D);display:flex;flex-direction:column;padding:var(--sp-4,16px) 0;flex-shrink:0;overflow-y:auto;';

    var logo = document.createElement('div');
    logo.style.cssText = 'display:flex;align-items:center;gap:10px;padding:0 var(--sp-4,16px) var(--sp-4,16px);border-bottom:1px solid var(--border,#30363D);margin-bottom:var(--sp-2,8px);';
    logo.innerHTML = '<svg viewBox="0 0 400 480" width="22" height="26" aria-hidden="true" style="flex-shrink:0;"><path d="M55 35 H345 a16 16 0 0 1 16 16 V265 c0 96-71 162-161 196 c-90-34-161-100-161-196 V51 a16 16 0 0 1 16-16 Z" fill="none" stroke="#00FFA3" stroke-width="16"/><circle cx="200" cy="155" r="24" fill="#00FFA3"/></svg>';
    var brand = document.createElement('span');
    brand.innerHTML = '<span style="color:var(--fg-1,#C9D1D9);">Zettel</span><span style="color:var(--signal-neon,#00FFA3);">Forge</span>';
    brand.style.cssText = 'font-family:var(--font-display);font-size:var(--text-md,15px);letter-spacing:0.02em;text-transform:uppercase;';
    logo.appendChild(brand);
    sidebar.appendChild(logo);

    this.NAV_ITEMS.forEach(function(item) {
      var active = item.key === activeView;
      var link = document.createElement('a');
      link.href = '#' + item.key;
      link.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px var(--sp-4,16px);text-decoration:none;font-size:var(--text-sm,12px);color:' + (active ? 'var(--signal-neon,#00FFA3)' : 'var(--fg-2,#8B949E)') + ';border-left:2px solid ' + (active ? 'var(--signal-neon,#00FFA3)' : 'transparent') + ';transition:color 120ms,background 120ms;';
      link.addEventListener('mouseenter', function() { if (!active) { link.style.color = 'var(--fg-1,#C9D1D9)'; link.style.background = 'rgba(255,255,255,0.03)'; } });
      link.addEventListener('mouseleave', function() { if (!active) { link.style.color = 'var(--fg-2,#8B949E)'; link.style.background = ''; } });

      var iconSpan = document.createElement('i');
      iconSpan.setAttribute('data-lucide', item.icon);
      iconSpan.style.cssText = 'width:16px;height:16px;flex-shrink:0;';
      link.appendChild(iconSpan);

      var labelSpan = document.createElement('span');
      labelSpan.textContent = item.label;
      link.appendChild(labelSpan);

      sidebar.appendChild(link);
    });

    var bottom = document.createElement('div');
    bottom.style.cssText = 'margin-top:auto;padding:var(--sp-4,16px);border-top:1px solid var(--border,#30363D);font-size:var(--text-xs,11px);color:var(--fg-3,#484F58);font-family:var(--font-mono);';
    var s = window.store.getState();
    var stats = s.stats || {};
    var versionLabel = stats.version ? 'v' + stats.version : 'version loading';
    var editionLabel = stats.edition_name || stats.edition || '';
    bottom.textContent = editionLabel ? versionLabel + ' \u00B7 ' + editionLabel : versionLabel;
    sidebar.appendChild(bottom);

    return sidebar;
  }
};
