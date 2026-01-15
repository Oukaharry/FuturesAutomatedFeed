import re, os
pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
emails = set()
for root, _, files in os.walk('.'):
    for f in files:
        if f.endswith(('.py', '.json', '.md', '.txt', '.html', '.csv')):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                    text = fh.read()
            except Exception:
                continue
            for m in pattern.findall(text):
                emails.add(m)
for e in sorted(emails, key=lambda s: s.lower()):
    print(e)
