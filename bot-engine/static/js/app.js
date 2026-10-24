/* ============================================
   Binance Futures Bot - Frontend Logic (v2)
   - Multi-coin support
   - Amount mode: fixed USDT or % of wallet
   - Real chart with historical candles
   - Error-resistant
   ============================================ */

// ===== State =====
let chart = null;
let candleSeries = null;
let ema8Series = null;
let ema13Series = null;
let ema21Series = null;
let ema55Series = null;
let isRunning = false;
let socket = null;

// Multi-coin state
let coins = [];              // list of symbol strings
let activeSymbol = null;     // currently displayed symbol
let signalsBySymbol = {};    // {BTCUSDT: 'BUY', ...}
let indicatorsBySymbol = {}; // latest indicators per symbol
let positionsBySymbol = {};  // latest position per symbol
let chartDataBySymbol = {};  // latest chart_data per symbol

// ===== DOM Helpers =====
const $ = (id) => document.getElementById(id);

function log(level, msg) {
    const logs = $('logs');
    if (!logs) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg">${msg}</span>`;
    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight;
    while (logs.children.length > 500) logs.removeChild(logs.firstChild);
}

function updateSlot(name, value, cls = null) {
    document.querySelectorAll(`[data-slot="${name}"]`).forEach(el => {
        if (value !== undefined && value !== null) el.textContent = value;
        if (cls) {
            el.classList.remove('up', 'down', 'gold', 'live', 'off', 'running', 'amber');
            const tokens = String(cls).split(/\s+/).filter(Boolean);
            if (tokens.length) el.classList.add(...tokens);
        }
    });
}

const fmtUsd    = v => (v == null || isNaN(v)) ? '--' : (v < 0 ? '-$' : '$') + Math.abs(Number(v)).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtSigned = v => (v == null || isNaN(v)) ? '--' : (v >= 0 ? '+$' : '-$') + Math.abs(Number(v)).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtPct    = v => (v == null || isNaN(v)) ? '--%' : (v >= 0 ? '+' : '−') + Math.abs(Number(v)).toFixed(2) + '%';

function drawRing(el, pct, color = '#F0B90B') {
    if (!el) return;
    el.querySelector('svg')?.remove();
    const r = (el.clientWidth || 44) / 2, size = r * 2, sw = 3, rad = r - sw / 2, c = 2 * Math.PI * rad;
    const safePct = Math.min(100, Math.max(0, Math.round(pct || 0)));
    el.insertAdjacentHTML('afterbegin',
        `<svg width="${size}" height="${size}" style="position:absolute;inset:0;pointer-events:none;" viewBox="0 0 ${size} ${size}">
           <circle cx="${r}" cy="${r}" r="${rad}" fill="none" stroke="${color}" stroke-width="${sw}"
             stroke-linecap="round" stroke-dasharray="${c * safePct / 100} ${c}" transform="rotate(-90 ${r} ${r})"/></svg>`);
    const b = el.querySelector('b');
    if (b) b.textContent = safePct + '%';
}

function renderSlotQueue() {
    const container = $('slotQueueList');
    if (!container) return;
    const symList = coins.length > 0 ? coins.slice(0, 3) : ['BTCUSDT'];
    let html = '';
    symList.forEach(sym => {
        const p = positionsBySymbol[sym];
        const hasPos = p && p.side && p.side !== 'NONE';
        const dotColor = hasPos ? 'var(--up)' : (isRunning ? 'var(--gold)' : 'var(--t3)');
        const pulseStyle = (isRunning && !hasPos) ? 'animation:pulse 1.6s infinite;' : '';
        const stateText = hasPos ? `${p.side} ACTIVE` : (isRunning ? 'SCANNING' : 'IDLE');
        html += `
        <div class="sq">
            <i class="dot" style="background:${dotColor}; ${pulseStyle}"></i>
            <span>${sym}</span>
            <span class="st8">${stateText}</span>
        </div>`;
    });
    container.innerHTML = html;
}

function setBotRunning(running) {
    isRunning = running;
    const startBtn = $('startBtn');
    const startBtnText = $('startBtnText');
    const stopBtn = $('stopBtn');
    if (startBtn) {
        if (running) {
            startBtn.className = 'btn btn-ghost red';
            if (startBtnText) startBtnText.textContent = 'HALT ENGINE';
            startBtn.onclick = stopBot;
        } else {
            startBtn.className = 'btn btn-gold';
            if (startBtnText) startBtnText.textContent = 'START ENGINE';
            startBtn.onclick = startBot;
        }
    }
    if (stopBtn) stopBtn.disabled = !running;
    const mobStart = $('mobQuickStartBtn');
    const mobStop = $('mobQuickStopBtn');
    if (mobStart) {
        mobStart.disabled = running;
        mobStart.onclick = startBot;
    }
    if (mobStop) {
        mobStop.disabled = !running;
        mobStop.onclick = stopBot;
    }
    const pill = $('botStatusPill');
    const text = $('botStatusText');
    if (pill && text) {
        if (running) {
            pill.className = 'pill live';
            text.textContent = 'RUNNING';
        } else {
            pill.className = 'pill off';
            text.textContent = 'STOPPED';
        }
    }
    const sbPill = $('sidebarStatusPill');
    if (sbPill) {
        if (running) {
            sbPill.className = 'pill live';
            sbPill.innerHTML = '<i class="dot"></i>RUNNING';
        } else {
            sbPill.className = 'pill off';
            sbPill.innerHTML = '<i class="dot"></i>STOPPED';
        }
    }
    updateSlot('engine.status', running ? 'ENGINE LIVE' : 'ENGINE OFFLINE', running ? 'live' : 'off');
    updateSlot('conn.status', running ? 'ONLINE' : 'OFFLINE', running ? 'live' : 'off');
    renderSlotQueue();
}

function fmt(n) {
    if (n == null || isNaN(n)) return '--';
    if (n >= 1000) return Number(n).toFixed(2);
    if (n >= 1) return Number(n).toFixed(4);
    return Number(n).toFixed(6);
}

// ===== EMA Stack Visualizer =====
function renderEMAStack(data) {
    const container = $('emaStackList');
    if (!container) return;
    if (!data || !data.ema_8 || !data.ema_55) {
        container.innerHTML = '<div class="ema-stack-empty">Waiting for data...</div>';
        return;
    }
    // Build array and sort by value DESC (top = highest)
    const emas = [
        { name: 'EMA 8',  value: data.ema_8,  cls: 'ema-8'  },
        { name: 'EMA 13', value: data.ema_13, cls: 'ema-13' },
        { name: 'EMA 21', value: data.ema_21, cls: 'ema-21' },
        { name: 'EMA 55', value: data.ema_55, cls: 'ema-55' },
    ];
    emas.sort((a, b) => b.value - a.value);

    container.innerHTML = '';
    emas.forEach((ema, idx) => {
        const posLabel = idx === 0 ? 'TOP' : idx === emas.length - 1 ? 'BOTTOM' : '';
        const posClass = idx === 0 ? 'top' : idx === emas.length - 1 ? 'bottom' : '';
        const row = document.createElement('div');
        row.className = `ema-stack-row ${ema.cls} ${posClass}`;
        row.innerHTML = `
            <span class="pos-num">${idx + 1}</span>
            <span class="ema-name">${ema.name}</span>
            ${posLabel ? `<span class="pos-label">${posLabel}</span>` : ''}
            <span class="ema-value">$${fmt(ema.value)}</span>
        `;
        container.appendChild(row);
    });

    // Highlight the EMA55 rule
    const ruleEl = $('emaStackRule');
    if (ruleEl) {
        const ema55Idx = emas.findIndex(e => e.name === 'EMA 55');
        if (ema55Idx === 0) {
            ruleEl.style.color = '#f6465d';
            ruleEl.style.borderColor = 'rgba(246, 70, 93, 0.5)';
            ruleEl.style.background = 'rgba(246, 70, 93, 0.08)';
            ruleEl.textContent = 'EMA55 is at TOP → SELL signal fires → Bot opens SHORT';
        } else if (ema55Idx === emas.length - 1) {
            ruleEl.style.color = '#0ecb81';
            ruleEl.style.borderColor = 'rgba(14, 203, 129, 0.5)';
            ruleEl.style.background = 'rgba(14, 203, 129, 0.08)';
            ruleEl.textContent = 'EMA55 is at BOTTOM → BUY signal fires → Bot opens LONG';
        } else {
            ruleEl.style.color = '#f0b90b';
            ruleEl.style.borderColor = 'rgba(240, 185, 11, 0.3)';
            ruleEl.style.background = 'rgba(240, 185, 11, 0.08)';
            ruleEl.textContent = 'EMA55 in middle → HOLD (no action). Strategy: EMA55 at BOTTOM = BUY | EMA55 at TOP = SELL';
        }
    }
}

// ===== HTTP Fallback for Chart Data (when socket disconnects) =====
async function fetchChartData(symbol) {
    if (!symbol || !isRunning) return;
    try {
        const r = await fetch(`/api/test_chart?symbol=${symbol}`);
        const data = await r.json();
        if (data.success && data.candles && data.candles.length > 0) {
            chartDataBySymbol[symbol] = { symbol, candles: data.candles, emas: {} };
            if (symbol === activeSymbol) {
                renderChartForSymbol(symbol);
            }
        }
    } catch (e) {
        // Silent fail
    }
}

// ===== TradingView-style Drawing Canvas Overlay System =====
let currentDrawingTool = 'cursor'; // 'cursor' | 'trendline' | 'horizontal' | 'rectangle' | 'text'
let activeDrawingColor = '#f0b90b';
let drawings = [];
let isDrawing = false;
let drawStartPoint = null;
let drawCurrentPoint = null;
let selectedDrawingId = null;
let drawingCanvas = null;
let drawingCtx = null;

function hexToRgba(hex, alpha) {
    let c = (hex || '#f0b90b').replace('#', '');
    if (c.length === 3) c = c.split('').map(x => x + x).join('');
    const num = parseInt(c, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
}

function getDrawingsStorageKey() {
    const sym = activeSymbol || 'DEFAULT';
    const tf = $('timeframe')?.value || '1m';
    const user = window._currentUserId || localStorage.getItem('current_user') || 'user';
    return `tv_drawings_${user}_${sym}_${tf}`;
}

function saveDrawingsForActiveSymbol() {
    try {
        const key = getDrawingsStorageKey();
        localStorage.setItem(key, JSON.stringify(drawings));
    } catch (e) {
        console.warn('saveDrawings error:', e);
    }
}

function loadDrawingsForActiveSymbol() {
    try {
        const key = getDrawingsStorageKey();
        const raw = localStorage.getItem(key);
        drawings = raw ? JSON.parse(raw) : [];
        selectedDrawingId = null;
        hideDeletePopover();
    } catch (e) {
        drawings = [];
    }
    redrawCanvas();
}

function chartPointToPixel(point) {
    if (!chart || !candleSeries || !point) return null;
    let x = null;
    if (point.time != null && chart.timeScale()) {
        try { x = chart.timeScale().timeToCoordinate(point.time); } catch (e) {}
    }
    if (x === null && point.logical != null && chart.timeScale()) {
        try { x = chart.timeScale().logicalToCoordinate(point.logical); } catch (e) {}
    }
    if (x === null && point.fallbackX != null) {
        x = point.fallbackX;
    }

    let y = null;
    if (point.price != null && candleSeries) {
        try { y = candleSeries.priceToCoordinate(point.price); } catch (e) {}
    }
    if (y === null && point.fallbackY != null) {
        y = point.fallbackY;
    }

    return { x, y };
}

function pixelToChartPoint(x, y) {
    if (!chart || !candleSeries) return null;
    let time = null;
    let logical = null;
    try {
        time = chart.timeScale().coordinateToTime(x);
        logical = chart.timeScale().coordinateToLogical(x);
    } catch (e) {}
    let price = null;
    try {
        price = candleSeries.coordinateToPrice(y);
    } catch (e) {}

    return {
        time: time || Math.floor(Date.now() / 1000),
        logical: logical,
        price: price || 0,
        fallbackX: x,
        fallbackY: y,
    };
}

function distToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) return Math.hypot(px - x1, py - y1);
    let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    const projX = x1 + t * dx;
    const projY = y1 + t * dy;
    return Math.hypot(px - projX, py - projY);
}

function findHitDrawing(clickX, clickY) {
    if (!drawingCanvas) return null;
    const w = drawingCanvas.width;
    const threshold = 10;

    for (let i = drawings.length - 1; i >= 0; i--) {
        const d = drawings[i];
        if (d.type === 'trendline') {
            const p1 = chartPointToPixel(d.p1);
            const p2 = chartPointToPixel(d.p2);
            if (p1 && p2 && p1.x != null && p1.y != null && p2.x != null && p2.y != null) {
                if (distToSegment(clickX, clickY, p1.x, p1.y, p2.x, p2.y) <= threshold) {
                    return d;
                }
            }
        } else if (d.type === 'horizontal') {
            const py = candleSeries ? candleSeries.priceToCoordinate(d.price) : null;
            if (py != null && Math.abs(clickY - py) <= threshold) {
                return d;
            }
        } else if (d.type === 'rectangle') {
            const p1 = chartPointToPixel(d.p1);
            const p2 = chartPointToPixel(d.p2);
            if (p1 && p2 && p1.x != null && p1.y != null && p2.x != null && p2.y != null) {
                const minX = Math.min(p1.x, p2.x) - 4;
                const maxX = Math.max(p1.x, p2.x) + 4;
                const minY = Math.min(p1.y, p2.y) - 4;
                const maxY = Math.max(p1.y, p2.y) + 4;
                if (clickX >= minX && clickX <= maxX && clickY >= minY && clickY <= maxY) {
                    return d;
                }
            }
        } else if (d.type === 'text') {
            const pt = chartPointToPixel(d.point);
            if (pt && pt.x != null && pt.y != null) {
                if (Math.hypot(clickX - pt.x, clickY - pt.y) <= 30) {
                    return d;
                }
            }
        }
    }
    return null;
}

function showDeletePopover(x, y, id) {
    selectedDrawingId = id;
    const pop = $('drawingContextMenu');
    if (!pop) return;
    pop.style.left = `${Math.max(60, Math.min(x, (drawingCanvas?.width || 600) - 60))}px`;
    pop.style.top = `${Math.max(30, y)}px`;
    pop.style.display = 'block';
    redrawCanvas();
}

