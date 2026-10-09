(() => {
  'use strict';

  const AUTH_HASH = '31be948c5e8804d5ec85869504c1ea7593c42cc6dfefb25ddf29fdb86c327b29';
  const GRACE_KEY = 'bqm-access-grace-v6';
  const LOCK_KEY = 'bqm-relock-required-v5';
  const GRACE_MS = 3 * 60 * 1000;

  if (['127.0.0.1', 'localhost', '::1'].includes(location.hostname)) return;

  document.documentElement.style.visibility = 'hidden';

  const clearGrace = () => {
    try { localStorage.removeItem(GRACE_KEY); } catch (_) {}
  };
  const hasGrace = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(GRACE_KEY) || 'null');
      const ok = !!(
        saved &&
        saved.hash === AUTH_HASH &&
        Number(saved.expiresAt) > Date.now()
      );
      if (!ok) localStorage.removeItem(GRACE_KEY);
      return ok;
    } catch (_) {
      clearGrace();
      return false;
    }
  };
  const base = '/banqiao-house-monitor/';
  const current = location.pathname + location.search + location.hash;
  const goLogin = () => {
    clearGrace();
    location.replace(base + 'access.html?v=20261006g&next=' + encodeURIComponent(current));
  };

  if (!hasGrace()) {
    goLogin();
    return;
  }

  document.documentElement.style.visibility = '';

  const markAway = () => {
    const now = Date.now();
    try { sessionStorage.setItem(LOCK_KEY, String(now)); } catch (_) {}
    try {
      localStorage.setItem(GRACE_KEY, JSON.stringify({
        hash: AUTH_HASH,
        expiresAt: now + GRACE_MS
      }));
    } catch (_) {}
  };
  const relockIfExpired = () => {
    let awayAt = 0;
    try { awayAt = Number(sessionStorage.getItem(LOCK_KEY) || 0); } catch (_) {}
    if (!awayAt) return;
    if (Date.now() - awayAt >= GRACE_MS || !hasGrace()) {
      goLogin();
      return;
    }
    try { sessionStorage.removeItem(LOCK_KEY); } catch (_) {}
  };

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) markAway();
    else relockIfExpired();
  });
  window.addEventListener('pagehide', markAway);
  window.addEventListener('blur', markAway);
  window.addEventListener('pageshow', relockIfExpired);
  window.addEventListener('focus', () => setTimeout(relockIfExpired, 0));
  document.addEventListener('freeze', markAway);
  document.addEventListener('resume', relockIfExpired);
})();