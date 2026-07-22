"""Compile TRADER_ADMIN_PLAYBOOK.md to standalone HTML."""
import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "TRADER_ADMIN_PLAYBOOK.md"
OUT_PATH = ROOT / "TRADER_ADMIN_PLAYBOOK.html"


def inline_md(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


def md_to_html_body(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    in_ul = in_ol = in_card = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_card():
        nonlocal in_card
        if in_card:
            close_lists()
            out.append("</section>")
            in_card = False

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "---":
            close_card()
            close_lists()
            out.append("<hr>")
            continue
        if not line.strip():
            close_lists()
            continue
        if line.startswith("# "):
            close_card()
            close_lists()
            out.append(f"<h1>{inline_md(line[2:].strip())}</h1>")
            continue
        if line.startswith("## "):
            close_card()
            close_lists()
            title = line[3:].strip()
            m = re.match(r"^(\d+)\.\s+(.+)$", title)
            if m:
                out.append(f'<section class="issue-card" id="issue-{m.group(1)}">')
                in_card = True
                out.append(
                    f"<h2><span class=\"issue-num\">{m.group(1)}.</span> {inline_md(m.group(2))}</h2>"
                )
            else:
                out.append(f"<h2>{inline_md(title)}</h2>")
            continue
        if line.startswith("### "):
            close_lists()
            out.append(f"<h3>{inline_md(line[4:].strip())}</h3>")
            continue
        if re.match(r"^\d+\.\s+", line):
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline_md(re.sub(r'^\d+\.\s+', '', line))}</li>")
            continue
        if line.startswith("- "):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline_md(line[2:].strip())}</li>")
            continue
        m_italic = re.match(r"^\*([^*]+)\*$", line)
        if m_italic:
            close_lists()
            out.append(f"<p class=\"meta\">{inline_md(m_italic.group(1).strip())}</p>")
            continue
        close_lists()
        out.append(f"<p>{inline_md(line)}</p>")

    close_card()
    close_lists()
    return "\n".join(out)


CSS = """
:root {
  --bg: #0f172a;
  --card: #1e293b;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --accent: #fbbf24;
  --border: #334155;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
  font-size: 15px;
}
.wrap { max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 1.75rem; margin: 0 0 8px; color: #fff; }
h2 { font-size: 1.12rem; margin: 0 0 12px; color: #f8fafc; line-height: 1.35; }
h3 { font-size: 1rem; margin: 20px 0 8px; color: var(--accent); }
p { margin: 8px 0; }
p.meta { color: var(--muted); font-size: 0.95rem; }
hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
ul, ol { margin: 8px 0 8px 1.2rem; padding: 0; }
li { margin: 4px 0; }
code { background: #0b1220; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
strong { color: #fff; }
.issue-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
  margin: 16px 0;
}
.issue-num { color: var(--accent); font-weight: 700; margin-right: 4px; }
@media print {
  body { background: #fff; color: #111; }
  .issue-card { break-inside: avoid; border-color: #ccc; background: #f8fafc; }
  strong { color: #000; }
}
"""


def main():
    md = MD_PATH.read_text(encoding="utf-8")
    body = md_to_html_body(md)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trader &amp; Admin Playbook — Quality Issues</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
{body}
  </div>
</body>
</html>
"""
    OUT_PATH.write_text(doc, encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