function hideDeletePopover() {
    const pop = $('drawingContextMenu');
    if (pop) pop.style.display = 'none';
}

function deleteSelectedDrawing() {
    if (!selectedDrawingId) return;
    drawings = drawings.filter(d => d.id !== selectedDrawingId);
    selectedDrawingId = null;
    hideDeletePopover();
    saveDrawingsForActiveSymbol();
    redrawCanvas();
}

function setDrawingTool(toolName) {
    currentDrawingTool = toolName;
    document.querySelectorAll('.draw-btn[data-tool]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tool === toolName);
    });
    hideDeletePopover();
    selectedDrawingId = null;

    if (!drawingCanvas) return;
    if (toolName === 'cursor') {
        drawingCanvas.classList.remove('interactive-mode');
        drawingCanvas.style.pointerEvents = 'none';
    } else {
        drawingCanvas.classList.add('interactive-mode');
        drawingCanvas.style.pointerEvents = 'auto';
    }
    redrawCanvas();
}

function redrawCanvas() {
    if (!drawingCanvas || !drawingCtx) return;
    const w = drawingCanvas.width;
    const h = drawingCanvas.height;
    drawingCtx.clearRect(0, 0, w, h);

    drawings.forEach((d) => {
        const isSelected = (d.id === selectedDrawingId);
        drawingCtx.save();
        drawingCtx.strokeStyle = d.color || '#f0b90b';
        drawingCtx.fillStyle = d.color || '#f0b90b';
        drawingCtx.lineWidth = isSelected ? 3 : 2;

        if (d.type === 'trendline') {
            const p1 = chartPointToPixel(d.p1);
            const p2 = chartPointToPixel(d.p2);
            if (p1 && p2 && p1.x != null && p1.y != null && p2.x != null && p2.y != null) {
                drawingCtx.beginPath();
                drawingCtx.moveTo(p1.x, p1.y);
                drawingCtx.lineTo(p2.x, p2.y);
                drawingCtx.stroke();

                if (isSelected) {
                    drawingCtx.fillStyle = '#ffffff';
                    [p1, p2].forEach(p => {
                        drawingCtx.beginPath();
                        drawingCtx.arc(p.x, p.y, 4, 0, Math.PI * 2);
                        drawingCtx.fill();
                        drawingCtx.stroke();
                    });
                }
            }
        } else if (d.type === 'horizontal') {
            const py = candleSeries ? candleSeries.priceToCoordinate(d.price) : null;
            if (py != null) {
                drawingCtx.beginPath();
                drawingCtx.setLineDash([5, 4]);
                drawingCtx.moveTo(0, py);
                drawingCtx.lineTo(w, py);
                drawingCtx.stroke();
                drawingCtx.setLineDash([]);

                const badgeText = fmt(d.price);
                drawingCtx.fillStyle = d.color || '#f0b90b';
                drawingCtx.fillRect(w - 75, py - 9, 75, 18);
                drawingCtx.fillStyle = '#0b0e11';
                drawingCtx.font = 'bold 10px JetBrains Mono, monospace';
                drawingCtx.fillText(badgeText, w - 70, py + 4);
            }
        } else if (d.type === 'rectangle') {
            const p1 = chartPointToPixel(d.p1);
            const p2 = chartPointToPixel(d.p2);
            if (p1 && p2 && p1.x != null && p1.y != null && p2.x != null && p2.y != null) {
                const rx = Math.min(p1.x, p2.x);
                const ry = Math.min(p1.y, p2.y);
                const rw = Math.abs(p2.x - p1.x);
                const rh = Math.abs(p2.y - p1.y);

                drawingCtx.fillStyle = hexToRgba(d.color || '#f0b90b', 0.16);
                drawingCtx.fillRect(rx, ry, rw, rh);
                drawingCtx.strokeRect(rx, ry, rw, rh);

                if (isSelected) {
                    drawingCtx.fillStyle = '#ffffff';
                    [[rx, ry], [rx + rw, ry], [rx, ry + rh], [rx + rw, ry + rh]].forEach(([hx, hy]) => {
                        drawingCtx.beginPath();
                        drawingCtx.arc(hx, hy, 4, 0, Math.PI * 2);
                        drawingCtx.fill();
                        drawingCtx.stroke();
                    });
                }
            }
        } else if (d.type === 'text') {
            const pt = chartPointToPixel(d.point);
            if (pt && pt.x != null && pt.y != null) {
                drawingCtx.font = 'bold 12px Inter, sans-serif';
                const metrics = drawingCtx.measureText(d.text);
                const bgW = metrics.width + 14;
                const bgH = 22;
                drawingCtx.fillStyle = 'rgba(11, 14, 22, 0.88)';
                drawingCtx.fillRect(pt.x, pt.y - 16, bgW, bgH);
                drawingCtx.strokeStyle = d.color || '#f0b90b';
                drawingCtx.strokeRect(pt.x, pt.y - 16, bgW, bgH);

                drawingCtx.fillStyle = d.color || '#f0b90b';
                drawingCtx.fillText(d.text, pt.x + 7, pt.y);
            }
        }
        drawingCtx.restore();
    });

    // Preview during dragging
    if (isDrawing && drawStartPoint && drawCurrentPoint) {
        drawingCtx.save();
        drawingCtx.strokeStyle = activeDrawingColor;
        drawingCtx.fillStyle = activeDrawingColor;
        drawingCtx.lineWidth = 2;

        if (currentDrawingTool === 'trendline') {
            drawingCtx.beginPath();
            drawingCtx.moveTo(drawStartPoint.fallbackX, drawStartPoint.fallbackY);
            drawingCtx.lineTo(drawCurrentPoint.fallbackX, drawCurrentPoint.fallbackY);
            drawingCtx.stroke();
        } else if (currentDrawingTool === 'rectangle') {
            const rx = Math.min(drawStartPoint.fallbackX, drawCurrentPoint.fallbackX);
            const ry = Math.min(drawStartPoint.fallbackY, drawCurrentPoint.fallbackY);
            const rw = Math.abs(drawCurrentPoint.fallbackX - drawStartPoint.fallbackX);
            const rh = Math.abs(drawCurrentPoint.fallbackY - drawStartPoint.fallbackY);
            drawingCtx.fillStyle = hexToRgba(activeDrawingColor, 0.18);
            drawingCtx.fillRect(rx, ry, rw, rh);
            drawingCtx.strokeRect(rx, ry, rw, rh);
        }
        drawingCtx.restore();
    }
}

function initDrawingSystem() {
    drawingCanvas = $('drawingCanvas');
    if (!drawingCanvas) return;
    drawingCtx = drawingCanvas.getContext('2d');
    const container = $('chartCanvasContainer') || $('chart');

    function syncCanvasSize() {
        if (!container || !drawingCanvas) return;
        const w = container.clientWidth || 800;
        const h = container.clientHeight || 500;
        if (drawingCanvas.width !== w || drawingCanvas.height !== h) {
            drawingCanvas.width = w;
            drawingCanvas.height = h;
            redrawCanvas();
        }
    }

    syncCanvasSize();
    const resizeObs = new ResizeObserver(() => syncCanvasSize());
    resizeObs.observe(container);

    // Sync when chart timescale pans/zooms
    if (chart && chart.timeScale()) {
        try {
            chart.timeScale().subscribeVisibleTimeRangeChange(() => requestAnimationFrame(redrawCanvas));
            chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(redrawCanvas));
        } catch (e) {}
    }

    // Toolbar buttons
    document.querySelectorAll('.draw-btn[data-tool]').forEach(btn => {
        btn.addEventListener('click', () => setDrawingTool(btn.dataset.tool));
    });

    const colorInp = $('drawColorInput');
    if (colorInp) {
        colorInp.addEventListener('input', (e) => {
            activeDrawingColor = e.target.value;
            if (selectedDrawingId) {
                const target = drawings.find(d => d.id === selectedDrawingId);
                if (target) { target.color = activeDrawingColor; saveDrawingsForActiveSymbol(); redrawCanvas(); }
            }
        });
    }

    const clearBtn = $('clearDrawingsBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (drawings.length === 0) return;
            if (confirm('Clear all drawings on this chart?')) {
                drawings = [];
                selectedDrawingId = null;
                hideDeletePopover();
                saveDrawingsForActiveSymbol();
                redrawCanvas();
            }
        });
    }

    const delItemBtn = $('btnDeleteSelectedDrawing');
    if (delItemBtn) {
        delItemBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteSelectedDrawing();
        });
    }

    // Keyboard Delete shortcut
    window.addEventListener('keydown', (e) => {
        if ((e.key === 'Delete' || e.key === 'Backspace') && selectedDrawingId) {
            if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
            deleteSelectedDrawing();
        }
    });

    // Pointer mode smart hover
    container.addEventListener('mousemove', (e) => {
        if (currentDrawingTool !== 'cursor') return;
        const rect = drawingCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const hit = findHitDrawing(x, y);
        if (hit) {
            drawingCanvas.style.pointerEvents = 'auto';
            drawingCanvas.style.cursor = 'pointer';
        } else if (!selectedDrawingId) {
            drawingCanvas.style.pointerEvents = 'none';
            drawingCanvas.style.cursor = 'default';
        }
    });

    // Canvas Mouse interaction
    drawingCanvas.addEventListener('mousedown', (e) => {
        const rect = drawingCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        if (currentDrawingTool === 'cursor') {
            const hit = findHitDrawing(x, y);
            if (hit) {
                showDeletePopover(x, y, hit.id);
            } else {
                selectedDrawingId = null;
                hideDeletePopover();
                drawingCanvas.style.pointerEvents = 'none';
                redrawCanvas();
            }
            return;
        }

        if (currentDrawingTool === 'horizontal') {
            const pt = pixelToChartPoint(x, y);
            if (pt) {
                drawings.push({
                    id: 'draw_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                    type: 'horizontal',
                    color: activeDrawingColor,
                    price: pt.price,
                });
                saveDrawingsForActiveSymbol();
                setDrawingTool('cursor');
            }
            return;
        }

        if (currentDrawingTool === 'text') {
            const textVal = prompt('Enter chart note text:');
            if (textVal && textVal.trim()) {
                const pt = pixelToChartPoint(x, y);
                if (pt) {
                    drawings.push({
                        id: 'draw_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                        type: 'text',
                        color: activeDrawingColor,
                        point: pt,
                        text: textVal.trim(),
                    });
                    saveDrawingsForActiveSymbol();
                }
            }
            setDrawingTool('cursor');
            return;
        }

        if (currentDrawingTool === 'trendline' || currentDrawingTool === 'rectangle') {
            isDrawing = true;
            drawStartPoint = pixelToChartPoint(x, y);
            drawCurrentPoint = drawStartPoint;
            redrawCanvas();
        }
    });

    drawingCanvas.addEventListener('mousemove', (e) => {
        if (!isDrawing) return;
        const rect = drawingCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        drawCurrentPoint = pixelToChartPoint(x, y);
        redrawCanvas();
    });

    drawingCanvas.addEventListener('mouseup', (e) => {
        if (!isDrawing) return;
        isDrawing = false;
        const rect = drawingCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const endPt = pixelToChartPoint(x, y);

        if (drawStartPoint && endPt) {
            const dist = Math.hypot(endPt.fallbackX - drawStartPoint.fallbackX, endPt.fallbackY - drawStartPoint.fallbackY);
            if (dist > 5) {
                drawings.push({
                    id: 'draw_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                    type: currentDrawingTool,
                    color: activeDrawingColor,
                    p1: drawStartPoint,
                    p2: endPt,
                });
                saveDrawingsForActiveSymbol();
            }
        }
        drawStartPoint = null;
        drawCurrentPoint = null;
        setDrawingTool('cursor');
    });

    loadDrawingsForActiveSymbol();
}

function updateChopIndicatorsUI(data) {
    // Pure EMA strategy active - chop indicators retired
}

