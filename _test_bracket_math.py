"""
Test: Which conversion is correct for _resolve_bracket_price?

NQ specs:
  tick_size  = 0.25  (price movement per tick)
  tick_value = $5.00 (dollar value per tick per NQ contract)

Blueprint values from prop_firm_manager.py (MFFU Challenge Trade 1, 50k):
  tradovate_tp_ticks = 151
  tradovate_sl_ticks = 200
  tradovate_qty      = 2
  mt5_tp_points      = 46
  mt5_sl_points      = 42
  mt5_volume         = 2.8

Expected profit formula (from predict_next_trade):
  stage_profit = qty * tp_ticks * tick_val
  = 2 * 151 * $5.00 = $1,510

MFFU Challenge target = $3,020
  Trade 1: $1,510
  Trade 2: $1,510
  Total:   $3,020  ✓
"""

# ── NQ Contract Specs ──
TICK_SIZE  = 0.25    # price per tick
TICK_VALUE = 5.00    # $/tick/contract
ENTRY      = 21500.00  # hypothetical entry price

# ── Blueprint: MFFU Challenge Trade 1 ──
TRADO_TP   = 151     # tradovate_tp_ticks
TRADO_SL   = 200     # tradovate_sl_ticks
TRADO_QTY  = 2

MT5_TP     = 46      # mt5_tp_points (NAS100 price points)
MT5_SL     = 42
MT5_VOL    = 2.8

# ── Expected from predict_next_trade formula ──
EXPECTED_PROFIT = TRADO_QTY * TRADO_TP * TICK_VALUE  # 2 * 151 * 5 = $1,510

print("=" * 70)
print("BRACKET PRICE CONVERSION TEST")
print("=" * 70)
print(f"\nNQ: tick_size={TICK_SIZE}, tick_value=${TICK_VALUE}/tick/contract")
print(f"Entry price: {ENTRY}")
print(f"Blueprint: TP={TRADO_TP} ticks, SL={TRADO_SL} ticks, qty={TRADO_QTY}")
print(f"MT5 side:  TP={MT5_TP} pts, SL={MT5_SL} pts, vol={MT5_VOL}")
print(f"\nExpected stage profit (qty × tp × tick_val): ${EXPECTED_PROFIT:,.2f}")

# ────────────────────────────────────────────────────────────
# Approach A: offset = value * tick_size  (treats value as ticks)
#   151 ticks * 0.25 = 37.75 point offset
# ────────────────────────────────────────────────────────────
offset_a = TRADO_TP * TICK_SIZE
tp_price_a = ENTRY + offset_a  # Buy TP
sl_price_a = ENTRY - (TRADO_SL * TICK_SIZE)

# Verify profit: price moves offset_a points → that's offset_a/tick_size ticks
ticks_moved_a = offset_a / TICK_SIZE  # = 151 ticks (same as input)
profit_a = ticks_moved_a * TICK_VALUE * TRADO_QTY

print(f"\n{'─'*70}")
print(f"APPROACH A: offset = value × tick_size  (value is ticks)")
print(f"{'─'*70}")
print(f"  TP offset = {TRADO_TP} × {TICK_SIZE} = {offset_a} points")
print(f"  TP price  = {ENTRY} + {offset_a} = {tp_price_a}")
print(f"  SL offset = {TRADO_SL} × {TICK_SIZE} = {TRADO_SL * TICK_SIZE} points")
print(f"  SL price  = {ENTRY} - {TRADO_SL * TICK_SIZE} = {sl_price_a}")
print(f"  Ticks to TP = {offset_a} / {TICK_SIZE} = {ticks_moved_a}")
print(f"  Profit = {ticks_moved_a} ticks × ${TICK_VALUE} × {TRADO_QTY} = ${profit_a:,.2f}")
print(f"  Matches expected ${EXPECTED_PROFIT:,.2f}? → {'✅ YES' if abs(profit_a - EXPECTED_PROFIT) < 0.01 else '❌ NO'}")

# ────────────────────────────────────────────────────────────
# Approach B: offset = value / tick_size  (treats value as MT5 points)
#   151 / 0.25 = 604 point offset
# ────────────────────────────────────────────────────────────
offset_b = TRADO_TP / TICK_SIZE
tp_price_b = ENTRY + offset_b
sl_price_b = ENTRY - (TRADO_SL / TICK_SIZE)

ticks_moved_b = offset_b / TICK_SIZE  # = 2416 ticks
profit_b = ticks_moved_b * TICK_VALUE * TRADO_QTY

