/**
 * AitherHub - Dashboard Page Parser
 * 
 * Extracts data from TikTok LIVE Dashboard (shop.tiktok.com/workbench/live/...).
 * 
 * Responsible for:
 * - KPI snapshot (GMV, items_sold, current_viewers, impressions, etc.)
 * - Product table snapshot (per-product: gmv, sales, cart, clicks, impressions, ctr)
 * - Trend data extraction (5-minute bucket graphs)
 * - Traffic source data
 * 
 * DOM selectors are imported from selectors.js
 * Confirmed DOM structure as of 2026-02-25.
 */

const DashboardParser = {
  _log(...args) {
    console.log('[AitherHub DashParser]', ...args);
  },

  // ══════════════════════════════════════════════════════════════
  // KPI Extraction
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract all KPI metrics from the dashboard overview.
   * Returns: { gmv, items_sold, current_viewers, impressions, views, ... }
   */
  extractKPI() {
    const metrics = {};
    const metricLabels = {
      'GMV': 'gmv',
      'Items sold': 'items_sold',
      'Current viewers': 'current_viewers',
      'Impressions': 'impressions',
      'Views': 'views',
      'GMV per hour': 'gmv_per_hour',
      'Impressions per hour': 'impressions_per_hour',
      'Show GPM': 'show_gpm',
      'Avg. viewing duration per view': 'avg_duration',
      'Comment rate': 'comment_rate',
      'Follow rate': 'follow_rate',
      'Tap-through rate': 'tap_through_rate',
      'Tap-through rate (via LIVE preview)': 'tap_through_preview',
      'LIVE CTR': 'live_ctr',
      'Order rate (SKU orders)': 'order_rate',
      'Share rate': 'share_rate',
      'Like rate': 'like_rate',
      '> 1 min. views': 'views_over_1min',
    };

    // Strategy 1: Hero metrics (Items sold, Current viewers)
    const heroLabels = document.querySelectorAll('.text-xl.font-medium.text-neutral-text-1');
    for (const el of heroLabels) {
      const text = el.textContent.trim();
      if (metricLabels[text]) {
        const valueEl = el.nextElementSibling;
        if (valueEl) {
          metrics[metricLabels[text]] = this._cleanValue(valueEl);
        }
      }
    }

    // Strategy 2: Detail metrics
    const detailLabels = document.querySelectorAll(
      '.text-base.text-neutral-text-1.truncate, .text-base.text-neutral-text-1'
    );
    for (const el of detailLabels) {
      const text = el.textContent.trim();
      const key = metricLabels[text];
      if (key && !metrics[key]) {
        const valueEl = el.nextElementSibling;
        if (valueEl) {
          metrics[key] = this._cleanValue(valueEl);
        }
      }
    }

    // Strategy 3: GMV (the big number)
    if (!metrics.gmv) {
      const allSpans = document.querySelectorAll('span');
      for (const span of allSpans) {
        const text = span.textContent.trim();
        if (text.match(/^GMV\s*(\(.*\))?$/)) {
          const container = span.closest('[class*="flex"][class*="col"]') || span.parentElement?.parentElement;
          if (container) {
            const numberEls = container.querySelectorAll('div, span');
            for (const numEl of numberEls) {
              const numText = numEl.textContent.trim();
              if (/^[\d,]+$/.test(numText) && numText.length > 3) {
                metrics.gmv = numText;
                break;
              }
            }
          }
        }
      }
    }

    // Strategy 4: Fallback - generic label-value
    if (Object.keys(metrics).length < 3) {
      const allElements = document.querySelectorAll('div');
      for (const el of allElements) {
        if (el.children.length > 3) continue;
        const text = el.textContent.trim();
        for (const [label, key] of Object.entries(metricLabels)) {
          if (text === label && !metrics[key]) {
            const parent = el.parentElement;
            if (parent) {
              const fullText = parent.textContent.trim();
              const value = fullText.replace(label, '').trim().split('\n')[0].trim();
              if (value && value !== label) {
                metrics[key] = value;
              }
            }
          }
        }
      }
    }

    this._log('KPI extracted:', Object.keys(metrics).length, 'keys');
    return metrics;
  },

  /**
   * Build a dashboard_kpi_snapshot event from extracted KPI.
   * @returns {Object} - Event object for EventBuffer
   */
  buildKPIEvent() {
    const kpi = this.extractKPI();
    return {
      event_type: 'dashboard_kpi_snapshot',
      source_type: 'dashboard_dom',
      captured_at: new Date().toISOString(),
      numeric_value: this._parseNumber(kpi.gmv),
      payload: kpi,
    };
  },

  // ══════════════════════════════════════════════════════════════
  // Product Table Extraction
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract product table data.
   * Returns array of product objects with funnel metrics.
   * 
   * Confirmed DOM (2026-02-25):
   * - Table with most rows = product table
   * - 9 columns: No, Name+ID, Pin, GMV, Sold, Cart, Clicks, Impressions, CTR
   */
  extractProducts() {
    const products = [];
    const tables = document.querySelectorAll('table');

    // Find the product table (most rows)
    let productTable = null;
    let maxRows = 0;
    for (const t of tables) {
      const rowCount = t.querySelectorAll('tr').length;
      if (rowCount > maxRows) {
        maxRows = rowCount;
        productTable = t;
      }
    }

    if (!productTable) {
      this._log('No product table found');
      return products;
    }

    const rows = productTable.querySelectorAll('tr');
    for (const row of rows) {
      const cells = row.querySelectorAll('td');
      if (cells.length < 7) continue;

      const no = cells[0]?.textContent.trim();
      const nameCell = cells[1];
      const name = nameCell?.querySelector('a')?.textContent.trim() ||
                   nameCell?.textContent.trim() || '';

      // Extract product ID
      const idMatch = nameCell?.textContent.match(/ID:\s*(\d+)/);
      const productId = idMatch ? idMatch[1] : '';

      let isPinned, gmv, sold, cartCount, clicks, impressions, ctr;

      if (cells.length >= 9) {
        isPinned = cells[2]?.textContent.trim() === 'Pinned';
        gmv = cells[3]?.textContent.trim() || '0';
        sold = cells[4]?.textContent.trim() || '0';
        cartCount = cells[5]?.textContent.trim() || '0';
        clicks = cells[6]?.textContent.trim() || '0';
        impressions = cells[7]?.textContent.trim() || '0';
        ctr = cells[8]?.textContent.trim() || '0%';
      } else if (cells.length >= 8) {
        isPinned = row.textContent.includes('Pinned');
        gmv = cells[2]?.textContent.trim() || '0';
        sold = cells[3]?.textContent.trim() || '0';
        cartCount = cells[4]?.textContent.trim() || '0';
        clicks = cells[5]?.textContent.trim() || '0';
        impressions = cells[6]?.textContent.trim() || '0';
        ctr = cells[7]?.textContent.trim() || '0%';
      } else {
        isPinned = row.textContent.includes('Pinned');
        gmv = cells[2]?.textContent.trim() || '0';
        sold = cells[3]?.textContent.trim() || '0';
        cartCount = cells[4]?.textContent.trim() || '0';
        clicks = cells[5]?.textContent.trim() || '0';
        impressions = cells[6]?.textContent.trim() || '0';
        ctr = '0%';
      }

      // Clean product name
      const cleanName = name.replace(/ID:\s*\d+/g, '').trim();

      if (cleanName && cleanName.length > 3) {
        products.push({
          product_id: productId,
          product_name: cleanName.substring(0, 150),
          pinned: isPinned,
          gmv: this._parseNumber(gmv),
          sales_count: this._parseNumber(sold),
          add_to_cart_count: this._parseNumber(cartCount),
          click_count: this._parseNumber(clicks),
          impression_count: this._parseNumber(impressions),
          ctr: this._parsePercent(ctr),
        });
      }
    }

    this._log('Products extracted:', products.length);
    return products;
  },

  /**
   * Build product_metrics_snapshot events from extracted products.
   * @returns {Object[]} - Array of event objects
   */
  buildProductEvents() {
    const products = this.extractProducts();
    const now = new Date().toISOString();

    return products.map(p => ({
      event_type: 'product_metrics_snapshot',
      source_type: 'dashboard_dom',
      captured_at: now,
      product_id: p.product_id,
      numeric_value: p.gmv,
      payload: p,
    }));
  },

  /**
   * Build product snapshot data for EventBuffer.setProductSnapshot().
   * @returns {Object[]} - Array matching ProductSnapshotItem schema
   */
  buildProductSnapshotData() {
    return this.extractProducts();
  },

  // ══════════════════════════════════════════════════════════════
  // Traffic Source Extraction
  // ══════════════════════════════════════════════════════════════

  /**
   * Extract traffic source table data.
   */
  extractTrafficSources() {
    const sources = [];
    const tables = document.querySelectorAll('table');

    for (const table of tables) {
      const headers = Array.from(table.querySelectorAll('th')).map(h => h.textContent.trim());
      if (headers.includes('Channel') && (headers.includes('Views') || headers.includes('Impressions'))) {
        const rows = table.querySelectorAll('tr');
        for (const row of rows) {
          const cells = row.querySelectorAll('td');
          if (cells.length >= 4) {
            sources.push({
              channel: cells[0]?.textContent.trim(),
              gmv: cells[1]?.textContent.trim(),
              impressions: cells[2]?.textContent.trim(),
              views: cells[3]?.textContent.trim(),
            });
          }
        }
        break;
      }
    }

    this._log('Traffic sources extracted:', sources.length);
    return sources;
  },

  /**
   * Build traffic_source_snapshot event.
   */
  buildTrafficSourceEvent() {
    const sources = this.extractTrafficSources();
    if (sources.length === 0) return null;

    return {
      event_type: 'traffic_source_snapshot',
      source_type: 'dashboard_dom',
      captured_at: new Date().toISOString(),
      payload: { sources },
    };
  },

  // ══════════════════════════════════════════════════════════════
  // Diff Detection (for delta events)
  // ══════════════════════════════════════════════════════════════

  _prevProducts: null,
  _prevKPI: null,

  /**
   * Compute product diffs between current and previous snapshot.
   * Returns array of products that changed, with delta values.
   * @param {Object[]} currentProducts
   * @returns {Object[]} - Changed products with deltas
   */
  computeProductDiffs(currentProducts) {
    if (!this._prevProducts) {
      this._prevProducts = currentProducts;
      return []; // First snapshot, no diff
    }

    const prevMap = {};
    for (const p of this._prevProducts) {
      if (p.product_id) prevMap[p.product_id] = p;
    }

    const diffs = [];
    for (const curr of currentProducts) {
      if (!curr.product_id) continue;
      const prev = prevMap[curr.product_id];
      if (!prev) {
        // New product
        diffs.push({ ...curr, is_new: true });
        continue;
      }

      const clickDelta = curr.click_count - prev.click_count;
      const cartDelta = curr.add_to_cart_count - prev.add_to_cart_count;
      const salesDelta = curr.sales_count - prev.sales_count;
      const gmvDelta = curr.gmv - prev.gmv;
      const impressionDelta = curr.impression_count - prev.impression_count;

      // Guard against negative deltas (page reload / data reset)
      // If any major metric goes significantly negative, treat as data reset
      if (clickDelta < -10 || salesDelta < -3 || gmvDelta < -1000) {
        this._log('Data reset detected for product:', curr.product_id,
          'click_delta:', clickDelta, 'sales_delta:', salesDelta, 'gmv_delta:', gmvDelta);
        // Skip this diff, update prev to current
        continue;
      }

      // Clamp small negative deltas to 0 (minor DOM parsing jitter)
      const safeClickDelta = Math.max(0, clickDelta);
      const safeCartDelta = Math.max(0, cartDelta);
      const safeSalesDelta = Math.max(0, salesDelta);
      const safeGmvDelta = Math.max(0, gmvDelta);
      const safeImpressionDelta = Math.max(0, impressionDelta);

      if (safeClickDelta > 0 || safeCartDelta > 0 || safeSalesDelta > 0 || safeGmvDelta > 0) {
        diffs.push({
          ...curr,
          click_delta: safeClickDelta,
          cart_delta: safeCartDelta,
          sales_delta: safeSalesDelta,
          gmv_delta: safeGmvDelta,
          impression_delta: safeImpressionDelta,
          is_new: false,
        });
      }
    }

    this._prevProducts = currentProducts;
    return diffs;
  },

  /**
   * Compute KPI diffs.
   * @param {Object} currentKPI
   * @returns {Object|null} - KPI deltas or null if first snapshot
   */
  computeKPIDiff(currentKPI) {
    if (!this._prevKPI) {
      this._prevKPI = currentKPI;
      return null;
    }

    const diff = {};
    for (const [key, val] of Object.entries(currentKPI)) {
      const prevVal = this._prevKPI[key];
      if (prevVal !== undefined) {
        const currNum = this._parseNumber(val);
        const prevNum = this._parseNumber(prevVal);
        if (currNum !== prevNum) {
          diff[key] = { current: val, previous: prevVal, delta: currNum - prevNum };
        }
      }
    }

    this._prevKPI = currentKPI;
    return Object.keys(diff).length > 0 ? diff : null;
  },

  // ══════════════════════════════════════════════════════════════
  // Pin State Tracking
  // ══════════════════════════════════════════════════════════════

  _prevPinnedProductId: null,

  /**
   * Detect product pin change.
   * @param {Object[]} products
   * @returns {Object|null} - Pin change event or null
   */
  detectPinChange(products) {
    const pinned = products.find(p => p.pinned);
    const pinnedId = pinned ? pinned.product_id : null;

    if (pinnedId !== this._prevPinnedProductId) {
      const event = {
        event_type: 'product_pinned',
        source_type: 'dashboard_dom',
        captured_at: new Date().toISOString(),
        product_id: pinnedId,
        payload: {
          from_product_id: this._prevPinnedProductId,
          to_product_id: pinnedId,
          product_name: pinned ? pinned.product_name : null,
        },
      };
      this._prevPinnedProductId = pinnedId;
      return event;
    }

    return null;
  },

  // ══════════════════════════════════════════════════════════════
  // Utility
  // ══════════════════════════════════════════════════════════════

  /**
   * Clean value from a DOM element (handle concatenated percentages etc.)
   */
  _cleanValue(el) {
    // Try direct text node first
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        const t = node.textContent.trim();
        if (t) return t;
      }
    }
    // Try first child element
    if (el.firstElementChild) {
      const val = el.firstElementChild.textContent.trim();
      if (val) return val;
    }
    // Fallback with concatenation fix
    let value = el.textContent.trim();
    const pctMatches = value.match(/(\d+\.?\d*%)/g);
    if (pctMatches && pctMatches.length >= 2) {
      value = pctMatches[0];
    }
    return value;
  },

  /**
   * Parse a number string (handles commas, yen symbol, K/M suffixes).
   */
  _parseNumber(val) {
    if (val === null || val === undefined) return 0;
    if (typeof val === 'number') return val;
    val = String(val).replace(/[¥$€£円,\s]/g, '');
    if (val.includes('K')) return Math.round(parseFloat(val) * 1000);
    if (val.includes('M')) return Math.round(parseFloat(val) * 1000000);
    return parseFloat(val) || 0;
  },

  /**
   * Parse a percentage string to decimal.
   */
  _parsePercent(val) {
    if (!val) return 0;
    const num = parseFloat(String(val).replace('%', ''));
    return isNaN(num) ? 0 : num / 100;
  },
};

// Export
if (typeof globalThis !== 'undefined') {
  globalThis.DashboardParser = DashboardParser;
}
