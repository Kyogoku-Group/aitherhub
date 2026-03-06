/**
 * AitherHub - Dashboard Content Script
 * 
 * Runs on: shop.tiktok.com/workbench/live/*
 * 
 * Responsibilities:
 * - Extract KPI metrics at regular intervals
 * - Extract product table with funnel metrics (click/cart/sales/gmv)
 * - Detect product diffs (deltas between snapshots)
 * - Detect pin changes → product_pinned events
 * - Send all data to background via messages
 * - Show minibar UI with tracking status
 * 
 * Data flow:
 *   DashboardParser.extractKPI()     → EXT_EVENTS (dashboard_kpi_snapshot)
 *   DashboardParser.extractProducts() → EXT_PRODUCT_SNAPSHOT
 *   DashboardParser.computeProductDiffs() → EXT_EVENTS (product delta events)
 *   DashboardParser.detectPinChange() → EXT_EVENTS (product_pinned)
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Constants
  // ══════════════════════════════════════════════════════════════
  const KPI_POLL_MS = 10000;          // KPI snapshot every 10 seconds
  const PRODUCT_POLL_MS = 30000;      // Product table every 30 seconds
  const TRAFFIC_POLL_MS = 60000;      // Traffic sources every 60 seconds
  const PING_INTERVAL_MS = 10000;     // Keep-alive ping every 10 seconds
  const INIT_DELAY_MS = 3000;         // Wait for page to load

  const LOG_PREFIX = '[AitherHub Dashboard]';

  // ══════════════════════════════════════════════════════════════
  // State
  // ══════════════════════════════════════════════════════════════
  let isTracking = false;
  let pollTimers = [];
  let snapshotSeq = 0;
  let minibar = null;
  let lastKPI = {};

  // ══════════════════════════════════════════════════════════════
  // Initialization
  // ══════════════════════════════════════════════════════════════

  function log(...args) {
    console.log(LOG_PREFIX, ...args);
  }

  function init() {
    log('Content script loaded on dashboard page');
    log('URL:', window.location.href);

    // Wait for page to fully render
    setTimeout(() => {
      // Notify background that dashboard tab is available
      chrome.runtime.sendMessage({
        type: 'EXT_BIND_TAB',
        data: {
          tab_type: 'dashboard',
          url: window.location.href,
        },
      }, (response) => {
        if (response && !response.error) {
          log('Dashboard tab bound, status:', response.status);
        }
      });

      // Check if we should auto-start tracking
      chrome.runtime.sendMessage({ type: 'EXT_GET_STATE' }, (state) => {
        if (state && state.hasSession) {
          log('Active session found, starting tracking');
          startTracking();
        } else {
          log('No active session. Waiting for user to start tracking.');
          showMinibar(false);
        }
      });
    }, INIT_DELAY_MS);

    // Listen for messages from background
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      switch (msg.type) {
        case 'START_TRACKING':
          startTracking();
          sendResponse({ status: 'started' });
          break;
        case 'STOP_TRACKING':
          stopTracking();
          sendResponse({ status: 'stopped' });
          break;
        case 'GET_DASHBOARD_STATE':
          sendResponse({
            isTracking,
            lastKPI,
            snapshotSeq,
            url: window.location.href,
          });
          break;
      }
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Tracking Control
  // ══════════════════════════════════════════════════════════════

  function startTracking() {
    if (isTracking) return;
    isTracking = true;
    snapshotSeq = 0;
    log('Tracking started');

    showMinibar(true);

    // 1. KPI polling
    pollKPI(); // Immediate first run
    const kpiTimer = setInterval(pollKPI, KPI_POLL_MS);
    pollTimers.push(kpiTimer);

    // 2. Product table polling
    pollProducts(); // Immediate first run
    const productTimer = setInterval(pollProducts, PRODUCT_POLL_MS);
    pollTimers.push(productTimer);

    // 3. Traffic source polling
    const trafficTimer = setInterval(pollTrafficSources, TRAFFIC_POLL_MS);
    pollTimers.push(trafficTimer);

    // 4. Keep-alive ping
    const pingTimer = setInterval(() => {
      chrome.runtime.sendMessage({ type: 'EXT_TAB_PING', tab_type: 'dashboard' });
    }, PING_INTERVAL_MS);
    pollTimers.push(pingTimer);
  }

  function stopTracking() {
    if (!isTracking) return;
    isTracking = false;
    log('Tracking stopped');

    for (const timer of pollTimers) {
      clearInterval(timer);
    }
    pollTimers = [];

    showMinibar(false);
  }

  // ══════════════════════════════════════════════════════════════
  // Polling Functions
  // ══════════════════════════════════════════════════════════════

  function pollKPI() {
    try {
      const kpiEvent = DashboardParser.buildKPIEvent();
      lastKPI = kpiEvent.payload || {};

      // Send as event
      chrome.runtime.sendMessage({
        type: 'EXT_EVENTS',
        source_type: 'dashboard_dom',
        events: [kpiEvent],
      });

      // Update minibar
      updateMinibar();

      log('KPI sent:', Object.keys(lastKPI).length, 'metrics');
    } catch (err) {
      console.error(LOG_PREFIX, 'KPI poll error:', err);
    }
  }

  function pollProducts() {
    try {
      const products = DashboardParser.buildProductSnapshotData();
      if (products.length === 0) {
        log('No products found in table');
        return;
      }

      snapshotSeq++;

      // Send product snapshot (for product_snapshots table)
      chrome.runtime.sendMessage({
        type: 'EXT_PRODUCT_SNAPSHOT',
        data: {
          products,
          snapshot_seq: snapshotSeq,
        },
      });

      // Compute diffs for delta events
      const diffs = DashboardParser.computeProductDiffs(products);
      if (diffs.length > 0) {
        const deltaEvents = diffs.map(d => ({
          event_type: 'product_metrics_delta',
          source_type: 'dashboard_dom',
          captured_at: new Date().toISOString(),
          product_id: d.product_id,
          numeric_value: d.gmv_delta || 0,
          payload: d,
        }));

        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'dashboard_dom',
          events: deltaEvents,
        });

        log('Product diffs:', diffs.length, 'products changed');
      }

      // Detect pin change
      const pinEvent = DashboardParser.detectPinChange(products);
      if (pinEvent) {
        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'dashboard_dom',
          events: [pinEvent],
        });
        log('Pin change detected:', pinEvent.payload.from_product_id, '→', pinEvent.payload.to_product_id);
      }

      log('Products sent:', products.length, 'seq:', snapshotSeq);
    } catch (err) {
      console.error(LOG_PREFIX, 'Product poll error:', err);
    }
  }

  function pollTrafficSources() {
    try {
      const event = DashboardParser.buildTrafficSourceEvent();
      if (event) {
        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'dashboard_dom',
          events: [event],
        });
      }
    } catch (err) {
      console.error(LOG_PREFIX, 'Traffic source poll error:', err);
    }
  }

  // ══════════════════════════════════════════════════════════════
  // Minibar UI
  // ══════════════════════════════════════════════════════════════

  function showMinibar(tracking) {
    if (minibar) {
      minibar.remove();
    }

    minibar = document.createElement('div');
    minibar.id = 'aitherhub-dashboard-minibar';
    minibar.innerHTML = `
      <div style="
        position: fixed;
        bottom: 16px;
        right: 16px;
        background: ${tracking ? '#1a1a2e' : '#2d2d3d'};
        color: white;
        padding: 12px 16px;
        border-radius: 12px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 13px;
        z-index: 99999;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        min-width: 220px;
        border: 1px solid ${tracking ? '#00C853' : '#666'};
      ">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <div style="
            width: 8px; height: 8px; border-radius: 50%;
            background: ${tracking ? '#00C853' : '#666'};
            ${tracking ? 'animation: aitherhub-pulse 2s infinite;' : ''}
          "></div>
          <span style="font-weight: 600;">AitherHub Dashboard</span>
          <span style="
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            background: ${tracking ? '#00C853' : '#666'};
            color: white;
          ">${tracking ? 'TRACKING' : 'STANDBY'}</span>
        </div>
        <div id="aitherhub-minibar-stats" style="
          font-size: 11px;
          color: #aaa;
          line-height: 1.6;
        ">
          ${tracking ? 'Collecting data...' : 'Start tracking from popup'}
        </div>
      </div>
      <style>
        @keyframes aitherhub-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      </style>
    `;

    document.body.appendChild(minibar);
  }

  function updateMinibar() {
    const statsEl = document.getElementById('aitherhub-minibar-stats');
    if (!statsEl || !isTracking) return;

    const gmv = lastKPI.gmv || '---';
    const sold = lastKPI.items_sold || '---';
    const viewers = lastKPI.current_viewers || '---';

    statsEl.innerHTML = `
      <div>GMV: <strong style="color: #FFD700;">${gmv}</strong></div>
      <div>Sales: <strong style="color: #00E676;">${sold}</strong> | Viewers: <strong>${viewers}</strong></div>
      <div style="color: #888;">Snapshot #${snapshotSeq} | ${new Date().toLocaleTimeString()}</div>
    `;
  }

  // ══════════════════════════════════════════════════════════════
  // Page Navigation Detection
  // ══════════════════════════════════════════════════════════════

  // TikTok uses SPA navigation, detect URL changes
  let lastUrl = window.location.href;
  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      log('URL changed:', lastUrl);

      // If navigated away from live dashboard, stop tracking
      if (!lastUrl.includes('/workbench/live/')) {
        stopTracking();
      }
    }
  });

  urlObserver.observe(document.body, { childList: true, subtree: true });

  // ══════════════════════════════════════════════════════════════
  // Start
  // ══════════════════════════════════════════════════════════════
  init();
})();
