"""Export a single chapter of CODEBASE_REFERENCE.pdf as plain Markdown
so it can be pasted into another Claude / IDE / chat without the PDF.

By default exports Chapter 3 (Phase 1 — Foundations).  Pass a different
chapter number on the CLI to pick another phase.

Usage:
    python _export_chapter_md.py            # chapter 3 → CHAPTER_03.md
    python _export_chapter_md.py 5          # chapter 5 → CHAPTER_05.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import _codebase_reference_pdf as pdf  # reuse extract_module, PHASES


REPO_ROOT = Path(__file__).resolve().parent


def render_module_md(m: dict) -> list[str]:
    out: list[str] = []
    rel = m["path"].relative_to(REPO_ROOT).as_posix()

    out.append(f"### `{rel}`")
    out.append("")
    out.append(
        f"_{m['loc']} loc · {len(m['classes'])} classes · "
        f"{len(m['functions'])} functions · "
        f"{len(m['imports'])} imports_"
    )
    out.append("")

    if m.get("parse_error"):
        out.append(f"> Could not parse: {m['parse_error']}")
        out.append("")
        return out

    if m["doc"]:
        out.append("**Module docstring**")
        out.append("")
        for para in m["doc"].split("\n\n"):
            para = para.strip().replace("\n", " ")
            if para:
                out.append(f"> {para}")
        out.append("")

    if m["imports"]:
        out.append("**Imports**")
        out.append("")
        out.append("```python")
        for line in m["imports"]:
            out.append(line)
        out.append("```")
        out.append("")

    if m["constants"]:
        out.append("**Module constants**")
        out.append("")
        for const_line in m["constants"]:
            out.append("```python")
            out.append(const_line)
            out.append("```")
            note = pdf.explain_constant(const_line)
            if note:
                # Strip reportlab HTML for plain markdown.
                note_md = (
                    note.replace("<code>", "`").replace("</code>", "`")
                    .replace("&mdash;", "—").replace("&hellip;", "…")
                    .replace("&amp;", "&").replace("&lt;", "<")
                    .replace("&gt;", ">").replace("&nbsp;", " ")
                )
                out.append(f"_{note_md}_")
            out.append("")

    if m["classes"]:
        out.append("**Classes**")
        out.append("")
        for c in m["classes"]:
            header = f"class {c['name']}"
            if c["bases"]:
                header += "(" + ", ".join(c["bases"]) + ")"
            out.append(f"#### `{header}`")
            out.append("")
            for d in c["decorators"]:
                out.append("```python")
                out.append(d)
                out.append("```")
            if c["doc"]:
                out.append(f"> {c['doc'].replace(chr(10), ' ')}")
                out.append("")
            if c["attrs"]:
                out.append("```python")
                for a in c["attrs"]:
                    out.append(a)
                out.append("```")
                out.append("")
            if c.get("excerpt"):
                out.append("```python")
                out.append(c["excerpt"])
                out.append("```")
                out.append("")
            for meth in c["methods"]:
                out.append(f"##### `{c['name']}.{meth['name']}`")
                out.append("")
                out.append("```python")
                out.append(meth["signature"])
                out.append("```")
                if meth["doc"]:
                    out.append(f"> {meth['doc'].replace(chr(10), ' ')}")
                    out.append("")
                if meth.get("steps"):
                    out.append("**What it does, step by step:**")
                    out.append("")
                    for i, step in enumerate(meth["steps"], 1):
                        out.append(f"{i}. {step}")
                    out.append("")
                if meth.get("excerpt"):
                    out.append("```python")
                    out.append(meth["excerpt"])
                    out.append("```")
                    out.append("")

    if m["functions"]:
        out.append("**Functions**")
        out.append("")
        for fn in m["functions"]:
            out.append(f"#### `{fn['name']}`")
            out.append("")
            out.append("```python")
            out.append(fn["signature"])
            out.append("```")
            if fn["doc"]:
                out.append(f"> {fn['doc'].replace(chr(10), ' ')}")
                out.append("")
            if fn.get("steps"):
                out.append("**What it does, step by step:**")
                out.append("")
                for i, step in enumerate(fn["steps"], 1):
                    out.append(f"{i}. {step}")
                out.append("")
            if fn.get("excerpt"):
                out.append("```python")
                out.append(fn["excerpt"])
                out.append("```")
                out.append("")

    return out


def export_chapter(chap_no: int) -> Path:
    """chap_no maps to a phase: chapter 3 = phase 1, chapter 4 = phase 2, ..."""
    phase_idx = chap_no - 3
    if phase_idx < 0 or phase_idx >= len(pdf.BUILD_PHASES):
        raise SystemExit(
            f"Chapter {chap_no} is not a build phase. Build phases run "
            f"from chapter 3 to chapter {2 + len(pdf.BUILD_PHASES)}."
        )
    phase = pdf.BUILD_PHASES[phase_idx]

    lines: list[str] = []
    lines.append(f"# Chapter {chap_no} — {phase['title'].split('— ', 1)[-1]}")
    lines.append("")
    lines.append(
        "_Exported from CODEBASE_REFERENCE.pdf as plain Markdown. "
        "Paste this into another Claude conversation, Notion, or any "
        "Markdown viewer._"
    )
    lines.append("")

    intro = phase["intro"]
    for tag, repl in [("<code>", "`"), ("</code>", "`"), ("<i>", "_"),
                      ("</i>", "_"), ("<b>", "**"), ("</b>", "**")]:
        intro = intro.replace(tag, repl)
    lines.append(intro)
    lines.append("")
    lines.append("**Files in this chapter:**")
    lines.append("")
    for f in phase["files"]:
        lines.append(f"- `{f}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    for rel in phase["files"]:
        path = REPO_ROOT / rel
        if not path.exists():
            lines.append(f"### `{rel}`")
            lines.append("")
            lines.append(f"> File not present in this checkout — skipped.")
            lines.append("")
            continue
        m = pdf.extract_module(path)
        lines.extend(render_module_md(m))
        lines.append("---")
        lines.append("")

    out = REPO_ROOT / f"CHAPTER_{chap_no:02d}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main():
    chap_no = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = export_chapter(chap_no)
    size_kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
