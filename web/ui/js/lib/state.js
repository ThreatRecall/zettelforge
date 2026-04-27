(function() {
  'use strict';

  var state = {
    view: 'dashboard',
    stats: {},
    health: null,
    telemetry: {}
  };
  var listeners = [];

  window.store = {
    getState: function() {
      return state;
    },
    get: function(key) {
      return state[key];
    },
    set: function(key, value) {
      state[key] = value;
      listeners.slice().forEach(function(listener) {
        try {
          listener(state, key, value);
        } catch (err) {
          console.error('store listener failed', err);
        }
      });
    },
    update: function(patch) {
      Object.keys(patch || {}).forEach(function(key) {
        state[key] = patch[key];
      });
      listeners.slice().forEach(function(listener) {
        try {
          listener(state, null, patch);
        } catch (err) {
          console.error('store listener failed', err);
        }
      });
    },
    subscribe: function(listener) {
      listeners.push(listener);
      return function() {
        listeners = listeners.filter(function(item) {
          return item !== listener;
        });
      };
    }
  };
})();
