(function() {
  'use strict';

  function isLoopbackHost() {
    return ['localhost', '127.0.0.1', '::1'].indexOf(window.location.hostname) !== -1;
  }

  function getApiKey() {
    return localStorage.getItem('zettelforgeApiKey') || '';
  }

  function setApiKey(key) {
    if (key) {
      localStorage.setItem('zettelforgeApiKey', key);
    }
  }

  function headers(extra) {
    var out = extra ? Object.assign({}, extra) : {};
    var key = getApiKey();
    if (key) out['X-API-Key'] = key;
    return out;
  }

  function promptForApiKey(reason) {
    if (isLoopbackHost()) return '';
    var message = reason || 'This LAN session needs the ZettelForge web API key.';
    var key = window.prompt(message + '\n\nPaste API key for this browser:');
    if (key) {
      key = key.trim();
      setApiKey(key);
    }
    return key || '';
  }

  function parseError(status, payload) {
    if (payload && payload.detail) return payload.detail;
    if (payload && payload.error) return payload.error;
    if (payload && payload.message) return payload.message;
    return 'HTTP ' + status;
  }

  function request(method, path, body, retried) {
    var opts = {
      method: method,
      headers: headers(body === undefined ? {} : { 'Content-Type': 'application/json' })
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }

    return fetch(path, opts).then(function(resp) {
      var contentType = resp.headers.get('content-type') || '';
      var parse = contentType.indexOf('application/json') !== -1 ? resp.json() : resp.text();
      return parse.then(function(payload) {
        if (resp.ok) return payload;
        if (!retried && (resp.status === 401 || resp.status === 503)) {
          var key = getApiKey() || promptForApiKey(parseError(resp.status, payload));
          if (key) return request(method, path, body, true);
        }
        throw new Error(parseError(resp.status, payload));
      });
    });
  }

  window.API = {
    getApiKey: getApiKey,
    setApiKey: setApiKey,
    headers: headers,
    get: function(path) {
      return request('GET', path);
    },
    post: function(path, body) {
      return request('POST', path, body);
    },
    put: function(path, body) {
      return request('PUT', path, body);
    },
    del: function(path) {
      return request('DELETE', path);
    }
  };
})();
