window.ResultCardComponent = {
  TIER_STYLES: {
    A: { background: 'var(--tier-a-bg,#1A472A)', color: 'var(--tier-a-fg,#3FB950)' },
    B: { background: 'var(--tier-b-bg,#2A1A47)', color: 'var(--tier-b-fg,#A371F7)' },
    C: { background: 'var(--tier-c-bg,#3A2A0F)', color: 'var(--tier-c-fg,#D29922)' }
  },
  render: function(note) {
    var card = document.createElement('div');
    card.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-4,16px);transition:border-color 120ms;';
    card.addEventListener('mouseenter', function() { card.style.borderColor = '#58A6FF'; });
    card.addEventListener('mouseleave', function() { card.style.borderColor = ''; });

    var titleRow = document.createElement('div');
    titleRow.style.cssText = 'color:var(--intent-factual,#58A6FF);font-size:var(--text-sm,12px);margin-bottom:var(--sp-2,8px);font-family:var(--font-mono);display:flex;gap:8px;align-items:center;flex-wrap:wrap;';

    var idSpan = document.createElement('span');
    idSpan.textContent = note.id;
    titleRow.appendChild(idSpan);

    if (note.tier) {
      var tierStyles = this.TIER_STYLES[note.tier] || this.TIER_STYLES.B;
      var tierPill = document.createElement('span');
      tierPill.textContent = 'TIER ' + note.tier;
      tierPill.style.cssText = 'display:inline-flex;padding:2px 8px;background:' + tierStyles.background + ';border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);color:' + tierStyles.color + ';font-weight:600;';
      titleRow.appendChild(tierPill);
    }

    if (note.domain) {
      var domainPill = document.createElement('span');
      domainPill.textContent = note.domain;
      domainPill.style.cssText = 'display:inline-flex;padding:2px 8px;background:var(--bg-surface-hi,#21262D);border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);color:var(--fg-2,#8B949E);';
      titleRow.appendChild(domainPill);
    }

    card.appendChild(titleRow);

    var content = document.createElement('div');
    content.textContent = note.content;
    content.style.cssText = 'color:var(--fg-1,#C9D1D9);font-size:var(--text-base,14px);line-height:1.6;white-space:pre-wrap;word-break:break-word;';
    card.appendChild(content);

    var footer = document.createElement('div');
    footer.style.cssText = 'display:flex;gap:10px;margin-top:10px;color:var(--fg-2,#8B949E);font-size:var(--text-sm,12px);font-family:var(--font-mono);flex-wrap:wrap;align-items:center;';

    if (note.created_at) {
      var dateSpan = document.createElement('span');
      dateSpan.textContent = note.created_at;
      footer.appendChild(dateSpan);
    }

    if (note.confidence !== undefined) {
      var confSpan = document.createElement('span');
      confSpan.textContent = 'confidence: ' + note.confidence.toFixed(2);
      footer.appendChild(confSpan);
    }

    if (note.entities && note.entities.length) {
      note.entities.forEach(function(e) {
        var ent = document.createElement('span');
        ent.textContent = e;
        ent.style.cssText = 'display:inline-flex;padding:2px 8px;background:var(--bg-surface-hi,#21262D);border-radius:var(--r-pill,9999px);font-size:var(--text-xs,11px);color:var(--intent-factual,#58A6FF);';
        footer.appendChild(ent);
      });
    }

    card.appendChild(footer);
    return card;
  }
};
