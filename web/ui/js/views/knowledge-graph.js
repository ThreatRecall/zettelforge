window.KnowledgeGraphView = {
  _nodes: [],
  _edges: [],
  _filteredIds: null,
  _selectedNode: null,
  _simulation: null,
  _canvasBound: false,
  _dragging: false,
  _dragMoved: false,
  _lastPointer: null,
  _view: { rotX: -0.45, rotY: 0.65, zoom: 560 },

  render: function() {
    this._canvasBound = false;
    var container = document.createElement('div');
    container.id = 'knowledge-graph-view';
    container.style.cssText = 'max-width:960px;';

    var heading = document.createElement('h2');
    heading.textContent = 'Knowledge Graph';
    heading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
    container.appendChild(heading);

    var note = document.createElement('div');
    note.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);padding:8px 12px;font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);margin-bottom:var(--sp-4,16px);';
    note.textContent = 'Interactive 3D orbital graph - drag to rotate, wheel to zoom, click a node for detail.';
    container.appendChild(note);

    // Search bar
    var searchWrap = document.createElement('div');
    searchWrap.style.cssText = 'display:flex;gap:var(--sp-2,8px);margin-bottom:var(--sp-4,16px);';

    var searchInput = document.createElement('input');
    searchInput.id = 'kg-search';
    searchInput.type = 'text';
    searchInput.placeholder = 'Filter nodes by label...';
    searchInput.style.cssText = 'flex:1;padding:8px 12px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-sm,6px);color:var(--fg-1,#C9D1D9);font-size:var(--text-sm,12px);font-family:var(--font-sans);outline:none;transition:border-color 120ms;';
    searchInput.addEventListener('focus', function() { searchInput.style.borderColor = 'var(--border-focus,#58A6FF)'; });
    searchInput.addEventListener('blur', function() { searchInput.style.borderColor = ''; });
    searchInput.addEventListener('input', function() {
      window.KnowledgeGraphView.filterNodes(this.value);
    });
    searchWrap.appendChild(searchInput);

    var statsSpan = document.createElement('span');
    statsSpan.id = 'kg-stats';
    statsSpan.style.cssText = 'padding:8px 12px;font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);font-family:var(--font-mono);white-space:nowrap;display:flex;align-items:center;';
    statsSpan.textContent = 'loading...';
    searchWrap.appendChild(statsSpan);

    container.appendChild(searchWrap);

    // Graph canvas
    var graphWrap = document.createElement('div');
    graphWrap.id = 'kg-graph';
    graphWrap.style.cssText = 'position:relative;background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);overflow:hidden;min-height:500px;';

    var loading = document.createElement('div');
    loading.id = 'kg-loading';
    loading.style.cssText = 'display:flex;align-items:center;justify-content:center;height:500px;gap:8px;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);';
    loading.innerHTML = '<div class="pulse" style="width:16px;height:16px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);"></div> Loading graph data...';
    graphWrap.appendChild(loading);

    var canvas = document.createElement('canvas');
    canvas.id = 'kg-canvas';
    canvas.width = 960;
    canvas.height = 500;
    canvas.style.cssText = 'display:none;width:100%;height:500px;cursor:grab;';
    graphWrap.appendChild(canvas);

    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'kg-svg';
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '500');
    svg.style.cssText = 'display:none;';

    var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    // Arrow marker
    var marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'kg-arrow');
    marker.setAttribute('viewBox', '0 0 10 10');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '5');
    marker.setAttribute('markerWidth', '6');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('orient', 'auto');
    var arrowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    arrowPath.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    arrowPath.setAttribute('fill', 'var(--border,#30363D)');
    marker.appendChild(arrowPath);
    defs.appendChild(marker);
    svg.appendChild(defs);

    var edgesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    edgesGroup.id = 'kg-edges';
    svg.appendChild(edgesGroup);

    var nodesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    nodesGroup.id = 'kg-nodes';
    svg.appendChild(nodesGroup);

    graphWrap.appendChild(svg);

    // Detail panel
    var detailPanel = document.createElement('div');
    detailPanel.id = 'kg-detail';
    detailPanel.style.cssText = 'display:none;position:absolute;top:12px;right:12px;width:280px;background:var(--bg-input,#0D1117);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);z-index:10;max-height:400px;overflow-y:auto;';
    graphWrap.appendChild(detailPanel);

    container.appendChild(graphWrap);

    // Empty state (hidden by default)
    var emptyState = document.createElement('div');
    emptyState.id = 'kg-empty';
    emptyState.style.cssText = 'display:none;text-align:center;padding:var(--sp-12,48px);color:var(--fg-3,#484F58);';
    var emptyTitle = document.createElement('h3');
    emptyTitle.textContent = 'No graph data';
    emptyTitle.style.cssText = 'font-size:var(--text-lg,18px);margin-bottom:var(--sp-2,8px);color:var(--fg-2,#8B949E);font-weight:500;';
    emptyState.appendChild(emptyTitle);
    var emptySub = document.createElement('p');
    emptySub.textContent = 'Ingest threat intelligence to build the knowledge graph.';
    emptySub.style.cssText = 'margin:0;font-size:var(--text-base,14px);';
    emptyState.appendChild(emptySub);
    container.appendChild(emptyState);

    this.load();
    return container;
  },

  load: function() {
    var self = this;
    var loading = document.getElementById('kg-loading');
    var svg = document.getElementById('kg-svg');
    var empty = document.getElementById('kg-empty');
    var statsSpan = document.getElementById('kg-stats');

    Promise.all([
      window.API.get('/api/graph/nodes').catch(function() { return { nodes: [] }; }),
      window.API.get('/api/graph/edges').catch(function() { return { edges: [] }; })
    ]).then(function(results) {
      var nodeData = results[0];
      var edgeData = results[1];

      self._nodes = nodeData.nodes || [];
      self._edges = edgeData.edges || [];

      if (loading) loading.style.display = 'none';

      if (self._nodes.length === 0) {
        var canvas = document.getElementById('kg-canvas');
        if (canvas) canvas.style.display = 'none';
        svg.style.display = 'none';
        empty.style.display = 'block';
        if (statsSpan) statsSpan.textContent = '0 nodes, 0 edges';
        return;
      }

      var canvas = document.getElementById('kg-canvas');
      if (canvas) canvas.style.display = 'block';
      svg.style.display = 'none';
      empty.style.display = 'none';
      if (statsSpan) statsSpan.textContent = self._nodes.length + ' nodes, ' + self._edges.length + ' edges';

      self.renderGraph();
    }).catch(function(err) {
      if (loading) loading.style.display = 'none';
      if (statsSpan) statsSpan.textContent = 'error loading graph';
      var svg = document.getElementById('kg-svg');
      if (svg) {
        svg.style.display = 'block';
        svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="var(--danger,#F85149)" font-size="12" font-family="var(--font-mono)">Failed to load: ' + (err.message || 'unknown error') + '</text>';
      }
    });
  },

  filterNodes: function(query) {
    if (!query.trim()) {
      this._filteredIds = null;
    } else {
      var q = query.toLowerCase();
      var matchingIds = {};
      this._nodes.forEach(function(n) {
        if ((n.label || '').toLowerCase().indexOf(q) !== -1 ||
            (n.id || '').toLowerCase().indexOf(q) !== -1 ||
            (n.type || '').toLowerCase().indexOf(q) !== -1) {
          matchingIds[n.id] = true;
        }
      });
      this._filteredIds = matchingIds;
    }
    this.renderGraph();
  },

  getNodeColor: function(type) {
    var map = {
      actor: '#58A6FF',
      cve: '#F85149',
      tool: '#A371F7',
      campaign: '#D29922'
    };
    return map[type] || '#8B949E';
  },

  getProjectedNode: function(node, w, h) {
    var rx = this._view.rotX;
    var ry = this._view.rotY;
    var x = node.x3 || 0;
    var y = node.y3 || 0;
    var z = node.z3 || 0;

    var cosY = Math.cos(ry);
    var sinY = Math.sin(ry);
    var x1 = x * cosY - z * sinY;
    var z1 = x * sinY + z * cosY;

    var cosX = Math.cos(rx);
    var sinX = Math.sin(rx);
    var y1 = y * cosX - z1 * sinX;
    var z2 = y * sinX + z1 * cosX;

    var zoom = this._view.zoom;
    var scale = zoom / (zoom + z2 + 260);
    scale = Math.max(0.25, Math.min(2.2, scale));

    return {
      x: w / 2 + x1 * scale,
      y: h / 2 + y1 * scale,
      z: z2,
      scale: scale
    };
  },

  init3DPositions: function() {
    var count = Math.max(this._nodes.length, 1);
    var radius = Math.min(230, 60 + count * 5);
    this._nodes.forEach(function(n, i) {
      if (n.x3 !== undefined && n.y3 !== undefined && n.z3 !== undefined) return;
      var t = count === 1 ? 0 : i / (count - 1);
      var inclination = Math.acos(1 - 2 * t);
      var azimuth = i * Math.PI * (3 - Math.sqrt(5));
      n.x3 = radius * Math.sin(inclination) * Math.cos(azimuth);
      n.y3 = radius * Math.sin(inclination) * Math.sin(azimuth);
      n.z3 = radius * Math.cos(inclination);
    });
  },

  bindCanvasControls: function(canvas) {
    if (this._canvasBound || !canvas) return;
    var self = this;
    this._canvasBound = true;

    canvas.addEventListener('pointerdown', function(e) {
      self._dragging = true;
      self._dragMoved = false;
      self._lastPointer = { x: e.clientX, y: e.clientY };
      canvas.style.cursor = 'grabbing';
      canvas.setPointerCapture(e.pointerId);
    });

    canvas.addEventListener('pointermove', function(e) {
      if (!self._dragging || !self._lastPointer) return;
      var dx = e.clientX - self._lastPointer.x;
      var dy = e.clientY - self._lastPointer.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) self._dragMoved = true;
      self._view.rotY += dx * 0.006;
      self._view.rotX += dy * 0.006;
      self._view.rotX = Math.max(-1.45, Math.min(1.45, self._view.rotX));
      self._lastPointer = { x: e.clientX, y: e.clientY };
      self.renderGraph();
    });

    canvas.addEventListener('pointerup', function(e) {
      canvas.style.cursor = 'grab';
      self._dragging = false;
      self._lastPointer = null;
      try { canvas.releasePointerCapture(e.pointerId); } catch (err) {}
      if (self._dragMoved) return;
      self.pickCanvasNode(e);
    });

    canvas.addEventListener('wheel', function(e) {
      e.preventDefault();
      self._view.zoom += e.deltaY * -0.45;
      self._view.zoom = Math.max(240, Math.min(1200, self._view.zoom));
      self.renderGraph();
    }, { passive: false });
  },

  pickCanvasNode: function(e) {
    var canvas = document.getElementById('kg-canvas');
    if (!canvas) return;
    var rect = canvas.getBoundingClientRect();
    var px = e.clientX - rect.left;
    var py = e.clientY - rect.top;
    var best = null;
    var bestDist = Infinity;
    var self = this;
    this._nodes.forEach(function(n) {
      var p = self.getProjectedNode(n, rect.width, 500);
      var radius = (8 + Math.min(n.confidence || 0.5, 1) * 8) * p.scale;
      var dist = Math.hypot(px - p.x, py - p.y);
      if (dist < Math.max(12, radius + 4) && dist < bestDist) {
        best = n;
        bestDist = dist;
      }
    });
    if (best) this.selectNode(best.id);
    else this.deselectNode();
  },

  renderCanvasGraph: function() {
    var canvas = document.getElementById('kg-canvas');
    if (!canvas || !canvas.getContext) return false;

    this.init3DPositions();
    this.bindCanvasControls(canvas);

    var rect = canvas.getBoundingClientRect();
    var w = rect.width || 960;
    var h = 500;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;

    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var bg = ctx.createRadialGradient(w / 2, h / 2, 20, w / 2, h / 2, Math.max(w, h) / 1.2);
    bg.addColorStop(0, 'rgba(88,166,255,0.08)');
    bg.addColorStop(1, 'rgba(10,14,23,0.98)');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    var self = this;
    var nodeMap = {};
    var projected = {};
    this._nodes.forEach(function(n) {
      nodeMap[n.id] = n;
      projected[n.id] = self.getProjectedNode(n, w, h);
    });

    this._edges.forEach(function(e) {
      var s = projected[e.source];
      var t = projected[e.target];
      if (!s || !t) return;
      var visible = !self._filteredIds || (self._filteredIds[e.source] && self._filteredIds[e.target]);
      var edgeColor = '48,54,61';
      if (e.relationship === 'uses') edgeColor = '163,113,247';
      else if (e.relationship === 'targets') edgeColor = '248,81,73';
      else if (e.relationship === 'related_to') edgeColor = '88,166,255';
      else if (e.relationship === 'attributed_to') edgeColor = '210,153,34';
      ctx.strokeStyle = 'rgba(' + edgeColor + ',' + (visible ? 0.52 : 0.08) + ')';
      ctx.lineWidth = visible ? 1.2 : 0.6;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
    });

    var sortedNodes = this._nodes.slice().sort(function(a, b) {
      return projected[a.id].z - projected[b.id].z;
    });

    sortedNodes.forEach(function(n) {
      var p = projected[n.id];
      var visible = !self._filteredIds || !!self._filteredIds[n.id];
      var selected = self._selectedNode === n.id;
      var radius = (7 + Math.min(n.confidence || 0.5, 1) * 7) * p.scale;
      var color = self.getNodeColor(n.type);

      ctx.globalAlpha = visible ? 1 : 0.16;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = selected ? 3 : 1;
      ctx.strokeStyle = selected ? '#00FFA3' : 'rgba(255,255,255,0.18)';
      ctx.stroke();

      if (selected) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, radius + 8, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(0,255,163,0.28)';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      if (visible && p.scale > 0.45) {
        ctx.font = '11px JetBrains Mono, monospace';
        ctx.fillStyle = '#8B949E';
        ctx.textAlign = 'center';
        ctx.fillText(n.label || n.id, p.x, p.y + radius + 13);
      }
      ctx.globalAlpha = 1;
    });

    return true;
  },

  renderGraph: function() {
    if (this.renderCanvasGraph()) return;

    var svg = document.getElementById('kg-svg');
    if (!svg) return;

    var w = svg.clientWidth || 800;
    var h = svg.clientHeight || 500;

    var edgeGroup = document.getElementById('kg-edges');
    var nodeGroup = document.getElementById('kg-nodes');
    if (!edgeGroup || !nodeGroup) return;

    edgeGroup.innerHTML = '';
    nodeGroup.innerHTML = '';

    var nodes = this._nodes;
    var edges = this._edges;

    if (nodes.length === 0) return;

    // Initialize positions if needed
    var hasPositions = true;
    nodes.forEach(function(n) {
      if (n.x === undefined || n.y === undefined) hasPositions = false;
    });

    if (!hasPositions) {
      // Place nodes in a circle
      var centerX = w / 2;
      var centerY = h / 2;
      var radius = Math.min(w, h) * 0.35;
      nodes.forEach(function(n, i) {
        var angle = (2 * Math.PI * i) / nodes.length;
        n.x = centerX + radius * Math.cos(angle) + (Math.random() - 0.5) * 40;
        n.y = centerY + radius * Math.sin(angle) + (Math.random() - 0.5) * 40;
      });
    }

    var self = this;
    var nodeMap = {};
    nodes.forEach(function(n) { nodeMap[n.id] = n; });

    // Render edges
    edges.forEach(function(e) {
      var source = nodeMap[e.source];
      var target = nodeMap[e.target];
      if (!source || !target) return;

      // Highlight if filtering
      var visible = true;
      if (self._filteredIds) {
        visible = self._filteredIds[e.source] && self._filteredIds[e.target];
      }

      var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', source.x);
      line.setAttribute('y1', source.y);
      line.setAttribute('x2', target.x);
      line.setAttribute('y2', target.y);
      var edgeColor = 'var(--border,#30363D)';
      if (e.relationship === 'uses') edgeColor = '#A371F7';
      else if (e.relationship === 'targets') edgeColor = '#F85149';
      else if (e.relationship === 'related_to') edgeColor = '#58A6FF';
      else if (e.relationship === 'attributed_to') edgeColor = '#D29922';
      line.style.cssText = 'stroke:' + edgeColor + ';stroke-width:1.5;stroke-opacity:' + (visible ? '0.6' : '0.08') + ';';
      line.setAttribute('data-edge', 'true');
      edgeGroup.appendChild(line);
    });

    // Render nodes
    nodes.forEach(function(n) {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('data-node-id', n.id);
      g.style.cursor = 'pointer';

      var visible = true;
      if (self._filteredIds) {
        visible = !!self._filteredIds[n.id];
      }

      var r = 6 + Math.min(n.confidence || 0.5, 1) * 8;
      r = Math.max(6, Math.min(14, r));

      var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', n.x);
      circle.setAttribute('cy', n.y);
      circle.setAttribute('r', r);
      var color = self.getNodeColor(n.type);
      circle.setAttribute('fill', color);
      circle.setAttribute('stroke', visible ? 'rgba(255,255,255,0.15)' : 'transparent');
      circle.setAttribute('stroke-width', '1');
      circle.style.cssText = 'transition:fill 120ms;opacity:' + (visible ? '0.9' : '0.12') + ';';
      g.appendChild(circle);

      // Label
      var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', n.x);
      label.setAttribute('y', n.y + r + 12);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('fill', 'var(--fg-2,#8B949E)');
      label.setAttribute('font-size', '10');
      label.setAttribute('font-family', 'var(--font-mono)');
      label.textContent = n.label || n.id;
      label.style.cssText = 'pointer-events:none;opacity:' + (visible ? '0.85' : '0');
      g.appendChild(label);

      // Click handler
      g.addEventListener('click', function(e) {
        e.stopPropagation();
        self.selectNode(n.id);
      });

      nodeGroup.appendChild(g);
    });

    // Click background to deselect
    svg.addEventListener('click', function() {
      self.deselectNode();
    });
  },

  selectNode: function(nodeId) {
    this._selectedNode = nodeId;
    var panel = document.getElementById('kg-detail');
    if (!panel) return;

    var node = null;
    for (var i = 0; i < this._nodes.length; i++) {
      if (this._nodes[i].id === nodeId) {
        node = this._nodes[i];
        break;
      }
    }

    if (!node) return;

    var html = '';
    html += '<div style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px;">Node Detail</div>';
    html += '<div style="font-size:var(--text-base,14px);font-weight:600;color:var(--fg-1,#C9D1D9);margin-bottom:8px;">' + (node.label || node.id) + '</div>';

    html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">ID:</span> <span style="font-size:var(--text-xs,11px);color:var(--intent-factual,#58A6FF);font-family:var(--font-mono);">' + node.id + '</span></div>';

    html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Type:</span> <span style="display:inline-block;padding:2px 8px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);background:var(--bg-surface-hi,#21262D);color:' + this.getNodeColor(node.type) + ';">' + (node.type || 'unknown') + '</span></div>';

    if (node.confidence !== undefined) {
      html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Confidence:</span> <span style="font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);">' + (typeof node.confidence === 'number' ? (node.confidence * 100).toFixed(0) + '%' : node.confidence) + '</span></div>';
    }

    if (node.tier) {
      var tierColor = node.tier === 'a' ? 'var(--tier-a-fg,#3FB950)' : node.tier === 'b' ? 'var(--tier-b-fg,#A371F7)' : 'var(--tier-c-fg,#D29922)';
      html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Tier:</span> <span style="display:inline-block;padding:1px 6px;border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);font-family:var(--font-mono);color:' + tierColor + ';background:var(--bg-surface-hi,#21262D);">' + node.tier.toUpperCase() + '</span></div>';
    }

    if (node.aliases && node.aliases.length) {
      html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Aliases:</span> <span style="font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);">' + node.aliases.join(', ') + '</span></div>';
    }

    if (node.created_at) {
      html += '<div style="margin-bottom:6px;"><span style="font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);">Created:</span> <span style="font-size:var(--text-xs,11px);color:var(--fg-1,#C9D1D9);font-family:var(--font-mono);">' + node.created_at + '</span></div>';
    }

    panel.innerHTML = html;
    panel.style.display = 'block';
    this.renderGraph();

    // Highlight node
    var allNodes = document.getElementById('kg-nodes');
    if (allNodes) {
      var groups = allNodes.querySelectorAll('g');
      groups.forEach(function(g) {
        var id = g.getAttribute('data-node-id');
        var circle = g.querySelector('circle');
        if (!circle) return;
        if (id === nodeId) {
          circle.setAttribute('stroke', 'var(--signal-neon,#00FFA3)');
          circle.setAttribute('stroke-width', '3');
        } else {
          circle.setAttribute('stroke', 'rgba(255,255,255,0.1)');
          circle.setAttribute('stroke-width', '1');
          circle.style.opacity = '0.3';
        }
      });
    }
  },

  deselectNode: function() {
    this._selectedNode = null;
    var panel = document.getElementById('kg-detail');
    if (panel) panel.style.display = 'none';

    var allNodes = document.getElementById('kg-nodes');
    if (allNodes) {
      var groups = allNodes.querySelectorAll('g');
      groups.forEach(function(g) {
        var circle = g.querySelector('circle');
        if (circle) {
          circle.setAttribute('stroke', 'rgba(255,255,255,0.15)');
          circle.setAttribute('stroke-width', '1');
          circle.style.opacity = '';
        }
      });
    }
    this.renderGraph();
  }
};