print(f"\n{'─'*70}")
print(f"APPROACH B: offset = value / tick_size  (value is MT5 points)")
print(f"{'─'*70}")
print(f"  TP offset = {TRADO_TP} / {TICK_SIZE} = {offset_b} points")
print(f"  TP price  = {ENTRY} + {offset_b} = {tp_price_b}")
print(f"  SL offset = {TRADO_SL} / {TICK_SIZE} = {TRADO_SL / TICK_SIZE} points")
print(f"  SL price  = {ENTRY} - {TRADO_SL / TICK_SIZE} = {sl_price_b}")
print(f"  Ticks to TP = {offset_b} / {TICK_SIZE} = {ticks_moved_b}")
print(f"  Profit = {ticks_moved_b} ticks × ${TICK_VALUE} × {TRADO_QTY} = ${profit_b:,.2f}")
print(f"  Matches expected ${EXPECTED_PROFIT:,.2f}? → {'✅ YES' if abs(profit_b - EXPECTED_PROFIT) < 0.01 else '❌ NO'}")

# ────────────────────────────────────────────────────────────
# Cross-check with MT5 side
# ────────────────────────────────────────────────────────────
# MT5 NAS100: 1 point = 1.0 price movement, $1/point/lot
mt5_profit_tp = MT5_TP * 1.0 * MT5_VOL  # 46 * 1 * 2.8 = $128.80
mt5_loss_sl   = MT5_SL * 1.0 * MT5_VOL  # 42 * 1 * 2.8 = $117.60

print(f"\n{'─'*70}")
print(f"MT5 HEDGE SIDE (NAS100, opposite direction)")
print(f"{'─'*70}")
print(f"  MT5 TP {MT5_TP} pts × {MT5_VOL} lots = ${mt5_profit_tp:,.2f} (hedge loss if Trado wins)")
print(f"  MT5 SL {MT5_SL} pts × {MT5_VOL} lots = ${mt5_loss_sl:,.2f} (hedge win if Trado loses)")

# ── Net profit with hedge ──
print(f"\n{'─'*70}")
print(f"NET PROFIT SCENARIOS (Tradovate wins, MT5 hedge loses)")
print(f"{'─'*70}")

net_a = profit_a - mt5_profit_tp
net_b = profit_b - mt5_profit_tp

print(f"  Approach A: ${profit_a:,.2f} - ${mt5_profit_tp:,.2f} = ${net_a:,.2f} net")
print(f"  Approach B: ${profit_b:,.2f} - ${mt5_profit_tp:,.2f} = ${net_b:,.2f} net")

# ── Full challenge check ──
print(f"\n{'─'*70}")
print(f"MFFU CHALLENGE FULL VERIFICATION")
print(f"{'─'*70}")
print(f"  Target: $3,020")
print(f"  Trade 1 + Trade 2 (same config, qty=2):")
print(f"    Approach A: 2 × ${profit_a:,.2f} = ${2*profit_a:,.2f}  {'✅ matches $3,020' if abs(2*profit_a - 3020) < 0.01 else '❌ WRONG'}")
print(f"    Approach B: 2 × ${profit_b:,.2f} = ${2*profit_b:,.2f}  {'✅ matches $3,020' if abs(2*profit_b - 3020) < 0.01 else '❌ WRONG'}")

# ── Additional stages ──
print(f"\n{'─'*70}")
print(f"ALL MFFU FUNDED STAGES")
print(f"{'─'*70}")

funded_stages = [
    ("funded",   1, 204, 400, 4.8, 96,  55),
    ("funded_1", 2, 500, 200, 15.8, 46, 129),
    ("funded_2", 2, 300, 290, 18.0, 68,  79),
    ("funded_3", 2, 100, 190, 18.0, 43,  29),
    ("funded_4", 2, 150, 165, 13.6, 37,  42),
]

total_a = 0
total_b = 0
for name, qty, tp, sl, mvol, mtp, msl in funded_stages:
    expected = qty * tp * TICK_VALUE
    pa = qty * (tp * TICK_SIZE / TICK_SIZE) * TICK_VALUE  # Approach A profit = qty * tp * tick_val
    pb = qty * ((tp / TICK_SIZE) / TICK_SIZE) * TICK_VALUE  # Approach B
    total_a += pa
    total_b += pb
    print(f"  {name:10s}: qty={qty}, tp={tp:3d} ticks → "
          f"A=${pa:>10,.2f} {'✅' if abs(pa-expected)<0.01 else '❌'}  "
          f"B=${pb:>10,.2f} {'✅' if abs(pb-expected)<0.01 else '❌'}  "
          f"(expected ${expected:,.2f})")

print(f"\n  Total funded A: ${total_a:,.2f}  (target $1,020 first payout)")
print(f"  Total funded B: ${total_b:,.2f}")

print(f"\n{'=' * 70}")
print(f"CONCLUSION: The values in tradovate_tp_ticks are TICK COUNTS.")
print(f"Correct conversion: offset = value × tick_size")
print(f"  e.g. 151 ticks × 0.25 = 37.75 points price offset")
print(f"  profit = 151 ticks × $5.00 × 2 contracts = $1,510")
print(f"{'=' * 70}")
