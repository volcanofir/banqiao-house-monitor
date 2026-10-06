(() => {
  'use strict';

  const AUTH_HASH = 'a4296c4ea0b7c65ae46a83a1e9e85d8b42b3b8640b90433cac63d32c5242af79';
  const STORAGE_KEY = 'bqm-access-v2';
  const VALID_MS = 12 * 60 * 60 * 1000;

  // Local CI/browser smoke tests must continue to exercise the application itself.
  if (['127.0.0.1', 'localhost', '::1'].includes(location.hostname)) return;

  // Hide the document before the rest of the page can paint.
  document.documentElement.style.visibility = 'hidden';

  let authorized = false;
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    authorized = !!(
      saved &&
      saved.hash === AUTH_HASH &&
      Number(saved.expiresAt) > Date.now()
    );
    if (!authorized) localStorage.removeItem(STORAGE_KEY);
  } catch (_) {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  if (authorized) {
    document.documentElement.style.visibility = '';
    return;
  }

  const base = '/banqiao-house-monitor/';
  const current = location.pathname + location.search + location.hash;
  const login = base + 'access.html?next=' + encodeURIComponent(current);
  location.replace(login);
})();