// ===== Chart Setup (TradingView style with zoom/pan) =====
function initChart() {
    try {
        if (typeof LightweightCharts === 'undefined') {
            log('warn', 'Chart library load nahi hui.');
            return false;
        }
        const container = $('chart');
        if (!container) return false;

        // Force container height if 0 (CSS issue fix)
        if (container.clientHeight < 100) {
            container.style.height = '500px';
        }

        chart = LightweightCharts.createChart(container, {
            layout: {
                background: { type: 'solid', color: '#0A0C10' },
                textColor: '#8D97A5',
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: 11,
            },
            grid: {
                vertLines: { color: '#141A23' },
                horzLines: { color: '#141A23' },
            },
            timeScale: {
                borderColor: '#1D2530',
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 5,
                barSpacing: 8,
                minBarSpacing: 2,
                fixLeftEdge: false,
                fixRightEdge: false,
            },
            rightPriceScale: {
                borderColor: '#1D2530',
                scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            crosshair: {
                mode: 1,  // Magnet mode
                vertLine: { color: '#F0B90B', width: 1, style: 2, labelBackgroundColor: '#F0B90B' },
                horzLine: { color: '#F0B90B', width: 1, style: 2, labelBackgroundColor: '#F0B90B' },
            },
            // TradingView style interactions
            handleScroll: true,    // Enable panning (drag to move)
            handleScale: true,     // Enable zoom (scroll wheel)
            kineticScroll: true,   // Smooth scrolling
            width: container.clientWidth || 800,
            height: container.clientHeight || 500,
        });

        candleSeries = chart.addCandlestickSeries({
            upColor: '#0ECB81',
            downColor: '#F6465D',
            borderUpColor: '#0ECB81',
            borderDownColor: '#F6465D',
            borderVisible: false,
            wickUpColor: '#0ECB81',
            wickDownColor: '#F6465D',
        });
        ema8Series  = chart.addLineSeries({ color: '#F0B90B', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema13Series = chart.addLineSeries({ color: '#4EA8FF', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema21Series = chart.addLineSeries({ color: '#9F7BFF', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema55Series = chart.addLineSeries({ color: '#8D97A5', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

        const ro = new ResizeObserver(() => {
            if (chart) {
                chart.applyOptions({
                    width: container.clientWidth,
                    height: container.clientHeight || 500
                });
            }
        });
        ro.observe(container);

        try {
            initDrawingSystem();
        } catch (dErr) {
            console.warn('initDrawingSystem err:', dErr);
        }

        log('success', '✅ Chart ready (TradingView style - zoom/pan + drawing tools enabled)');
        return true;
    } catch (e) {
        console.error('Chart init failed:', e);
        log('warn', `Chart init failed: ${e.message}. Bot phir bhi chalega.`);
        return false;
    }
}

function renderChartForSymbol(symbol) {
    if (!chart || !symbol) return;
    const data = chartDataBySymbol[symbol];
    if (!data) return;
    try {
        if (data.candles && data.candles.length > 0) {
            // Sort by time and remove duplicates (LightweightCharts requires this)
            let candles = data.candles.slice().sort((a, b) => a.time - b.time);
            let unique = [];
            let lastTime = 0;
            for (let c of candles) {
                if (c.time > lastTime) {
                    unique.push(c);
                    lastTime = c.time;
                }
            }
            candleSeries.setData(unique);
        }
        if (data.emas) {
            if (data.emas.ema8) {
                let e8 = data.emas.ema8.slice().sort((a, b) => a.time - b.time);
                let u8 = []; let lt = 0;
                for (let c of e8) { if (c.time > lt) { u8.push(c); lt = c.time; } }
                ema8Series.setData(u8);
            }
            if (data.emas.ema13) {
                let e13 = data.emas.ema13.slice().sort((a, b) => a.time - b.time);
                let u13 = []; let lt = 0;
                for (let c of e13) { if (c.time > lt) { u13.push(c); lt = c.time; } }
                ema13Series.setData(u13);
            }
            if (data.emas.ema21) {
                let e21 = data.emas.ema21.slice().sort((a, b) => a.time - b.time);
                let u21 = []; let lt = 0;
                for (let c of e21) { if (c.time > lt) { u21.push(c); lt = c.time; } }
                ema21Series.setData(u21);
            }
            if (data.emas.ema55) {
                let e55 = data.emas.ema55.slice().sort((a, b) => a.time - b.time);
                let u55 = []; let lt = 0;
                for (let c of e55) { if (c.time > lt) { u55.push(c); lt = c.time; } }
                ema55Series.setData(u55);
            }
        }
        chart.timeScale().fitContent();
        requestAnimationFrame(redrawCanvas);
    } catch (e) {
        console.error('Chart render failed:', e);
    }
}

// ===== Socket Setup (failsafe with auto-reconnect) =====
function initSocket() {
    try {
        if (typeof io === 'undefined') {
            log('warn', 'Socket.IO load nahi hui. Status polling se hogi.');
            return false;
        }
        // Stable polling socket through SaaS proxy
        socket = io({
            transports: ['polling'],
            upgrade: false,
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 5000,
            timeout: 25000,
        });

        socket.on('connect', () => {
            if (!window._socketConnectedOnce) {
                log('success', '✅ Socket connected to bot stream');
                window._socketConnectedOnce = true;
            }
            if (activeSymbol && isRunning) {
                fetchChartData(activeSymbol);
            }
        });
        socket.on('disconnect', (reason) => {
            // Only log if explicit server forced disconnect, not normal polling packet renewal
            if (reason === 'io server disconnect') {
                log('warn', `⚠️ Session closed by server. Reconnecting...`);
                socket.connect();
            }
        });
        socket.on('reconnect', (attempt) => {
            // Reconnected cleanly
        });
        socket.on('reconnect_error', (error) => {});
        socket.on('connect_error', (error) => {});

        socket.on('log', (data) => log(data.level || 'info', data.msg));

        socket.on('status', (data) => {
            setBotRunning(!!data.running);
            if (data.message) log('info', data.message);
            if (data.symbols) {
                // update coins from server if running
                if (data.running && data.symbols.length && coins.length === 0) {
                    coins = [...data.symbols];
                    renderCoinChips();
                    renderCoinTabs();
                    if (!activeSymbol && coins.length) selectSymbol(coins[0]);
                    if ($('statCoins')) $('statCoins').textContent = coins.length;
                }
                // Update trades/stats from status or workers
                let totalTrades = data.trades_today != null ? data.trades_today : null;
                if (totalTrades === null && data.workers) {
                    totalTrades = 0;
                    for (const sym in data.workers) {
                        totalTrades += data.workers[sym].trades_today || 0;
                    }
                }
                if (totalTrades !== null && $('statTrades')) $('statTrades').textContent = totalTrades;
            }
        });

        socket.on('indicators', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            indicatorsBySymbol[sym] = data;
            if (data.signal) {
                signalsBySymbol[sym] = data.signal;
                const tab = document.querySelector(`.coin-tab[data-symbol="${sym}"]`);
                if (tab) {
                    tab.classList.remove('signal-buy', 'signal-sell', 'signal-hold');
                    tab.classList.add(`signal-${data.signal.toLowerCase()}`);
                }
            }
            if (sym === activeSymbol) {
                if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
                const mp = data.mark_price;
                if ($('indPrice')) $('indPrice').textContent = (mp && mp > 0) ? `$${fmt(mp)}` : '--';
                if ($('indEma8'))  $('indEma8').textContent  = (data.ema_8 && data.ema_8 > 0)  ? `$${fmt(data.ema_8)}`  : '--';
                if ($('indEma13')) $('indEma13').textContent = (data.ema_13 && data.ema_13 > 0) ? `$${fmt(data.ema_13)}` : '--';
                if ($('indEma21')) $('indEma21').textContent = (data.ema_21 && data.ema_21 > 0) ? `$${fmt(data.ema_21)}` : '--';
                if ($('indEma55')) $('indEma55').textContent = (data.ema_55 && data.ema_55 > 0) ? `$${fmt(data.ema_55)}` : '--';
                renderEMAStack(data);
                updateChopIndicatorsUI(data);

                // Auto-sync signal card with live EMA indicators
                let sig = data.signal || signalsBySymbol[sym];
                if (!sig || sig === 'HOLD') {
                    const e8 = data.ema_8, e13 = data.ema_13, e21 = data.ema_21, e55 = data.ema_55;
                    const sep = data.ema_sep_pct || ((e8 && e55) ? Math.abs(e8 - e55) / e55 * 100 : 0);
                    if (e8 && e13 && e21 && e55 && sep >= 0.15) {
                        if (e8 >= e13 && e13 >= e21 && e21 > e55) sig = 'BUY';
                        else if (e8 <= e13 && e13 <= e21 && e21 < e55) sig = 'SELL';
                        else sig = 'HOLD';
                    } else {
                        sig = 'HOLD';
                    }
                }
                signalsBySymbol[sym] = sig || 'HOLD';
                const el = $('indSignal');
                if (el) {
                    el.textContent = signalsBySymbol[sym];
                    el.className = '';
                    el.classList.add(`signal-${signalsBySymbol[sym].toLowerCase()}`);
                }
            }
        });

        socket.on('chart_data', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            chartDataBySymbol[sym] = data;
            if (sym === activeSymbol) {
                renderChartForSymbol(sym);
            }
        });

        socket.on('signal', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            const prevSignal = signalsBySymbol[sym];
            signalsBySymbol[sym] = data.signal;
            // Only log when signal CHANGES (not every tick - prevents spam)
            if (prevSignal !== data.signal && data.signal !== 'HOLD') {
                log(data.signal === 'BUY' ? 'success' : 'warn',
                    `[${sym}] SIGNAL: ${data.signal} - ${data.reason}`);
            }
            // Update coin tab
            const tab = document.querySelector(`.coin-tab[data-symbol="${sym}"]`);
            if (tab) {
                tab.classList.remove('signal-buy', 'signal-sell', 'signal-hold');
                tab.classList.add(`signal-${data.signal.toLowerCase()}`);
            }
            // Update indicator panel if active
            if (sym === activeSymbol) {
                const el = $('indSignal');
                if (el) {
                    el.textContent = data.signal;
                    el.className = '';
                    el.classList.add(`signal-${data.signal.toLowerCase()}`);
                }
            }
        });

        socket.on('position', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            const prev = positionsBySymbol[sym] || {};
            // If new payload is an open position but missing tp/sl info, retain previous values
            if (data.side && data.side !== 'NONE') {
                if ((data.tp_price === undefined || data.tp_price === 0) && prev.tp_price) {
                    data.tp_price = prev.tp_price;
                }
                if ((data.tp_stage === undefined || data.tp_stage === 0) && prev.tp_stage) {
                    data.tp_stage = prev.tp_stage;
                }
                if ((data.sl_price === undefined || data.sl_price === 0) && prev.sl_price) {
                    data.sl_price = prev.sl_price;
                }
                if (!data.tp_mode && prev.tp_mode) {
                    data.tp_mode = prev.tp_mode;
                }
                if (!data.target_roe && prev.target_roe) {
                    data.target_roe = prev.target_roe;
                }
            }
            positionsBySymbol[sym] = data;
            if (sym === activeSymbol) updatePositionUI(data);
        });

        // Balance event from MonitorThread (works even when bot is STOPPED)
        socket.on('balance', (data) => {
            const bal = data.balance || 0;
            const exchange = (data.exchange || 'binance').toUpperCase();
            const env = data.testnet ? (exchange === 'BINANCE' ? 'TESTNET' : 'DEMO') : 'LIVE';
            if ($('statBalance')) {
                $('statBalance').textContent = `$${Number(bal).toFixed(2)}`;
                $('statBalance').title = `${exchange} ${env} balance`;
            }
        });

        // Real-time Trade History update event
        socket.on('trades_updated', (data) => {
            if (data) {
                if (data.trades) window.tradeHistoryData = data.trades;
                if (data.stats) window.tradeHistoryStats = data.stats;
                if (typeof window.renderTradeHistoryUI === 'function') {
                    window.renderTradeHistoryUI();
                }
            }
        });

        return true;
    } catch (e) {
        console.error('Socket init failed:', e);
        log('warn', `Socket init failed: ${e.message}`);
        return false;
    }
}

function updatePositionUI(data) {
    if ($('positionSymbol')) $('positionSymbol').textContent = data.symbol || '--';
    const posSide = $('posSide');
    if (posSide) {
        posSide.textContent = data.side;
        posSide.className = '';
        if (data.side === 'LONG') posSide.classList.add('pos-side-long');
        else if (data.side === 'SHORT') posSide.classList.add('pos-side-short');
    }
    if ($('posSize')) $('posSize').textContent = Math.abs(data.size || 0).toFixed(4);
    if ($('posEntry')) $('posEntry').textContent = data.entry_price ? `$${fmt(data.entry_price)}` : '--';
    if ($('posMark')) $('posMark').textContent = data.mark_price ? `$${fmt(data.mark_price)}` : '--';
    const pnl = Number(data.unrealized_pnl) || 0;
    const pnlEl = $('posPnl');
    if (pnlEl) {
        pnlEl.textContent = fmtSigned(pnl);
        pnlEl.className = 'v num ' + (pnl >= 0 ? 'up' : 'down');
    }
    updateSlot('positions.unrealizedPnl', fmtSigned(pnl), pnl >= 0 ? 'up' : 'down');

    const cfgLev = parseInt($('leverage')?.value) || 75;
    const rawLev = parseInt(data.leverage) || 0;
    const hasOpenTrade = data.side && data.side !== 'NONE';
    const lev = (hasOpenTrade && rawLev > 1) ? rawLev : (rawLev > 1 && !$('leverage')?.value ? rawLev : cfgLev);
    if ($('posLeverage')) $('posLeverage').textContent = `${lev}x`;
    if ($('chartLeverageChip')) $('chartLeverageChip').textContent = `PERP · ${lev}x`;
    updateSlot('chart.leverage', `PERP · ${lev}x`);
    updateSlot('chart.symbol', data.symbol || activeSymbol || 'BTCUSDT');
    if (data.mark_price) updateSlot('chart.price', '$' + fmt(data.mark_price));

    const roe = Number(data.roe) || 0;
    if ($('posRoe')) {
        $('posRoe').textContent = `${roe >= 0 ? '+' : ''}${roe.toFixed(2)}% ROE · ${coins.length} SLOTS`;
    }
    updateSlot('positions.roeSlots', `${roe >= 0 ? '+' : ''}${roe.toFixed(2)}% ROE · ${coins.length} SLOTS`);

    const notional = Math.abs(Number(data.size) || 0) * (data.mark_price || data.entry_price || 0);
    const margin = lev > 0 ? notional / lev : 0;
    updateSlot('positions.roeMargin', `${roe >= 0 ? '+' : ''}${roe.toFixed(2)}% ROE · MARGIN $${margin.toFixed(2)}`);

    const totalEquity = parseFloat(($('statBalance')?.textContent || '1000').replace(/[^0-9.-]+/g, '')) || 1000;
    const riskPct = Math.min(100, Math.max(0, Math.round((margin / totalEquity) * 100)));
    const riskBar = $('posFocusRiskBar');
    if (riskBar) riskBar.style.width = riskPct + '%';
    const riskBarSlot = document.querySelector('[data-slot="positions.riskBar"]');
    if (riskBarSlot) riskBarSlot.style.width = riskPct + '%';
    updateSlot('positions.riskPct', riskPct + '%');
    const riskLabel = riskPct > 60 ? 'RISK: HIGH' : (riskPct > 25 ? 'RISK: MODERATE' : 'RISK: LOW');
    const riskChipCls = riskPct > 60 ? 'chip down' : (riskPct > 25 ? 'chip amber' : 'chip up');
    updateSlot('positions.riskLabel', riskLabel, riskChipCls);

    // 1:1 Take Profit Target & 1:1 Stop Loss
    const trailingEl = $('posTrailingTp');
    const targetRoe = Number(data.target_roe) || 100;

    if (trailingEl) {
        if (data.side && data.side !== 'NONE' && data.tp_price) {
            trailingEl.textContent = `$${fmt(data.tp_price)} (1:1 Target)`;
            trailingEl.style.color = '#0ecb81';
        } else {
            trailingEl.textContent = '--';
            trailingEl.style.color = '#848e9c';
        }
    }
    const slEl = $('posCurrentSl');
    if (slEl) {
        if (data.side && data.side !== 'NONE' && data.sl_price) {
            slEl.textContent = `$${fmt(data.sl_price)} (1:1 SL)`;
            slEl.style.color = '#f6465d';
        } else {
            slEl.textContent = '--';
            slEl.style.color = '#848e9c';
        }
    }

    // Estimated Fees calculation:
    // UI requirement: har trade card pe dikhao: "Fees ≈ $0.0X (margin ka Y%)"
    const feesEl = $('posFees');
    const focusFeesEl = $('posFocusFees');
    if (data.side && data.side !== 'NONE') {
        const size = Math.abs(Number(data.size) || 0);
        const price = Number(data.entry_price || data.mark_price || 0);
        const notional = size * price;
        const estFees = notional * 0.0010; // ~0.10% round-trip taker
        const margin = lev > 0 ? notional / lev : 0;
        const feeMarginPct = margin > 0 ? (estFees / margin) * 100 : (0.10 * lev);
        const feeStr = `Fees ≈ $${estFees.toFixed(2)} (margin ka ${feeMarginPct.toFixed(1)}%)`;
        if (feesEl) {
            feesEl.textContent = feeStr;
            feesEl.style.color = 'var(--gold-primary)';
        }
        if (focusFeesEl) {
            focusFeesEl.textContent = feeStr;
            focusFeesEl.style.color = 'var(--gold-primary)';
        }
    } else {
        if (feesEl) feesEl.textContent = '--';
        if (focusFeesEl) focusFeesEl.textContent = '--';
    }

    // Dynamic aura glow on Position Card
    const posCard = $('positionCard');
    if (posCard) {
        posCard.classList.remove('is-long', 'is-short');
        if (data.side === 'LONG') posCard.classList.add('is-long');
        else if (data.side === 'SHORT') posCard.classList.add('is-short');
    }

    // Mobile quick strip update
    if ($('mobCoin')) $('mobCoin').textContent = data.symbol || activeSymbol || 'BTCUSDT';
    if ($('mobPrice')) $('mobPrice').textContent = data.mark_price ? `$${fmt(data.mark_price)}` : '$--';
    const mobPnl = $('mobPnl');
    if (mobPnl) {
        if (data.side && data.side !== 'NONE') {
            const sign = pnl > 0 ? '+' : '';
            mobPnl.textContent = `${data.side} ${sign}$${pnl.toFixed(2)}`;
            mobPnl.className = 'mob-quick-pnl ' + (pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-zero');
        } else {
            mobPnl.textContent = '$0.00 (FLAT)';
            mobPnl.className = 'mob-quick-pnl pnl-zero';
        }
    }

    // Position Tab synchronization
    if ($('posTabActiveSym')) $('posTabActiveSym').textContent = data.symbol || activeSymbol || '--';
    if ($('posFocusSymbol')) $('posFocusSymbol').textContent = data.symbol || activeSymbol || '--';
    if ($('posBtnSymbol')) $('posBtnSymbol').textContent = data.symbol || activeSymbol || 'Selected';

    const posFocusBadge = $('posFocusBadge');
    if (posFocusBadge) {
        posFocusBadge.className = '';
        if (data.side === 'LONG') {
            posFocusBadge.textContent = 'LONG ACTIVE';
            posFocusBadge.className = 'pos-badge-long';
        } else if (data.side === 'SHORT') {
            posFocusBadge.textContent = 'SHORT ACTIVE';
            posFocusBadge.className = 'pos-badge-short';
        } else {
            posFocusBadge.textContent = 'NO POSITION';
            posFocusBadge.className = 'pos-badge-none';
        }
    }

    if ($('posTabSide')) {
        $('posTabSide').textContent = data.side || 'NONE';
        $('posTabSide').style.color = data.side === 'LONG' ? 'var(--green-success)' : (data.side === 'SHORT' ? 'var(--red-danger)' : 'var(--text-secondary)');
    }
    if ($('posFocusSide')) {
        $('posFocusSide').textContent = data.side || 'NONE';
        $('posFocusSide').style.color = data.side === 'LONG' ? 'var(--green-success)' : (data.side === 'SHORT' ? 'var(--red-danger)' : 'var(--text-secondary)');
    }
    if ($('posTabLeverage')) $('posTabLeverage').textContent = `${lev}x Leverage`;
    if ($('posFocusLeverage')) $('posFocusLeverage').textContent = `${lev}x`;
    if ($('posFocusSize')) $('posFocusSize').textContent = Math.abs(data.size || 0).toFixed(4);
    if ($('posFocusEntry')) $('posFocusEntry').textContent = data.entry_price ? `$${fmt(data.entry_price)}` : '--';
    if ($('posFocusMark')) $('posFocusMark').textContent = data.mark_price ? `$${fmt(data.mark_price)}` : '--';

    const pnlFormatted = `$${pnl.toFixed(2)}`;
    if ($('posTabPnl')) {
        $('posTabPnl').textContent = pnlFormatted;
        $('posTabPnl').className = 'pos-metric-value ' + (pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-zero');
    }
    if ($('posFocusPnl')) {
        $('posFocusPnl').textContent = pnlFormatted;
        $('posFocusPnl').className = (pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : 'pnl-zero');
    }

    // ROE calculation
    let roeEstimated = 0;
    if (data.side && data.side !== 'NONE' && data.entry_price && data.mark_price) {
        if (data.side === 'LONG') {
            roeEstimated = ((data.mark_price - data.entry_price) / data.entry_price) * lev * 100;
        } else if (data.side === 'SHORT') {
            roeEstimated = ((data.entry_price - data.mark_price) / data.entry_price) * lev * 100;
        }
    }
    const roeSign = roeEstimated > 0 ? '+' : '';
    const roeText = `ROE: ${roeSign}${roeEstimated.toFixed(2)}%`;
    if ($('posTabRoe')) $('posTabRoe').textContent = roeText;
    if ($('posFocusRoe')) {
        $('posFocusRoe').textContent = `${roeSign}${roeEstimated.toFixed(2)}%`;
        $('posFocusRoe').style.color = roeEstimated > 0 ? 'var(--green-success)' : (roeEstimated < 0 ? 'var(--red-danger)' : 'inherit');
    }

    if ($('posFocusTrailingTp')) $('posFocusTrailingTp').textContent = trailingEl ? trailingEl.textContent : '--';
    if ($('posFocusCurrentSl')) $('posFocusCurrentSl').textContent = slEl ? slEl.textContent : '--';
    if ($('posTabStage')) $('posTabStage').textContent = data.side && data.side !== 'NONE' ? '1:1 Active' : '1:1 Auto';
    if ($('posTabTpTarget')) $('posTabTpTarget').textContent = data.tp_price ? `TP: $${fmt(data.tp_price)}` : 'Target: --';

    // Update positions table
    renderPositionsTable();
}

window.fetchPositions = async function() {
    try {
        const r = await fetch('/api/positions' + (activeSymbol ? `?symbol=${activeSymbol}` : ''));
        const d = await r.json();
        if (d.success && d.positions) {
            d.positions.forEach(p => {
                if (p.symbol) positionsBySymbol[p.symbol] = p;
            });
            if (activeSymbol && positionsBySymbol[activeSymbol]) {
                updatePositionUI(positionsBySymbol[activeSymbol]);
            }
            renderPositionsTable();
        }
    } catch (e) {
        console.warn('fetchPositions error:', e);
    }
};

function renderPositionsTable() {
    const tbody = $('positionsTableBody');
    if (!tbody) return;

    const symList = coins.length > 0 ? coins : Object.keys(positionsBySymbol);
    if (symList.length === 0) {
        tbody.innerHTML = `<div class="empty">No monitored coins in watchlist yet. Add coins in Bot Strategy &amp; Settings.</div>`;
        if ($('posCountBadge')) $('posCountBadge').textContent = '0';
        updateSlot('positions.openCount', '0');
        if (typeof window.renderDetailedPositions === 'function') window.renderDetailedPositions();
        return;
    }

    let activeCount = 0;
    let html = '';
    symList.forEach(sym => {
        const p = positionsBySymbol[sym] || { symbol: sym, side: 'NONE', size: 0, entry_price: 0, mark_price: 0, unrealized_pnl: 0 };
        const hasPos = p.side && p.side !== 'NONE';
        if (hasPos) activeCount++;
        const pnl = Number(p.unrealized_pnl) || 0;
        const pnlClass = pnl >= 0 ? 'up' : 'down';
        const sideClass = p.side === 'LONG' ? 'badge long' : (p.side === 'SHORT' ? 'badge short' : 'badge manual');
        const notional = Math.abs(p.size || 0) * (p.mark_price || p.entry_price || 0);
        const estFee = (notional * 0.0010).toFixed(2);
        const lev = p.leverage || 125;

        html += `
        <div class="tr" onclick="selectSymbol('${sym}')" style="cursor:pointer;">
            <span class="sym" style="color:var(--gold); font-weight:800;">${sym}</span>
            <span><i class="${sideClass}">${p.side || 'FLAT'}</i> <i class="chip amber">${lev}x</i></span>
            <span class="num t2">${Math.abs(p.size || 0).toFixed(4)}</span>
            <span class="num">${p.entry_price ? '$' + fmt(p.entry_price) : '--'}</span>
            <span class="num">${p.mark_price ? '$' + fmt(p.mark_price) : '--'}</span>
            <span class="num ${pnlClass}"><span style="font-weight:800;">${hasPos ? fmtSigned(pnl) : '$0.00'}</span><em>(${p.roe ? p.roe.toFixed(2) : '0.00'}%)</em></span>
            <span class="num"><b class="up">${p.tp_price ? '$' + fmt(p.tp_price) : '--'}</b> / <b class="down">${p.sl_price ? '$' + fmt(p.sl_price) : '--'}</b></span>
            <span class="acts">
                ${hasPos ? `<button type="button" class="mbtn danger" onclick="event.stopPropagation(); closePositionForSymbol('${sym}');">CLOSE</button>` : `<button type="button" class="mbtn" onclick="event.stopPropagation(); selectSymbol('${sym}'); switchWorkspaceTab('terminal');">VIEW</button>`}
            </span>
        </div>`;
    });

    tbody.innerHTML = html;
    if ($('posCountBadge')) $('posCountBadge').textContent = `${activeCount}`;
    updateSlot('positions.openCount', `${activeCount}`);
    renderSlotQueue();
    if (typeof window.renderDetailedPositions === 'function') window.renderDetailedPositions();
}

window.renderDetailedPositions = function() {
    const container = $('detailedPositionsList');
    if (!container) return;
    const symList = coins.length > 0 ? coins : Object.keys(positionsBySymbol);
    const openPositions = symList.map(s => positionsBySymbol[s]).filter(p => p && p.side && p.side !== 'NONE');

    if (openPositions.length === 0) {
        container.innerHTML = '<div class="empty">NO OPEN POSITIONS</div>';
        return;
    }

    let html = '';
    openPositions.forEach(p => {
        const pnl = Number(p.unrealized_pnl) || 0;
        const pnlCls = pnl >= 0 ? 'up' : 'down';
        const sideCls = p.side === 'LONG' ? 'badge long' : 'badge short';
        const entry = Number(p.entry_price) || 0;
        const mark = Number(p.mark_price) || entry;
        const tp = Number(p.tp_price) || (entry * 1.02);
        const sl = Number(p.sl_price) || (entry * 0.98);

        let lanePct = 50;
        if (p.side === 'LONG') {
            if (tp !== sl) lanePct = Math.max(0, Math.min(100, ((mark - sl) / (tp - sl)) * 100));
        } else {
            if (sl !== tp) lanePct = Math.max(0, Math.min(100, ((sl - mark) / (sl - tp)) * 100));
        }

        html += `
        <div class="card" style="padding:16px 20px;">
            <div class="spread">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="sym" style="font:800 15px var(--font); color:var(--gold);">${p.symbol}</span>
                    <span class="${sideCls}">${p.side}</span>
                    <span class="chip amber">${p.leverage || 125}x</span>
                </div>
                <div style="text-align:right;">
                    <span class="num ${pnlCls}" style="font:800 17px var(--font);">${fmtSigned(pnl)}</span>
                    <em class="t3" style="font-size:11px; margin-left:4px;">(${p.roe ? p.roe.toFixed(2) : '0.00'}%)</em>
                </div>
            </div>

            <div class="lane" style="margin-top:14px;">
                <div class="track">
                    <div class="cur" style="left:${lanePct.toFixed(1)}%;"></div>
                </div>
                <div class="tlabels" style="display:flex; justify-content:space-between; margin-top:6px; font-size:10px; font-family:var(--mono);">
                    <span class="down">SL: $${fmt(sl)}</span>
                    <span class="gold">MARK: $${fmt(mark)}</span>
                    <span class="up">TP: $${fmt(tp)}</span>
                </div>
            </div>

            <div class="spread" style="margin-top:14px; padding-top:10px; border-top:1px solid #141A22;">
                <div class="t2" style="font-size:11px; font-family:var(--mono);">
                    Size: <b>${Math.abs(p.size || 0).toFixed(4)}</b> · Entry: <b>$${fmt(entry)}</b>
                </div>
                <button type="button" class="btn btn-ghost red" onclick="closePositionForSymbol('${p.symbol}')" style="padding:6px 14px; font-size:10px;">Market Close</button>
            </div>
        </div>`;
    });
    container.innerHTML = html;
};

window.closePositionForSymbol = async function(symbol) {
    if (!confirm(`Are you sure you want to market close position for ${symbol}?`)) return;
    try {
        const r = await fetch('/api/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: symbol })
        });
        const contentType = r.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            log('error', `[${symbol}] Close request returned HTTP ${r.status}`);
            return;
        }
        const d = await r.json();
        if (d.success) {
            log('success', `[${symbol}] Position closed successfully!`);
            if (positionsBySymbol[symbol]) {
                positionsBySymbol[symbol].side = 'NONE';
                positionsBySymbol[symbol].size = 0;
                positionsBySymbol[symbol].unrealized_pnl = 0;
            }
            if (typeof renderPositionsTable === 'function') renderPositionsTable();
            window.fetchPositions();
            if (typeof window.fetchTradeHistory === 'function') window.fetchTradeHistory();
        } else {
            log('error', `[${symbol}] Close failed: ${d.error || 'Unknown error'}`);
        }
    } catch (e) {
        log('error', `[${symbol}] Close error: ${e.message || e}`);
    }
}

// ===== Trade History & Realized PnL Management =====
window.tradeHistoryData = [];
window.tradeHistoryStats = {};

window.fetchTradeHistory = async function(force = false) {
    try {
        const r = await fetch('/api/trades?limit=100');
        const d = await r.json();
        if (d.success) {
            window.tradeHistoryData = d.trades || [];
            window.tradeHistoryStats = d.stats || {};
            window.renderTradeHistoryUI();
        }
    } catch (e) {
        console.warn('fetchTradeHistory error:', e);
    }
};

window.renderTradeHistoryUI = function() {
    const stats = window.tradeHistoryStats || {};
    const trades = window.tradeHistoryData || [];

    // 1. Update KPI stats
    if ($('hStatTotalTrades')) $('hStatTotalTrades').textContent = stats.total_trades || 0;
    if ($('hStatWinLoss')) {
        $('hStatWinLoss').textContent = `${stats.wins || 0}W • ${stats.losses || 0}L FILLED TRADES`;
    }
    const wr = Number(stats.win_rate_pct) || 0;
    if ($('hStatWinRate')) {
        $('hStatWinRate').textContent = `${wr.toFixed(0)}%`;
    }
    drawRing($('hStatWinRateRing'), wr, '#0ECB81');

    const net = Number(stats.net_pnl) || 0;
    const gross = Number(stats.total_pnl) || 0;
    const fees = Number(stats.total_fees) || 0;

    if ($('hStatNetPnl')) {
        $('hStatNetPnl').textContent = fmtSigned(net);
        $('hStatNetPnl').className = 'num ' + (net >= 0 ? 'up' : 'down');
    }
    if ($('hStatGrossPnl')) {
        $('hStatGrossPnl').textContent = fmtSigned(gross);
    }
    if ($('hStatTotalFees')) {
        $('hStatTotalFees').textContent = fmtUsd(fees);
    }
    if ($('hStatAvgPnl')) {
        const avg = stats.avg_trade_pnl || 0;
        $('hStatAvgPnl').textContent = `Avg: ${avg >= 0 ? '+' : ''}$${avg.toFixed(2)} / trade`;
    }

    if ($('histFootCount')) $('histFootCount').textContent = `${stats.total_trades || 0} TRADES`;
    if ($('histFootGross')) $('histFootGross').textContent = fmtSigned(gross);
    if ($('histFootFees')) $('histFootFees').textContent = fmtUsd(fees);
    if ($('histFootNet')) {
        $('histFootNet').textContent = fmtSigned(net);
        $('histFootNet').className = net >= 0 ? 'up' : 'down';
    }

    updateSlot('history.netPnlToday', fmtSigned(net), net >= 0 ? 'up' : 'down');
    updateSlot('history.grossPnlToday', fmtSigned(gross));
    updateSlot('history.feesToday', fmtUsd(fees));
    updateSlot('history.winRate', `${wr.toFixed(0)}%`);

    // 2. Update Symbol Filter Dropdown Options
    const symSelect = $('historyFilterSymbol');
    if (symSelect) {
        const currentVal = symSelect.value || 'ALL';
        const uniqueSymbols = Array.from(new Set(trades.map(t => t.symbol).filter(Boolean))).sort();
        let symOpts = '<option value="ALL">All Symbols</option>';
        uniqueSymbols.forEach(s => {
            symOpts += `<option value="${s}" ${s === currentVal ? 'selected' : ''}>${s}</option>`;
        });
        symSelect.innerHTML = symOpts;
    }

    // 3. Render Full Table
    window.renderTradeHistoryTable();

    // 4. Render Quick Summary Table on Position Tab
    window.renderRecentTradesQuickTable();
};

window.renderTradeHistoryTable = function() {
    const tbody = $('tradeHistoryTableBody');
    if (!tbody) return;

    const trades = window.tradeHistoryData || [];
    const symFilter = $('historyFilterSymbol') ? $('historyFilterSymbol').value : 'ALL';
    const statusFilter = $('historyFilterStatus') ? $('historyFilterStatus').value : 'ALL';

    let filtered = trades.filter(t => {
        if (symFilter !== 'ALL' && t.symbol !== symFilter) return false;
        if (statusFilter !== 'ALL' && t.status !== statusFilter) return false;
        return true;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<div class="empty">NO CLOSED TRADES RECORDED</div>`;
        return;
    }

    let html = '';
    filtered.forEach(t => {
        const isClosed = t.status === 'CLOSED';
        const net = Number(t.net_pnl != null ? t.net_pnl : (t.pnl - (t.fee || 0))) || 0;
        const gross = Number(t.pnl || t.gross_pnl) || 0;
        const fee = Number(t.fee || t.commission || t.fee_est) || 0;
        const pnlCls = net >= 0 ? 'up' : 'down';
        const sideCls = t.side === 'LONG' ? 'badge long' : 'badge short';

        let reasonBadge = '<span class="badge manual">MANUAL</span>';
        const cr = (t.close_reason || t.reason || '').toUpperCase();
        if (cr.includes('TP') || cr.includes('TRAILING') || cr.includes('TARGET')) {
            reasonBadge = '<span class="badge tp">TP HIT</span>';
        } else if (cr.includes('SL') || cr.includes('STOP')) {
            reasonBadge = '<span class="badge sl">SL HIT</span>';
        } else if (cr.includes('REVERSAL')) {
            reasonBadge = '<span class="badge manual">AUTO-REV</span>';
        }

        const closeDate = t.closed_at ? new Date(t.closed_at) : (t.opened_at ? new Date(t.opened_at) : null);
        const timeDisplay = closeDate ? closeDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'}) : '--:--:--';

        html += `
        <div class="tr-hist">
            <span class="tm num">${timeDisplay}</span>
            <span><strong style="color:var(--gold); font-size:12px;">${t.symbol}</strong> <i class="${sideCls}" style="margin-left:4px;">${t.side}</i></span>
            <span class="num t2">${Math.abs(t.qty || t.size || 0).toFixed(4)}</span>
            <span class="num">$${fmt(t.entry_price)} → $${fmt(t.exit_price || t.close_price)}</span>
            <span class="num ${gross >= 0 ? 'up' : 'down'}">${fmtSigned(gross)}</span>
            <span class="num down">${fmtUsd(fee)}</span>
            <span style="text-align:right;">
                <b class="num ${pnlCls}">${fmtSigned(net)}</b>
                ${reasonBadge}
            </span>
        </div>`;
    });

    tbody.innerHTML = html;
};

window.renderRecentTradesQuickTable = function() {
    const tbody = $('recentTradesTableBody');
    if (!tbody) return;

    const trades = (window.tradeHistoryData || []).filter(t => t.status === 'CLOSED').slice(0, 5);
    if (trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:24px; color:var(--text-secondary);">No closed trades yet.</td></tr>`;
        return;
    }

    let html = '';
    trades.forEach(t => {
        const pnl = Number(t.pnl || 0);
        const roe = Number(t.roe_pct || 0);
        const pnlColor = pnl > 0 ? 'var(--green-success)' : (pnl < 0 ? 'var(--red-danger)' : 'var(--text-secondary)');
        const pnlSign = pnl > 0 ? '+' : '';
        const sideClass = t.side === 'LONG' ? 'pos-badge-long' : (t.side === 'SHORT' ? 'pos-badge-short' : 'pos-badge-none');
        const closeDate = t.closed_at ? new Date(t.closed_at) : null;
        const timeStr = closeDate ? `${closeDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}` : '--';

        html += `
        <tr>
            <td style="font-family:var(--font-mono); font-size:12px;">${timeStr}</td>
            <td><strong style="color:var(--gold-primary);">${t.symbol}</strong></td>
            <td><span class="${sideClass}">${t.side}</span></td>
            <td style="font-family:var(--font-mono); font-size:12px;">$${t.entry_price ? fmt(t.entry_price) : '--'} ➔ $${t.exit_price ? fmt(t.exit_price) : '--'}</td>
            <td style="color:${pnlColor}; font-weight:700; font-family:var(--font-mono);">${pnlSign}$${pnl.toFixed(2)} (${pnlSign}${roe.toFixed(1)}%)</td>
            <td style="font-size:11px;">${t.close_reason || 'Closed'}</td>
            <td style="font-family:var(--font-mono); color:var(--gold-primary); font-size:12px;">$${Number(t.fee_est || 0).toFixed(3)}</td>
        </tr>`;
    });

    tbody.innerHTML = html;
};

window.clearTradeHistory = async function() {
    if (!confirm('Are you sure you want to clear all closed trade history records? Active open positions will not be affected.')) return;
    try {
        const r = await fetch('/api/trades/clear', { method: 'POST' });
        const d = await r.json();
        if (d.success) {
            log('info', '🧹 Trade history cleared successfully.');
            window.tradeHistoryData = (window.tradeHistoryData || []).filter(t => t.status === 'OPEN');
            window.tradeHistoryStats = { total_trades: 0, wins: 0, losses: 0, win_rate_pct: 0, total_pnl: 0, total_fees: 0, net_pnl: 0 };
            window.renderTradeHistoryUI();
        }
    } catch (e) {
        log('error', `Clear history error: ${e.message}`);
    }
};

// ===== Multi-Coin Management =====
function renderCoinChips() {
    const container = $('coinChips');
    if (!container) return;
    container.innerHTML = '';
    coins.forEach((sym, idx) => {
        const chip = document.createElement('div');
        chip.className = 'coin-chip' + (sym === activeSymbol ? ' active' : '');
        chip.innerHTML = `<span class="sym">${sym}</span><span class="remove" data-sym="${sym}">×</span>`;
        chip.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove')) return;
            selectSymbol(sym);
        });
        chip.querySelector('.remove').addEventListener('click', (e) => {
            e.stopPropagation();
            removeCoin(sym);
        });
        container.appendChild(chip);
    });
}

function renderCoinTabs() {
    const container = $('coinTabs');
    if (!container) return;
    if (coins.length === 0) {
        container.innerHTML = '<span class="hint-inline">No coins added yet. Add coins from settings panel.</span>';
        return;
    }
    container.innerHTML = '';
    coins.forEach(sym => {
        const tab = document.createElement('div');
        tab.className = 'coin-tab' + (sym === activeSymbol ? ' active' : '');
        tab.dataset.symbol = sym;
        const sig = signalsBySymbol[sym];
        if (sig) tab.classList.add(`signal-${sig.toLowerCase()}`);
        tab.innerHTML = `${sym}<span class="signal-dot"></span>`;
        tab.addEventListener('click', () => selectSymbol(sym));
        container.appendChild(tab);
    });
}

function selectSymbol(sym) {
    if (!sym) return;
    activeSymbol = sym;
    if ($('chartTitle')) $('chartTitle').textContent = `Price Chart - ${sym}`;
    if ($('statSymbol')) $('statSymbol').textContent = sym;
    renderCoinChips();
    renderCoinTabs();
    // Tell backend which coin is active (updates monitor thread + streaming)
    fetch('/api/active_symbol', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym })
    }).catch(() => {});
    // Render cached data immediately
    if (indicatorsBySymbol[sym]) {
        const data = indicatorsBySymbol[sym];
        if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
        if ($('indPrice')) $('indPrice').textContent = `$${fmt(data.mark_price)}`;
        if ($('indEma8'))  $('indEma8').textContent  = data.ema_8  ? `$${fmt(data.ema_8)}`  : '--';
        if ($('indEma13')) $('indEma13').textContent = data.ema_13 ? `$${fmt(data.ema_13)}` : '--';
        if ($('indEma21')) $('indEma21').textContent = data.ema_21 ? `$${fmt(data.ema_21)}` : '--';
        if ($('indEma55')) $('indEma55').textContent = data.ema_55 ? `$${fmt(data.ema_55)}` : '--';
        renderEMAStack(data);
        updateChopIndicatorsUI(data);
        let sig = data.signal || signalsBySymbol[sym];
        if (!sig || sig === 'HOLD') {
            const e8 = data.ema_8, e13 = data.ema_13, e21 = data.ema_21, e55 = data.ema_55;
            const sep = data.ema_sep_pct || ((e8 && e55) ? Math.abs(e8 - e55) / e55 * 100 : 0);
            if (e8 && e13 && e21 && e55 && sep >= 0.15) {
                if (e8 >= e13 && e13 >= e21 && e21 > e55) sig = 'BUY';
                else if (e8 <= e13 && e13 <= e21 && e21 < e55) sig = 'SELL';
                else sig = 'HOLD';
            } else {
                sig = 'HOLD';
            }
        }
        signalsBySymbol[sym] = sig || 'HOLD';
        const el = $('indSignal');
        if (el) {
            el.textContent = signalsBySymbol[sym];
            el.className = '';
            el.classList.add(`signal-${signalsBySymbol[sym].toLowerCase()}`);
        }
    } else {
        // reset
        ['indPrice','indEma8','indEma13','indEma21','indEma55'].forEach(id => {
            if ($(id)) $(id).textContent = '--';
        });
        if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
        const el = $('indSignal');
        if (el) { el.textContent = '--'; el.className = ''; }
        renderEMAStack(null);
        updateChopIndicatorsUI(null);
    }
    if (positionsBySymbol[sym]) {
        updatePositionUI(positionsBySymbol[sym]);
    } else {
        const curLev = parseInt($('leverage')?.value) || 10;
        updatePositionUI({ symbol: sym, side: 'NONE', size: 0, entry_price: 0, mark_price: 0, unrealized_pnl: 0, leverage: curLev });
    }
    loadDrawingsForActiveSymbol();
    if (chartDataBySymbol[sym]) {
        renderChartForSymbol(sym);
    } else if (chart) {
        // Clear chart
        try {
            candleSeries.setData([]);
            ema8Series.setData([]);
            ema13Series.setData([]);
            ema21Series.setData([]);
            ema55Series.setData([]);
        } catch (e) {}
    }
}

function addCoin(customSym = null) {
    const input = $('coinInput');
    const sym = (customSym || input?.value || '').trim().toUpperCase();
    if (!sym) return;
    const ex = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
    if (ex === 'primexbt') {
        if (!/^[A-Z0-9\/\s\.\-_]+$/.test(sym)) {
            log('warn', `${sym} valid nahi. PrimeXBT format: XAU/USD, BTC/USD, USTEC, US30 etc.`);
            return;
        }
    } else {
        if (!/^[A-Z0-9]+USDT$/.test(sym)) {
            log('warn', `${sym} valid nahi. Format: BTCUSDT, ETHUSDT, BTCSUSDT etc.`);
            return;
        }
    }
    if (coins.includes(sym)) {
        log('info', `${sym} pehle se added hai.`);
        if (input) input.value = '';
        return;
    }
    coins.push(sym);
    if (input) input.value = '';
    renderCoinChips();
    renderCoinTabs();
    if (!activeSymbol || coins.length === 1) selectSymbol(sym);
    if ($('statCoins')) $('statCoins').textContent = coins.length;
    log('success', `+ ${sym} watchlist mein add ho gaya.`);
    // Auto-save coins to config
    saveSettings();
}

function removeCoin(sym) {
    coins = coins.filter(c => c !== sym);
    delete signalsBySymbol[sym];
    delete indicatorsBySymbol[sym];
    delete positionsBySymbol[sym];
    delete chartDataBySymbol[sym];
    if (activeSymbol === sym) {
        activeSymbol = coins[0] || null;
        if (activeSymbol) selectSymbol(activeSymbol);
        else if ($('chartTitle')) $('chartTitle').textContent = 'Price Chart - Select a coin';
    }
    renderCoinChips();
    renderCoinTabs();
    if ($('statCoins')) $('statCoins').textContent = coins.length;
    log('info', `${sym} removed.`);
    // Auto-save coins to config
    saveSettings();
}

// ===== Amount Mode Toggle =====
function setAmountMode(mode) {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    if (mode === 'percent') {
        $('fixedAmountGroup').classList.add('hidden');
        $('percentAmountGroup').classList.remove('hidden');
    } else {
        $('fixedAmountGroup').classList.remove('hidden');
        $('percentAmountGroup').classList.add('hidden');
    }
}

// ===== Settings Load/Save =====
async function loadSettings() {
    try {
        const r = await fetch('/api/config');
        const cfg = await r.json();
        // Exchange
        const exchange = cfg.exchange || 'binance';
        setExchange(exchange);
        if ($('apiPassphrase')) $('apiPassphrase').placeholder = cfg.api_passphrase ? 'Saved' : 'WEEX Passphrase';
        if ($('timeframe')) $('timeframe').value = cfg.timeframe || '1d';
        if ($('leverage')) {
            const savedLev = cfg.leverage || 10;
            $('leverage').value = savedLev;
            if ($('posLeverage') && (!$('posLeverage').textContent || $('posLeverage').textContent === '1x')) {
                $('posLeverage').textContent = `${savedLev}x`;
            }
        }
        if ($('amount')) $('amount').value = cfg.amount || 100;
        if ($('amountPct')) $('amountPct').value = cfg.amount_pct || 10;
        const slVal = cfg.stop_loss_pct || 2;
        if ($('stopLossPct')) $('stopLossPct').value = slVal;
        if ($('takeProfitPct')) $('takeProfitPct').value = slVal;
        if ($('tpMode')) $('tpMode').value = 'fixed';
        if (typeof window.updateTPModeUI === 'function') window.updateTPModeUI();
        if ($('maxConcurrentTrades')) $('maxConcurrentTrades').value = String(cfg.max_concurrent_trades || 3);
        if ($('mode')) $('mode').value = cfg.mode || 'both';
        if ($('testnet')) $('testnet').value = String(cfg.testnet ?? true);
        if (cfg.api_key && $('apiKey')) $('apiKey').placeholder = cfg.api_key_masked || 'Saved';

        // Notifications - Telegram
        if ($('telegramEnabled')) $('telegramEnabled').checked = !!cfg.telegram_enabled;
        if ($('telegramBotToken')) $('telegramBotToken').placeholder = cfg.telegram_bot_token ? 'Saved' : 'Bot Token';
        if ($('telegramChatId')) $('telegramChatId').value = cfg.telegram_chat_id || '';
        // Email
        if ($('emailEnabled')) $('emailEnabled').checked = !!cfg.email_enabled;
        if ($('emailSender')) $('emailSender').value = cfg.email_sender || '';
        if ($('emailPassword')) $('emailPassword').placeholder = cfg.email_password ? 'Saved' : 'App Password';
        if ($('emailReceiver')) $('emailReceiver').value = cfg.email_receiver || '';
        if ($('emailSmtpServer')) $('emailSmtpServer').value = cfg.email_smtp_server || 'smtp.gmail.com';
        if ($('emailSmtpPort')) $('emailSmtpPort').value = cfg.email_smtp_port || 587;
        // WhatsApp
        if ($('whatsappEnabled')) $('whatsappEnabled').checked = !!cfg.whatsapp_enabled;
        if ($('whatsappPhone')) $('whatsappPhone').value = cfg.whatsapp_phone || '';
        if ($('whatsappApikey')) $('whatsappApikey').placeholder = cfg.whatsapp_apikey ? 'Saved' : 'CallMeBot API Key';

        // Amount mode
        const amtMode = cfg.amount_mode || 'fixed';
        setAmountMode(amtMode);

        // Coins
        const savedCoins = Array.isArray(cfg.symbols_list) ? cfg.symbols_list : (cfg.symbol ? [cfg.symbol] : ['BTCUSDT']);
        coins = savedCoins.map(s => String(s).toUpperCase());
        if (coins.length === 0) coins = ['BTCUSDT'];
        if (!activeSymbol) activeSymbol = coins[0];
        renderCoinChips();
        renderCoinTabs();
        selectSymbol(activeSymbol);
        if ($('statCoins')) $('statCoins').textContent = coins.length;

        updateEnvBadge(cfg.testnet ?? true, exchange);
    } catch (e) {
        log('error', `Settings load failed: ${e}`);
    }
}

function setExchange(exchange) {
    const prevExchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || null;
    document.querySelectorAll('.exchange-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.exchange === exchange);
    });
    // Show/hide passphrase field (WEEX only)
    const passGroup = $('passphraseGroup');
    if (passGroup) {
        if (exchange === 'weex') {
            passGroup.classList.remove('hidden');
            passGroup.style.display = '';
        } else {
            passGroup.classList.add('hidden');
            passGroup.style.display = 'none';
        }
    }
    // Update API Key / Secret / Coin placeholders based on exchange
    if ($('apiKey')) {
        if (exchange === 'primexbt') $('apiKey').placeholder = 'Enter PrimeXBT API Key ID';
        else if (exchange === 'weex') $('apiKey').placeholder = 'Enter WEEX API Key';
        else $('apiKey').placeholder = 'Enter Binance API Key';
    }
    if ($('apiSecret')) {
        if (exchange === 'primexbt') $('apiSecret').placeholder = 'Enter Ed25519 Private Key (PKCS#8)';
        else if (exchange === 'weex') $('apiSecret').placeholder = 'Enter WEEX API Secret';
        else $('apiSecret').placeholder = 'Enter Binance API Secret';
    }
    if ($('coinInput')) {
        if (exchange === 'primexbt') $('coinInput').placeholder = 'XAU/USD, BTC/USD, ETH/USD, USTEC...';
        else $('coinInput').placeholder = 'BTCUSDT, SOLUSDT, ETHUSDT...';
    }

    // Show/hide WEEX-only and PrimeXBT-only leverage buttons
    document.querySelectorAll('.weex-only').forEach(btn => {
        btn.style.display = exchange === 'weex' ? '' : 'none';
    });
    document.querySelectorAll('.primexbt-only').forEach(btn => {
        btn.style.display = exchange === 'primexbt' ? '' : 'none';
    });

    // Update max leverage label and input max
    const maxLevLabel = $('maxLevLabel');
    const levInput = $('leverage');
    const maxLevBtn = $('maxLeverageBtn');
    if (exchange === 'primexbt') {
        if (maxLevLabel) maxLevLabel.textContent = '1000';
        if (levInput) levInput.max = '1000';
        if (maxLevBtn) maxLevBtn.textContent = '⚡ SET 1000x LEVERAGE';
    } else if (exchange === 'weex') {
        if (maxLevLabel) maxLevLabel.textContent = '500';
        if (levInput) levInput.max = '500';
        if (maxLevBtn) maxLevBtn.textContent = 'SET 500x LEVERAGE';
    } else {
        if (maxLevLabel) maxLevLabel.textContent = '125';
        if (levInput) levInput.max = '125';
        if (maxLevBtn) maxLevBtn.textContent = 'SET 100x LEVERAGE';
    }
    // Update env badge
    const testnet = $('testnet') ? $('testnet').value === 'true' : true;
    updateEnvBadge(testnet, exchange);

    // CRITICAL FIX: When exchange is switched, auto-refresh the coin dropdown
    // from the NEW exchange's API.
    if (prevExchange && prevExchange !== exchange) {
        log('info', `Exchange switched: ${prevExchange} -> ${exchange}. Refreshing coin list...`);
        // Adapt existing coins for new exchange
        if (exchange === 'primexbt') {
            coins = ['XAU/USD', 'BTC/USD', 'ETH/USD'];
        } else if (exchange === 'weex' && testnet) {
            coins = coins.map(c => (c.endsWith('USDT') && !c.endsWith('SUSDT')) ? c.replace('USDT', 'SUSDT') : c);
            if (coins.some(c => c.includes('/') || !c.endsWith('USDT'))) coins = ['BTCSUSDT'];
        } else {
            coins = coins.map(c => c.endsWith('SUSDT') ? c.replace('SUSDT', 'USDT') : c);
            if (coins.some(c => c.includes('/') || !c.endsWith('USDT'))) coins = ['BTCUSDT'];
        }
        if (coins.length === 0) {
            coins = exchange === 'primexbt' ? ['XAU/USD'] : (exchange === 'weex' && testnet ? ['BTCSUSDT'] : ['BTCUSDT']);
        }
        activeSymbol = coins[0];
        renderCoinChips();
        renderCoinTabs();
        selectSymbol(activeSymbol);
        if ($('statCoins')) $('statCoins').textContent = coins.length;
        refreshCoinDropdown(exchange);
        saveSettings();
    }
}

