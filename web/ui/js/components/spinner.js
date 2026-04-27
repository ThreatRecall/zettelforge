window.SpinnerComponent = {
  render: function() {
    var el = document.createElement('div');
    el.style.cssText = 'display:flex;align-items:center;justify-content:center;padding:var(--sp-8,32px) 0;';
    el.innerHTML = '<div class="pulse" style="width:32px;height:32px;border-radius:50%;border:2px solid var(--border,#30363D);border-top-color:var(--signal-neon,#00FFA3);animation:pulse 1.4s ease-in-out infinite;"></div>';
    return el;
  }
};
