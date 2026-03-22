// ─── CONFIG ───────────────────────────────────────────────────────────────────
const DISPLAY_INTERVAL = 5000;   // ms between showing each coin in the spotlight
const POLL_INTERVAL    = 15000;  // ms between API polls for new data
const API_BASE         = "/api/intelligence";

// ─── STATE ────────────────────────────────────────────────────────────────────
let coinQueue        = [];   // coins waiting to be displayed
let displayedCoins   = [];   // full history (for the feed)
let currentCoin      = null;
let lastSeenId       = null; // MongoDB _id of the most recently fetched coin
let memeCount        = 0;
let legitCount       = 0;
let totalScanned     = 0;
let countdownInterval = null;
let displayTimer      = null;
let isLoading         = true; // true until the first successful API response

// ─── HELPERS ──────────────────────────────────────────────────────────────────
function isMeme(coin) {
  return coin.is_rug || coin.degen_score >= 60 || coin.rug_score >= 50;
}

function formatAddress(addr) {
  if (!addr || addr.length < 12) return addr;
  return addr.slice(0, 6) + '...' + addr.slice(-6);
}

function formatDate(iso) {
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch { return iso; }
}

// Deterministic color from a string — used when the API doesn't supply one
function hashColor(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = (h * 33) ^ str.charCodeAt(i);
  const hue = Math.abs(h) % 360;
  return `hsl(${hue}, 80%, 60%)`;
}

// Map degen score ranges to emojis that match the existing UI vocabulary
function scoreEmoji(coin) {
  if (coin.is_rug)            return '☠️';
  if (coin.degen_score >= 90) return '🚀';
  if (coin.degen_score >= 70) return '🔥';
  if (coin.degen_score >= 50) return '⚡';
  if (coin.degen_score >= 30) return '🧠';
  return '🔐';
}

function coinColor(coin) {
  // Prefer server-supplied color, fall back to deterministic hash
  return coin._color || hashColor(coin.mint_address);
}

function coinEmoji(coin) {
  return coin._emoji || scoreEmoji(coin);
}

// Build a human-readable verdict from on-chain risk signals
// (used when the API doc has no pre-baked _verdict field)
function buildVerdict(coin) {
  const flags = [];
  if (coin.is_rug)             flags.push('flagged as a rug');
  if (!coin.lp_locked)         flags.push('LP is unlocked');
  if (coin.freeze_authority)   flags.push('freeze authority active');
  if (coin.mint_authority)     flags.push('mint authority active');
  if (coin.top_holder_pct > 30)
    flags.push(`top holder owns ${coin.top_holder_pct.toFixed(1)}% of supply`);

  if (flags.length === 0)
    return `Clean token profile. Degen score ${coin.degen_score.toFixed(1)}, rug score ${coin.rug_score.toFixed(1)}.`;
  return `Risk factors detected: ${flags.join(', ')}. Degen ${coin.degen_score.toFixed(1)} / Rug ${coin.rug_score.toFixed(1)}.`;
}

// ─── API ──────────────────────────────────────────────────────────────────────

/**
 * Initial load — fetch the most recent 50 coins from Atlas.
 * Populates coinQueue and kicks off the display loop.
 */
async function initialFetch() {
  try {
    const res  = await fetch(API_BASE);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const coins = (data.coins || []).reverse(); // oldest first so queue drains in discovery order

    if (coins.length > 0) {
      // Track the most recent _id so incremental polls only return newer docs
      lastSeenId = data.coins[0]._id || null;
      coinQueue.push(...coins);
      isLoading = false;
      hideLoadingState();
      scheduleNextDisplay();
    } else {
      showEmptyState();
    }
  } catch (err) {
    console.error('[NeuroScout] Initial fetch failed:', err);
    showErrorState(err.message);
  }
}

/**
 * Incremental poll — only fetches documents newer than lastSeenId.
 * New coins are appended to the back of coinQueue so they appear
 * after whatever is currently waiting to be displayed.
 */
