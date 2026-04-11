"""Quick peek at the MT5 HTML report structure to understand the format."""
with open(r'C:\Users\harry\OneDrive\Documents\ReportHistory-3081193.html', 'r', encoding='utf-16') as f:
    content = f.read()

# Find key sections
for keyword in ['Positions', 'Orders', 'Deals', 'History']:
    idx = content.find(f'>{keyword}<')
    if idx >= 0:
        print(f"\n{'='*60}")
        print(f"  Section: {keyword} (at char {idx})")
        print(f"{'='*60}")
        # Show surrounding HTML
        snippet = content[idx-100:idx+1500]
        print(snippet[:1500])