// Fetch fresh coin list from /api/symbols and populate the dropdown (datalist)
async function refreshCoinDropdown(exchange) {
    try {
        const r = await fetch('/api/symbols');
        const data = await r.json();
        if (data.success && data.symbols && data.symbols.length > 0) {
            const datalist = $('coinSuggestions');
            if (datalist) {
                datalist.innerHTML = '';
                data.symbols.forEach(sym => {
                    const opt = document.createElement('option');
                    opt.value = sym;
                    datalist.appendChild(opt);
                });
            }
            log('success', `Loaded ${data.symbols.length} ${exchange.toUpperCase()} coins into dropdown.`);
        }
    } catch (e) {
        log('error', `Failed to refresh coin dropdown: ${e}`);
    }
}

async function saveSettings() {
    log('info', 'Save request bhej rahe hain...');
    if (coins.length === 0) {
        log('warn', 'Kam az kam ek coin add karein.');
        return;
    }
    const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
    const cfg = {
        exchange: exchange,
        api_key: $('apiKey')?.value?.trim() || undefined,
        api_secret: $('apiSecret')?.value?.trim() || undefined,
        api_passphrase: $('apiPassphrase')?.value?.trim() || undefined,
        symbols_list: coins,
        symbol: coins[0],
        timeframe: $('timeframe').value,
        leverage: parseInt($('leverage').value),
        amount_mode: document.querySelector('.toggle-btn.active')?.dataset.mode || 'fixed',
        amount: parseFloat($('amount').value),
        amount_pct: parseFloat($('amountPct').value),
        stop_loss_pct: parseFloat($('stopLossPct').value) || 0,
        take_profit_pct: parseFloat($('stopLossPct').value) || 0,
        trailing_roe_pct: 100,
        tp_mode: 'fixed',
        max_concurrent_trades: parseInt($('maxConcurrentTrades')?.value || 3),
        mode: $('mode').value,
        testnet: $('testnet').value === 'true',
        // Notifications
        telegram_enabled: $('telegramEnabled')?.checked || false,
        telegram_bot_token: $('telegramBotToken')?.value || undefined,
        telegram_chat_id: $('telegramChatId')?.value || undefined,
        email_enabled: $('emailEnabled')?.checked || false,
        email_sender: $('emailSender')?.value || undefined,
        email_password: $('emailPassword')?.value || undefined,
        email_receiver: $('emailReceiver')?.value || undefined,
        email_smtp_server: $('emailSmtpServer')?.value || undefined,
        email_smtp_port: parseInt($('emailSmtpPort')?.value) || undefined,
        whatsapp_enabled: $('whatsappEnabled')?.checked || false,
        whatsapp_phone: $('whatsappPhone')?.value || undefined,
        whatsapp_apikey: $('whatsappApikey')?.value || undefined,
    };
    const maxLev = exchange === 'primexbt' ? 1000 : (exchange === 'weex' ? 500 : 125);
    if (cfg.leverage < 1 || cfg.leverage > maxLev) {
        log('warn', `Leverage must be between 1-${maxLev}`);
        return;
    }
    if (cfg.leverage > maxLev) {
        log('warn', `${exchange.toUpperCase()} pe max leverage ${maxLev}x hai`);
        cfg.leverage = maxLev;
    }
    try {
        const r = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg),
        });
        const data = await r.json();
        if (data.success) {
            log('success', `Settings saved! Exchange: ${exchange.toUpperCase()}`);
            $('apiKey').value = '';
            $('apiSecret').value = '';
            $('apiPassphrase').value = '';
            $('apiKey').placeholder = 'Saved';
            if (exchange === 'weex') $('apiPassphrase').placeholder = 'Saved';
            // Clear notification sensitive fields
            if ($('telegramBotToken')) { $('telegramBotToken').value = ''; $('telegramBotToken').placeholder = 'Saved'; }
            if ($('emailPassword')) { $('emailPassword').value = ''; $('emailPassword').placeholder = 'Saved'; }
            if ($('whatsappApikey')) { $('whatsappApikey').value = ''; $('whatsappApikey').placeholder = 'Saved'; }
            updateEnvBadge(cfg.testnet, exchange);
            if (cfg.stop_loss_pct > 0) log('info', `Stop Loss ACTIVE: ${cfg.stop_loss_pct}%`);
            else log('info', `Stop Loss OFF`);
            if (cfg.take_profit_pct > 0) log('info', `Take Profit ACTIVE: ${cfg.take_profit_pct}%`);
            else log('info', `Take Profit: opposite-signal only`);
            // Log notification status
            const notifs = [];
            if (cfg.telegram_enabled) notifs.push('Telegram');
            if (cfg.email_enabled) notifs.push('Email');
            if (cfg.whatsapp_enabled) notifs.push('WhatsApp');
            if (notifs.length > 0) {
                log('info', `Notifications ON: ${notifs.join(', ')}`);
            } else {
                log('info', `Notifications OFF`);
            }
            // Show monitor status (auto-started by backend after Save)
            if (data.monitor) {
                if (data.monitor.success) {
                    log('success', `🔌 Monitor connected to ${exchange.toUpperCase()} — live balance/chart streaming now`);
                    // Immediately fetch balance (don't wait for next 10s cycle)
                    refreshBalance();
                } else if (data.monitor.error && data.monitor.error.indexOf('API key') >= 0) {
                    log('warn', `⚠️ Monitor not started: ${data.monitor.error}`);
                } else if (data.monitor.error && data.monitor.error !== 'skipped') {
                    log('warn', `⚠️ Monitor: ${data.monitor.error}`);
                }
            }
        } else {
            log('error', `Save failed: ${data.error}`);
        }
    } catch (e) {
        log('error', `Save failed: ${e}`);
    }
}