async function pollForNew() {
  if (!lastSeenId) {
    await initialFetch();
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/since/${lastSeenId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const newCoins = (data.coins || []).reverse();

    if (newCoins.length > 0) {
      // Update cursor to the newest _id returned
      lastSeenId = data.coins[0]._id || lastSeenId;
      coinQueue.push(...newCoins);
      console.log(`[NeuroScout] Queued ${newCoins.length} new coin(s). Queue depth: ${coinQueue.length}`);
    }
  } catch (err) {
    console.warn('[NeuroScout] Poll failed (will retry):', err);
  }
}

// ─── DISPLAY LOOP ─────────────────────────────────────────────────────────────

function scheduleNextDisplay() {
  clearTimeout(displayTimer);

  if (coinQueue.length === 0) {
    // Nothing queued — check again in 2s without advancing the countdown
    displayTimer = setTimeout(scheduleNextDisplay, 2000);
    return;
  }

  const coin = coinQueue.shift();
  currentCoin = coin;
  addToFeed(coin);
  renderCoin(coin);

  displayTimer = setTimeout(scheduleNextDisplay, DISPLAY_INTERVAL);
}

// ─── RENDER ───────────────────────────────────────────────────────────────────

function renderCoin(coin) {
  const card = document.getElementById('coin-card');
  card.classList.add('exiting');

  setTimeout(() => {
    card.classList.remove('exiting');
    card.style.animation = 'none';
    void card.offsetWidth;
    card.style.animation = '';

    const color    = coinColor(coin);
    const memeCoin = isMeme(coin);

    // Avatar
    const avatar = document.getElementById('coin-avatar');
    avatar.style.background = color + '22';
    document.getElementById('coin-emoji').textContent = coinEmoji(coin);
    const ring = document.getElementById('avatar-ring');
    ring.style.borderColor = `${color} transparent transparent transparent`;

    // Header
    document.getElementById('coin-name').textContent    = coin.name;
    document.getElementById('coin-sym').textContent     = coin.symbol;
    document.getElementById('coin-address').textContent = formatAddress(coin.mint_address);
    document.getElementById('coin-created').textContent = '// CREATED ' + formatDate(coin.created_at);

    const badge = document.getElementById('verdict-badge');
    badge.textContent = memeCoin ? 'MEMECOIN' : 'LEGIT';
    badge.className   = 'verdict-badge ' + (memeCoin ? 'meme' : 'legit');

    // Scores
    const degenPct = Math.min(coin.degen_score, 100);
    const rugPct   = Math.min(coin.rug_score,   100);
    document.getElementById('degen-score-val').textContent = coin.degen_score.toFixed(1);
    document.getElementById('rug-score-val').textContent   = coin.rug_score.toFixed(1);
    document.getElementById('degen-bar').style.width = degenPct + '%';
    document.getElementById('rug-bar').style.width   = rugPct   + '%';

    // Flags
    setFlag('flag-rug',    coin.is_rug,          true);
    setFlag('flag-lp',     coin.lp_locked,       false);
    setFlag('flag-freeze', coin.freeze_authority, true);
    setFlag('flag-mint',   coin.mint_authority,   true);

    // Stats
    document.getElementById('stat-top-holder').textContent = coin.top_holder_pct.toFixed(1) + '%';
    document.getElementById('stat-decimals').textContent   = coin.decimals;
    document.getElementById('stat-creator').textContent    = formatAddress(coin.creator_address);

    // Scorer mode badge (heuristic vs xgboost) — update if the element exists
    const scorerEl = document.getElementById('stat-scorer');
    if (scorerEl) scorerEl.textContent = coin.scorer_mode || 'heuristic';

    // Verdict
    const vs = document.getElementById('verdict-section');
    vs.className = 'verdict-section ' + (memeCoin ? 'is-meme' : 'is-legit');
    document.getElementById('verdict-title').textContent =
      memeCoin ? '⚠ MEMECOIN DETECTED' : '✓ LEGITIMATE PROJECT';
    document.getElementById('verdict-text').textContent  =
      coin._verdict || buildVerdict(coin);

    restartProgress();
  }, 340);
}

function setFlag(id, value, badWhenTrue) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('active-bad', 'active-good');
  if (badWhenTrue) {
    if (value) el.classList.add('active-bad');
  } else {
    if (value) el.classList.add('active-good');
    else       el.classList.add('active-bad');
  }
}

