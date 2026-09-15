# Blue Guardian Reserve Simulation Notes

This document records the agreed test/simulation behavior. It is test documentation only.

## Scope

The current test simulation models one Blue Guardian Reserve 50K account through the funded lifecycle:

```text
FD1 -> four farming days -> payout reset -> FD2 -> four farming days -> payout reset -> FD3 -> four farming days -> payout reset -> FD4
```

The simulation can stop early when a funded or farming trade loses, or when the account is below the funded-trade eligibility balance.

## Contract Values

Blue Guardian farming uses **one NQ mini**, not MNQ:

```text
Farming symbol: NQ
Contract size: 1 mini
Tick value: $5.00
```

Therefore:

```text
Farming TP = 31 ticks = $155.00
Farming SL = SL ticks * $5.00
```

The simulator must not convert Blue Guardian farming results using the MNQ `$0.50` tick value.

## Funded Lifecycle

### FD1

- Starting balance: exactly `$50,000`.
- Select the FD1 target according to the Blue Guardian FD1 randomization rule.
- TP is derived from the selected target.
- FD1 stop: `200` ticks in the current Reserve test behavior.
- A loss stops the account lifecycle.
- A win moves the account into farming.

### Farming

After a funded win, simulate four farming days.

For each farming day, print:

- Farming day number
- Balance before the trade
- TP ticks
- SL ticks
- Result: `WIN` or `LOSS`
- Balance after the trade

The current farming randomization is:

- TP: fixed at `31` ticks.
- SL base: per-account random base in the Reserve range.
- Daily jitter: re-drawn for each farming day.
- Final SL is clamped to the Reserve limits.
- Farming result conversion uses `$5.00` per tick.

A farming loss does not automatically stop the account. Farming continues while the balance remains at or above the locked floor of `$50,100`. The account is breached only when the balance falls below `$50,100`; then farming stops and no payout or next funded trade is created.

### Payout Reset

After all four farming days succeed:

```text
profit_above_50k = farming_balance - 50,000
payout = profit_above_50k / 2
next_funded_balance = 50,000 + profit_above_50k / 2
```

Example:

```text
Farming balance:       $56,000
Profit above $50,000:  $6,000
Payout:                $3,000
Next funded balance:   $53,000
```

The next funded trade must randomize from this retained post-payout balance, not from `$50,000` and not from the pre-payout balance.

### FD2-FD4

- FD2, FD3, and FD4 use the current retained live balance after the previous payout.
- Each funded trade receives a new target draw according to the Reserve FT2+ rule.
- TP and SL are calculated from the balance passed into that trade.
- A funded loss stops that account's lifecycle.
- A funded win starts another four-day farming sequence.
- FD2-FD4 are gated unless the starting balance is at least `$50,100`.

## Required Output

The test output should make the complete lifecycle visible for each account. At minimum, each account should show:

```text
Account
FD1: balance, target, TP ticks, SL ticks, result, next balance
Farming day 1: balance, TP ticks, SL ticks, result, next balance
Farming day 2: balance, TP ticks, SL ticks, result, next balance
Farming day 3: balance, TP ticks, SL ticks, result, next balance
Farming day 4: balance, TP ticks, SL ticks, result, next balance
Farming day 4: balance, TP ticks, SL ticks, result, next balance
Payout: pre-payout balance, payout amount, retained balance
FD2 / FD3 / FD4: same funded fields when reached
Final status: completed, failed, or gated
```

Failed and gated accounts must remain visible in the output. They must not be silently removed from the report.

## Test Command

From the repository root:

```bash
/Users/ouka/Projects/tradeops-ai/.venv/bin/python tests/simulate_blue_guardian.py \
	--accounts 4 --seed 20260915 --json tests/blue_guardian_reserve.json
```

The simulator writes the JSON fixture to:

```text
tests/blue_guardian_reserve.json
```

## Production-Code Boundary

Until explicitly authorized, changes are limited to:

- Test scripts
- Test fixtures
- Test assertions
- Test reports
- Test documentation

Do not edit production implementation files such as:

- `trader_companion/prop_firm_manager.py`
- `trader_companion/trader_app.py`
- Broker connectors

The production Blue Guardian changes, if any, will be reviewed only after the test behavior and expected lifecycle output are agreed.
