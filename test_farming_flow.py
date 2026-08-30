#!/usr/bin/env python3
"""Simulate the exact GUI flow to find where farming trade gets filtered"""

import sys
sys.path.insert(0, r'c:\Users\harry\Music\MT5HedgingEngine')

from datetime import datetime, timedelta
from trader_companion.trader_app import MT5DataPusher
import requests

print("=" * 80)
print("FARMING TRADE DETECTION FLOW TEST")
print("=" * 80)

# Get the evaluation from API
email = "harryodhiambo16@gmail.com"
dashboard_url = "https://www.tradeopss.com"

print(f"1. Fetching evaluations from API for {email}...")
response = requests.post(
    f"{dashboard_url}/api/client/data",
    json={"email": email},
    headers={"Content-Type": "application/json"},
    timeout=15
)

data = response.json()
evaluations = data.get("evaluations", [])
print(f"   ✅ Got {len(evaluations)} evaluations")
print()

# Find the Funded Next Flex evaluation with TUESDAY placeholder
target_eval = None
for ev in evaluations:
    if (ev.get('Account #') == 'FNFTCHHARRISONOUKA17586' and 
        ev.get('Account #.1') == 'FNFTFAHARRISONOUKA79286'):
        target_eval = ev
        break

if not target_eval:
    print("❌ Could not find target evaluation")
    sys.exit(1)

print(f"2. Found target evaluation:")
print(f"   Account #: {target_eval.get('Account #')}")
print(f"   Account #.1: {target_eval.get('Account #.1')}")
print(f"   Status: {target_eval.get('Status')}")
print(f"   Hedge Day 9: {target_eval.get('Hedge Day 9')}")
print(f"   _is_active: {target_eval.get('_is_active')}")
print()