function updateEnvBadge(testnet, exchange) {
    const exBadge = $('exchangeBadge');
    const modeBadge = $('modeBadge');
    if (exBadge) {
        exBadge.textContent = (exchange || 'binance').toUpperCase();
        exBadge.style.color = exchange === 'primexbt' ? '#3b82f6' : (exchange === 'weex' ? '#0ecb81' : '#f0b90b');
    }
    if (modeBadge) {
        if (exchange === 'primexbt') {
            modeBadge.textContent = testnet ? 'DEMO' : 'LIVE';
        } else if (exchange === 'weex') {
            modeBadge.textContent = testnet ? 'DEMO' : 'LIVE';
        } else {
            modeBadge.textContent = testnet ? 'TESTNET' : 'MAINNET';
        }
        modeBadge.style.color = testnet ? '#f0b90b' : '#f6465d';
    }
}

// ===== Bot Controls =====
async function startBot() {
    if (coins.length === 0) {
        log('warn', 'Pehle coins add karein ya "Load All Coins" dabao.');
        return;
    }
    log('info', 'Start request bhej rahe hain...');
    // Add 30s timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    try {
        const r = await fetch('/api/start', { method: 'POST', signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await r.json();
        if (data.success) {
            log('success', 'Bot started!');
            setBotRunning(true);
        } else {
            log('error', `Start failed: ${data.error}`);
        }
    } catch (e) {
        clearTimeout(timeoutId);
        if (e.name === 'AbortError') {
            log('error', 'Start timeout (30s). FORCE RESET dabao aur dobara try karo.');
        } else {
            log('error', `Start error: ${e}`);
        }
    }
}

async function stopBot() {
    log('info', 'Stop request bhej rahe hain...');
    try {
        const r = await fetch('/api/stop', { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            log('success', 'Bot stopped');
            setBotRunning(false);
        } else {
            log('error', `Stop failed: ${data.error}`);
        }
    } catch (e) {
        log('error', `Stop error: ${e}`);
    }
}

async function closePosition() {
    if (!activeSymbol) {
        log('warn', 'Pehle ek coin select karein.');
        return;
    }
    if (!confirm(`${activeSymbol} ki position close karein?`)) return;
    log('warn', `[${activeSymbol}] Manual close request bhej rahe hain...`);
    try {
        const r = await fetch('/api/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: activeSymbol }),
        });
        const contentType = r.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            log('error', `[${activeSymbol}] Close request returned HTTP ${r.status}`);
            return;
        }
        const data = await r.json();
        if (data.success) {
            log('success', `[${activeSymbol}] Position close request accepted`);
            if (positionsBySymbol[activeSymbol]) {
                positionsBySymbol[activeSymbol].side = 'NONE';
                positionsBySymbol[activeSymbol].size = 0;
                positionsBySymbol[activeSymbol].unrealized_pnl = 0;
            }
            if (typeof renderPositionsTable === 'function') renderPositionsTable();
            window.fetchPositions();
            if (typeof window.fetchTradeHistory === 'function') window.fetchTradeHistory();
        } else {
            log('error', `[${activeSymbol}] Close failed: ${data.error || 'Unknown error'}`);
        }
    } catch (e) {
        log('error', `Close error: ${e.message || e}`);
    }
}
window.closePosition = closePosition;

