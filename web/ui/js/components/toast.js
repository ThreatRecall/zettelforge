window.ToastComponent = {
  _el: null,
  _timeout: null,
  init: function() {
    var el = document.createElement('div');
    el.id = 'toast-container';
    el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
    document.body.appendChild(el);
    this._el = el;
  },
  show: function(message, type) {
    type = type || 'info';
    var self = this;
    var colors = {
      info: { bg: 'var(--bg-surface,#161B22)', border: 'var(--border,#30363D)', color: 'var(--fg-1,#C9D1D9)' },
      success: { bg: '#1A472A', border: 'var(--success,#3FB950)', color: 'var(--success,#3FB950)' },
      error: { bg: '#2D1517', border: 'var(--danger,#F85149)', color: 'var(--danger,#F85149)' },
      warning: { bg: '#3A2A0F', border: 'var(--warning,#D29922)', color: 'var(--warning,#D29922)' }
    };
    var c = colors[type] || colors.info;
    var toast = document.createElement('div');
    toast.style.cssText = 'background:' + c.bg + ';border:1px solid ' + c.border + ';border-radius:var(--r-md,8px);padding:12px 16px;font-size:var(--text-sm,12px);color:' + c.color + ';font-family:var(--font-mono);box-shadow:var(--shadow-md,0 4px 12px rgba(0,0,0,0.4));max-width:380px;opacity:0;transform:translateY(-8px);transition:opacity 200ms,transform 200ms;';
    toast.textContent = message;
    self._el.appendChild(toast);
    requestAnimationFrame(function() {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });
    setTimeout(function() {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-8px)';
      setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 200);
    }, 4000);
  }
};
