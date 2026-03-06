/**
 * AitherHub - LIVE Streamer Page Parser
 * 
 * Extracts data from TikTok LIVE Streamer page (shop.tiktok.com/streamer/live/...).
 * 
 * Responsible for:
 * - Viewer count extraction
 * - Comment extraction (MutationObserver + polling)
 * - Comment spike detection (30s window)
 * - Product list extraction (pinned state, clicks, carts, sold)
 * - Product switch detection
 * - Activity feed (purchase notices, joins, shares)
 * - Live duration / video_sec extraction
 * - AI Suggestion extraction
 * 
 * DOM selectors confirmed 2026-02-25.
 */

const LiveParser = {
  _log(...args) {
    console.log('[AitherHub LiveParser]', ...args);
  },

  // ══════════════════════════════════════════════════════════════
  // State for diff tracking
  // ══════════════════════════════════════════════════════════════
  _prevPinnedProductName: null,
  _prevProducts: null,
  _seenCommentIds: new Set(),
  _seenActivityIds: new Set(),
  _commentWindow: [],       // { timestamp, count } for spike detection
  _viewerHistory: [],       // { timestamp, count } for delta tracking

  // ══════════════════════════════════════════════════════════════
  // Viewer Count
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract current viewer count.
   * @returns {number|null}
   */
  extractViewerCount() {
    const metrics = this._extractMetrics();
    const raw = metrics.current_viewers;
    if (!raw) return null;
    return this._parseNumber(raw);
  },

  /**
   * Build viewer_count_snapshot event.
   */
  buildViewerEvent() {
    const count = this.extractViewerCount();
    if (count === null) return null;

    // Track history for delta
    const now = Date.now();
    this._viewerHistory.push({ timestamp: now, count });
    // Keep last 5 minutes
    this._viewerHistory = this._viewerHistory.filter(v => now - v.timestamp < 300000);

    const prevCount = this._viewerHistory.length >= 2
      ? this._viewerHistory[this._viewerHistory.length - 2].count
      : count;

    return {
      event_type: 'viewer_count_snapshot',
      source_type: 'live_dom',
      captured_at: new Date().toISOString(),
      numeric_value: count,
      video_sec: this.extractVideoSec(),
      payload: {
        viewer_count: count,
        viewer_delta: count - prevCount,
      },
    };
  },

  // ══════════════════════════════════════════════════════════════
  // Metrics (GMV, Viewers, Impressions, etc.)
  // ══════════════════════════════════════════════════════════════

  _extractMetrics() {
    const metrics = {};
    const metricLabels = {
      'GMV': 'gmv',
      'Viewers': 'current_viewers',
      'Current viewers': 'current_viewers',
      'Current viewer': 'current_viewers',
      'LIVE impression': 'impressions',
      'LIVE impressions': 'impressions',
      'Impressions': 'impressions',
      'Tap-through rate': 'tap_through_rate',
      'TRR': 'tap_through_rate',
      'Avg. viewing duration': 'avg_duration',
      'Avg. duration': 'avg_duration',
      'Product clicks': 'product_clicks',
    };

    // Strategy 1: metricCard class pattern
    const metricCards = document.querySelectorAll('[class*="metricCard"]');
    for (const card of metricCards) {
      const nameEl = card.querySelector('[class*="name--"]');
      if (nameEl) {
        const label = nameEl.textContent.trim();
        const key = metricLabels[label];
        if (key) {
          const valueEl = nameEl.nextElementSibling;
          if (valueEl) {
            metrics[key] = valueEl.textContent.trim();
          }
        }
      }
    }

    // Strategy 2: Fallback
    if (Object.keys(metrics).length === 0) {
      const labelEls = document.querySelectorAll('.text-neutral-text3.text-body-s-medium');
      for (const el of labelEls) {
        const label = el.textContent.trim();
        const key = metricLabels[label];
        if (key) {
          const valueEl = el.nextElementSibling;
          if (valueEl) metrics[key] = valueEl.textContent.trim();
        }
      }
    }

    return metrics;
  },

  /**
   * Build live_metrics_snapshot event (all streamer metrics).
   */
  buildMetricsEvent() {
    const metrics = this._extractMetrics();
    return {
      event_type: 'live_metrics_snapshot',
      source_type: 'live_dom',
      captured_at: new Date().toISOString(),
      video_sec: this.extractVideoSec(),
      payload: metrics,
    };
  },

  // ══════════════════════════════════════════════════════════════
  // Comments
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract new comments from the comment container.
   * Returns only unseen comments.
   * @returns {Object[]}
   */
  extractNewComments() {
    const comments = [];

    // Primary: CSS module class pattern
    const commentEls = document.querySelectorAll('[class*="comment--"]');

    for (const el of commentEls) {
      if (el.className.includes('commentContainer')) continue;

      const usernameEl = el.querySelector('[class*="username--"]');
      const contentEl = el.querySelector('[class*="commentContent--"]');
      if (!contentEl) continue;

      let username = '';
      const content = contentEl.textContent.trim();

      if (usernameEl) {
        username = usernameEl.textContent.trim().replace(/:$/, '');
      } else {
        const fullText = el.textContent.trim();
        const colonIdx = fullText.indexOf(':');
        if (colonIdx > 0 && colonIdx < 50) {
          username = fullText.substring(0, colonIdx).trim();
        }
      }

      if (!content) continue;

      const commentId = this._hashString(username + content);
      if (this._seenCommentIds.has(commentId)) continue;
      this._seenCommentIds.add(commentId);

      // Extract user tags
      const tagEls = el.querySelectorAll('[class*="userTag"], [class*="tag"]');
      const tags = Array.from(tagEls).map(t => t.textContent.trim()).filter(t => t);

      comments.push({
        username,
        content,
        tags,
        timestamp: new Date().toISOString(),
      });
    }

    // Keep set manageable
    if (this._seenCommentIds.size > 1000) {
      const arr = Array.from(this._seenCommentIds);
      this._seenCommentIds = new Set(arr.slice(-500));
    }

    return comments;
  },

  /**
   * Build comment_added events from new comments.
   * @returns {Object[]}
   */
  buildCommentEvents() {
    const comments = this.extractNewComments();
    const videoSec = this.extractVideoSec();

    return comments.map(c => ({
      event_type: 'comment_added',
      source_type: 'live_dom',
      captured_at: c.timestamp,
      video_sec: videoSec,
      text_value: c.content,
      payload: {
        username: c.username,
        content: c.content,
        tags: c.tags,
      },
    }));
  },

  // ══════════════════════════════════════════════════════════════
  // Comment Spike Detection
  // ══════════════════════════════════════════════════════════════

  /**
   * Track comment rate and detect spikes.
   * @param {number} newCommentCount - Number of new comments in this batch
   * @returns {Object|null} - comment_spike event or null
   */
  detectCommentSpike(newCommentCount) {
    const now = Date.now();
    this._commentWindow.push({ timestamp: now, count: newCommentCount });

    // Keep last 5 minutes
    this._commentWindow = this._commentWindow.filter(w => now - w.timestamp < 300000);

    // 30-second window count
    const recent30s = this._commentWindow
      .filter(w => now - w.timestamp < 30000)
      .reduce((sum, w) => sum + w.count, 0);

    // Baseline: average per 30s over last 5 minutes
    const totalComments = this._commentWindow.reduce((sum, w) => sum + w.count, 0);
    const windowDurationSec = Math.max(30, (now - this._commentWindow[0].timestamp) / 1000);
    const baseline30s = (totalComments / windowDurationSec) * 30;

    // Spike: 2x baseline or >= 10 comments in 30s
    if (recent30s >= Math.max(10, baseline30s * 2)) {
      return {
        event_type: 'comment_spike',
        source_type: 'live_dom',
        captured_at: new Date().toISOString(),
        video_sec: this.extractVideoSec(),
        numeric_value: recent30s,
        payload: {
          comment_count_30s: recent30s,
          baseline_30s: Math.round(baseline30s),
          spike_ratio: baseline30s > 0 ? (recent30s / baseline30s).toFixed(2) : 'inf',
        },
      };
    }

    return null;
  },

  // ══════════════════════════════════════════════════════════════
  // Products
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract product list from #product-list.
   * @returns {Object[]}
   */
  extractProducts() {
    const products = [];
    const productList = document.querySelector('#product-list');
    if (!productList) return products;

    const cards = productList.querySelectorAll('.rounded-4.mb-8');

    for (const card of cards) {
      const fullText = card.textContent.trim();

      // Extract product name
      const spans = card.querySelectorAll('span');
      let name = '';
      for (const span of spans) {
        const text = span.textContent.trim();
        if (text.length > 15 &&
          !text.includes('Clicks') &&
          !text.includes('Pin') &&
          !text.includes('Stock') &&
          !text.includes('Added to cart') &&
          !text.includes('Items sold') &&
          !text.includes('Sold Out') &&
          !text.includes('All')) {
          name = text;
          break;
        }
      }
      if (!name) continue;

      // Extract price
      const priceMatch = fullText.match(/([\d,]+)円/);
      const price = priceMatch ? priceMatch[1] : '';

      // Extract stats
      const clicksMatch = fullText.match(/Clicks\s*([\d,.K]+)/i);
      const cartsMatch = fullText.match(/Added to cart\s*([\d,.K]+)/i);
      const soldMatch = fullText.match(/Items sold\s*([\d,.K]+)/i);

      // Pin status
      const isPinned = fullText.includes('Unpin') || fullText.includes('Pinned');

      // Stock
      const stockMatch = fullText.match(/(Low Stock|Stock)[:\s]*([\d,]+)/i);
      const isSoldOut = fullText.includes('Sold Out');

      products.push({
        name: name.substring(0, 150),
        pinned: isPinned,
        price,
        stock: isSoldOut ? 'Sold Out' : (stockMatch ? stockMatch[2] : ''),
        clicks: this._parseNumber(clicksMatch ? clicksMatch[1] : '0'),
        carts: this._parseNumber(cartsMatch ? cartsMatch[1] : '0'),
        sold: this._parseNumber(soldMatch ? soldMatch[1] : '0'),
      });
    }

    // Fallback: broader search
    if (products.length === 0) {
      const allDivs = productList.querySelectorAll('div');
      const processedNames = new Set();

      for (const div of allDivs) {
        const text = div.textContent.trim();
        if (text.includes('Clicks') && text.includes('Items sold') && text.length < 500) {
          const spans = div.querySelectorAll('span');
          let name = '';
          for (const span of spans) {
            const t = span.textContent.trim();
            if (t.length > 15 && !t.includes('Clicks') && !processedNames.has(t)) {
              name = t;
              break;
            }
          }
          if (!name || processedNames.has(name)) continue;
          processedNames.add(name);

          const priceMatch = text.match(/([\d,]+)円/);
          const clicksMatch = text.match(/Clicks\s*([\d,.K]+)/i);
          const cartsMatch = text.match(/Added to cart\s*([\d,.K]+)/i);
          const soldMatch = text.match(/Items sold\s*([\d,.K]+)/i);
          const isPinned = text.includes('Unpin') || text.includes('Pinned');

          products.push({
            name: name.substring(0, 150),
            pinned: isPinned,
            price: priceMatch ? priceMatch[1] : '',
            stock: '',
            clicks: this._parseNumber(clicksMatch ? clicksMatch[1] : '0'),
            carts: this._parseNumber(cartsMatch ? cartsMatch[1] : '0'),
            sold: this._parseNumber(soldMatch ? soldMatch[1] : '0'),
          });
        }
      }
    }

    return products;
  },

  // ══════════════════════════════════════════════════════════════
  // Product Switch Detection
  // ══════════════════════════════════════════════════════════════

  /**
   * Detect product pin/switch changes.
   * @returns {Object|null} - product_switched event or null
   */
  detectProductSwitch() {
    const products = this.extractProducts();
    const pinned = products.find(p => p.pinned);
    const pinnedName = pinned ? pinned.name : null;

    if (pinnedName !== this._prevPinnedProductName && this._prevPinnedProductName !== null) {
      const event = {
        event_type: 'product_switched',
        source_type: 'live_dom',
        captured_at: new Date().toISOString(),
        video_sec: this.extractVideoSec(),
        text_value: pinnedName,
        payload: {
          from_product: this._prevPinnedProductName,
          to_product: pinnedName,
          product_price: pinned ? pinned.price : null,
        },
      };
      this._prevPinnedProductName = pinnedName;
      return event;
    }

    if (this._prevPinnedProductName === null) {
      this._prevPinnedProductName = pinnedName;
    }

    return null;
  },

  /**
   * Compute product diffs between current and previous extraction.
   * @returns {Object[]} - Array of products with deltas
   */
  computeProductDiffs() {
    const currentProducts = this.extractProducts();

    if (!this._prevProducts) {
      this._prevProducts = currentProducts;
      return [];
    }

    const prevMap = {};
    for (const p of this._prevProducts) {
      prevMap[p.name] = p;
    }

    const diffs = [];
    for (const curr of currentProducts) {
      const prev = prevMap[curr.name];
      if (!prev) continue;

      const clickDelta = curr.clicks - prev.clicks;
      const cartDelta = curr.carts - prev.carts;
      const soldDelta = curr.sold - prev.sold;

      if (clickDelta > 0 || cartDelta > 0 || soldDelta > 0) {
        diffs.push({
          product_name: curr.name,
          click_delta: clickDelta,
          cart_delta: cartDelta,
          sold_delta: soldDelta,
          pinned: curr.pinned,
        });
      }
    }

    this._prevProducts = currentProducts;
    return diffs;
  },

  // ══════════════════════════════════════════════════════════════
  // Activity Feed (Purchase Notices, Joins, etc.)
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract activity feed items.
   * @returns {Object[]}
   */
  extractActivities() {
    const activities = [];
    const allElements = document.querySelectorAll('div, span');

    for (const el of allElements) {
      const text = el.textContent.trim();
      if (text.length > 200 || text.length < 5) continue;

      let type = null;
      if (text.includes('just joined')) type = 'join';
      else if (text.includes('viewing product')) type = 'view_product';
      else if (text.includes('purchased')) type = 'purchase';
      else if (text.includes('placed an order')) type = 'purchase';
      else if (text.includes('shared')) type = 'share';
      else if (text.includes('followed')) type = 'follow';

      if (type && el.children.length <= 2) {
        if (!this._seenActivityIds.has(text)) {
          this._seenActivityIds.add(text);
          activities.push({ type, text, timestamp: new Date().toISOString() });
        }
      }
    }

    // Keep set manageable
    if (this._seenActivityIds.size > 500) {
      const arr = Array.from(this._seenActivityIds);
      this._seenActivityIds = new Set(arr.slice(-200));
    }

    return activities;
  },

  /**
   * Build activity events (purchase_notice_detected, etc.).
   * @returns {Object[]}
   */
  buildActivityEvents() {
    const activities = this.extractActivities();
    const videoSec = this.extractVideoSec();

    return activities
      .filter(a => a.type === 'purchase')
      .map(a => ({
        event_type: 'purchase_notice_detected',
        source_type: 'live_dom',
        captured_at: a.timestamp,
        video_sec: videoSec,
        text_value: a.text,
        payload: {
          activity_type: a.type,
          raw_text: a.text,
        },
      }));
  },

  // ══════════════════════════════════════════════════════════════
  // Live Duration / Video Sec
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract live duration in seconds.
   * Looks for timer displays like "01:23:45" or "1:23:45"
   * @returns {number|null}
   */
  extractVideoSec() {
    // Strategy 1: Duration selectors
    const selectors = [
      '[class*="duration"]',
      '[class*="Duration"]',
      '[class*="live-time"]',
      '[class*="timer"]',
      '[class*="Timer"]',
    ];

    for (const sel of selectors) {
      try {
        const el = document.querySelector(sel);
        if (el) {
          const sec = this._parseTimestamp(el.textContent.trim());
          if (sec !== null) return sec;
        }
      } catch (e) { /* skip */ }
    }

    // Strategy 2: Scan for HH:MM:SS pattern
    const allSpans = document.querySelectorAll('span, div');
    for (const el of allSpans) {
      if (el.children.length > 0) continue;
      const text = el.textContent.trim();
      if (/^\d{1,2}:\d{2}:\d{2}$/.test(text)) {
        return this._parseTimestamp(text);
      }
    }

    return null;
  },

  /**
   * Parse "HH:MM:SS" or "MM:SS" to seconds.
   */
  _parseTimestamp(text) {
    const match = text.match(/(\d{1,2}):(\d{2}):(\d{2})/);
    if (match) {
      return parseInt(match[1]) * 3600 + parseInt(match[2]) * 60 + parseInt(match[3]);
    }
    const match2 = text.match(/(\d{1,2}):(\d{2})/);
    if (match2) {
      return parseInt(match2[1]) * 60 + parseInt(match2[2]);
    }
    return null;
  },

  // ══════════════════════════════════════════════════════════════
  // AI Suggestions
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract TikTok AI suggestions.
   * @returns {Object[]}
   */
  extractSuggestions() {
    const suggestions = [];

    const collapseHeaders = document.querySelectorAll(
      '.arco-collapse-item-header-title, [class*="collapse"] [class*="header"]'
    );
    for (const header of collapseHeaders) {
      if (header.textContent.trim().includes('Suggestion')) {
        const parent = header.closest('.arco-collapse-item') || header.parentElement;
        if (parent) {
          const content = parent.querySelector('.arco-collapse-item-content, [class*="content"]');
          if (content) {
            const text = content.textContent.trim();
            if (text.length > 10) {
              suggestions.push({ text, timestamp: new Date().toISOString() });
            }
          }
        }
      }
    }

    return suggestions.slice(0, 5);
  },

  // ══════════════════════════════════════════════════════════════
  // Utility
  // ══════════════════════════════════════════════════════════════

  _parseNumber(val) {
    if (val === null || val === undefined) return 0;
    if (typeof val === 'number') return val;
    val = String(val).replace(/[¥$€£円,\s]/g, '');
    if (val.includes('K')) return Math.round(parseFloat(val) * 1000);
    if (val.includes('M')) return Math.round(parseFloat(val) * 1000000);
    return parseFloat(val) || 0;
  },

  _hashString(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(36);
  },

  /**
   * Reset all state (for new session).
   */
  reset() {
    this._prevPinnedProductName = null;
    this._prevProducts = null;
    this._seenCommentIds = new Set();
    this._seenActivityIds = new Set();
    this._commentWindow = [];
    this._viewerHistory = [];
  },
};

// Export
if (typeof globalThis !== 'undefined') {
  globalThis.LiveParser = LiveParser;
}
