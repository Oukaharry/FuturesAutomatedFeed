"""Verify the parse_currency fix"""
import sys
sys.path.insert(0, '.')
from utils.data_processor import parse_currency, fetch_evaluations

print("parse_currency tests:")
print(f"  '-573,79'  -> {parse_currency('-573,79')}   (expect -573.79)")
print(f"  '1,562.00' -> {parse_currency('1,562.00')}  (expect 1562.0)")
print(f"  '-2315.91' -> {parse_currency('-2315.91')} (expect -2315.91)")
print(f"  '1,234'    -> {parse_currency('1,234')}   (expect 1234.0)")
print(f"  '-$76.80'  -> {parse_currency('-$76.80')}  (expect -76.8)")
print(f"  '$1,562.00'-> {parse_currency('$1,562.00')}  (expect 1562.0)")
print(f"  '1.234,56' -> {parse_currency('1.234,56')} (expect 1234.56)")

KEY = '1hA-X9MlxS7EdQ-Zv9ecT4Zhek8h34pF4Rh9arypxt1M'
print()
print("Fetching Nikki evaluations...")
evals, _ = fetch_evaluations(f'https://docs.google.com/spreadsheets/d/{KEY}/edit')
p1cols = ['Hedge Result 1','Hedge Result 2','Hedge Result 3','Hedge Result 4','Hedge Result 5']
fdcols = ['Hedge Result 1.1','Hedge Result 2.1','Hedge Result 3.1','Hedge Result 4.1',
          'Hedge Result 5.1','Hedge Result 6','Hedge Result 7']
p1 = sum(parse_currency(ev.get(c)) for ev in evals for c in p1cols)
fd = sum(parse_currency(ev.get(c)) for ev in evals for c in fdcols)
print(f"SUM(J:N)  = {p1:>12,.2f}")
print(f"SUM(U:AA) = {fd:>12,.2f}")
print(f"TOTAL     = {p1+fd:>12,.2f}  (InProgress hedge, expect -30,959.91)")
print(f"DIFF      = {p1+fd-(-30959.91):>+12,.2f}")
