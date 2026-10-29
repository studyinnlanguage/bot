"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { Home, LayoutGrid, Zap, Wallet, User, Wifi, BatteryFull, Signal } from "lucide-react";
import { AuthScreen, ConnectingScreen } from "@/components/wx/auth";
import { HomeTab, MarketsTab } from "@/components/wx/home-markets";
import { BotTab } from "@/components/wx/bot-tab";
import { WalletTab, ProfileTab } from "@/components/wx/wallet-profile";
import { YELLOW, GREEN } from "@/components/wx/types";
import type { EngineResponse, EngineSnapshot, MarketData, WxUser, ApiKeyRow, Txn } from "@/components/wx/types";

type Tab = "home" | "markets" | "bot" | "wallet" | "profile";

const NAV: { id: Tab; icon: typeof Home; label: string; center?: boolean }[] = [
  { id: "home", icon: Home, label: "Home" },
  { id: "markets", icon: LayoutGrid, label: "Markets" },
  { id: "bot", icon: Zap, label: "Bot", center: true },
  { id: "wallet", icon: Wallet, label: "Wallet" },
  { id: "profile", icon: User, label: "Profile" },
];

export default function Page() {
  const { toast } = useToast();
  const [phase, setPhase] = useState<"splash" | "auth" | "connecting" | "app">("splash");
  const [token, setToken] = useState("");
  const [user, setUser] = useState<WxUser | null>(null);
  const [engine, setEngine] = useState<EngineSnapshot | null>(null);
  const [market, setMarket] = useState<MarketData>({});
  const [tab, setTab] = useState<Tab>("home");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [busy, setBusy] = useState<string | null>(null);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [connectName, setConnectName] = useState("");
  const [clock, setClock] = useState("");
  const tokenRef = useRef("");
  tokenRef.current = token;

  const notify = useCallback((msg: string) => toast({ description: msg }), [toast]);

  const authHeaders = useCallback((): HeadersInit => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (tokenRef.current) h["Authorization"] = `Bearer ${tokenRef.current}`;
    return h;
  }, []);

  /* session bootstrap */
  useEffect(() => {
    const saved = localStorage.getItem("wx_token") || sessionStorage.getItem("wx_token");
    if (!saved) { setPhase("auth"); return; }
    setToken(saved);
    tokenRef.current = saved;
    (async () => {
      try {
        const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${saved}` } });
        if (!res.ok) throw new Error("expired");
        const data = await res.json();
        setUser(data.user); setKeys(data.keys); setTxns(data.txns);
        setConnectName(data.user.name);
        setPhase("connecting");
        setTimeout(() => setPhase("app"), 1600);
      } catch {
        localStorage.removeItem("wx_token"); sessionStorage.removeItem("wx_token");
        setPhase("auth");
      }
    })();
  }, []);

  /* live polling */
  useEffect(() => {
    if (phase !== "app" || !token) return;
    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch("/api/engine", { headers: { Authorization: `Bearer ${token}` } });
        if (res.status === 401) {
          localStorage.removeItem("wx_token"); sessionStorage.removeItem("wx_token");
          setPhase("auth"); setToken(""); return;
        }
        const data: EngineResponse = await res.json();
        if (!alive || !data.ok) return;
        setEngine(data.engine); setMarket(data.market); setUser(data.user);
      } catch { /* transient */ }
    };
    void poll();
    const id = setInterval(poll, 2500);
    return () => { alive = false; clearInterval(id); };
  }, [phase, token]);

  /* status bar clock */
  useEffect(() => {
    const upd = () => setClock(new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase());
    upd();
    const id = setInterval(upd, 15000);
    return () => clearInterval(id);
  }, []);

  function handleAuthed(newToken: string, remember: boolean) {
    if (remember) localStorage.setItem("wx_token", newToken);
    else sessionStorage.setItem("wx_token", newToken);
    setToken(newToken);
    tokenRef.current = newToken;
    setPhase("connecting");
    (async () => {
      try {
        const res = await fetch("/api/me", { headers: { Authorization: `Bearer ${newToken}` } });
        const data = await res.json();
        if (res.ok && data.ok) { setUser(data.user); setKeys(data.keys); setTxns(data.txns); }
      } catch { /* non-fatal */ }
      setTimeout(() => setPhase("app"), 1600);
    })();
  }

  async function engineAction(body: Record<string, unknown>, okMsg?: string) {
    try {
      const res = await fetch("/api/engine", { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok || !data.ok) { notify(data.error || "Action failed"); return false; }
      setEngine(data.engine); setMarket(data.market);
      if (okMsg) notify(okMsg);
      return true;
    } catch {
      notify("Network error — check connection");
      return false;
    }
  }

  async function addKey(payload: { exchange: string; apiKey: string; apiSecret: string; label: string }): Promise<boolean> {
    try {
      const res = await fetch("/api/keys", { method: "POST", headers: authHeaders(), body: JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok || !data.ok) { notify(data.error || "Could not save key"); return false; }
      const me = await fetch("/api/me", { headers: authHeaders() });
      const meData = await me.json();
      if (me.ok && meData.ok) { setKeys(meData.keys); setTxns(meData.txns); }
      notify(`${payload.exchange} key linked — engine ab aapke exchange ko use karega`);
      return true;
    } catch {
      notify("Network error");
      return false;
    }
  }

  async function deleteKey(id: string) {
    try {
      await fetch(`/api/keys?id=${id}`, { method: "DELETE", headers: authHeaders() });
      setKeys(prev => prev.filter(k => k.id !== id));
      notify("Key removed");
    } catch { notify("Network error"); }
  }

  async function requestPayout() {
    try {
      const res = await fetch("/api/wallet", { method: "POST", headers: authHeaders(), body: JSON.stringify({ action: "payout" }) });
      const data = await res.json();
      if (!res.ok || !data.ok) { notify(data.error || "Payout failed"); return; }
      const me = await fetch("/api/me", { headers: authHeaders() });
      const meData = await me.json();
      if (me.ok && meData.ok) { setKeys(meData.keys); setTxns(meData.txns); setUser((u) => (u ? { ...u, walletBalance: meData.user.walletBalance } : u)); }
      notify("Payout requested — processing in 24h");
    } catch { notify("Network error"); }
  }

  async function logout() {
    try { await fetch("/api/auth/logout", { method: "POST", headers: authHeaders() }); } catch { /* fine */ }
    localStorage.removeItem("wx_token"); sessionStorage.removeItem("wx_token");
    setToken(""); tokenRef.current = ""; setUser(null); setEngine(null);
    setPhase("auth");
    notify("Logged out — data cloud par safe hai");
  }

  function selectMarket(sym: string) { setSymbol(sym); setTab("bot"); }

  /* ─────────── render ─────────── */

  const screen = (
    <div className="relative flex h-full flex-col overflow-hidden bg-[#05070B] text-white">
      {/* status bar */}
      {phase === "app" && (
        <div className="flex items-center justify-between bg-[#05070B] px-5 pb-1 pt-2">
          <span className="font-mono text-[11px] font-bold text-white">{clock}</span>
          <div className="flex items-center gap-1.5 text-white">
            <Signal className="h-3 w-3" />
            <Wifi className="h-3 w-3" />
            <BatteryFull className="h-4 w-4" />
          </div>
        </div>
      )}

      {/* app header */}
      {phase === "app" && (
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg text-sm font-black text-black" style={{ background: YELLOW }}>W</div>
            <div>
              <p className="text-[13px] font-extrabold leading-tight text-white">Weexionic</p>
              <p className="text-[8px] font-semibold tracking-[0.18em] text-[#6B7488]">CLOUD TRADING</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 rounded-full border px-2 py-0.5 text-[8.5px] font-bold tracking-wider"
              style={{ borderColor: `${GREEN}55`, background: `${GREEN}12`, color: GREEN }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: GREEN, boxShadow: `0 0 6px ${GREEN}` }} /> CLOUD
            </span>
            <span className="rounded-full border px-2 py-0.5 text-[8.5px] font-bold tracking-wider"
              style={{ borderColor: `${YELLOW}44`, background: `${YELLOW}10`, color: YELLOW }}>{user?.plan ?? "PRO"}</span>
          </div>
        </div>
      )}

      {/* body */}
      <div className="flex-1 overflow-y-auto [scrollbar-width:thin]">
        {phase === "splash" && (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3">
              <div className="flex h-14 w-14 animate-pulse items-center justify-center rounded-2xl text-2xl font-black text-black" style={{ background: YELLOW }}>W</div>
              <div className="text-2xl font-extrabold"><span style={{ color: YELLOW }}>WEEX</span><span className="text-white">IONIC</span></div>
            </div>
          </div>
        )}
        {phase === "auth" && <AuthScreen onAuthed={handleAuthed} />}
        {phase === "connecting" && <ConnectingScreen name={connectName || "trader"} />}
        {phase === "app" && user && engine && (
          <>
            {tab === "home" && (
              <HomeTab user={user} engine={engine} keysCount={keys.length} goto={t => setTab(t as Tab)}
                onStart={() => void engineAction({ action: "start" }, "Quad-Trend Engine started")}
                onStop={() => void engineAction({ action: "stop" }, "Engine stopped")}
                onReset={() => void engineAction({ action: "reset" }, "Demo account reset — $10,000 restored")} />
            )}
            {tab === "markets" && <MarketsTab market={market} onSelect={selectMarket} />}
            {tab === "bot" && (
              <BotTab engine={engine} market={market} symbol={symbol} setSymbol={setSymbol} busy={busy}
                onConfig={cfg => { void engineAction({ action: "config", config: cfg }); }}
                onManual={async side => {
                  setBusy(side);
                  await engineAction({ action: "manual", symbol, side });
                  setBusy(null);
                }}
                onClose={id => void engineAction({ action: "close", id })}
                onCloseAll={() => void engineAction({ action: "closeAll" }, "All positions closed")} />
            )}
            {tab === "wallet" && <WalletTab user={user} txns={txns} onToast={notify} onPayout={requestPayout} />}
            {tab === "profile" && (
              <ProfileTab user={user} keys={keys} network={{
                cluster: "WEEXIONIC CLOUD", host: "cloud.weexionic.app",
                region: "auto-assigned on login", client: "Weexionic App v3.0.0", engine: "Native Engine Client",
              }} onLogout={logout} onToast={notify} onAddKey={addKey} onDeleteKey={deleteKey} />
            )}
          </>
        )}
      </div>

      {/* bottom nav */}
      {phase === "app" && (
        <nav className="flex items-end justify-around border-t border-white/[0.07] bg-[#07090D] pb-2 pt-1.5" aria-label="Main navigation">
          {NAV.map(({ id, icon: Icon, label, center }) =>
            center ? (
              <button key={id} onClick={() => setTab(id)} aria-label="Bot terminal"
                className="relative -mt-5 flex h-12 w-12 items-center justify-center rounded-2xl transition-transform active:scale-95"
                style={{ background: YELLOW, boxShadow: `0 6px 20px ${YELLOW}44` }}>
                <Zap className="h-5 w-5 text-black" strokeWidth={2.5} />
                {engine?.running && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-[#07090D]" style={{ background: GREEN }} />}
              </button>
            ) : (
              <button key={id} onClick={() => setTab(id)} aria-label={label}
                className="flex w-14 flex-col items-center gap-0.5 py-1">
                <Icon className="h-5 w-5" style={{ color: tab === id ? YELLOW : "#5A6378" }} strokeWidth={tab === id ? 2.4 : 2} />
                <span className="text-[8.5px] font-semibold" style={{ color: tab === id ? YELLOW : "#5A6378" }}>{label}</span>
              </button>
            )
          )}
        </nav>
      )}
    </div>
  );

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#030405] p-0 sm:p-6">
      {/* desktop ambience */}
      <div className="pointer-events-none fixed inset-0 hidden sm:block">
        <div className="absolute left-1/2 top-1/3 h-[480px] w-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-[0.07]"
          style={{ background: "radial-gradient(circle, #F5C518 0%, transparent 65%)" }} />
      </div>

      {/* phone frame on desktop, full-bleed on mobile */}
      <div className="relative w-full sm:w-[400px]">
        <div className="hidden sm:mb-4 sm:block">
          <p className="text-center text-[11px] font-semibold tracking-[0.22em] text-[#4A5265]">
            WEEXIONIC — QUAD-TREND ENGINE · CLOUD TRADING APP PREVIEW
          </p>
        </div>
        <div className="relative h-[100dvh] w-full overflow-hidden bg-[#05070B] sm:h-[780px] sm:rounded-[42px] sm:border-[7px] sm:border-[#151920] sm:shadow-[0_30px_80px_rgba(0,0,0,0.7),0_0_40px_rgba(245,197,24,0.06)]">
          {/* notch */}
          <div className="absolute left-1/2 top-0 z-50 hidden h-6 w-32 -translate-x-1/2 rounded-b-2xl bg-[#151920] sm:block" />
          {screen}
        </div>
        <p className="mt-4 hidden text-center text-[10px] leading-relaxed text-[#3E4658] sm:block">
          Demo PIN-free login — register any email &amp; password, ya pehle se banaye account se log in karein.
          <br />Data aapki ID se save hota hai — login par wahi terminal, wahi positions.
        </p>
      </div>
    </main>
  );
}
