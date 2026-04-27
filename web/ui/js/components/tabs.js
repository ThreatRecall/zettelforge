window.TabsComponent = {
  render: function(mode, modes, labels, onChange) {
    var container = document.createElement('div');
    container.style.cssText = 'display:flex;gap:6px;margin-bottom:var(--sp-4,16px);flex-wrap:wrap;';
    modes.forEach(function(m) {
      var active = mode === m;
      var btn = document.createElement('button');
      btn.textContent = labels[m] || m;
      btn.style.cssText = 'padding:8px 16px;background:' + (active ? 'var(--bg-surface-hi,#21262D)' : 'transparent') + ';border:1px solid ' + (active ? 'var(--border-focus,#58A6FF)' : 'var(--border,#30363D)') + ';border-radius:var(--r-sm,6px);color:' + (active ? 'var(--fg-1,#C9D1D9)' : 'var(--fg-2,#8B949E)') + ';cursor:pointer;font-size:var(--text-sm,12px);font-family:var(--font-sans);transition:color 120ms,background 120ms,border-color 120ms;';
      btn.addEventListener('mouseenter', function() { if (!active) btn.style.color = 'var(--fg-1,#C9D1D9)'; });
      btn.addEventListener('mouseleave', function() { if (!active) btn.style.color = 'var(--fg-2,#8B949E)'; });
      btn.addEventListener('click', function() { onChange(m); });
      container.appendChild(btn);
    });
    return container;
  }
};
