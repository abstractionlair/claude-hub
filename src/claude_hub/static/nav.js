/**
 * Claude Hub - Shared Bottom Navigation
 *
 * Usage:
 *   <script src="/static/nav.js"></script>
 *   <script>initNav('chat');</script>
 *
 * activePage: 'chat' | 'terminal' | 'notifications'
 */

(function () {
  'use strict';

  var NAV_ITEMS = [
    { id: 'chat',          label: 'Chat',          icon: '\uD83D\uDCAC', href: '/chat' },
    { id: 'terminal',      label: 'Terminal',      icon: '\u2328\uFE0F',  href: '/terminal' },
    { id: 'notifications', label: 'Notifications', icon: '\uD83D\uDD14', href: '/notifications/view' },
  ];

  function initNav(activePage) {
    // Inject styles
    var style = document.createElement('style');
    style.textContent = [
      '.claude-hub-nav {',
      '  position: fixed;',
      '  bottom: 0;',
      '  left: 0;',
      '  right: 0;',
      '  height: 56px;',
      '  background: #16213e;',
      '  border-top: 1px solid #30475e;',
      '  display: flex;',
      '  align-items: center;',
      '  justify-content: space-around;',
      '  z-index: 9999;',
      '  padding-bottom: env(safe-area-inset-bottom, 0px);',
      '  -webkit-user-select: none;',
      '  user-select: none;',
      '}',
      '',
      '.claude-hub-nav a {',
      '  display: flex;',
      '  flex-direction: column;',
      '  align-items: center;',
      '  justify-content: center;',
      '  flex: 1;',
      '  height: 100%;',
      '  text-decoration: none;',
      '  color: #a0a0a0;',
      '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;',
      '  font-size: 10px;',
      '  font-weight: 500;',
      '  letter-spacing: 0.3px;',
      '  transition: color 0.15s ease;',
      '  -webkit-tap-highlight-color: transparent;',
      '  gap: 2px;',
      '}',
      '',
      '.claude-hub-nav a.active {',
      '  color: #e94560;',
      '}',
      '',
      '.claude-hub-nav a:not(.active):active {',
      '  color: #e8e8e8;',
      '}',
      '',
      '.claude-hub-nav-icon {',
      '  font-size: 22px;',
      '  line-height: 1;',
      '}',
      '',
      '.claude-hub-nav-label {',
      '  line-height: 1;',
      '}',
      '',
      /* Push page content above the nav bar */
      '.claude-hub-nav-spacer {',
      '  height: 56px;',
      '  flex-shrink: 0;',
      '}',
    ].join('\n');
    document.head.appendChild(style);

    // Build nav element
    var nav = document.createElement('nav');
    nav.className = 'claude-hub-nav';
    nav.setAttribute('role', 'navigation');
    nav.setAttribute('aria-label', 'Main navigation');

    for (var i = 0; i < NAV_ITEMS.length; i++) {
      var item = NAV_ITEMS[i];
      var link = document.createElement('a');
      link.href = item.href;
      if (item.id === activePage) {
        link.className = 'active';
        link.setAttribute('aria-current', 'page');
      }

      var icon = document.createElement('span');
      icon.className = 'claude-hub-nav-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = item.icon;

      var label = document.createElement('span');
      label.className = 'claude-hub-nav-label';
      label.textContent = item.label;

      link.appendChild(icon);
      link.appendChild(label);
      nav.appendChild(link);
    }

    document.body.appendChild(nav);

    // Insert spacer so page content is not hidden behind the nav bar.
    // For flex-column layouts, append a spacer div.
    // For non-flex layouts, add bottom padding to body.
    var bodyDisplay = window.getComputedStyle(document.body).display;
    if (bodyDisplay === 'flex') {
      var spacer = document.createElement('div');
      spacer.className = 'claude-hub-nav-spacer';
      // Insert before the nav (at the end of the content flow)
      document.body.insertBefore(spacer, nav);
    } else {
      document.body.style.paddingBottom = '56px';
    }
  }

  // Register service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(function (err) {
      console.warn('[Claude Hub] SW registration failed:', err.message);
    });
  }

  // Expose globally
  window.initNav = initNav;
})();
