window.HeaderComponent = {
  render: function() {
    var s = window.store.getState();
    var stats = s.stats || {};
    var header = document.createElement('header');
    header.style.cssText = 'background:var(--graphite-1,#0D0F1C);border-bottom:1px solid var(--border,#30363D);padding:10px 24px;display:flex;align-items:center;gap:var(--sp-4,16px);';

    var brand = document.createElement('div');
    brand.style.cssText = 'display:flex;align-items:center;gap:10px;';

    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 400 480');
    svg.setAttribute('width', '28');
    svg.setAttribute('height', '24');
    svg.style.cssText = 'flex-shrink:0;';
    var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    var filter = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    filter.setAttribute('id', 'header-glow');
    filter.setAttribute('x', '-60%');
    filter.setAttribute('y', '-60%');
    filter.setAttribute('width', '220%');
    filter.setAttribute('height', '220%');
    var blur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
    blur.setAttribute('in', 'SourceGraphic');
    blur.setAttribute('stdDeviation', '12');
    blur.setAttribute('result', 'b');
    filter.appendChild(blur);
    var colorMat = document.createElementNS('http://www.w3.org/2000/svg', 'feColorMatrix');
    colorMat.setAttribute('in', 'b');
    colorMat.setAttribute('type', 'matrix');
    colorMat.setAttribute('values', '0 0 0 0 0  1 0 0 0 1  0.6 0 0 0 0.4  0 0 0 0.5 0');
    colorMat.setAttribute('result', 'c');
    filter.appendChild(colorMat);
    var merge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
    var mergeNode1 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
    mergeNode1.setAttribute('in', 'c');
    merge.appendChild(mergeNode1);
    var mergeNode2 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
    mergeNode2.setAttribute('in', 'SourceGraphic');
    merge.appendChild(mergeNode2);
    filter.appendChild(merge);
    defs.appendChild(filter);
    svg.appendChild(defs);

    var shield = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    shield.setAttribute('d', 'M55 35 H345 a16 16 0 0 1 16 16 V265 c0 96-71 162-161 196 c-90-34-161-100-161-196 V51 a16 16 0 0 1 16-16 Z');
    shield.setAttribute('fill', 'none');
    shield.setAttribute('stroke', '#00FFA3');
    shield.setAttribute('stroke-width', '16');
    svg.appendChild(shield);

    var soma = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    soma.setAttribute('cx', '200');
    soma.setAttribute('cy', '155');
    soma.setAttribute('r', '24');
    soma.setAttribute('fill', '#00FFA3');
    soma.setAttribute('filter', 'url(#header-glow)');
    svg.appendChild(soma);

    brand.appendChild(svg);

    var h1 = document.createElement('h1');
    h1.style.cssText = 'font-family:var(--font-display);font-size:var(--text-lg,18px);font-weight:400;letter-spacing:0.05em;text-transform:uppercase;margin:0;line-height:1;';
    h1.innerHTML = '<span style="color:#C9D1D9;">Zettel</span><span style="color:#00FFA3;">Forge</span>';
    brand.appendChild(h1);

    var ver = document.createElement('span');
    ver.style.cssText = 'color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);font-family:var(--font-mono);';
    var versionLabel = stats.version ? 'v' + stats.version : 'version loading';
    var editionLabel = stats.edition_name || stats.edition || '';
    ver.textContent = editionLabel ? versionLabel + ' \u00B7 ' + editionLabel : versionLabel;
    brand.appendChild(ver);

    header.appendChild(brand);

    var statsSpan = document.createElement('span');
    statsSpan.style.cssText = 'margin-left:auto;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);font-family:var(--font-mono);';
    var notes = stats.total_notes !== undefined ? stats.total_notes.toLocaleString() : '---';
    var recalls = stats.retrievals !== undefined ? stats.retrievals.toLocaleString() : '---';
    statsSpan.textContent = notes + ' notes \u00B7 ' + recalls + ' recalls';
    header.appendChild(statsSpan);

    var statusEl = document.createElement('span');
    statusEl.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:var(--text-xs,11px);color:var(--success,#3FB950);font-family:var(--font-mono);';
    var dot = document.createElement('span');
    dot.style.cssText = 'width:6px;height:6px;border-radius:50%;background:var(--success,#3FB950);';
    statusEl.appendChild(dot);
    var statusText = document.createElement('span');
    statusText.textContent = 'online';
    statusEl.appendChild(statusText);
    header.appendChild(statusEl);

    return header;
  }
};
