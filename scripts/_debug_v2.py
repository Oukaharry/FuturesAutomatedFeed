import json, re, sqlite3
db = sqlite3.connect('dashboard/dashboard.db')
cur = db.cursor()
cur.execute("SELECT evaluations FROM clients_data WHERE client_id='Chris'")
evals = json.loads(cur.fetchone()[0])
db.close()

VALID_ACCT = re.compile(r'^[A-Z]{2,5}-[A-Z0-9]{3,6}$')
for i in [15, 16, 18, 31, 32, 56, 62, 63, 66, 67]:
    ev = evals[i]
    a = (ev.get('Account #') or '').strip()
    a1 = (ev.get('Account #.1') or '').strip()
    firm = (ev.get('Prop Firm') or '').strip()
    m_a = bool(VALID_ACCT.match(a))
    m_a1 = bool(VALID_ACCT.match(a1))
    starts_v2_a = a.startswith('V2-')
    starts_v2_a1 = a1.startswith('V2-')
    print(f'Row {i:>3}: firm={firm!r:25} a={a!r:35} valid={m_a} v2={starts_v2_a}  a1={a1!r:35} valid={m_a1} v2={starts_v2_a1}')
