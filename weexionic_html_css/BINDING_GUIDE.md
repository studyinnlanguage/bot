# WEEXIONIC UI KIT — BINDING GUIDE (HTML/CSS → Real Data)

**Package:** `weexionic_html_css/` · **Design:** Obsidian × Gold (approved mockups)
**Iron rule:** Is kit me **EK BHI fake number nahi hai.** Tum data connect karoge — HTML/CSS me kuch bhi hardcode nahi karna (wapas wo Antigravity wali galti nahi — forbidden).

---

## 1. FOLDER STRUCTURE

```
weexionic_html_css/
├── index.html                  ← preview navigator (sab pages ke links)
├── css/base.css                ← tokens + atoms (design system, EDIT MAT KARO)
├── fonts/                      ← Inter + JetBrains Mono (local woff2)
├── mobile/                     ← 390px screens (mockup 01–05 se 1:1)
│   ├── 01_terminal.html
│   ├── 02_positions.html
│   ├── 03_history.html
│   ├── 04_alerts.html
│   └── 05_landing.html         ← APK download button (hero + footer)
└── desktop/                    ← 1440px screens (mockup 06/07/08/10 se 1:1)
    ├── 06_desktop_terminal.html
    ├── 07_desktop_positions.html
    ├── 08_desktop_landing.html ← APK button (hero CTA + footer)
    └── 10_desktop_history.html
```

Har page self-contained hai: sirf `../css/base.css` + `<style>` block (page-specific). Koi JS dependency nahi — `charts.js` deliberately **remove** kiya gaya (wo fake candles/sparklines banata tha).

---

## 2. TEEN CONVENTIONS (sirf ye 3 cheezein seekhni hain)

### 2.1 `data-slot` — single value
```html
<div class="v num" data-slot="account.equity">--</div>
```
JS me value daalo:
```js
document.querySelector('[data-slot="account.equity"]').textContent = '$12,847.32';
```
Default hamesha `--` hai. Backend down = `--` dikhta rahega. **Ye honesty test hai.**

### 2.2 `data-list` + `<template>` — repeating rows (positions/trades/alerts)
Har list ka structure:
```html
<div data-list="positions">
  <template data-template="position-row"> ...ek row ka skeleton, data-field tags... </template>
  <div class="empty" data-empty>NO OPEN POSITIONS</div>
</div>
```
Ready-made builder (apni app.js me paste karo):
```js
function renderList(listName, items, fill) {
  const box = document.querySelector(`[data-list="${listName}"]`);
  if (!box) return;
  box.querySelectorAll('[data-field]').length && // purane rows (template ke ilawa) hatao
    box.querySelectorAll(':scope > :not(template):not([data-empty])').forEach(n => n.remove());
  const tpl = box.querySelector('template');
  const empty = box.querySelector('[data-empty]');
  if (!items || !items.length) { empty && empty.classList.remove('hidden'); return; }
  empty && empty.classList.add('hidden');
  items.forEach(it => {
    const row = tpl.content.firstElementChild.cloneNode(true);
    fill(row, it);            // <- tumhara fill function neeche
    box.appendChild(row);
  });
}
```
Fill function example (positions ke liye):
```js
renderList('positions', data.positions, (row, p) => {
  row.querySelector('[data-field="symbol"]').textContent = p.symbol;
  row.querySelector('[data-field="side"]').textContent = p.side;              // LONG/SHORT
  row.querySelector('[data-field="side"]').className = 'badge ' + p.side.toLowerCase(); // long/short
  row.querySelector('[data-field="leverage"]').textContent = p.leverage + 'x';
  row.querySelector('[data-field="entry"]').textContent = fmtUsd(p.entry);
  row.querySelector('[data-field="mark"]').textContent = fmtUsd(p.markPrice);
  row.querySelector('[data-field="lanePct"]').style.left = lanePercent(p) + '%'; // SL→TP 0–100
  row.querySelector('[data-field="pnlNet"]').textContent = fmtSigned(p.pnlNet);  // NET AFTER FEES
  row.querySelector('[data-field="pnlNet"]').classList.add(p.pnlNet >= 0 ? 'up' : 'down');
});
```

### 2.3 Color classes — JS lagayega, HTML me nahi hain
Kisi bhi PnL/change value pe sign aane ke baad:
```js
el.classList.add(v >= 0 ? 'up' : 'down');   // .up = #0ECB81, .down = #F6465D
```
Badges: `badge.long` / `badge.short` / `badge.tp` / `badge.sl` / `badge.manual` — trade data ke hisaab se className set karo. Default HTML me sab `manual` (neutral gray) hai, taake bina data ke kuch bhi green/red jhoot na dikhe.

---

## 3. PAGE → SLOT MAP

