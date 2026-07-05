/**
 * Claude Hub - Service Worker
 *
 * Caching strategies:
 *   - App shell (HTML pages, static assets): cache-first with network fallback
 *   - API calls (/tools/*, /chat/*, /notifications/*): network-first with cache fallback
 *   - Manifest & icons: cache-first
 */

const CACHE_NAME = 'claude-hub-v2';

const APP_SHELL = [
  '/static/manifest.json',
  '/static/nav.js',
  '/static/icon-192.svg',
  '/static/icon-512.svg',
];

// Routes that should use network-first strategy
const NETWORK_FIRST_PATTERNS = [
  /^\/tools\//,
  /^\/chat\/send/,
  /^\/chat\/verify/,
  /^\/notifications\/api\//,
  /^\/terminal\//,
  /^\/health/,
  /^\/debug\//,
  /^\/webhooks\//,
  /^\/authorize/,
  /^\/token/,
  /^\/register/,
];

// Routes that should never be cached
const NO_CACHE_PATTERNS = [
  /^\/terminal\/ws/,
  /^\/mcp/,
];


// ---------- Install ----------

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        // Pre-cache app shell; don't fail install if individual fetches fail
        return Promise.allSettled(
          APP_SHELL.map((url) =>
            cache.add(url).catch((err) => {
              console.warn(`[SW] Failed to pre-cache ${url}:`, err.message);
            })
          )
        );
      })
      .then(() => self.skipWaiting())
  );
});


// ---------- Activate ----------

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});


// ---------- Fetch ----------

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // Skip non-GET requests (POST/PUT/DELETE always go to network)
  if (event.request.method !== 'GET') return;

  // Never cache certain paths
  if (NO_CACHE_PATTERNS.some((p) => p.test(url.pathname))) return;

  // Network-first for API calls
  if (NETWORK_FIRST_PATTERNS.some((p) => p.test(url.pathname))) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Navigation requests (HTML pages) use network-first to avoid caching auth walls
  if (event.request.mode === 'navigate') {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Cache-first for static assets only
  event.respondWith(cacheFirst(event.request));
});


// ---------- Strategies ----------

/**
 * Cache-first: return cached response if available, else fetch and cache.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    // Offline fallback: return a simple offline page for navigation requests
    if (request.mode === 'navigate') {
      return new Response(
        offlinePage(),
        { headers: { 'Content-Type': 'text/html' } }
      );
    }
    throw err;
  }
}

/**
 * Network-first: try network, fall back to cache on failure.
 */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

/**
 * Minimal offline fallback page.
 */
function offlinePage() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Claude Hub - Offline</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #1a1a2e;
      color: #e8e8e8;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      text-align: center;
    }
    .offline {
      padding: 32px;
    }
    h1 {
      color: #e94560;
      margin-bottom: 12px;
      font-size: 24px;
    }
    p {
      color: #a0a0a0;
      font-size: 16px;
      line-height: 1.5;
    }
    button {
      margin-top: 24px;
      background: #e94560;
      color: white;
      border: none;
      padding: 12px 32px;
      border-radius: 8px;
      font-size: 16px;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div class="offline">
    <h1>Offline</h1>
    <p>Claude Hub is not reachable right now.<br>Check your connection and try again.</p>
    <button onclick="location.reload()">Retry</button>
  </div>
</body>
</html>`;
}
