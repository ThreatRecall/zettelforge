(function() {
  'use strict';

  var APP = {
    init: function() {
      window.ToastComponent.init();

      // Listen for hash changes
      window.addEventListener('hashchange', this.route.bind(this));
      window.store.subscribe(function(_state, key) {
        if (key === 'stats') APP.refreshChrome();
      });

      // Initial load
      this.route();
      this.loadAppInfo();
    },

    loadHeader: function() {
      var headerRoot = document.getElementById('header-root');
      if (headerRoot) {
        headerRoot.innerHTML = '';
        headerRoot.appendChild(window.HeaderComponent.render());
      }
    },

    refreshChrome: function() {
      this.loadHeader();
      var sidebarRoot = document.getElementById('sidebar-root');
      if (sidebarRoot) {
        var active = window.store.get('view') || window.location.hash.slice(1) || 'dashboard';
        sidebarRoot.innerHTML = '';
        sidebarRoot.appendChild(window.SidebarComponent.render(active));
        if (window.lucide) window.lucide.createIcons();
      }
    },

    loadAppInfo: function() {
      window.API.get('/api/stats')
        .then(function(stats) {
          window.store.set('stats', stats || {});
        })
        .catch(function() {
          return window.API.get('/api/version').then(function(info) {
            window.store.set('stats', info || {});
          });
        })
        .catch(function() {});
    },

    route: function() {
      var hash = window.location.hash.slice(1) || 'dashboard';
      window.store.set('view', hash);

      this.loadHeader();

      var sidebarRoot = document.getElementById('sidebar-root');
      if (sidebarRoot) {
        sidebarRoot.innerHTML = '';
        sidebarRoot.appendChild(window.SidebarComponent.render(hash));
      }

      var contentRoot = document.getElementById('content-root');
      if (!contentRoot) return;

      contentRoot.innerHTML = '';

      var view;
      switch (hash) {
        case 'dashboard':
          view = window.DashboardView.render();
          break;
        case 'search':
          view = window.SearchView.render();
          break;
        case 'knowledge-graph':
          view = window.KnowledgeGraphView.render();
          break;
        case 'logs':
          view = window.LogsView.render();
          break;
        case 'ingest':
          view = window.IngestView.render();
          break;
        case 'entities':
          view = window.EntitiesView.render();
          break;
        case 'history':
          view = window.HistoryView.render();
          break;
        case 'configuration':
          view = window.ConfigurationView.render();
          break;
        default:
          view = this.renderPlaceholder(hash);
          break;
      }

      contentRoot.appendChild(view);

      // Init Lucide icons
      if (window.lucide) {
        window.lucide.createIcons();
      }
    },

    renderPlaceholder: function(viewName) {
      var container = document.createElement('div');

      var heading = document.createElement('h2');
      heading.textContent = viewName.replace(/-/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
      heading.style.cssText = 'margin:0 0 var(--sp-4,16px);font-size:var(--text-xl,20px);font-weight:var(--fw-semibold,600);color:var(--fg-1,#C9D1D9);';
      container.appendChild(heading);

      var card = document.createElement('div');
      card.style.cssText = 'background:var(--bg-surface,#161B22);border:1px solid var(--border,#30363D);border-radius:var(--r-md,8px);padding:var(--sp-8,32px);text-align:center;';

      var iconDiv = document.createElement('div');
      iconDiv.style.cssText = 'font-size:32px;color:var(--fg-3,#484F58);margin-bottom:var(--sp-4,16px);';
      iconDiv.textContent = '\u26A0\uFE0F';
      card.appendChild(iconDiv);

      var title = document.createElement('h3');
      title.textContent = 'Coming Soon';
      title.style.cssText = 'font-size:var(--text-lg,18px);color:var(--fg-2,#8B949E);font-weight:500;margin:0 0 var(--sp-2,8px);';
      card.appendChild(title);

      var desc = document.createElement('p');
      desc.textContent = 'This view is under construction and will be available in a future release.';
      desc.style.cssText = 'font-size:var(--text-base,14px);color:var(--fg-3,#484F58);margin:0;';
      card.appendChild(desc);

      container.appendChild(card);
      return container;
    }
  };

  // Start the app when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { APP.init(); });
  } else {
    APP.init();
  }
})();