### mobile/01_terminal.html
| data-slot | Kya bharna hai | Source (example) |
|---|---|---|
| `engine.status` | text `ENGINE LIVE`/`ENGINE OFFLINE` + class `pill live`/`pill off` | engine heartbeat |
| `engine.env` | `TESTNET` / `MAINNET` | config |
| `engine.uptime` | `UPTIME 14H 22M` | process start time |
| `account.equity` | `$12,847.32` format | getAccount().equity |
| `account.changePct24h` | `+2.74% TODAY` (+ class up/down chip pe) | equity - equity24hAgo |
| `account.changeAbs24h` | `+$342.18` | same |
| `account.available` / `account.marginUsed` / `account.openRiskPct` | USD / USD / `1.8%` | getAccount() |
| `mkt.0..3.symbol/price/changePct` | watchlist top 4 | ticker API |
| `chart.symbol` / `chart.leverage` / `chart.price` / `chart.changePct` | chart header | klines + config |
| `signal.tf` / `signal.bias` / `signal.crossInfo` / `signal.strengthPct` | EMA trend card | strategy output |
| `engine.slotInfo` | `3 SLOTS · 20x CAP` | config |

### mobile/02_positions.html
| data-slot | Kya | Source |
|---|---|---|
| `positions.unrealizedPnl` | total uPnL NET | getPositions() sum |
| `positions.roeMargin` | `+3.46% ROE · MARGIN $4,607.22` | same |
| `positions.riskLabel` | `RISK: MODERATE` + chip class | risk calc |
| `positions.riskPct` + `positions.riskBar` | `62%` + `style.width='62%'` | risk calc |
| list `positions` (template fields) | symbol/side/leverage/duration/entry/mark/liqEst/sl/tp/lanePct/pnlNet/roe | getPositions() |
| `session.winRate` / `session.tradesToday` / `session.streak` | session stats | history calc |

### mobile/03_history.html
| data-slot | Kya | Source |
|---|---|---|
| `history.winRate` | `64%` (ring JS se draw — §5) | closed trades |
| `history.netPnl30d` | **NET after fees** 30D | getClosedTrades() |
| `history.wl` | `95W · 53L FILLED TRADES` | counts |
| `history.profitFactor` / `history.maxDd` | PF / max DD | calc |
| `history.totalTrades` / `history.avgHold` / `history.bestTrade` | statrow | calc |
| `history.cumPnl` | cumulative NET (range ke hisaab se) | series |
| list `trades` | reason/symbol/sideLev/entryExit/pnlNet/duration | getClosedTrades() |

### mobile/04_alerts.html
| item | Kya |
|---|---|
| list `alerts` + `alert-day` | day divider optional; rows: ico/title/desc/time/unread |
| icon rule | SIGNAL→`aico gold` bolt · FILL→`aico up` check · RISK→`aico warn` triangle · SYSTEM→`aico dim` |

### mobile/05_landing.html + desktop/08_desktop_landing.html
| data-slot | Kya |
|---|---|
| `landing.engineStatus` | `24/7 CLOUD ENGINE · LIVE` + class pill live/off |
| `stats.tradesExecuted` / `stats.uptimePct` / `stats.signalLatency` | **sirf verified real data** — nahi hai to `--` rehne do |
| `ticker.0..5.symbol/price/changePct` | watchlist (change pe class `u`/`d`) |
| `engine.strategy` / `engine.slots` / `engine.lastSignal` / `pnl.realized24hNet` | terminal `<pre>` lines |
| `pnl.todayPct` | hero float chip (desktop) |
| **`apk.href` (3 jagah)** | `<a href="app-release.apk" download>` — real path lagao (§7) |

### desktop/06_desktop_terminal.html
| data-slot | Kya |
|---|---|
| sidebar: `engine.status`, `engine.version`, `engine.uptimeEnv`, `alerts.unread` (count, `hidden` hatao) | |
| topbar: `engine.env`, `conn.status` (pill live/off), `user.initial` | |
| statrow: `account.equity`, `account.change24h`, `positions.unrealizedPnl`, `positions.roeSlots`, `account.marginUsed`, `account.marginAllocPct`, `account.openRiskPct`, `engine.riskGuard` | |
| chart: `chart.*` + `data-chart="klines"` shell (§6) | |
| signal: `signal.*`, `fees.today` (`$4.82 TAKER / $2.41 MAKER`) | |
| list `slotQueue` | label/state/dot — ACTIVE→dot `var(--up)`, SCANNING→`var(--gold)` + `animation:pulse 1.6s infinite` |
| list `recentAlerts` | title/desc/time |
| list `positions` + `positions.openCount` | table rows (g1 grid) |

### desktop/07_desktop_positions.html
| data-slot | Kya |
|---|---|
| statrow: `positions.unrealizedPnl`, `positions.roeAll`, `account.marginUsed`, `account.marginInfo`, `positions.riskPct`+`positions.riskBar`, `session.winRate`, `session.summary` | |
| list `positions` (same fields as 06 + duration) | |
| list `closedTrades` | reason/symbol/sideLev/entryExit/duration/pnlNet |
| `history.cumPnl` + `data-chart="pnl-curve"` | |