// ─── PROGRESS BAR ─────────────────────────────────────────────────────────────

function restartProgress() {
  const bar = document.getElementById('progress-bar');
  if (!bar) return;
  bar.style.animation = 'none';
  void bar.offsetWidth;
  bar.style.setProperty('--duration', (DISPLAY_INTERVAL / 1000) + 's');
  bar.style.animation = `countdown ${DISPLAY_INTERVAL / 1000}s linear forwards`;

  let secs = Math.ceil(DISPLAY_INTERVAL / 1000);
  const label = document.getElementById('countdown-label');
  if (label) label.textContent = secs + 's';
  clearInterval(countdownInterval);
  countdownInterval = setInterval(() => {
    secs = Math.max(0, secs - 1);
    if (label) label.textContent = secs + 's';
  }, 1000);
}

// ─── FEED ─────────────────────────────────────────────────────────────────────

function addToFeed(coin) {
  const memeCoin = isMeme(coin);
  const color    = coinColor(coin);
  const list     = document.getElementById('feed-list');
  if (!list) return;

  const item = document.createElement('div');
  item.className = 'feed-item';
  item.innerHTML = `
    <div class="feed-icon" style="background:${color}22;color:${color}">${coinEmoji(coin)}</div>
    <div class="feed-info">
      <div class="feed-name">${coin.name}</div>
      <div class="feed-sub">${coin.symbol} · ${formatAddress(coin.mint_address)}</div>
    </div>
    <div class="feed-scores">
      <div class="feed-badge ${memeCoin ? 'meme' : 'legit'}">${memeCoin ? 'MEME' : 'LEGIT'}</div>
      <div class="feed-score-line">D:${coin.degen_score.toFixed(0)} R:${coin.rug_score.toFixed(0)}</div>
    </div>
  `;
  list.insertBefore(item, list.firstChild);
  while (list.children.length > 30) list.removeChild(list.lastChild);

  totalScanned++;
  if (memeCoin) memeCount++; else legitCount++;

  const totalEl = document.getElementById('total-count');
  const feedEl  = document.getElementById('feed-count');
  const memeEl  = document.getElementById('meme-count');
  const legitEl = document.getElementById('legit-count');

  if (totalEl) totalEl.textContent = totalScanned;
  if (feedEl)  feedEl.textContent  = totalScanned + ' COINS';
  if (memeEl)  memeEl.textContent  = memeCount;
  if (legitEl) legitEl.textContent = legitCount;
}

// ─── UI STATE HELPERS ─────────────────────────────────────────────────────────

function hideLoadingState() {
  const el = document.getElementById('loading-state');
  if (el) el.style.display = 'none';
  const card = document.getElementById('coin-card');
  if (card) card.style.display = '';
}

function showEmptyState() {
  const el = document.getElementById('loading-state');
  if (el) {
    el.style.display = '';
    el.textContent = 'No tokens scored yet. Waiting for the swarm…';
  }
}

function showErrorState(msg) {
  const el = document.getElementById('loading-state');
  if (el) {
    el.style.display = '';
    el.textContent = `⚠ API error: ${msg}. Retrying…`;
  }
  // Retry initial fetch after 10s
  setTimeout(initialFetch, 10_000);
}

// ─── BOOT ─────────────────────────────────────────────────────────────────────

// Hide the main card until data arrives
(function () {
  const card = document.getElementById('coin-card');
  if (card) card.style.display = 'none';
})();

initialFetch();
setInterval(pollForNew, POLL_INTERVAL);

function seedFromServerData() {
  const el = document.getElementById('initial-data');
  if (!el) return false;
  
  let data;
  try {
    data = JSON.parse(el.textContent);
  } catch (err) {
    console.error('[NeuroScout] Failed to parse initial data:', err);
    return false;
  }

  if (!Array.isArray(data) || data.length === 0) return false;

  lastSeenId = data[data.length - 1]._id || null;
  coinQueue.push(...data);
  hideLoadingState();
  return true;
}