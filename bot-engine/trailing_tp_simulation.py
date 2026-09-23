"""
Trailing TP Simulation — Exact 1:1 with Leverage Scaling
"""

def simulate(entry, leverage, target_roe_pct=80.0, stages=5):
    print(f"\n{'='*70}")
    print(f"  TRAILING TP SIMULATION (TRUE 1:1 WITH LEVERAGE SCALING)")
    print(f"  Entry = ${entry:,.2f}, Leverage = {leverage}x, Target ROE per stage = {target_roe_pct}%")
    print(f"{'='*70}")

    # 1R price percentage = target_roe_pct / leverage
    target_price_pct = target_roe_pct / leverage
    r_distance = entry * (target_price_pct / 100.0)

    # Initial Stop Loss at 1R (exact 1:1 risk-to-reward, strictly safe from liquidation)
    sl_price = entry - r_distance

    print(f"  1R Price Move : {target_price_pct:.3f}% (${r_distance:,.2f})")
    print(f"  Initial SL    : ${sl_price:,.2f} (-{target_roe_pct:.0f}% ROE Risk [SAFE])")
    print(f"  Initial TP1   : ${entry + r_distance:,.2f} (+{target_roe_pct:.0f}% ROE Target [1:1])")
    print(f"\n  {'Stage':<8} {'Ratio':<8} {'Target Price':<14} {'Price Move':<12} {'ROE @TP':<10} {'SL After Hit':<28} {'Locked ROE':<12}")
    print(f"  {'-'*95}")

    for stage in range(1, stages + 1):
        tp_price = entry + (stage * r_distance)
        move_pct = (tp_price - entry) / entry * 100
        roe = move_pct * leverage

        if stage == 1:
            next_sl = entry
            sl_note = f"Break-even (${next_sl:,.2f})"
            locked_roe = 0
        else:
            locked_stage = stage - 1
            next_sl = entry + (locked_stage * r_distance)
            sl_note = f"TP{locked_stage} (${next_sl:,.2f})"
            locked_roe = locked_stage * target_roe_pct

        print(f"  TP{stage:<6} 1:{stage:<6} ${tp_price:<13.2f} +{move_pct:<10.3f}% +{roe:<8.0f}% {sl_note:<28} +{locked_roe:.0f}% ROE")

    print(f"\n  Risk:Reward at TP1 is EXACTLY 1:1 (Risk = ${r_distance:,.2f}, Reward = ${r_distance:,.2f})")
    print()

def simulate_short(entry, leverage, qty=0.2631, target_roe_pct=100.0, stages=5):
    margin = (entry * qty) / leverage
    print(f"\n{'='*80}")
    print(f"  SHORT TRAILING TP SIMULATION (TRUE 1:1 WITH LEVERAGE SCALING)")
    print(f"  Entry = ${entry:,.2f}, Leverage = {leverage}x, Qty = {qty} BTC, Margin = ${margin:.2f} USDT")
    print(f"  Target ROE per stage = {target_roe_pct}% (100% ROE = +${margin:.2f} USDT profit)")
    print(f"{'='*80}")

    target_price_pct = target_roe_pct / leverage
    r_distance = entry * (target_price_pct / 100.0)

    # Safe SL capped at 80% ROE to guarantee trigger before 125x liquidation (~99% ROE)
    safe_sl_roe = min(target_roe_pct, 80.0)
    sl_distance = entry * ((safe_sl_roe / leverage) / 100.0)
    initial_sl = entry + sl_distance
    tp1 = entry - r_distance

    print(f"  1R Price Move : {target_price_pct:.3f}% (${r_distance:,.2f})")
    print(f"  Initial SL    : ${initial_sl:,.2f} (-{safe_sl_roe:.0f}% ROE Risk [SAFE BEFORE LIQUIDATION])")
    print(f"  Initial TP1   : ${tp1:,.2f} (+{target_roe_pct:.0f}% ROE Target [1:1 / +${margin:.2f} Profit])")
    print(f"\n  {'Stage':<6} {'Ratio':<6} {'Target Price':<14} {'Price Drop':<12} {'ROE':<8} {'Est Profit':<14} {'SL After Hit':<26} {'Locked Profit':<14}")
    print(f"  {'-'*108}")

    for stage in range(1, stages + 1):
        tp_price = entry - (stage * r_distance)
        drop_pct = (entry - tp_price) / entry * 100
        roe = drop_pct * leverage
        profit = (entry - tp_price) * qty

        if stage == 1:
            next_sl = entry
            sl_note = f"Break-even (${next_sl:,.2f})"
            locked_profit = "$0.00 (0 Loss)"
        else:
            locked_stage = stage - 1
            next_sl = entry - (locked_stage * r_distance)
            sl_note = f"TP{locked_stage} (${next_sl:,.2f})"
            locked_profit = f"+${(entry - next_sl) * qty:.2f} USDT"

        print(f"  TP{stage:<4} 1:{stage:<4} ${tp_price:<13.2f} -{drop_pct:<10.3f}% +{roe:<6.0f}% +${profit:<11.2f} {sl_note:<26} {locked_profit:<14}")

    print(f"\n  Risk:Reward at TP1 is EXACT 1:1 (Margin = ${margin:.2f}, Reward = +${(entry - tp1) * qty:.2f})")
    print()

if __name__ == "__main__":
    # User's live SHORT trade:
    simulate_short(entry=84306.50, leverage=125, qty=0.2631, target_roe_pct=100.0)