### desktop/10_desktop_history.html
| data-slot | Kya | Source |
|---|---|---|
| `history.grossPnlToday` + `history.todaySub` | GROSS realized today | getClosedTrades(today) |
| `history.feesToday` + `history.feesSplit` | total fees + `TAKER $-- · MAKER $--` | fills ka commission sum |
| **`history.netPnlToday`** | **GROSS − FEES. Ye honesty ka hero hai** | calc |
| `history.netNote` | context (e.g. `FEES > PNL — VOLUME TOO HIGH`) ya `--` | rule-based |
| `history.exitTop` + `history.exitBreakdown` | exit reason stats | counts |
| list `closedTrades` + `hist-day` divider | time/date/symbol/side/sizeLev/entry/exit/pnlNet/pnlPct/reason | getClosedTrades() |
| tfoot: `history.todayTrades`, `history.grossPnl`, `history.fees`, `history.netPnl` | footer strip (GROSS/FEES/NET alag alag — milana MANA hai) | |
| `history.xr.*` (manual/tp/sl/flip + *N counts) | bar `style.width` + count | |
| `history.exitAuditNote` | derived note — warna `hidden` | |

---

## 4. FORMATTERS (consistent rakhna)

```js
const fmtUsd    = v => (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtSigned = v => (v >= 0 ? '+$' : '-$') + Math.abs(v).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtPct    = v => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(2) + '%';
```

## 5. RING / DONUT ARC (win rate, signal strength)

`data-slot="signal.strengthPct"` wale `.ring` / `.dwrap` pe JS se SVG arc draw karo:
```js
function drawRing(el, pct, color = '#F0B90B') {
  el.querySelector('svg')?.remove();
  const r = el.clientWidth / 2, size = r * 2, sw = 3, rad = r - sw / 2, c = 2 * Math.PI * rad;
  el.insertAdjacentHTML('afterbegin',
    `<svg width="${size}" height="${size}" style="position:absolute;inset:0" viewBox="0 0 ${size} ${size}">
       <circle cx="${r}" cy="${r}" r="${rad}" fill="none" stroke="${color}" stroke-width="${sw}"
         stroke-linecap="round" stroke-dasharray="${c * pct / 100} ${c}" transform="rotate(-90 ${r} ${r})"/></svg>`);
  el.querySelector('b').textContent = pct + '%';
}
```
(Base.css me empty gray track pehle se hai — data aane pe sirf arc overlay hota hai.)

## 6. CHART (`data-chart` shells)

- `data-chart="klines"` → candlestick + EMA 8/13/21/55 overlay (colors: `#F0B90B #4EA8FF #9F7BFF #8D97A5`), volume neeche.
- `data-chart="pnl-curve"` → cumulative NET PnL area (color `#0ECB81`).
- Koi bhi library chalegi (lightweight-charts recommended) — shell div ke andar canvas/svg render karo, `.cempty` span delete kar dena.
- **Sirf real klines/closed trades se.** Fake/seeded candles grok-module bhi nahi.

## 7. APK DOWNLOAD (already added — bas path lagana)

Mobile `05_landing.html`: hero ke neeche full-width gold-outline button + footer link.
Desktop `08_desktop_landing.html`: hero CTA row (3rd button) + footer SUPPORT link.

```html
<a class="btn btn-apk" href="app-release.apk" download data-slot="apk.href">…DOWNLOAD ANDROID APP…</a>
```
Kaam: apna signed APK deploy karo (e.g. Flask: `static/app/weexionic.apk`) aur teeno jagah `href` replace karo. `apk.meta` slot me `v1.0.0 · 18 MB` jaisa text daal sakte ho.

## 8. HONESTY ACCEPTANCE TEST (har deploy se pehle)

1. Backend **band** karke har page kholo → har number `--`, har list empty state, engine pill `OFFLINE`. Koi green/red profit kahin nahi dikhta.
2. Ye greps 0 hits dene chahiye: `$12,847` · `+$159` · `48,200` · `99.98` · `42MS` · `68,420` · `+$342` · `BTCUSDT` (static HTML me — runtime DOM me allowed).
3. PnL display = `exchange fills − fees`. Kabhi bhi mark-price estimate nahi (audit F-01).
4. GROSS aur FEES aur NET alag dikhana — mila ke sirf GROSS dikhana = fraud. (Tumhare live site pe yehi hua tha: gross +$2.69 dikha, fees $6.41 chhupi, net −$3.72.)

## 9. DESIGN TOKENS (base.css me already set)

`bg #0A0C10` · `card #131922/#151B24` · `border #1D2530` · `gold #F0B90B` · `up #0ECB81` · `down #F6465D` · `text #EDF0F4/#8D97A5/#5B6472` · Inter 400–800 + JetBrains Mono (`.num` = tabular figures) · radius 18px cards / 14px buttons.

Colors change karne ho to sirf `:root` variables chhedo — pages khud sync ho jayenge.
