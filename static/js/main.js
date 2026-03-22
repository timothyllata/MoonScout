const INTERVAL = 5000; // ms between coins

// ─── MOCK DATA in real API shape ───
// Each object matches the API response format exactly.
// Replace this array with a fetch() call to your real endpoint when ready.
const coins = [
  {
    mint_address:    "DogeZi11aXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "DOGZL",
    name:            "DogeZilla",
    degen_score:     91.0,
    rug_score:       78.5,
    is_rug:          false,
    lp_locked:       false,
    top_holder_pct:  42.3,
    freeze_authority: true,
    mint_authority:  true,
    decimals:        9,
    creator_address: "RuGPu11XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2024-06-12T03:22:00+00:00",
    broadcast_sent:  true,
    // UI extras (drop these once real API is wired up)
    _emoji: "🦖", _color: "#f7931a",
    _verdict: "Textbook memecoin. No whitepaper, anonymous devs, freeze & mint authority both enabled — classic rug setup. The 42% top holder concentration is a massive red flag.",
  },
  {
    mint_address:    "NRC1NeuRa1ChainXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "NRC",
    name:            "NeuralChain",
    degen_score:     18.0,
    rug_score:       4.2,
    is_rug:          false,
    lp_locked:       true,
    top_holder_pct:  6.1,
    freeze_authority: false,
    mint_authority:  false,
    decimals:        6,
    creator_address: "Le9itDevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2022-11-03T09:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "🧠", _color: "#7c5cfc",
    _verdict: "Low risk across the board. LP is locked, no freeze or mint authority, and top holder concentration is healthy at 6%. Degen and rug scores are both minimal.",
  },
  {
    mint_address:    "PEPECashM0neyXLXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "PCMXL",
    name:            "PepeCashMoneyXL",
    degen_score:     98.5,
    rug_score:       91.0,
    is_rug:          true,
    lp_locked:       false,
    top_holder_pct:  67.0,
    freeze_authority: true,
    mint_authority:  true,
    decimals:        6,
    creator_address: "ScamWa11etXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2025-01-07T03:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "🐸", _color: "#00c851",
    _verdict: "Flagged as a rug. 67% top holder concentration, freeze and mint authority both active, LP not locked. Every risk indicator is at maximum. Do not touch.",
  },
  {
    mint_address:    "AQUALedger1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "AQUA",
    name:            "AquaLedger",
    degen_score:     22.0,
    rug_score:       6.8,
    is_rug:          false,
    lp_locked:       true,
    top_holder_pct:  9.4,
    freeze_authority: false,
    mint_authority:  false,
    decimals:        6,
    creator_address: "H2ODevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2021-08-15T12:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "💧", _color: "#00aae4",
    _verdict: "Solid fundamentals. LP locked, no dangerous authorities, low rug score, and reasonable holder distribution. A legitimate RWA project with clean on-chain hygiene.",
  },
  {
    mint_address:    "SHIB2ReVeNGeXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "SHIB2",
    name:            "Shib2TheRevenge",
    degen_score:     87.0,
    rug_score:       64.0,
    is_rug:          false,
    lp_locked:       false,
    top_holder_pct:  38.9,
    freeze_authority: false,
    mint_authority:  true,
    decimals:        9,
    creator_address: "AnonDevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2025-03-01T21:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "🐕", _color: "#ff6b35",
    _verdict: "High degen and rug scores. Mint authority is still active (supply can be inflated at any time), LP is unlocked, and one wallet holds 39% of supply. Speculative play at best.",
  },
  {
    mint_address:    "OVT0mniVau1tXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "OVT",
    name:            "OmniVault",
    degen_score:     11.0,
    rug_score:       2.1,
    is_rug:          false,
    lp_locked:       true,
    top_holder_pct:  4.2,
    freeze_authority: false,
    mint_authority:  false,
    decimals:        6,
    creator_address: "AuditedDevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2020-05-20T08:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "🔐", _color: "#00f5c4",
    _verdict: "Excellent risk profile. Near-zero rug score, LP locked, no authorities enabled, and extremely distributed holder base. One of the cleanest token configs in the feed.",
  },
  {
    mint_address:    "MR1UMo0nR0cketInuXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "MRIU",
    name:            "MoonRocketInu",
    degen_score:     95.0,
    rug_score:       82.0,
    is_rug:          false,
    lp_locked:       false,
    top_holder_pct:  51.0,
    freeze_authority: true,
    mint_authority:  true,
    decimals:        9,
    creator_address: "3amDevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2025-02-14T03:14:00+00:00",
    broadcast_sent:  true,
    _emoji: "🚀", _color: "#ffe44d",
    _verdict: "Extremely high risk. Over half the supply is in one wallet, both freeze and mint authority are active, and the LP is wide open. Deployed at 3am — classic launch pattern for a pump-and-dump.",
  },
  {
    mint_address:    "GR1DGridiron1XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    symbol:          "GRID",
    name:            "GridironFi",
    degen_score:     25.0,
    rug_score:       9.3,
    is_rug:          false,
    lp_locked:       true,
    top_holder_pct:  11.2,
    freeze_authority: false,
    mint_authority:  false,
    decimals:        6,
    creator_address: "GreenDevXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    created_at:      "2022-03-08T10:00:00+00:00",
    broadcast_sent:  true,
    _emoji: "⚡", _color: "#ffd700",
    _verdict: "Low risk profile with locked LP, no dangerous authorities, and reasonable holder distribution. Degen score slightly elevated but within acceptable range for a legitimate project.",
  },
];