window.closeAllPositions = async function() {
    if (!confirm('Kya aap saari active positions market close karna chahte hain?')) return;
    log('warn', '⚡ Closing ALL active positions...');
    try {
        const r = await fetch('/api/close_all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const contentType = r.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            log('error', `Close all request returned HTTP ${r.status}`);
            return;
        }
        const data = await r.json();
        if (data.success) {
            log('success', '✅ Saari active positions close request successfully process ho gayi!');
            for (const sym in positionsBySymbol) {
                positionsBySymbol[sym].side = 'NONE';
                positionsBySymbol[sym].size = 0;
                positionsBySymbol[sym].unrealized_pnl = 0;
            }
            if (typeof renderPositionsTable === 'function') renderPositionsTable();
            window.fetchPositions();
            if (typeof window.fetchTradeHistory === 'function') window.fetchTradeHistory();
        } else {
            log('error', `Close all failed: ${data.error || 'Unknown error'}`);
        }
    } catch (e) {
        log('error', `Close all error: ${e.message || e}`);
    }
};

async function refreshStatus() {
    try {
        const r = await fetch('/api/status');
        const s = await r.json();
        setBotRunning(!!s.running);
        let totalTrades = s.trades_today != null ? s.trades_today : null;
        if (totalTrades === null && s.workers) {
            totalTrades = 0;
            for (const sym in s.workers) totalTrades += s.workers[sym].trades_today || 0;
        }
        if (totalTrades !== null && $('statTrades')) $('statTrades').textContent = totalTrades;
        if (s.workers) {
            // If backend says running but has symbols, sync coins array
            if (s.running && s.symbols && s.symbols.length && coins.length === 0) {
                coins = [...s.symbols];
                renderCoinChips();
                renderCoinTabs();
                if (!activeSymbol && coins.length) selectSymbol(coins[0]);
                if ($('statCoins')) $('statCoins').textContent = coins.length;
            }
        }
        // HTTP fallback: If socket is disconnected, fetch chart data via HTTP
        if (isRunning && activeSymbol && (!socket || !socket.connected)) {
            fetchChartData(activeSymbol);
        }
    } catch (e) { /* ignore */ }
}

