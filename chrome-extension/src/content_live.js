/**
 * AitherHub - LIVE Streamer Content Script
 * 
 * Runs on: shop.tiktok.com/streamer/live/*
 * 
 * Responsibilities:
 * - Extract viewer count at regular intervals
 * - Extract comments via MutationObserver + polling
 * - Detect comment spikes (30s window)
 * - Detect product switches (pin changes)
 * - Extract purchase notifications from activity feed
 * - Extract live duration (video_sec)
 * - Send all data to background via messages
 * - Show minibar UI with recording status + manual mark button
 * 
 * Data flow:
 *   LiveParser.buildViewerEvent()     → EXT_EVENTS (viewer_count_snapshot)
 *   LiveParser.buildCommentEvents()   → EXT_EVENTS (comment_added)
 *   LiveParser.detectCommentSpike()   → EXT_EVENTS (comment_spike)
 *   LiveParser.detectProductSwitch()  → EXT_EVENTS (product_switched)
 *   LiveParser.buildActivityEvents()  → EXT_EVENTS (purchase_notice_detected)
 */

(function () {
  'use strict';

  // ══════════════════════════════════════════════════════════════
  // Constants
  // ══════════════════════════════════════════════════════════════
  const VIEWER_POLL_MS = 10000;       // Viewer count every 10 seconds
  const COMMENT_POLL_MS = 3000;       // Comment check every 3 seconds
  const PRODUCT_POLL_MS = 15000;      // Product switch check every 15 seconds
  const ACTIVITY_POLL_MS = 5000;      // Activity feed every 5 seconds
  const METRICS_POLL_MS = 30000;      // Full metrics every 30 seconds
  const PING_INTERVAL_MS = 10000;     // Keep-alive ping
  const INIT_DELAY_MS = 3000;         // Wait for page to load

  const LOG_PREFIX = '[AitherHub Live]';

  // ══════════════════════════════════════════════════════════════
  // State
  // ══════════════════════════════════════════════════════════════
  let isTracking = false;
  let pollTimers = [];
  let minibar = null;
  let commentCount = 0;
  let lastViewerCount = 0;
  let lastPinnedProduct = '';

  // ══════════════════════════════════════════════════════════════
  // Initialization
  // ══════════════════════════════════════════════════════════════

  function log(...args) {
    console.log(LOG_PREFIX, ...args);
  }

  function init() {
    log('Content script loaded on LIVE streamer page');
    log('URL:', window.location.href);

    // Wait for page to fully render
    setTimeout(() => {
      // Notify background that live tab is available
      chrome.runtime.sendMessage({
        type: 'EXT_BIND_TAB',
        data: {
          tab_type: 'live',
          url: window.location.href,
        },
      }, (response) => {
        if (response && !response.error) {
          log('Live tab bound, status:', response.status);
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
        case 'GET_LIVE_STATE':
          sendResponse({
            isTracking,
            lastViewerCount,
            commentCount,
            lastPinnedProduct,
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
    commentCount = 0;
    log('Tracking started');

    // Reset parser state
    LiveParser.reset();

    showMinibar(true);

    // Send live_started event
    chrome.runtime.sendMessage({
      type: 'EXT_EVENTS',
      source_type: 'live_dom',
      events: [{
        event_type: 'live_started',
        source_type: 'live_dom',
        captured_at: new Date().toISOString(),
        payload: {
          url: window.location.href,
          title: document.title,
        },
      }],
    });

    // 1. Viewer count polling
    pollViewers(); // Immediate
    const viewerTimer = setInterval(pollViewers, VIEWER_POLL_MS);
    pollTimers.push(viewerTimer);

    // 2. Comment polling
    pollComments(); // Immediate
    const commentTimer = setInterval(pollComments, COMMENT_POLL_MS);
    pollTimers.push(commentTimer);

    // 3. Product switch detection
    pollProducts(); // Immediate
    const productTimer = setInterval(pollProducts, PRODUCT_POLL_MS);
    pollTimers.push(productTimer);

    // 4. Activity feed (purchase notices)
    const activityTimer = setInterval(pollActivities, ACTIVITY_POLL_MS);
    pollTimers.push(activityTimer);

    // 5. Full metrics snapshot
    const metricsTimer = setInterval(pollMetrics, METRICS_POLL_MS);
    pollTimers.push(metricsTimer);

    // 6. Keep-alive ping
    const pingTimer = setInterval(() => {
      chrome.runtime.sendMessage({ type: 'EXT_TAB_PING', tab_type: 'live' });
    }, PING_INTERVAL_MS);
    pollTimers.push(pingTimer);

    // 7. Setup MutationObserver for real-time comment detection
    setupCommentObserver();
  }

  function stopTracking() {
    if (!isTracking) return;
    isTracking = false;
    log('Tracking stopped');

    // Send live_ended event
    chrome.runtime.sendMessage({
      type: 'EXT_EVENTS',
      source_type: 'live_dom',
      events: [{
        event_type: 'live_ended',
        source_type: 'live_dom',
        captured_at: new Date().toISOString(),
        video_sec: LiveParser.extractVideoSec(),
        payload: {
          total_comments: commentCount,
          last_viewer_count: lastViewerCount,
        },
      }],
    });

    for (const timer of pollTimers) {
      clearInterval(timer);
    }
    pollTimers = [];

    showMinibar(false);
  }

  // ══════════════════════════════════════════════════════════════
  // Polling Functions
  // ══════════════════════════════════════════════════════════════

  function pollViewers() {
    try {
      const event = LiveParser.buildViewerEvent();
      if (event) {
        lastViewerCount = event.numeric_value;
        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'live_dom',
          events: [event],
        });
      }
      updateMinibar();
    } catch (err) {
      console.error(LOG_PREFIX, 'Viewer poll error:', err);
    }
  }

  function pollComments() {
    try {
      const events = LiveParser.buildCommentEvents();
      if (events.length > 0) {
        commentCount += events.length;

        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'live_dom',
          events,
        });

        // Check for comment spike
        const spikeEvent = LiveParser.detectCommentSpike(events.length);
        if (spikeEvent) {
          chrome.runtime.sendMessage({
            type: 'EXT_EVENTS',
            source_type: 'live_dom',
            events: [spikeEvent],
          });
          log('Comment spike detected!', spikeEvent.payload);
        }

        updateMinibar();
      }
    } catch (err) {
      console.error(LOG_PREFIX, 'Comment poll error:', err);
    }
  }

  function pollProducts() {
    try {
      // Check for product switch
      const switchEvent = LiveParser.detectProductSwitch();
      if (switchEvent) {
        lastPinnedProduct = switchEvent.text_value || '';
        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'live_dom',
          events: [switchEvent],
        });
        log('Product switch:', switchEvent.payload.from_product, '→', switchEvent.payload.to_product);
        updateMinibar();
      }

      // Product diffs (click/cart/sold deltas)
      const diffs = LiveParser.computeProductDiffs();
      if (diffs.length > 0) {
        const diffEvents = diffs.map(d => ({
          event_type: 'product_live_delta',
          source_type: 'live_dom',
          captured_at: new Date().toISOString(),
          video_sec: LiveParser.extractVideoSec(),
          text_value: d.product_name,
          payload: d,
        }));

        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'live_dom',
          events: diffEvents,
        });
      }
    } catch (err) {
      console.error(LOG_PREFIX, 'Product poll error:', err);
    }
  }

  function pollActivities() {
    try {
      const events = LiveParser.buildActivityEvents();
      if (events.length > 0) {
        chrome.runtime.sendMessage({
          type: 'EXT_EVENTS',
          source_type: 'live_dom',
          events,
        });
      }
    } catch (err) {
      console.error(LOG_PREFIX, 'Activity poll error:', err);
    }
  }

  function pollMetrics() {
    try {
      const event = LiveParser.buildMetricsEvent();
      chrome.runtime.sendMessage({
        type: 'EXT_EVENTS',
        source_type: 'live_dom',
        events: [event],
      });
    } catch (err) {
      console.error(LOG_PREFIX, 'Metrics poll error:', err);
    }
  }

  // ══════════════════════════════════════════════════════════════
  // MutationObserver for Real-time Comments
  // ══════════════════════════════════════════════════════════════

  function setupCommentObserver() {
    const findAndObserve = () => {
      const container = document.querySelector('[class*="commentContainer"]');
      if (container) {
        log('MutationObserver attached to comment container');
        const observer = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            if (mutation.addedNodes.length > 0) {
              // Debounce: let the polling handle batch extraction
              // MutationObserver just triggers an immediate poll
              pollComments();
            }
          }
        });
        observer.observe(container, { childList: true, subtree: true });
        return true;
      }
      return false;
    };

    if (!findAndObserve()) {
      // Retry after delay
      setTimeout(() => {
        if (!findAndObserve()) {
          log('Comment container not found for MutationObserver');
        }
      }, 5000);
    }
  }

  // ══════════════════════════════════════════════════════════════
  // Minibar UI
  // ══════════════════════════════════════════════════════════════

  function showMinibar(tracking) {
    const existing = document.getElementById('aitherhub-live-minibar');
    if (existing) existing.remove();

    minibar = document.createElement('div');
    minibar.id = 'aitherhub-live-minibar';
    minibar.innerHTML = `
      <div style="
        position: fixed;
        bottom: 16px;
        left: 16px;
        background: ${tracking ? '#1a1a2e' : '#2d2d3d'};
        color: white;
        padding: 12px 16px;
        border-radius: 12px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 13px;
        z-index: 99999;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        min-width: 200px;
        border: 1px solid ${tracking ? '#FF1744' : '#666'};
      ">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <div style="
            width: 8px; height: 8px; border-radius: 50%;
            background: ${tracking ? '#FF1744' : '#666'};
            ${tracking ? 'animation: aitherhub-pulse 2s infinite;' : ''}
          "></div>
          <span style="font-weight: 600;">AitherHub LIVE</span>
          <span style="
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 4px;
            background: ${tracking ? '#FF1744' : '#666'};
            color: white;
          ">${tracking ? 'REC' : 'STANDBY'}</span>
        </div>
        <div id="aitherhub-live-stats" style="
          font-size: 11px;
          color: #aaa;
          line-height: 1.6;
        ">
          ${tracking ? 'Starting...' : 'Start tracking from popup'}
        </div>
        ${tracking ? `
        <button id="aitherhub-mark-btn" class="aitherhub-mark-btn" style="
          margin-top: 8px;
          width: 100%;
          padding: 6px 12px;
          background: #E91E63;
          color: white;
          border: none;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s;
        ">MARK (important moment)</button>
        ` : ''}
      </div>
      <style>
        @keyframes aitherhub-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      </style>
    `;

    document.body.appendChild(minibar);

    // Bind mark button
    if (tracking) {
      const markBtn = document.getElementById('aitherhub-mark-btn');
      if (markBtn) {
        markBtn.addEventListener('click', () => {
          const event = {
            event_type: 'manual_marker_added',
            source_type: 'manual',
            captured_at: new Date().toISOString(),
            video_sec: LiveParser.extractVideoSec(),
            payload: {
              marker_type: 'important',
              viewer_count: lastViewerCount,
              pinned_product: lastPinnedProduct,
            },
          };

          chrome.runtime.sendMessage({
            type: 'EXT_EVENTS',
            source_type: 'manual',
            events: [event],
          });

          // Visual feedback
          markBtn.textContent = 'MARKED!';
          markBtn.style.background = '#00C853';
          setTimeout(() => {
            markBtn.textContent = 'MARK (important moment)';
            markBtn.style.background = '#E91E63';
          }, 2000);

          log('Manual marker added at video_sec:', event.video_sec);
        });
      }
    }
  }

  function updateMinibar() {
    const statsEl = document.getElementById('aitherhub-live-stats');
    if (!statsEl || !isTracking) return;

    const videoSec = LiveParser.extractVideoSec();
    const duration = videoSec !== null
      ? `${Math.floor(videoSec / 3600)}:${String(Math.floor((videoSec % 3600) / 60)).padStart(2, '0')}:${String(videoSec % 60).padStart(2, '0')}`
      : '--:--:--';

    statsEl.innerHTML = `
      <div>Viewers: <strong style="color: #64B5F6;">${lastViewerCount || '---'}</strong></div>
      <div>Comments: <strong style="color: #81C784;">${commentCount}</strong></div>
      <div>Product: <strong style="color: #FFD54F;">${lastPinnedProduct || 'none'}</strong></div>
      <div style="color: #888;">Duration: ${duration}</div>
    `;
  }

  // ══════════════════════════════════════════════════════════════
  // Page Navigation Detection
  // ══════════════════════════════════════════════════════════════

  let lastUrl = window.location.href;
  const urlObserver = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      log('URL changed:', lastUrl);
      if (!lastUrl.includes('/streamer/live/')) {
        stopTracking();
      }
    }
  });

  urlObserver.observe(document.body, { childList: true, subtree: true });

  // Clean up on page unload
  window.addEventListener('beforeunload', () => {
    if (isTracking) stopTracking();
  });

  // ══════════════════════════════════════════════════════════════
  // Start
  // ══════════════════════════════════════════════════════════════

  // Wait for page content to be ready
  const checkReady = setInterval(() => {
    const root = document.querySelector('#root');
    const hasContent = root && root.textContent.length > 100;
    if (hasContent) {
      clearInterval(checkReady);
      init();
    }
  }, 1000);

  // Timeout after 60 seconds
  setTimeout(() => {
    clearInterval(checkReady);
    init();
  }, 60000);
})();