// ─── STATE ───
let currentIndex    = 0;
let memeCount       = 0;
let legitCount      = 0;
let totalScanned    = 0;
let countdownInterval = null;

// ─── HELPERS ───
function isMeme(coin) {
  // Classify as memecoin if degen_score >= 60 OR rug_score >= 50 OR is_rug
  return coin.is_rug || coin.degen_score >= 60 || coin.rug_score >= 50;
}

function formatAddress(addr) {
  if (!addr || addr.length < 12) return addr;
  return addr.slice(0, 6) + '...' + addr.slice(-6);
}

function formatDate(iso) {
  try {
    const d = new Date(iso);
    return d.toISOString().slice(0, 10);
  } catch { return iso; }
}

function coinColor(coin) {
  return coin._color || '#00f5c4';
}

function coinEmoji(coin) {
  return coin._emoji || '🪙';
}

// ─── RENDER ───
function renderCoin(coin) {
  const card = document.getElementById('coin-card');
  card.classList.add('exiting');

  setTimeout(() => {
    card.classList.remove('exiting');
    card.style.animation = 'none';
    void card.offsetWidth;
    card.style.animation = '';

    const color   = coinColor(coin);
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
    badge.textContent  = memeCoin ? 'MEMECOIN' : 'LEGIT';
    badge.className    = 'verdict-badge ' + (memeCoin ? 'meme' : 'legit');

    // Scores
    const degenPct = Math.min(coin.degen_score, 100);
    const rugPct   = Math.min(coin.rug_score, 100);
    document.getElementById('degen-score-val').textContent = coin.degen_score.toFixed(1);
    document.getElementById('rug-score-val').textContent   = coin.rug_score.toFixed(1);
    document.getElementById('degen-bar').style.width = degenPct + '%';
    document.getElementById('rug-bar').style.width   = rugPct + '%';

    // Flags — bad = active-bad, good (lp_locked) = active-good, else dim
    setFlag('flag-rug',    coin.is_rug,          true);
    setFlag('flag-lp',     coin.lp_locked,       false);  // locked = good
    setFlag('flag-freeze', coin.freeze_authority, true);
    setFlag('flag-mint',   coin.mint_authority,   true);

    // Stats
    document.getElementById('stat-top-holder').textContent = coin.top_holder_pct.toFixed(1) + '%';
    document.getElementById('stat-decimals').textContent   = coin.decimals;
    document.getElementById('stat-creator').textContent    = formatAddress(coin.creator_address);

    // Verdict
    const vs = document.getElementById('verdict-section');
    vs.className = 'verdict-section ' + (memeCoin ? 'is-meme' : 'is-legit');
    document.getElementById('verdict-title').textContent = memeCoin ? '⚠ MEMECOIN DETECTED' : '✓ LEGITIMATE PROJECT';
    document.getElementById('verdict-text').textContent  = coin._verdict || buildVerdict(coin);

    restartProgress();
  }, 340);
}

function setFlag(id, value, badWhenTrue) {
  const el = document.getElementById(id);
  el.classList.remove('active-bad', 'active-good');
  if (badWhenTrue) {
    if (value) el.classList.add('active-bad');
  } else {
    // lp_locked — good when true
    if (value) el.classList.add('active-good');
    else        el.classList.add('active-bad');
  }
}

// Fallback verdict builder if no _verdict string provided (useful once real API is wired)
function buildVerdict(coin) {
  const flags = [];
  if (coin.is_rug)          flags.push('flagged as a rug');
  if (!coin.lp_locked)      flags.push('LP is unlocked');
  if (coin.freeze_authority) flags.push('freeze authority active');
  if (coin.mint_authority)   flags.push('mint authority active');
  if (coin.top_holder_pct > 30) flags.push(`top holder owns ${coin.top_holder_pct.toFixed(1)}% of supply`);

  if (flags.length === 0) return `Clean token profile. Degen score ${coin.degen_score}, rug score ${coin.rug_score}.`;
  return `Risk factors detected: ${flags.join(', ')}. Degen score ${coin.degen_score} / Rug score ${coin.rug_score}.`;
}

// ─── PROGRESS ───
function restartProgress() {
  const bar = document.getElementById('progress-bar');
  bar.style.animation = 'none';
  void bar.offsetWidth;
  bar.style.setProperty('--duration', (INTERVAL / 1000) + 's');
  bar.style.animation = `countdown ${INTERVAL / 1000}s linear forwards`;

  let secs = Math.ceil(INTERVAL / 1000);
  document.getElementById('countdown-label').textContent = secs + 's';
  clearInterval(countdownInterval);
  countdownInterval = setInterval(() => {
    secs = Math.max(0, secs - 1);
    document.getElementById('countdown-label').textContent = secs + 's';
  }, 1000);
}

// ─── FEED ───
function addToFeed(coin) {
  const memeCoin = isMeme(coin);
  const color    = coinColor(coin);
  const list     = document.getElementById('feed-list');

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
  document.getElementById('total-count').textContent = totalScanned;
  document.getElementById('feed-count').textContent  = totalScanned + ' COINS';
  document.getElementById('meme-count').textContent  = memeCount;
  document.getElementById('legit-count').textContent = legitCount;
}

// ─── CYCLE ───
function nextCoin() {
  const coin = coins[currentIndex % coins.length];
  currentIndex++;
  addToFeed(coin);
  renderCoin(coin);
}

nextCoin();
setInterval(nextCoin, INTERVAL);