async function refreshBalance() {
    try {
        const r = await fetch('/api/balance');
        const d = await r.json();
        if (d.success && $('statBalance')) {
            const bal = Number(d.balance || d.total) || 0;
            const avail = Number(d.available != null ? d.available : d.balance) || 0;
            const marginUsed = Math.max(0, bal - avail);
            const marginAllocPct = bal > 0 ? ((marginUsed / bal) * 100).toFixed(1) : '0.0';

            $('statBalance').textContent = fmtUsd(bal);
            updateSlot('account.equity', fmtUsd(bal));
            updateSlot('account.available', fmtUsd(avail));
            updateSlot('account.marginUsed', fmtUsd(marginUsed));
            updateSlot('account.marginAllocPct', `${marginAllocPct}% ALLOCATED`);

            if ($('statMarginUsed')) $('statMarginUsed').textContent = fmtUsd(marginUsed);
            if ($('statMarginAlloc')) $('statMarginAlloc').textContent = `${marginAllocPct}% ALLOCATED`;

            const exchange = (d.exchange || 'binance').toUpperCase();
            const env = d.testnet ? (exchange === 'BINANCE' ? 'TESTNET' : 'DEMO') : 'LIVE';
            $('statBalance').title = `${exchange} ${env} balance`;
            updateSlot('engine.env', env);
        } else if (!d.success && d.error && d.error.includes('not connected')) {
            if ($('statBalance')) $('statBalance').textContent = '--';
            updateSlot('account.equity', '--');
            updateSlot('account.available', '--');
            updateSlot('account.marginUsed', '--');
        }
    } catch (e) { /* ignore */ }
}

