from dashboard.watermark_service import compute_waterlog_from_db
r = compute_waterlog_from_db('Chris')
if r:
    for p in r['periods'][-6:]:
        print(f"{p['from_date']:>12} - {p['to_date']:>12}  NP={p['low']:>16}  Split={p['profit_split']:>10}  {p['split_pct']}%")
    print(f"last_split_net_profit: {r['last_split_net_profit']}")
else:
    print("None")
