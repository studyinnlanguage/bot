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

if __name__ == "__main__":
    # User's exact live case:
    simulate(entry=84160.20, leverage=125, target_roe_pct=80.0)
    # Lower leverage comparisons:
    simulate(entry=84160.20, leverage=50, target_roe_pct=80.0)
    simulate(entry=84160.20, leverage=10, target_roe_pct=80.0)