// ===== Attach Event Listeners FIRST =====
function attachListeners() {
    const saveBtn = $('saveSettings');
    const startBtn = $('startBtn');
    const stopBtn = $('stopBtn');
    const closeBtn = $('closeBtn');
    const clearLogs = $('clearLogs');

    if (saveBtn) saveBtn.addEventListener('click', saveSettings);
    if (startBtn) startBtn.addEventListener('click', startBot);
    if (stopBtn) stopBtn.addEventListener('click', stopBot);
    if (closeBtn) closeBtn.addEventListener('click', closePosition);

    const mobStart = $('mobQuickStartBtn');
    const mobStop = $('mobQuickStopBtn');
    if (mobStart) mobStart.addEventListener('click', startBot);
    if (mobStop) mobStop.addEventListener('click', stopBot);

    // Test Connection button - checks API credentials
    const testConnBtn = $('testConnBtn');
    if (testConnBtn) {
        testConnBtn.addEventListener('click', async () => {
            log('info', '🔌 Testing API connection...');
            testConnBtn.disabled = true;
            testConnBtn.textContent = 'Testing...';
            try {
                const r = await fetch('/api/test_connection', { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    log('success', `✅ ${data.message}`);
                    if (data.balance !== undefined) {
                        log('info', `💰 Balance: $${Number(data.balance).toFixed(2)} (${data.exchange.toUpperCase()} ${data.demo ? 'DEMO' : 'LIVE'})`);
                    }
                    // Refresh balance display
                    refreshBalance();
                } else {
                    log('error', `❌ Connection FAILED: ${data.cause || 'Unknown'}`);
                    log('warn', `🔧 Fix: ${data.fix || 'Check settings'}`);
                    log('error', `📋 Error detail: ${data.error || ''}`);
                }
            } catch (e) {
                log('error', `Test connection error: ${e}`);
            } finally {
                testConnBtn.disabled = false;
                testConnBtn.textContent = '🔌 TEST CONNECTION (Check API Keys)';
            }
        });
    }

    // Force Stop button - emergency reset
    const forceStopBtn = $('forceStopBtn');
    if (forceStopBtn) {
        forceStopBtn.addEventListener('click', async () => {
            if (!confirm('FORCE RESET karein? Yeh sab state clear kar dega. Position (agar open hai) Binance pe rahegi, lekin bot ka internal state reset ho jaayega.')) return;
            log('warn', 'Force reset request bhej rahe hain...');
            try {
                const r = await fetch('/api/force_stop', { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    log('success', '✅ Force reset done! Ab START fresh kar sakte ho.');
                    setBotRunning(false);
                    // Refresh status
                    setTimeout(refreshStatus, 1000);
                } else {
                    log('error', `Force reset failed: ${data.error}`);
                }
            } catch (e) {
                log('error', `Force reset error: ${e}`);
            }
        });
    }
    if (clearLogs) clearLogs.addEventListener('click', () => {
        const logs = $('logs');
        if (logs) logs.innerHTML = '';
    });

    // Test notification button - sends current form values WITHOUT saving
    const testNotifBtn = $('testNotificationBtn');
    if (testNotifBtn) {
        testNotifBtn.addEventListener('click', async () => {
            // Collect current form values (no save needed)
            const testData = {
                telegram_enabled: $('telegramEnabled')?.checked || false,
                telegram_bot_token: $('telegramBotToken')?.value || undefined,
                telegram_chat_id: $('telegramChatId')?.value || undefined,
                email_enabled: $('emailEnabled')?.checked || false,
                email_sender: $('emailSender')?.value || undefined,
                email_password: $('emailPassword')?.value || undefined,
                email_receiver: $('emailReceiver')?.value || undefined,
                email_smtp_server: $('emailSmtpServer')?.value || undefined,
                email_smtp_port: parseInt($('emailSmtpPort')?.value) || undefined,
                whatsapp_enabled: $('whatsappEnabled')?.checked || false,
                whatsapp_phone: $('whatsappPhone')?.value || undefined,
                whatsapp_apikey: $('whatsappApikey')?.value || undefined,
            };

            // Check if at least one channel is enabled
            if (!testData.telegram_enabled && !testData.email_enabled && !testData.whatsapp_enabled) {
                log('warn', 'Pehle koi channel enable karein (Telegram/Email/WhatsApp checkbox on karein)');
                return;
            }

            log('info', 'Test notification bhej rahe hain (bina save kiye)...');
            testNotifBtn.disabled = true;
            testNotifBtn.textContent = 'Sending...';
            try {
                const r = await fetch('/api/test_notification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(testData),
                });
                const data = await r.json();
                if (data.success) {
                    log('success', `✅ Notification sent! ${data.message || ''}`);
                } else if (data.results) {
                    // Detailed per-channel errors
                    const results = data.results;
                    let hadAny = false;
                    for (const ch of ['telegram', 'email', 'whatsapp']) {
                        const r = results[ch];
                        if (r) {
                            hadAny = true;
                            if (r.success) {
                                log('success', `${ch}: ✅ sent`);
                            } else {
                                log('error', `${ch}: ❌ ${r.error}`);
                            }
                        }
                    }
                    if (!hadAny) {
                        log('warn', 'Koi channel enabled nahi hai. Checkbox on karein.');
                    }
                } else {
                    log('error', `Test failed: ${data.error || 'unknown'}`);
                }
            } catch (e) {
                log('error', `Test error: ${e}`);
            } finally {
                testNotifBtn.disabled = false;
                testNotifBtn.textContent = 'Test';
            }
        });
    }

    // Add coin
    const addCoinBtn = $('addCoinBtn');
    if (addCoinBtn) addCoinBtn.addEventListener('click', addCoin);
    const coinInput = $('coinInput');
    if (coinInput) {
        coinInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addCoin(); }
        });
        coinInput.addEventListener('change', () => {
            // Trigger add when user clicks/selects an option from datalist
            if (coinInput.value.trim()) addCoin();
        });
    }

    // Top 10 Coins Quick Loader
    const loadTopBtn = $('loadTopCoinsBtn');
    if (loadTopBtn) {
        loadTopBtn.addEventListener('click', () => {
            const ex = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
            const testnet = $('testnet') ? $('testnet').value === 'true' : true;
            let topCoins = [];
            if (ex === 'primexbt') {
                topCoins = ["XAU/USD", "GOLD 24/7", "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "EUR/USD", "GBP/USD", "USTEC", "US30"];
            } else if (ex === 'weex') {
                if (testnet) {
                    topCoins = ["BTCSUSDT", "ETHSUSDT", "SOLSUSDT", "BNBSUSDT", "XRPSUSDT", "DOGESUSDT", "ADASUSDT", "AVAXSUSDT", "LINKSUSDT", "SUISUSDT"];
                } else {
                    topCoins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"];
                }
            } else {
                topCoins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT"];
            }
            coins = [...topCoins];
            if (!coins.includes(activeSymbol)) activeSymbol = coins[0];
            renderCoinChips();
            renderCoinTabs();
            selectSymbol(activeSymbol);
            if ($('statCoins')) $('statCoins').textContent = coins.length;
            log('success', `✅ Top 10 coins active watchlist mein add ho gaye! (${topCoins.slice(0, 5).join(', ')}...)`);
            saveSettings();
        });
    }

    // Load Market Coins / All Coins
    const loadAllBtn = $('loadAllCoinsBtn');
    if (loadAllBtn) {
        loadAllBtn.addEventListener('click', async () => {
            log('info', 'Market se coins load ho rahe hain...');
            loadAllBtn.disabled = true;
            loadAllBtn.textContent = 'Loading...';
            try {
                const r = await fetch('/api/symbols');
                const data = await r.json();
                if (data.success && data.symbols && data.symbols.length > 0) {
                    // Populate datalist (autocomplete dropdown)
                    const datalist = $('coinSuggestions');
                    if (datalist) {
                        datalist.innerHTML = '';
                        data.symbols.forEach(sym => {
                            const opt = document.createElement('option');
                            opt.value = sym;
                            datalist.appendChild(opt);
                        });
                    }
                    // If watchlist has only 1 coin, load top 10 from API into active watchlist directly
                    if (coins.length <= 1) {
                        const topToAdd = data.symbols.slice(0, 10);
                        coins = [...topToAdd];
                        if (!coins.includes(activeSymbol)) activeSymbol = coins[0];
                        renderCoinChips();
                        renderCoinTabs();
                        selectSymbol(activeSymbol);
                        if ($('statCoins')) $('statCoins').textContent = coins.length;
                        log('success', `✅ ${data.symbols.length} coins load hue. Top ${topToAdd.length} coins active watchlist mein add ho gaye!`);
                        saveSettings();
                    } else {
                        log('success', `✅ ${data.symbols.length} coins available. Dropdown se coin select karein ya '+ Top 10' dabayein.`);
                    }
                } else {
                    log('error', `Coins load fail: ${data.error || 'unknown'}`);
                }
            } catch (e) {
                log('error', `Coins load error: ${e}`);
            } finally {
                loadAllBtn.disabled = false;
                loadAllBtn.textContent = 'Load All Coins';
            }
        });
    }

    // Auto-load all coins when bot starts (populate dropdown only)
    async function autoLoadCoins() {
        try {
            const r = await fetch('/api/symbols');
            const data = await r.json();
            if (data.success && data.symbols && data.symbols.length > 0) {
                const datalist = $('coinSuggestions');
                if (datalist) {
                    datalist.innerHTML = '';
                    data.symbols.forEach(sym => {
                        const opt = document.createElement('option');
                        opt.value = sym;
                        datalist.appendChild(opt);
                    });
                }
            }
        } catch (e) {
            // Silent fail
        }
    }

    // Auto-calculate 1:1 TP from SL + sync automated execution badges
    const slInput = $('stopLossPct');
    const tfSelect = $('timeframe');
    if (tfSelect) {
        tfSelect.addEventListener('change', () => {
            loadDrawingsForActiveSymbol();
        });
    }

    function updateTPModeUI() {
        const sl = parseFloat(slInput?.value) || 2.0;
        const tpInput = $('takeProfitPct');
        if (tpInput) {
            tpInput.value = sl.toFixed(1);
        }
        if ($('autoTpDisplay')) $('autoTpDisplay').textContent = sl.toFixed(1);
        if ($('autoSlDisplay')) $('autoSlDisplay').textContent = sl.toFixed(1);
        const tpModeInput = $('tpMode');
        if (tpModeInput) tpModeInput.value = 'fixed';
    }

    if (slInput) {
        slInput.addEventListener('input', updateTPModeUI);
        slInput.dispatchEvent(new Event('input'));
    }
    // Expose for the config loader to call
    window.updateTPModeUI = updateTPModeUI;

    // Exchange toggle
    document.querySelectorAll('.exchange-btn').forEach(btn => {
        btn.addEventListener('click', () => setExchange(btn.dataset.exchange));
    });

    // Environment change
    const testnetSelect = $('testnet');
    if (testnetSelect) {
        testnetSelect.addEventListener('change', () => {
            const ex = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
            updateEnvBadge(testnetSelect.value === 'true', ex);
            saveSettings();
        });
    }

    // Amount mode toggle
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => setAmountMode(btn.dataset.mode));
    });

    // Helper function to apply leverage immediately to exchange and UI
    async function applyLeverageDirect(lev) {
        const levInput = $('leverage');
        if (levInput) levInput.value = lev;
        if ($('posLeverage')) $('posLeverage').textContent = `${lev}x`;
        log('info', `Applying ${lev}x leverage...`);
        try {
            const res = await fetch('/api/leverage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ leverage: lev, symbol: activeSymbol })
            });
            const data = await res.json();
            if (data.success) {
                const finalLev = data.leverage || lev;
                if (levInput) levInput.value = finalLev;
                if ($('posLeverage')) $('posLeverage').textContent = `${finalLev}x`;
                if (data.adjusted) {
                    log('warn', `⚠️ Binance Rule: ${activeSymbol} par max limit ${finalLev}x hai (${lev}x Binance allow nahi karta). Set to ${finalLev}x.`);
                } else {
                    log('success', `⚡ Leverage successfully set to ${finalLev}x!`);
                }
            } else {
                log('warn', `Leverage notice: ${data.error || 'Saved in config'}`);
            }
        } catch (e) {
            log('info', `Leverage set to ${lev}x (Save settings dabayein apply karne ke liye)`);
        }
    }

    const levInputElem = $('leverage');
    if (levInputElem) {
        ['input', 'change'].forEach(evt => {
            levInputElem.addEventListener(evt, () => {
                const val = parseInt(levInputElem.value) || 75;
                if ($('posLeverage')) $('posLeverage').textContent = `${val}x`;
            });
        });
    }

    // Quick leverage
    document.querySelectorAll('.quick-leverage .btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const lev = parseInt(btn.dataset.lev);
            document.querySelectorAll('.quick-leverage .btn').forEach(b => {
                b.style.background = '';
                b.style.color = '';
            });
            btn.style.background = '#f0b90b';
            btn.style.color = '#0b0e11';
            applyLeverageDirect(lev);
        });
    });

    // Max leverage button (100x for Binance, 500x for WEEX)
    const maxLevBtn = $('maxLeverageBtn');
    if (maxLevBtn) {
        maxLevBtn.addEventListener('click', () => {
            const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
            const maxLev = exchange === 'primexbt' ? 1000 : (exchange === 'weex' ? 500 : 100);
            // Highlight matching quick-lev button
            document.querySelectorAll('.quick-leverage .btn').forEach(b => {
                b.style.background = '';
                b.style.color = '';
            });
            const btnMatch = document.querySelector(`.quick-leverage .btn[data-lev="${maxLev}"]`);
            if (btnMatch) {
                btnMatch.style.background = '#f0b90b';
                btnMatch.style.color = '#0b0e11';
            }
            applyLeverageDirect(maxLev);
        });
    }

    // Testnet badge
    const tn = $('testnet');
    if (tn) tn.addEventListener('change', () => {
        const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
        updateEnvBadge(tn.value === 'true', exchange);
    });
}

// ===== Mobile Navigation & Live Clock =====
function initMobileNav() {
    const nav = $('mobileNav');
    if (!nav) return;
    const items = nav.querySelectorAll('.mob-nav-item');
    items.forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.dataset.tab;
            if (typeof window.switchWorkspaceTab === 'function') {
                window.switchWorkspaceTab(tab);
            } else {
                document.body.dataset.mobTab = tab;
                items.forEach(i => i.classList.toggle('active', i === item));
            }
        });
    });
}

function initLiveClock() {
    const el = $('liveClock');
    if (!el) return;
    function tick() {
        const now = new Date();
        const h = String(now.getUTCHours()).padStart(2, '0');
        const m = String(now.getUTCMinutes()).padStart(2, '0');
        const s = String(now.getUTCSeconds()).padStart(2, '0');
        el.textContent = `${h}:${m}:${s} UTC`;
    }
    setInterval(tick, 1000);
    tick();
}

// ===== Main Init =====
document.addEventListener('DOMContentLoaded', () => {
    try { attachListeners(); } catch (e) { console.error(e); }
    try { initMobileNav(); } catch (e) { console.error(e); }
    try { initLiveClock(); } catch (e) { console.error(e); }
    try { initSocket(); } catch (e) { console.error(e); }
    try { loadSettings(); } catch (e) { console.error(e); }
    try { refreshStatus(); } catch (e) { console.error(e); }
    try { window.fetchPositions(); } catch (e) { console.error(e); }
    try { if (typeof window.fetchTradeHistory === 'function') window.fetchTradeHistory(); } catch (e) { console.error(e); }

    log('info', 'Welcome! Coins add karein, settings set karein, aur START dabayein.');
    log('info', 'Strategy: EMA 8,13,21,55 crossover (55 at bottom = LONG, 55 at top = SHORT)');

    try { initChart(); } catch (e) { console.error(e); }

    // Auto-populate coin dropdown from the SELECTED exchange on page load
    // (delayed so loadSettings can set the exchange first)
    setTimeout(() => {
        const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
        refreshCoinDropdown(exchange);
    }, 800);

    setInterval(() => {
        refreshStatus();
        const curTab = document.body.dataset.activeTab || '';
        const mobTab = document.body.dataset.mobTab || '';
        if (curTab === 'position' || mobTab === 'position' || curTab === 'history' || mobTab === 'history') {
            window.fetchPositions();
            if (typeof window.fetchTradeHistory === 'function') window.fetchTradeHistory();
        }
    }, 3000);
    setInterval(refreshBalance, 10000);
});

window.applyQuickPosLeverage = async function() {
    const sel = $('quickPosLevSelect');
    if (!sel) return;
    const lev = parseInt(sel.value, 10);
    const sym = activeSymbol || (coins.length ? coins[0] : 'BTCUSDT');
    if (!lev || isNaN(lev)) return;

    const btn = $('btnQuickSetLev');
    try {
        if (btn) { btn.textContent = '...'; btn.disabled = true; }
        const r = await fetch('/api/leverage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ leverage: lev, symbol: sym })
        });
        const res = await r.json();
        if (res.success) {
            if ($('posLeverage')) $('posLeverage').textContent = `${lev}x`;
            if ($('leverage')) $('leverage').value = lev;
            if (typeof logMsg === 'function') logMsg(`⚡ Leverage updated to ${lev}x for ${sym}`, 'success');
        } else {
            alert(res.error || 'Failed to update leverage');
        }
    } catch (e) {
        console.error('applyQuickPosLeverage error:', e);
    } finally {
        if (btn) { btn.textContent = 'Set'; btn.disabled = false; }
    }
};

window.fetchReferralData = async function() {
    try {
        const res = await fetch('/api/user/referral');
        if (!res.ok) return;
        const d = await res.json();
        if (d.success) {
            if ($('modalUserName')) $('modalUserName').textContent = d.user?.name || d.user?.email || 'Trader';
            if ($('modalUserEmail')) $('modalUserEmail').textContent = d.user?.email || '--';
            const initial = (d.user?.name || d.user?.email || 'U')[0].toUpperCase();
            if ($('accountBtnInitial')) $('accountBtnInitial').textContent = initial;
            if ($('modalUserAvatar')) $('modalUserAvatar').textContent = initial;
            if ($('modalRefCode')) $('modalRefCode').value = d.referral_code || '--';
            if ($('modalRefLink')) $('modalRefLink').value = d.referral_link || `${window.location.origin}/?ref=${d.referral_code || ''}`;
            if ($('statRefUsers')) $('statRefUsers').textContent = d.referrals_count || 0;
            if ($('statRefEarned')) $('statRefEarned').textContent = '$' + (Number(d.commissions_earned || 0)).toFixed(2);
            if ($('statRefAvailable')) $('statRefAvailable').textContent = '$' + (Number(d.payout_balance || 0)).toFixed(2);
            if ($('modalPayoutWalletInput') && d.payout_wallet) $('modalPayoutWalletInput').value = d.payout_wallet;
        }
    } catch (e) {
        // Silently skip if running in standalone engine mode
    }
};

window.requestPayout = async function() {
    const wallet = $('modalPayoutWalletInput')?.value.trim();
    if (!wallet) {
        alert('Please enter your USDT payout wallet address.');
        return;
    }
    const btn = $('btnRequestWithdrawal');
    try {
        if (btn) { btn.textContent = 'Processing...'; btn.disabled = true; }
        const res = await fetch('/api/user/request-payout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ wallet: wallet })
        });
        const d = await res.json();
        if (d.success) {
            alert('Withdrawal request submitted successfully! Admin will process your transfer.');
            window.fetchReferralData();
        } else {
            alert(d.error || 'Failed to submit withdrawal request.');
        }
    } catch (e) {
        alert('Error submitting withdrawal: ' + (e.message || e));
    } finally {
        if (btn) { btn.textContent = 'Withdraw'; btn.disabled = false; }
    }
};