# Create a minimal MT5DataPusher instance to access the helper methods
class TestApp:
    def __init__(self):
        # Initialize minimal attributes needed for the methods
        self.prop_firm_mgr = None
        
    _DAY_ABBREVS = {
        "mon": 0, "monday": 0,
        "tue": 1, "tues": 1, "tuesday": 1,
        "wed": 2, "weds": 2, "wednesday": 2,
        "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }
    
    _ALL_PHASE_FIELD_SETS = [
        ("Challenge",  [f"Hedge Result {i}" for i in range(1, 6)]),
        ("Funded",     [f"Hedge Result {i}.1" for i in range(1, 8)]),
        ("Farming",    [f"Hedge Day {i}" for i in range(1, 35)]),
    ]
    
    _FAILED_STATUSES = {"fail", "failed", "breach", "delete", "deleted", "closed", "sl", "ended", "lost"}
    _INACTIVE_KEYWORDS = ("fail", "breach", "delete", "closed", "ended", "lost")
    
    @staticmethod
    def _cell(val):
        if val is None:
            return ""
        s = str(val).strip()
        return "" if s in ("", "—", "-", "–", "n/a", "na", "tbd", "pending", "none") else s
    
    @classmethod
    def _parse_day_token(cls, value):
        if value is None:
            return None
        s = str(value).strip().lower()
        for tok in s.split():
            tok = tok.strip()
            if tok in cls._DAY_ABBREVS:
                return cls._DAY_ABBREVS[tok]
        return None
    
    def _has_passed_to_funded(self, ev):
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        return bool(ch and fu)
    
    def _is_funded_only_row(self, ev):
        ch = self._cell(ev.get("Account #"))
        fu = self._cell(ev.get("Account #.1"))
        return bool(fu) and not ch
    
    def _on_funded_leg(self, ev):
        return self._has_passed_to_funded(ev) or self._is_funded_only_row(ev)
    
    def _detect_eval_phase(self, ev):
        """The FIXED version"""
        challenge_status = self._cell(ev.get("Status P1")).lower()
        funded_status = self._cell(ev.get("Status")).lower()
        has_funded_acct = bool(self._cell(ev.get("Account #.1")))
        passed_funded = self._has_passed_to_funded(ev)

        # Check if farming data exists — look for Hedge Day cell data with or without
        # the Prop Day marker (some dashboard views don't include Prop Day columns)
        has_farming_marker = bool(self._cell(ev.get("Prop Day 1")))
        has_hedge_day_data = False
        has_hedge_day_placeholder = False
        for i in range(1, 35):
            val = self._cell(ev.get(f"Hedge Day {i}"))
            if val and val not in ("—", "-"):
                has_hedge_day_data = True
                # Check if it's a day-name placeholder (not a dollar value)
                if self._parse_day_token(val) is not None:
                    has_hedge_day_placeholder = True
                    break

        # Farming if: (1) explicit marker + data, OR (2) day placeholder exists
        if (has_farming_marker and has_hedge_day_data) or has_hedge_day_placeholder:
            return "Farming", "farming"
        
        # Both Account # + Account #.1 → eval passed; never trade challenge leg.
        if passed_funded:
            return "Funded", "funded_trade1"
        elif has_funded_acct and funded_status not in self._FAILED_STATUSES:
            return "Funded", "funded_trade1"
        elif challenge_status in self._FAILED_STATUSES:
            return "Challenge", "challenge_trade1"
        else:
            return "Challenge", "challenge_trade1"
    
    def _phase_field_sets_for_scan(self, ev):
        if self._on_funded_leg(ev):
            phase_display, _ = self._detect_eval_phase(ev)
            names = ("Funded",) if phase_display != "Farming" else ("Funded", "Farming")
            return [(n, flist) for n, flist in self._ALL_PHASE_FIELD_SETS if n in names]
        return self._ALL_PHASE_FIELD_SETS
    
    def _classify_day_placeholder(self, day_num, today_weekday):
        if today_weekday >= 5:
            return "future"
        if day_num == today_weekday:
            return "today"
        if today_weekday == 4 and day_num == 0:
            return "future"
        if day_num < today_weekday:
            return "past"
        return "future"
    
    def _scan_day_placeholders(self, ev, phase_sets, target_weekday=None):
        found_any = False
        for _phase, fields in phase_sets:
            for f in fields:
                val = ev.get(f)
                if val is None:
                    continue
                day_num = self._parse_day_token(val)
                if day_num is None:
                    continue
                found_any = True
                if target_weekday is None:
                    continue
                bucket = self._classify_day_placeholder(day_num, target_weekday)
                if bucket in ("today", "past"):
                    return True, True
        if target_weekday is not None:
            return False, found_any
        return found_any, found_any
    
    def _funded_leg_exhausted(self, ev):
        if not self._cell(ev.get("Account #.1")):
            print("      _funded_leg_exhausted: No Account #.1")
            return False
        
        # Detect current phase to check the right fields
        phase_display, _ = self._detect_eval_phase(ev)
        print(f"      _funded_leg_exhausted: Phase = {phase_display}")
        
        # Farming accounts check Hedge Day fields, not Hedge Result fields
        if phase_display == "Farming":
            fields = [f"Hedge Day {i}" for i in range(1, 35)]
        else:
            fields = [f"Hedge Result {i}.1" for i in range(1, 8)]
        
        print(f"      _funded_leg_exhausted: Checking {len(fields)} {phase_display} fields")
        placeholders = 0
        results = 0
        for f in fields:
            val = self._cell(ev.get(f))
            if not val or val in ("—", "-"):
                continue
            if self._parse_day_token(val) is not None:
                placeholders += 1
                print(f"      _funded_leg_exhausted: {f}={val} is PLACEHOLDER")
            else:
                try:
                    float(val.replace("$", "").replace(",", ""))
                    results += 1
                    print(f"      _funded_leg_exhausted: {f}={val} is RESULT")
                except ValueError:
                    print(f"      _funded_leg_exhausted: {f}={val} is UNKNOWN")
        exhausted = results >= 2 and placeholders == 0
        print(f"      _funded_leg_exhausted: results={results}, placeholders={placeholders}, exhausted={exhausted}")
        return exhausted
    
    def _funded_leg_tradeable(self, ev, weekday):
        print(f"   _funded_leg_tradeable: Checking...")
        if self._funded_leg_exhausted(ev):
            print(f"   _funded_leg_tradeable: EXHAUSTED - returning False")
            return False
        funded_st = self._cell(ev.get("Status")).lower()
        print(f"   _funded_leg_tradeable: Status = '{funded_st}'")
        if funded_st and any(kw in funded_st for kw in (
                "complete", "completed", "paid", "payout", "closed",
                *self._INACTIVE_KEYWORDS)):
            print(f"   _funded_leg_tradeable: Status has inactive keyword - returning False")
            return False
        phase_sets = self._phase_field_sets_for_scan(ev)
        print(f"   _funded_leg_tradeable: Scanning {len(phase_sets)} phase sets...")
        today_ok, _found = self._scan_day_placeholders(ev, phase_sets, weekday)
        print(f"   _funded_leg_tradeable: today_ok={today_ok}, _found={_found}")
        return bool(today_ok)
    
    def _has_placeholder_for_weekday(self, ev, weekday):
        passed_funded = self._has_passed_to_funded(ev)
        if passed_funded or self._is_funded_only_row(ev):
            return self._funded_leg_tradeable(ev, weekday)

        phase_sets = self._phase_field_sets_for_scan(ev)
        today_scoped, found_any_scoped = self._scan_day_placeholders(
            ev, phase_sets, weekday)
        if today_scoped:
            return True
        if not found_any_scoped:
            return False
        return False

app = TestApp()

# Simulate today being Monday (1 = Tuesday)
today_weekday = 1  # Tuesday
print(f"3. Simulating today as TUESDAY (weekday={today_weekday})...")
print()

# Test phase detection
print("4. Testing _detect_eval_phase()...")
phase_display, phase_key = app._detect_eval_phase(target_eval)
print(f"   Phase detected: {phase_display} ({phase_key})")
print()

# Test if on funded leg
print("5. Testing _on_funded_leg()...")
on_funded = app._on_funded_leg(target_eval)
print(f"   On funded leg: {on_funded}")
print()

# Test phase field sets for scan
print("6. Testing _phase_field_sets_for_scan()...")
phase_sets = app._phase_field_sets_for_scan(target_eval)
print(f"   Phase sets to scan:")
for phase_name, fields in phase_sets:
    print(f"      - {phase_name}: {len(fields)} fields")
    # Show first few fields
    print(f"        {fields[:5]}...")
print()

# Test scan day placeholders
print("7. Testing _scan_day_placeholders()...")
today_ok, found_any = app._scan_day_placeholders(target_eval, phase_sets, today_weekday)
print(f"   Today OK: {today_ok}")
print(f"   Found any: {found_any}")
print()

# Check each field manually
print("8. Manual field check:")
for phase_name, fields in phase_sets:
    print(f"   {phase_name} fields:")
    for field in fields:
        val = target_eval.get(field)
        if val:
            day_num = app._parse_day_token(val)
            if day_num is not None:
                bucket = app._classify_day_placeholder(day_num, today_weekday)
                print(f"      {field}: {val} -> day_num={day_num}, bucket={bucket}")
print()

# Test funded leg tradeable
print("9. Testing _funded_leg_tradeable()...")
tradeable = app._funded_leg_tradeable(target_eval, today_weekday)
print(f"   Funded leg tradeable: {tradeable}")
print()

# Test has placeholder for weekday
print("10. Testing _has_placeholder_for_weekday()...")
has_placeholder = app._has_placeholder_for_weekday(target_eval, today_weekday)
print(f"    Has placeholder for Tuesday: {has_placeholder}")
print()

# Final verdict
print("=" * 80)
print("VERDICT")
print("=" * 80)
if has_placeholder:
    print("✅ SHOULD BE DETECTED AS ACTIVE!")
else:
    print("❌ WILL BE FILTERED OUT")
print("=" * 80)
