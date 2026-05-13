"""Generate 'Python: The Greatest Hits' — a 12-lesson tutorial PDF
that teaches the most-used Python concepts using real code from the
MT5HedgingEngine codebase.

Output: PYTHON_GREATEST_HITS.pdf at the repo root.

Each lesson follows the same shape:
  1. The idea — concept explanation in two or three sentences.
  2. Real code from the book — actual snippets from this project.
  3. Walkthrough — numbered notes on what each line does and why.
  4. Try it yourself — a small, self-contained exercise.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


REPO_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def make_styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=30, leading=36,
            spaceAfter=14, alignment=1,
            textColor=colors.HexColor("#1a365d"),
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Italic"], fontSize=14, leading=20,
            alignment=1, spaceAfter=12,
            textColor=colors.HexColor("#4a5568"),
        ),
        "tag": ParagraphStyle(
            "tag", parent=base["Normal"], fontSize=11, leading=14,
            alignment=1, spaceAfter=10,
            textColor=colors.HexColor("#1a202c"),
        ),
        "cover_foot": ParagraphStyle(
            "cover_foot", parent=base["Normal"], fontSize=10, leading=13,
            alignment=1,
            textColor=colors.HexColor("#718096"),
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontSize=22, leading=28,
            textColor=colors.HexColor("#1a365d"),
            spaceBefore=10, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=14, leading=18,
            textColor=colors.HexColor("#2c5282"),
            spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=10.5, leading=15,
            spaceAfter=8,
        ),
        "list_item": ParagraphStyle(
            "list_item", parent=base["Normal"], fontSize=10.5, leading=15,
            leftIndent=20, bulletIndent=6, spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontSize=8.5, leading=11,
            leftIndent=12, rightIndent=4,
            spaceBefore=4, spaceAfter=8,
            textColor=colors.HexColor("#1a202c"),
            backColor=colors.HexColor("#f1f5f9"),
            borderColor=colors.HexColor("#cbd5e0"),
            borderWidth=0.4, borderPadding=8,
        ),
        "callout_body": ParagraphStyle(
            "callout_body", parent=base["Normal"], fontSize=10.5,
            leading=15, spaceAfter=6,
        ),
        "callout_heading_blue": ParagraphStyle(
            "callout_heading_blue", parent=base["Normal"], fontSize=12,
            leading=15, spaceAfter=6,
            textColor=colors.HexColor("#1a365d"),
        ),
        "callout_heading_orange": ParagraphStyle(
            "callout_heading_orange", parent=base["Normal"], fontSize=12,
            leading=15, spaceAfter=6,
            textColor=colors.HexColor("#9c4221"),
        ),
    }
    return s


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------


def on_page(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    if page_num > 1:
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#a0aec0"))
        canvas.drawRightString(
            LETTER[0] - 0.7 * inch, 0.45 * inch, str(page_num),
        )
        canvas.drawString(
            0.7 * inch, 0.45 * inch,
            "Python: The Greatest Hits",
        )
    canvas.restoreState()


def callout(content_flowables, doc_width, kind="blue"):
    """Render a colored callout box (blue or orange-tinted)."""
    if kind == "orange":
        bg = colors.HexColor("#fef3e7")
        border = colors.HexColor("#dd6b20")
    else:
        bg = colors.HexColor("#ebf4ff")
        border = colors.HexColor("#3182ce")
    t = Table(
        [[content_flowables]],
        colWidths=[doc_width - 0.2 * inch],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, 0), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


# ---------------------------------------------------------------------------
# Code helpers
# ---------------------------------------------------------------------------


def code(text: str) -> Preformatted:
    """Render a code block.  Lines are kept verbatim — copy-paste safe."""
    return Preformatted(text.rstrip("\n"), make_styles()["code"])


def numbered_step(n: int, body: str, styles) -> Paragraph:
    """A numbered step in a Walkthrough or 'How to keep practising' list.

    The step counter is global across lessons (1..51 in the reference
    PDF), matching the format of the source document.
    """
    return Paragraph(
        f"<b>{n}.</b>&nbsp;&nbsp;{body}",
        styles["list_item"],
    )


def bullet(body: str, styles) -> Paragraph:
    return Paragraph(f"&bull;&nbsp;&nbsp;{body}", styles["list_item"])


# ---------------------------------------------------------------------------
# Story builders for each lesson
# ---------------------------------------------------------------------------


class StepCounter:
    """Walkthrough numbering continues across lessons in the source
    document (1, 2, ... 51).  This counter keeps the same property."""
    def __init__(self, start: int = 1):
        self.n = start

    def next(self) -> int:
        v = self.n
        self.n += 1
        return v


def cover(story, styles, doc_width):
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("Python: The Greatest Hits", styles["title"]))
    story.append(Paragraph(
        "A step-by-step tutorial using real code<br/>"
        "from the MT5HedgingEngine codebase",
        styles["subtitle"],
    ))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "12 lessons &middot; ~30 minutes each &middot; type the code yourself",
        styles["tag"],
    ))
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(
        "For learners who can already write a function",
        styles["cover_foot"],
    ))
    story.append(PageBreak())


def how_to_use(story, styles, doc_width):
    story.append(Paragraph("How to use this guide", styles["h1"]))
    story.append(Paragraph(
        "This guide picks twelve Python concepts that show up everywhere "
        "in real codebases &mdash; the ones that separate a script that "
        "runs from code that <b>scales, reads cleanly, and is easy to "
        "change later</b>. Each lesson has the same shape:",
        styles["body"],
    ))
    story.append(Paragraph(
        "<b>1.</b>&nbsp;&nbsp;<b>The idea</b> &mdash; what the concept is, "
        "in two or three sentences.", styles["list_item"],
    ))
    story.append(Paragraph(
        "<b>2.</b>&nbsp;&nbsp;<b>Real code from the book</b> &mdash; an "
        "actual snippet from the MT5HedgingEngine project, lightly "
        "trimmed.", styles["list_item"],
    ))
    story.append(Paragraph(
        "<b>3.</b>&nbsp;&nbsp;<b>Walkthrough</b> &mdash; what each line is "
        "doing and why it was written that way.", styles["list_item"],
    ))
    story.append(Paragraph(
        "<b>4.</b>&nbsp;&nbsp;<b>Try it yourself</b> &mdash; a small, "
        "self-contained exercise you can run in any Python REPL.",
        styles["list_item"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(
        "<b>Before you start:</b> you need Python 3.10 or newer. Open a "
        "terminal and run <font face='Courier'>python --version</font>. "
        "If you see something below 3.10, install a newer one before "
        "continuing &mdash; a couple of the snippets use modern syntax "
        "(like <font face='Courier'>int | None</font>) that older versions "
        "reject.", styles["body"],
    ))
    story.append(Paragraph(
        "<b>How to actually do this:</b> create a folder called "
        "<font face='Courier'>greatest_hits</font>, and for each lesson "
        "make a file like <font face='Courier'>01_modules.py</font>, "
        "<font face='Courier'>02_classes.py</font>, and so on. <b>Type "
        "the code in by hand.</b> Don't paste it. The small typos and "
        "&ldquo;wait, why does that work?&rdquo; moments are where the "
        "learning lives.", styles["body"],
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(callout([
        Paragraph("<b>About the source codebase</b>",
                  styles["callout_heading_blue"]),
        Paragraph(
            "The examples come from <b>MT5HedgingEngine</b> &mdash; a real "
            "Python project (~51,000 lines, 72 files) that connects to "
            "the MetaTrader 5 trading platform, scrapes prop-firm "
            "dashboards in a headless browser, and serves a Flask web "
            "app on top. You don't need to understand trading to follow "
            "the tutorial &mdash; every snippet is presented standalone. "
            "The trading context is only there to give the code something "
            "real to <b>do</b>.", styles["callout_body"],
        ),
        Paragraph(
            "Where the original code contained sample credentials or URLs, "
            "I've replaced them with empty defaults or placeholders so you "
            "can read the pattern without copying anything sensitive.",
            styles["callout_body"],
        ),
    ], doc_width))
    story.append(PageBreak())


def lesson_modules(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 1 &mdash; Modules and packages", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "Every <font face='Courier'>.py</font> file is a <b>module</b>. "
        "A folder that contains an <font face='Courier'>__init__.py</font> "
        "file (even an empty one) is a <b>package</b>. When you write "
        "<font face='Courier'>from trader_companion.signals import sma</font>, "
        "Python finds the file <font face='Courier'>trader_companion/signals/sma.py</font>, "
        "runs it from top to bottom <i>once</i>, and exposes the names "
        "defined inside (functions, classes, constants) under that module. "
        "Subsequent imports get the cached version &mdash; the file is "
        "<b>not</b> re-executed.", styles["body"],
    ))
    story.append(Paragraph(
        "This caching matters: if you put code with side effects (writing "
        "files, opening network connections) at module top level, that "
        "code runs the first time anything imports the module &mdash; "
        "sometimes in surprising places.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "The MT5HedgingEngine project organises its trading-signal "
        "calculations into a tiny package. Here is the actual layout:",
        styles["body"],
    ))
    story.append(code(
        "trader_companion/\n"
        "    __init__.py\n"
        "    signals/\n"
        "        __init__.py        # 2 lines — see below\n"
        "        sma.py             # Simple Moving Average\n"
        "        ema.py             # Exponential Moving Average\n"
        "        rsi.py             # Relative Strength Index\n"
        "        macd.py            # MACD\n"
        "        bb.py              # Bollinger Bands\n"
        "        ...                # 25 more indicators"
    ))
    story.append(Paragraph(
        "And here, calling code somewhere else in the project does:",
        styles["body"],
    ))
    story.append(code(
        "from trader_companion.signals import sma, ema, rsi\n"
        "\n"
        "fast = sma.calculate(prices, period=10)\n"
        "slow = ema.calculate(prices, period=50)"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "Putting an empty <font face='Courier'>__init__.py</font> in "
        "<font face='Courier'>signals/</font> tells Python <b>&ldquo;this "
        "folder is a package, not just a folder of scripts.&rdquo;</b>",
        styles))
    story.append(numbered_step(sc.next(),
        "Each indicator lives in its own file. That keeps each module "
        "short, focused, and easy to test in isolation.", styles))
    story.append(numbered_step(sc.next(),
        "Calling code uses dotted paths "
        "(<font face='Courier'>trader_companion.signals.sma</font>) that "
        "mirror the folder structure exactly. If you can read the import, "
        "you can find the file.", styles))
    story.append(numbered_step(sc.next(),
        "The first import of <font face='Courier'>sma</font> runs "
        "<font face='Courier'>sma.py</font> once. Every later import "
        "&mdash; from anywhere in the codebase &mdash; gets the same "
        "cached module object.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph("Create this folder structure on your machine:",
                  styles["callout_body"]),
        code(
            "lesson01/\n"
            "    main.py\n"
            "    mathkit/\n"
            "        __init__.py     # leave it empty\n"
            "        arithmetic.py"
        ),
        Paragraph("In <font face='Courier'>arithmetic.py</font> put:",
                  styles["callout_body"]),
        code(
            'print("arithmetic.py is being executed")\n'
            "\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "def multiply(a, b):\n"
            "    return a * b"
        ),
        Paragraph("In <font face='Courier'>main.py</font> put:",
                  styles["callout_body"]),
        code(
            "from mathkit import arithmetic\n"
            "\n"
            "print(arithmetic.add(2, 3))\n"
            "print(arithmetic.multiply(4, 5))\n"
            "\n"
            "# Import a second time — does the print at the top of arithmetic.py run again?\n"
            "from mathkit import arithmetic\n"
            'print("done")'
        ),
        Paragraph(
            "<b>What you should see:</b> the &ldquo;arithmetic.py is being "
            "executed&rdquo; line prints <b>once</b>, not twice. That's "
            "the import cache at work. Now delete "
            "<font face='Courier'>__init__.py</font> and run again "
            "&mdash; depending on your Python version you may get an "
            "<font face='Courier'>ImportError</font> or a deprecation "
            "warning, because that file is what marks the folder as a "
            "package.", styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_classes(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 2 &mdash; Classes and objects", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "A <b>class</b> is a blueprint. Calling the class &mdash; "
        "<font face='Courier'>Trade(symbol='EURUSD', volume=0.1)</font> "
        "&mdash; runs the special <font face='Courier'>__init__</font> "
        "method to construct an <b>instance</b>. Methods take "
        "<font face='Courier'>self</font> as their first parameter; "
        "Python passes the instance in automatically when you call "
        "<font face='Courier'>trade.close()</font>. Attributes set on "
        "<font face='Courier'>self</font> are per-instance; attributes "
        "set at class scope are shared across all instances.",
        styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "Here is one of the SQLAlchemy ORM models from "
        "<font face='Courier'>dashboard/models.py</font>. It maps a "
        "Python class to a database table &mdash; every instance of "
        "<font face='Courier'>ApiKey</font> represents one row:",
        styles["body"],
    ))
    story.append(code(
        "from sqlalchemy import Column, Integer, Text, SmallInteger, text\n"
        "from sqlalchemy.orm import DeclarativeBase\n"
        "\n"
        "class Base(DeclarativeBase):\n"
        "    pass\n"
        "\n"
        "class ApiKey(Base):\n"
        "    __tablename__ = 'api_keys'\n"
        "\n"
        "    id          = Column(Integer, primary_key=True, autoincrement=True)\n"
        "    key_hash    = Column(Text, unique=True, nullable=False)\n"
        "    key_prefix  = Column(Text, nullable=False)\n"
        "    admin       = Column(Text, nullable=False)\n"
        "    trader      = Column(Text, nullable=False)\n"
        "    scope       = Column(Text, server_default=text(\"'full'\"))\n"
        "    created_at  = Column(Text, nullable=False)\n"
        "    is_active   = Column(SmallInteger, server_default=text('1'))"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>class ApiKey(Base):</font> defines a new "
        "class that inherits from <font face='Courier'>Base</font> "
        "(more on inheritance in lesson 3).", styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>__tablename__</font> is a <b>class-level</b> "
        "attribute &mdash; every <font face='Courier'>ApiKey</font> "
        "instance shares the same table name. There is no "
        "<font face='Courier'>self</font> because the value belongs to "
        "the class, not to any one instance.", styles))
    story.append(numbered_step(sc.next(),
        "Each <font face='Courier'>Column(...)</font> line is also at "
        "class scope. SQLAlchemy reads them once when the class is "
        "defined, builds an internal description of the table, and uses "
        "that for queries.", styles))
    story.append(numbered_step(sc.next(),
        "When you later write "
        "<font face='Courier'>key = ApiKey(admin='alice', trader='bob', ...)</font>, "
        "SQLAlchemy generates an <font face='Courier'>__init__</font> "
        "that assigns each keyword argument to "
        "<font face='Courier'>self</font>. So "
        "<font face='Courier'>key.admin</font> is "
        "<font face='Courier'>'alice'</font> &mdash; that one's "
        "per-instance.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph(
            "Without any database, build a tiny "
            "<font face='Courier'>Trade</font> class:",
            styles["callout_body"],
        ),
        code(
            "class Trade:\n"
            '    DEFAULT_BROKER = "PlexyTrade"     # class attribute — shared\n'
            "\n"
            "    def __init__(self, symbol, volume, side):\n"
            "        self.symbol = symbol           # instance attributes — unique\n"
            "        self.volume = volume\n"
            "        self.side   = side             # 'buy' or 'sell'\n"
            "        self.is_open = True\n"
            "\n"
            "    def close(self):\n"
            "        self.is_open = False\n"
            '        return f"Closed {self.side} {self.volume} {self.symbol}"\n'
            "\n"
            't1 = Trade("EURUSD", 0.1, "buy")\n'
            't2 = Trade("GBPUSD", 0.05, "sell")\n'
            "\n"
            "print(t1.symbol, t2.symbol)              # different\n"
            "print(t1.DEFAULT_BROKER, t2.DEFAULT_BROKER)  # same\n"
            "print(t1.close())\n"
            "print(t1.is_open, t2.is_open)            # True/False — independent state"
        ),
        Paragraph(
            "<b>Now try this experiment:</b> change "
            "<font face='Courier'>Trade.DEFAULT_BROKER = \"NewBroker\"</font> "
            "(note: <font face='Courier'>Trade</font>, not "
            "<font face='Courier'>t1</font>) and re-print "
            "<font face='Courier'>t1.DEFAULT_BROKER</font>. Both "
            "instances now see the new value, because there's still only "
            "one. That's class-attribute sharing in action.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_inheritance(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 3 &mdash; Inheritance", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "A class can extend another class by listing it in parentheses: "
        "<font face='Courier'>class DevelopmentConfig(Config):</font>. "
        "The subclass gets every method and attribute of the parent for "
        "free, but can <b>override</b> any of them by redefining it. "
        "<font face='Courier'>super().method()</font> calls the parent's "
        "version &mdash; useful when you want to <b>extend</b> behaviour "
        "rather than replace it entirely.", styles["body"],
    ))
    story.append(Paragraph(
        "Inheritance is one form of code reuse. It works well when "
        "subclasses really <b>are a</b> kind of the parent (a "
        "<font face='Courier'>DevelopmentConfig</font> <b>is a</b> "
        "<font face='Courier'>Config</font>). When that's not the case, "
        "prefer composition &mdash; holding another object as an "
        "attribute instead of inheriting from it.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From <font face='Courier'>config/production.py</font> &mdash; "
        "a base config class plus three environment-specific subclasses:",
        styles["body"],
    ))
    story.append(code(
        "class Config:\n"
        '    """Base configuration."""\n'
        "    DEBUG    = False\n"
        "    TESTING  = False\n"
        "    APP_NAME    = 'MT5 Hedging Dashboard'\n"
        "    APP_VERSION = '1.0.1'\n"
        "    SESSION_COOKIE_SECURE   = True   # HTTPS only\n"
        "    SESSION_COOKIE_HTTPONLY = True\n"
        "    DATABASE_TYPE = os.getenv('DATABASE_TYPE', 'sqlite')\n"
        "\n"
        "class DevelopmentConfig(Config):\n"
        '    """Development overrides."""\n'
        "    DEBUG = True\n"
        "    SESSION_COOKIE_SECURE = False     # http is fine on localhost\n"
        "    DATABASE_TYPE = 'sqlite'\n"
        "    LOG_LEVEL = 'DEBUG'\n"
        "\n"
        "class ProductionConfig(Config):\n"
        '    """Production overrides."""\n'
        "    DEBUG = False\n"
        "    SESSION_COOKIE_SECURE = True\n"
        "    LOG_LEVEL = 'INFO'\n"
        "\n"
        "class TestingConfig(Config):\n"
        '    """Test overrides."""\n'
        "    TESTING = True\n"
        "    DATABASE_TYPE = 'sqlite'          # in-memory for tests"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>Config</font> defines the defaults. "
        "Anything that's the <b>same</b> across environments lives here "
        "only once.", styles))
    story.append(numbered_step(sc.next(),
        "Each subclass redeclares only the values it wants to "
        "<b>change</b>. <font face='Courier'>DevelopmentConfig.APP_NAME</font> "
        "doesn't appear, but the lookup walks up to the parent and "
        "returns <font face='Courier'>'MT5 Hedging Dashboard'</font> "
        "anyway.", styles))
    story.append(numbered_step(sc.next(),
        "This is the classic <b>template + variations</b> pattern. Every "
        "Flask app, Django app, and most web frameworks use exactly this "
        "shape for environment configuration.", styles))
    story.append(numbered_step(sc.next(),
        "To pick which one to use, the application reads an environment "
        "variable at startup &mdash; something like "
        "<font face='Courier'>config_class = {'dev': DevelopmentConfig, 'prod': ProductionConfig}[os.getenv('ENV')]</font>.",
        styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph(
            "Build a tiny hierarchy. The mechanic to feel here is "
            "<font face='Courier'>super()</font>:",
            styles["callout_body"],
        ),
        code(
            "class PropFirm:\n"
            "    def __init__(self, name, account_size):\n"
            "        self.name = name\n"
            "        self.account_size = account_size\n"
            "\n"
            "    def describe(self):\n"
            '        return f"{self.name} - ${self.account_size:,}"\n'
            "\n"
            "class Topstep(PropFirm):\n"
            "    def __init__(self, account_size):\n"
            '        super().__init__("Topstep", account_size)   # parent\'s __init__\n'
            "        self.daily_loss_limit = account_size * 0.03\n"
            "\n"
            "    def describe(self):\n"
            "        base = super().describe()                   # parent's version\n"
            '        return f"{base} (daily loss: ${self.daily_loss_limit:,.0f})"\n'
            "\n"
            "ts = Topstep(50_000)\n"
            "print(ts.describe())\n"
            "# Topstep - $50,000 (daily loss: $1,500)"
        ),
        Paragraph(
            "<b>Question to sit with:</b> what would happen if you "
            "removed the <font face='Courier'>super().__init__(...)</font> "
            "call from <font face='Courier'>Topstep.__init__</font>? Try "
            "it. The error message you get is one of the most common in "
            "Python and worth memorising.", styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_fstrings(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 4 &mdash; f-strings", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "An <b>f-string</b> &mdash; written with an "
        "<font face='Courier'>f</font> prefix like "
        '<font face=\'Courier\'>f"hello {name}"</font> &mdash; is '
        "Python's modern string interpolation. Anything in "
        "<font face='Courier'>{ }</font> is a real Python expression, "
        "evaluated and converted to a string. After a colon you can add "
        "a <b>format spec</b> that controls width, precision, alignment, "
        "and number formatting.", styles["body"],
    ))
    story.append(Paragraph(
        "f-strings are compiled at parse time, so they're also the "
        "<b>fastest</b> formatting option in Python &mdash; faster than "
        "<font face='Courier'>.format()</font> and far faster than "
        "<font face='Courier'>%</font> formatting.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From <font face='Courier'>config/production.py</font> &mdash; "
        "building a database connection URL:", styles["body"],
    ))
    story.append(code(
        "@property\n"
        "def DATABASE_URL(self):\n"
        '    """Generate database URL based on configuration."""\n'
        "    if self.DATABASE_TYPE == 'postgresql':\n"
        "        return (\n"
        '            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"\n'
        '            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"\n'
        "        )\n"
        '    return f"sqlite:///{self.SQLITE_PATH}"'
    ))
    story.append(Paragraph(
        "And from <font face='Courier'>dashboard/db.py</font> &mdash; "
        "building a fallback path for SQLite:", styles["body"],
    ))
    story.append(code(
        "DATABASE_URL = os.environ.get(\n"
        "    'DATABASE_URL',\n"
        '    f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), \'dashboard.db\')}"\n'
        ")"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "Each <font face='Courier'>{...}</font> can hold any expression "
        "&mdash; attribute lookups (<font face='Courier'>self.SQLITE_PATH</font>), "
        "function calls (<font face='Courier'>os.path.join(...)</font>), "
        "arithmetic, anything.", styles))
    story.append(numbered_step(sc.next(),
        "Adjacent string literals concatenate at parse time, so the "
        "multi-line <font face='Courier'>postgresql://...</font> string "
        "is one continuous URL with no whitespace between the parts.",
        styles))
    story.append(numbered_step(sc.next(),
        "Watch the quoting: an f-string with double quotes "
        '<font face=\'Courier\'>f"..."</font> can hold single quotes '
        "inside its expressions, and vice versa. Mixing them up is the "
        "most common syntax error people hit.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph("Try every common format spec at the REPL:",
                  styles["callout_body"]),
        code(
            "balance = 12345.6789\n"
            'name    = "Alice"\n'
            "pct     = 0.0734\n"
            "n       = 7\n"
            "\n"
            'print(f"Balance: ${balance:,.2f}")        # Balance: $12,345.68\n'
            'print(f"Pct:     {pct:.1%}")              # Pct:     7.3%\n'
            'print(f"Name:    {name:>10}")             # Name:          Alice  (right-aligned, width 10)\n'
            'print(f"Name:    {name:<10}|")            # Name:    Alice     |  (left, width 10)\n'
            'print(f"Hex:     {n:#06x}")               # Hex:     0x0007\n'
            'print(f"Repr:    {name!r}")               # Repr:    \'Alice\'  (calls repr())'
        ),
        Paragraph(
            "<b>The two most useful in real codebases:</b> "
            "<font face='Courier'>:,.2f</font> for money, and "
            "<font face='Courier'>:.1%</font> for percentages. Memorise "
            "those two and you'll cover 80% of formatting needs.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_typehints(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 5 &mdash; Type hints", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "Python is <b>dynamically typed at runtime</b> &mdash; variables "
        "don't have declared types, just whatever value is currently "
        "assigned. But you can <b>annotate</b> parameters and return "
        "values to document what the code expects:", styles["body"],
    ))
    story.append(code(
        "def fetch(account: int) -> Trade:\n"
        "    ..."
    ))
    story.append(Paragraph(
        "These annotations are <b>not enforced</b> &mdash; at runtime "
        "Python ignores them. They exist for <b>you</b> (the reader), "
        "for static checkers like mypy and pyright, and for your IDE's "
        "auto-complete. The <font face='Courier'>typing</font> module "
        "supplies generics like <font face='Courier'>list[int]</font>, "
        "<font face='Courier'>Optional[str]</font>, and "
        "<font face='Courier'>dict[str, Any]</font>. From Python 3.10 "
        "onward, <font face='Courier'>int | None</font> replaces "
        "<font face='Courier'>Optional[int]</font> &mdash; shorter and "
        "easier to read.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "Type hints from across the codebase, mixed-and-matched. These "
        "are realistic shapes you'll see in production Python:",
        styles["body"],
    ))
    story.append(code(
        "from typing import Any\n"
        "from datetime import datetime\n"
        "\n"
        "def get_client_profile(client_id: str) -> dict[str, Any]:\n"
        '    """Fetch a client\'s settings from the hierarchy config."""\n'
        "    ...\n"
        "\n"
        "def parse_sheet_date(value: str | None) -> datetime | None:\n"
        '    """Parse a date string from the spreadsheet, or None if missing/bad."""\n'
        "    if not value:\n"
        "        return None\n"
        "    ...\n"
        "\n"
        "def find_matches(\n"
        "    matches: list[tuple[int, dict]],\n"
        "    evaluations: list[dict],\n"
        "    trade_timestamp: float | None,\n"
        ") -> tuple[int, dict] | None:\n"
        '    """Pick the best evaluation row for a given trade."""\n'
        "    ..."
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>client_id: str</font> &mdash; one "
        "annotation per parameter, separated from the type by a colon.",
        styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>-&gt; dict[str, Any]</font> &mdash; the "
        "return type, after the parameter list. "
        "<font face='Courier'>dict[str, Any]</font> is <b>&ldquo;a dict "
        "whose keys are strings and whose values can be anything.&rdquo;</b>",
        styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>str | None</font> &mdash; the union "
        "syntax, read as <b>&ldquo;a string or None&rdquo;</b>. This is "
        "the modern way to express optional values, and you'll see it "
        "everywhere in code written for Python 3.10+.", styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>list[tuple[int, dict]]</font> &mdash; "
        "annotations nest, so <b>&ldquo;a list of (int, dict) "
        "pairs&rdquo;</b> reads naturally. Read these from the inside "
        "out.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph(
            "Annotate this function. There's one right answer for the "
            "parameters and the return type:", styles["callout_body"],
        ),
        code(
            "# Before — no annotations\n"
            "def biggest_winner(trades):\n"
            "    if not trades:\n"
            "        return None\n"
            '    return max(trades, key=lambda t: t["profit"])'
        ),
        Paragraph("After (one good way to write it):",
                  styles["callout_body"]),
        code(
            "def biggest_winner(trades: list[dict]) -> dict | None:\n"
            "    if not trades:\n"
            "        return None\n"
            '    return max(trades, key=lambda t: t["profit"])'
        ),
        Paragraph(
            "<b>Want to see hints actually catch bugs?</b> Install mypy "
            "with <font face='Courier'>pip install mypy</font> and run "
            "<font face='Courier'>mypy your_file.py</font>. Now try "
            "calling <font face='Courier'>biggest_winner(\"hello\")</font> "
            "&mdash; mypy will refuse, even though Python itself would "
            "happily run the code and crash later.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_decorators(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 6 &mdash; Decorators", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "A <b>decorator</b> is a function that wraps another function "
        "(or class) to add behaviour. The "
        "<font face='Courier'>@</font> syntax sitting above a function:",
        styles["body"],
    ))
    story.append(code(
        "@app.route('/login')\n"
        "def login():\n"
        "    ..."
    ))
    story.append(Paragraph("is just shorthand for:", styles["body"]))
    story.append(code(
        "def login():\n"
        "    ...\n"
        "login = app.route('/login')(login)"
    ))
    story.append(Paragraph(
        "That's it. Everything else about decorators follows from this "
        "one substitution. Decorators are how Flask attaches URL handlers, "
        "how <font face='Courier'>@property</font> turns a method into "
        "an attribute lookup, and how "
        "<font face='Courier'>@staticmethod</font> tells Python a method "
        "doesn't need <font face='Courier'>self</font>. When decorators "
        "stack, the one <b>closest to the function</b> runs first.",
        styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From <font face='Courier'>dashboard/app.py</font> &mdash; a "
        "Flask route. The decorator turns a plain function into a URL "
        "handler:", styles["body"],
    ))
    story.append(code(
        "@app.route('/maintenance')\n"
        "def maintenance():\n"
        '    """Show the maintenance page."""\n'
        "    return render_template('maintenance.html')\n"
        "\n"
        "@app.route('/')\n"
        "def index():\n"
        '    """Home page — the main dashboard."""\n'
        "    if not session.get('user_id'):\n"
        "        return redirect(url_for('login'))\n"
        "    return render_template('index.html', user=current_user())"
    ))
    story.append(Paragraph(
        "And here's a real decorator stack you'll see all over Flask "
        "code:", styles["body"],
    ))
    story.append(code(
        "@app.route('/admin/users', methods=['POST'])\n"
        "@login_required\n"
        "@admin_only\n"
        "def create_user():\n"
        "    ..."
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>@app.route('/maintenance')</font> tells "
        "Flask: <b>&ldquo;when a request comes in for /maintenance, call "
        "this function.&rdquo;</b> The decorator registers the function "
        "in a routing table inside the <font face='Courier'>app</font> "
        "object, then returns the function unchanged.", styles))
    story.append(numbered_step(sc.next(),
        "In the stacked example, decorators apply <b>bottom-up</b>. So "
        "<font face='Courier'>admin_only</font> wraps "
        "<font face='Courier'>create_user</font> first, then "
        "<font face='Courier'>login_required</font> wraps that wrapped "
        "version, then <font face='Courier'>app.route</font> registers "
        "the final wrapped thing.", styles))
    story.append(numbered_step(sc.next(),
        "This means <font face='Courier'>login_required</font> runs "
        "<b>before</b> <font face='Courier'>admin_only</font> when a "
        "request comes in &mdash; outer decorators run first. (The order "
        "looks reversed but read it from the request's point of view: it "
        "has to get past <font face='Courier'>login_required</font> "
        "before <font face='Courier'>admin_only</font> even gets a "
        "chance.)", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph(
            "Write a decorator from scratch &mdash; once you do, every "
            "<font face='Courier'>@something</font> you ever see will "
            "demystify:", styles["callout_body"],
        ),
        code(
            "import time\n"
            "from functools import wraps\n"
            "\n"
            "def timed(fn):\n"
            "    @wraps(fn)                    # preserves fn.__name__, fn.__doc__\n"
            "    def wrapper(*args, **kwargs):\n"
            "        start = time.perf_counter()\n"
            "        result = fn(*args, **kwargs)\n"
            "        elapsed = time.perf_counter() - start\n"
            '        print(f"{fn.__name__} took {elapsed*1000:.2f} ms")\n'
            "        return result\n"
            "    return wrapper\n"
            "\n"
            "@timed\n"
            "def slow_add(a, b):\n"
            '    """Pretend this is a real calculation."""\n'
            "    time.sleep(0.05)\n"
            "    return a + b\n"
            "\n"
            "print(slow_add(2, 3))\n"
            "# slow_add took 50.12 ms\n"
            "# 5"
        ),
        Paragraph(
            "<b>Read this carefully:</b> "
            "<font face='Courier'>timed</font> takes a function, builds "
            "a <font face='Courier'>wrapper</font> that does extra stuff "
            "around the call, and returns "
            "<font face='Courier'>wrapper</font>. The "
            "<font face='Courier'>@timed</font> line just rebinds "
            "<font face='Courier'>slow_add</font> to "
            "<font face='Courier'>timed(slow_add)</font>. That's the "
            "entire mechanism.", styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_properties(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 7 &mdash; Properties", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>@property</font> is a built-in decorator "
        "that turns a method into an attribute lookup. Instead of "
        "writing <font face='Courier'>account.equity()</font> (with "
        "parentheses), the caller writes "
        "<font face='Courier'>account.equity</font> (without). The "
        "method runs every time, but the call syntax is hidden.",
        styles["body"],
    ))
    story.append(Paragraph(
        "Why does this matter? Because it lets you <b>migrate a public "
        "attribute to a computed value without breaking anyone</b>. You "
        "can ship <font face='Courier'>account.balance = 1000</font> "
        "today, and tomorrow turn "
        "<font face='Courier'>balance</font> into a property that reads "
        "from a database &mdash; and every caller still works unchanged.",
        styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From <font face='Courier'>config/production.py</font> &mdash; "
        "the same database URL we saw in the f-string lesson, this time "
        "looking at the <font face='Courier'>@property</font> on top:",
        styles["body"],
    ))
    story.append(code(
        "class Config:\n"
        "    DATABASE_TYPE = 'sqlite'\n"
        "    SQLITE_PATH   = 'dashboard/dashboard.db'\n"
        "\n"
        "    @property\n"
        "    def DATABASE_URL(self):\n"
        '        """Generate the database URL based on configuration."""\n'
        "        if self.DATABASE_TYPE == 'postgresql':\n"
        "            return (\n"
        '                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"\n'
        '                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"\n'
        "            )\n"
        '        return f"sqlite:///{self.SQLITE_PATH}"\n'
        "\n"
        "config = Config()\n"
        "print(config.DATABASE_URL)   # no parentheses — it computes on access"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "Without <font face='Courier'>@property</font>, callers would "
        "have to write <font face='Courier'>config.DATABASE_URL()</font>. "
        "With it, <font face='Courier'>config.DATABASE_URL</font> alone "
        "runs the method.", styles))
    story.append(numbered_step(sc.next(),
        "Properties are read-only by default. To allow assignment, you "
        "add a <font face='Courier'>@DATABASE_URL.setter</font> "
        "decorator on a second method (see the exercise).", styles))
    story.append(numbered_step(sc.next(),
        "This is exactly the right tool when the <b>storage shape</b> "
        "of a value should be hidden from callers. The DB type might be "
        "SQLite or Postgres &mdash; callers shouldn't have to know, and "
        "they don't.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise</b>", styles["callout_heading_orange"]),
        Paragraph(
            "Build an <font face='Courier'>Account</font> class where "
            "<font face='Courier'>equity</font> is computed from "
            "<font face='Courier'>balance + open positions</font>. Then "
            "add a setter that does validation:", styles["callout_body"],
        ),
        code(
            "class Account:\n"
            "    def __init__(self, balance):\n"
            '        self._balance = balance       # leading underscore = "private by convention"\n'
            "        self.open_pnl = 0.0\n"
            "\n"
            "    @property\n"
            "    def equity(self):\n"
            "        return self._balance + self.open_pnl\n"
            "\n"
            "    @property\n"
            "    def balance(self):\n"
            "        return self._balance\n"
            "\n"
            "    @balance.setter\n"
            "    def balance(self, value):\n"
            "        if value < 0:\n"
            '            raise ValueError(f"Balance cannot be negative: {value}")\n'
            "        self._balance = value\n"
            "\n"
            "a = Account(1000)\n"
            "a.open_pnl = 250\n"
            "print(a.equity)         # 1250  — computed, no parentheses\n"
            "\n"
            "a.balance = 2000        # goes through the setter, validates\n"
            "print(a.equity)         # 2250\n"
            "\n"
            "a.balance = -100        # raises ValueError"
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_context_managers(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 8 &mdash; Context managers (the with statement)", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>with open('file.txt') as f:</font> "
        "guarantees that <font face='Courier'>f.close()</font> runs "
        "whether the block succeeds or raises an exception. The object's "
        "<font face='Courier'>__enter__</font> runs at the start, "
        "<font face='Courier'>__exit__</font> at the end. Context "
        "managers express the <b>acquire / release</b> pattern: open "
        "files, lock a mutex, start a database transaction, connect to "
        "MetaTrader 5 &mdash; and release / close / rollback / disconnect "
        "cleanly even if something goes wrong.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From a data-migration script in the project &mdash; reading "
        "two JSON files into the database. Both files are opened with "
        "<font face='Courier'>with</font>, so they close even if the "
        "JSON is malformed:", styles["body"],
    ))
    story.append(code(
        "import os, json\n"
        "\n"
        "def migrate(api_keys_file, data_file):\n"
        '    """Migrate data from JSON files to SQLite database."""\n'
        "    migrated = {'api_keys': 0, 'clients': 0}\n"
        "\n"
        "    if os.path.exists(api_keys_file):\n"
        "        try:\n"
        "            with open(api_keys_file, 'r') as f:\n"
        "                old_keys = json.load(f)\n"
        '                print(f"Found {len(old_keys)} API keys to migrate")\n'
        "                migrated['api_keys'] = len(old_keys)\n"
        "        except Exception as e:\n"
        '            print(f"Error reading API keys file: {e}")\n'
        "\n"
        "    if os.path.exists(data_file):\n"
        "        try:\n"
        "            with open(data_file, 'r') as f:\n"
        "                data = json.load(f)\n"
        "            for client_id, client_data in data.get('clients_db', {}).items():\n"
        "                save_client_data(client_id, client_data)\n"
        "                migrated['clients'] += 1\n"
        "        except Exception as e:\n"
        '            print(f"Error migrating client data: {e}")\n'
        "\n"
        "    return migrated"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>with open(...) as f:</font> calls "
        "<font face='Courier'>open(...).__enter__()</font> which returns "
        "the file object, then binds it to "
        "<font face='Courier'>f</font>.", styles))
    story.append(numbered_step(sc.next(),
        "When the indented block ends &mdash; for any reason: success, "
        "<font face='Courier'>return</font>, an exception &mdash; "
        "<font face='Courier'>__exit__</font> runs, which closes the "
        "file. You don't need a <font face='Courier'>finally:</font> "
        "clause, the <font face='Courier'>with</font> gives you one for "
        "free.", styles))
    story.append(numbered_step(sc.next(),
        "Notice the <font face='Courier'>try / except</font> sits "
        "<b>outside</b> the <font face='Courier'>with</font>, not inside "
        "it. If <font face='Courier'>json.load</font> raises, the file "
        "still closes, and the error message is logged.", styles))
    story.append(numbered_step(sc.next(),
        "This pattern &mdash; <b>with-block inside try-block</b> &mdash; "
        "is the standard way to handle file I/O safely in Python. "
        "Memorise the shape.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph("<b>Exercise &mdash; write your own context manager</b>",
                  styles["callout_heading_orange"]),
        Paragraph(
            "The fastest way to <b>get</b> context managers is to write "
            "one. Two ways:", styles["callout_body"],
        ),
        Paragraph(
            "<b>Way 1: a class with __enter__ and __exit__</b>",
            styles["callout_body"],
        ),
        code(
            "class Timer:\n"
            "    def __enter__(self):\n"
            "        import time\n"
            "        self.start = time.perf_counter()\n"
            "        return self\n"
            "\n"
            "    def __exit__(self, exc_type, exc_val, exc_tb):\n"
            "        import time\n"
            "        elapsed = time.perf_counter() - self.start\n"
            '        print(f"Took {elapsed*1000:.2f} ms")\n'
            "        # return False (or None) — propagate any exception\n"
            "\n"
            "with Timer():\n"
            "    sum(i*i for i in range(1_000_000))\n"
            "# Took 38.24 ms"
        ),
        Paragraph(
            "<b>Way 2: a generator with @contextmanager (much shorter)</b>",
            styles["callout_body"],
        ),
        code(
            "from contextlib import contextmanager\n"
            "import time\n"
            "\n"
            "@contextmanager\n"
            "def timer():\n"
            "    start = time.perf_counter()\n"
            "    try:\n"
            "        yield                          # the with-block runs here\n"
            "    finally:\n"
            "        elapsed = time.perf_counter() - start\n"
            '        print(f"Took {elapsed*1000:.2f} ms")\n'
            "\n"
            "with timer():\n"
            "    sum(i*i for i in range(1_000_000))"
        ),
        Paragraph(
            "Both do the same thing. The decorator version is the bridge "
            "to the <b>next lesson</b> &mdash; generators.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_generators(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 9 &mdash; Generators and yield", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "A function that uses <font face='Courier'>yield</font> instead "
        "of <font face='Courier'>return</font> becomes a <b>generator</b>. "
        "Calling it doesn't run the body &mdash; it returns an "
        "<b>iterator</b> that produces values one at a time, on demand. "
        "Each <font face='Courier'>yield</font> suspends the function; "
        "the next call resumes it right where it left off.",
        styles["body"],
    ))
    story.append(Paragraph(
        "This is how Python streams data without holding it all in "
        "memory. <font face='Courier'>for row in read_csv(path):</font> "
        "can iterate a million-row file without ever loading the whole "
        "thing. <font face='Courier'>yield from</font> delegates to "
        "another iterator. Generators were also the historical "
        "foundation that <font face='Courier'>async / await</font> was "
        "later built on top of.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From <font face='Courier'>dashboard/db.py</font> &mdash; a "
        "database session helper. This is one of the most important "
        "patterns in production Python. <b>Every web framework uses some "
        "version of it</b>:", styles["body"],
    ))
    story.append(code(
        "from contextlib import contextmanager\n"
        "from sqlalchemy.orm import sessionmaker\n"
        "\n"
        "SessionLocal = sessionmaker(bind=engine)\n"
        "\n"
        "@contextmanager\n"
        "def get_session():\n"
        '    """Dependency-style session: use as a context manager."""\n'
        "    session = SessionLocal()\n"
        "    try:\n"
        "        yield session\n"
        "        session.commit()        # success path\n"
        "    except Exception:\n"
        "        session.rollback()      # failure path\n"
        "        raise\n"
        "    finally:\n"
        "        session.close()         # always runs"
    ))
    story.append(Paragraph("Used like this:", styles["body"]))
    story.append(code(
        "with get_session() as session:\n"
        "    user = session.query(User).filter_by(email=email).first()\n"
        "    user.last_login = datetime.utcnow()\n"
        "    # no explicit commit — get_session does it on the way out"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "This single function combines three concepts: a <b>generator</b> "
        "(it has <font face='Courier'>yield</font>), a <b>context "
        "manager</b> (the <font face='Courier'>@contextmanager</font> "
        "decorator turns the generator into one), and <b>structured "
        "exception handling</b> "
        "(<font face='Courier'>try/except/finally</font>).", styles))
    story.append(numbered_step(sc.next(),
        "When the caller writes "
        "<font face='Courier'>with get_session() as session:</font>, "
        "everything before the <font face='Courier'>yield</font> runs "
        "(<b>setup</b>). The yielded value becomes "
        "<font face='Courier'>session</font> in the with-block.",
        styles))
    story.append(numbered_step(sc.next(),
        "When the with-block ends successfully, the generator resumes "
        "after the <font face='Courier'>yield</font> and runs "
        "<font face='Courier'>session.commit()</font>. If it ended with "
        "an exception, the <font face='Courier'>except</font> arm runs "
        "and <font face='Courier'>session.rollback()</font> undoes any "
        "half-finished writes.", styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>finally:</font> runs in <b>both</b> cases "
        "&mdash; the connection always returns to the pool. This is the "
        "property that makes the pattern safe.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph(
            "<b>Exercise &mdash; see lazy evaluation in action</b>",
            styles["callout_heading_orange"],
        ),
        Paragraph(
            "Generators only do work when asked. Watch the print "
            "statements to see when each line actually runs:",
            styles["callout_body"],
        ),
        code(
            "def numbers(n):\n"
            '    print(f"  starting up to {n}")\n'
            "    for i in range(n):\n"
            '        print(f"  about to yield {i}")\n'
            "        yield i\n"
            '        print(f"  resumed after {i}")\n'
            '    print("  done")\n'
            "\n"
            'print("creating generator...")\n'
            "g = numbers(3)\n"
            'print("got generator, asking for first value")\n'
            'print("first:", next(g))\n'
            'print("asking for second")\n'
            'print("second:", next(g))'
        ),
        Paragraph(
            "<b>Notice:</b> creating <font face='Courier'>g</font> "
            "prints <b>nothing</b>. The body doesn't start running "
            "until the first <font face='Courier'>next(g)</font>. Then "
            "it runs up to the first <font face='Courier'>yield</font> "
            "and pauses. The "
            "<font face='Courier'>\"resumed after 0\"</font> line prints "
            "on the <b>second</b> <font face='Courier'>next()</font>, "
            "not the first. That suspending-and-resuming is the whole "
            "trick.", styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_exceptions(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 10 &mdash; Exceptions", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "Errors in Python <b>travel up the call stack</b> until "
        "something catches them. <font face='Courier'>try / except</font> "
        "catches; <font face='Courier'>raise</font> throws; "
        "<font face='Courier'>finally</font> runs cleanup either way. "
        "The most important rule: <b>catch the narrowest exception you "
        "can.</b> A bare <font face='Courier'>except:</font> or "
        "<font face='Courier'>except Exception:</font> catches "
        "everything &mdash; including "
        "<font face='Courier'>KeyboardInterrupt</font> on older Python "
        "and bugs you'd rather see &mdash; and hides real problems.",
        styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "From a sheet-parsing helper. The function <b>expects</b> some "
        "inputs to be malformed (CSVs from spreadsheets are messy), so "
        "it catches the specific failure mode and falls back gracefully:",
        styles["body"],
    ))
    story.append(code(
        "from datetime import datetime\n"
        "\n"
        "def parse_trade_date(value):\n"
        '    """Parse a timestamp or ISO date string. Return None on bad input."""\n'
        "    if not value:\n"
        "        return None\n"
        "    try:\n"
        "        # First try: numeric Unix timestamp\n"
        "        return datetime.fromtimestamp(float(value))\n"
        "    except (ValueError, TypeError):\n"
        "        # Not a number — try ISO format\n"
        "        try:\n"
        "            return datetime.fromisoformat(str(value).replace('Z', '+00:00'))\n"
        "        except ValueError:\n"
        "            return None"
    ))
    story.append(Paragraph(
        "And the connection-pool initialiser, which uses a deliberately "
        "re-raising pattern:", styles["body"],
    ))
    story.append(code(
        "def _init_pool():\n"
        '    """Initialize the connection pool on first use."""\n'
        "    global _connection_pool\n"
        "    if _connection_pool is None:\n"
        "        try:\n"
        "            _connection_pool = SimpleConnectionPool(5, 15, DATABASE_URL, connect_timeout=5)\n"
        '            logger.info("[DB] Connection pool initialized")\n'
        "        except Exception as e:\n"
        '            logger.error(f"[DB] Failed to initialize connection pool: {e}")\n'
        "            raise        # log, then bubble up — don't swallow"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>except (ValueError, TypeError):</font> "
        "&mdash; a tuple of specific exception classes. We know exactly "
        "which two failures we're prepared for. Anything else (e.g. "
        "<font face='Courier'>KeyboardInterrupt</font>) still "
        "propagates.", styles))
    story.append(numbered_step(sc.next(),
        "The function returns <font face='Courier'>None</font> when "
        "input is bad, instead of crashing the caller. This is "
        "appropriate <b>here</b> because the caller can't do anything "
        "useful with a garbled date &mdash; but for unrecoverable "
        "failures, you <b>want</b> the crash.", styles))
    story.append(numbered_step(sc.next(),
        "In the pool initialiser, the pattern is <b>log, then re-raise</b>. "
        "The catch only exists so we can write a useful error message. "
        "Without the bare <font face='Courier'>raise</font>, a startup "
        "failure would silently leave "
        "<font face='Courier'>_connection_pool</font> as "
        "<font face='Courier'>None</font> and every later query would "
        "crash with a confusing message.", styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph(
            "<b>Exercise &mdash; make a custom exception type</b>",
            styles["callout_heading_orange"],
        ),
        Paragraph(
            "In real code, defining your own exception classes lets "
            "callers catch failures by <b>meaning</b>, not by accident:",
            styles["callout_body"],
        ),
        code(
            "class TradeRejected(Exception):\n"
            '    """Raised when a broker refuses an order."""\n'
            "    pass\n"
            "\n"
            "class InsufficientMargin(TradeRejected):\n"
            '    """More specific — not enough margin."""\n'
            "    pass\n"
            "\n"
            "def submit_order(symbol, volume, available_margin):\n"
            "    needed = volume * 1000     # pretend\n"
            "    if needed > available_margin:\n"
            "        raise InsufficientMargin(\n"
            '            f"Need ${needed:,.2f}, have ${available_margin:,.2f}"\n'
            "        )\n"
            '    return {"symbol": symbol, "volume": volume, "status": "filled"}\n'
            "\n"
            "try:\n"
            '    submit_order("EURUSD", 10, available_margin=500)\n'
            "except InsufficientMargin as e:\n"
            '    print(f"Specific catch: {e}")\n'
            "except TradeRejected as e:\n"
            '    print(f"General catch: {e}")'
        ),
        Paragraph(
            "<b>Why this matters:</b> a caller that needs to handle "
            "<font face='Courier'>InsufficientMargin</font> "
            "specifically (e.g., to ask for more funds) can. A caller "
            "that just wants to know the order failed can catch "
            "<font face='Courier'>TradeRejected</font>. Inheritance "
            "lines up with the <b>granularity</b> of caller intent.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_comprehensions(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 11 &mdash; Comprehensions", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "<font face='Courier'>[x*2 for x in xs if x &gt; 0]</font> "
        "builds a list in a single expression. There are four flavours: "
        "<b>list</b>, <b>set</b>, <b>dict</b>, and <b>generator</b>. "
        "They're usually clearer than "
        "<font face='Courier'>map/filter</font> and faster than the "
        "equivalent <font face='Courier'>for</font>-loop, because the "
        "list is sized once instead of grown one element at a time.",
        styles["body"],
    ))
    story.append(Paragraph(
        "Generator comprehensions look the same but use "
        "<font face='Courier'>( parentheses )</font> instead of "
        "brackets. They <b>don't materialise</b> the intermediate list "
        "&mdash; <font face='Courier'>sum(x*2 for x in xs)</font> "
        "computes the running total without ever holding the doubled "
        "list in memory.", styles["body"],
    ))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "Comprehensions are everywhere in the codebase. Here are the "
        "four flavours, drawn from typical patterns in the project:",
        styles["body"],
    ))
    story.append(code(
        "# 1. List comprehension — collect open trades\n"
        "open_trades = [t for t in all_trades if t.is_open]\n"
        "\n"
        "# 2. Dict comprehension — index trades by ID\n"
        "by_id = {t.id: t for t in all_trades}\n"
        "\n"
        "# 3. Set comprehension — unique symbols traded today\n"
        "symbols = {t.symbol for t in all_trades if t.opened_today}\n"
        "\n"
        "# 4. Generator expression — sum total profit without\n"
        "#    building an intermediate list\n"
        "total_profit = sum(t.profit for t in all_trades if t.is_closed)"
    ))
    story.append(Paragraph(
        "And one specifically pulled from the codebase &mdash; building "
        "a list of valid date matches with a filter:", styles["body"],
    ))
    story.append(code(
        "valid_matches = [\n"
        "    {\n"
        "        'match': (idx, account),\n"
        "        'delta': raw_delta_seconds,\n"
        "        'valid_date': True,\n"
        "    }\n"
        "    for idx, account in matches\n"
        "    if within_buffer(idx, account, BUFFER_SECONDS)\n"
        "]"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "Read every comprehension in three parts: <b>output expression</b> "
        "(left of <font face='Courier'>for</font>), <b>source</b> "
        "(<font face='Courier'>for x in xs</font>), <b>filter</b> "
        "(optional <font face='Courier'>if ...</font>).", styles))
    story.append(numbered_step(sc.next(),
        "In the multi-line example, the output is a <b>dictionary</b> "
        "being built fresh on each iteration. Comprehensions can output "
        "anything, including dicts, tuples, or other comprehensions.",
        styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>sum(t.profit for t in all_trades if t.is_closed)</font> "
        "&mdash; the parentheses-free generator expression as the "
        "<b>only</b> argument to a function. You don't need extra parens "
        "around it.", styles))
    story.append(numbered_step(sc.next(),
        "When you find yourself writing nested comprehensions more than "
        "two levels deep, that's the signal to switch back to a regular "
        "<font face='Courier'>for</font>-loop. Comprehensions are for "
        "<b>clarity</b> &mdash; when they stop being clear, drop them.",
        styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph(
            "<b>Exercise &mdash; convert each loop to a comprehension</b>",
            styles["callout_heading_orange"],
        ),
        Paragraph(
            "Each of these is a real-world shape. Try rewriting each as "
            "a comprehension before peeking at the answer.",
            styles["callout_body"],
        ),
        code(
            "trades = [\n"
            '    {"symbol": "EURUSD", "profit": 120.5, "closed": True},\n'
            '    {"symbol": "GBPUSD", "profit": -45.0, "closed": True},\n'
            '    {"symbol": "EURUSD", "profit":  30.0, "closed": False},\n'
            '    {"symbol": "USDJPY", "profit":  88.2, "closed": True},\n'
            "]\n"
            "\n"
            "# 1. Symbols of all closed, profitable trades  →  ['EURUSD', 'USDJPY']\n"
            "# 2. Total profit of closed trades             →  163.7\n"
            "# 3. Set of unique symbols                     →  {'EURUSD', 'GBPUSD', 'USDJPY'}\n"
            "# 4. Dict mapping symbol → list of its profits →  {'EURUSD': [120.5, 30.0], ...}"
        ),
        Paragraph("<b>Answers (try first, then check):</b>",
                  styles["callout_body"]),
        code(
            "# 1.\n"
            '[t["symbol"] for t in trades if t["closed"] and t["profit"] > 0]\n'
            "\n"
            "# 2.\n"
            'sum(t["profit"] for t in trades if t["closed"])\n'
            "\n"
            "# 3.\n"
            '{t["symbol"] for t in trades}\n'
            "\n"
            "# 4. — this one is harder, easier as a regular loop:\n"
            "from collections import defaultdict\n"
            "by_symbol = defaultdict(list)\n"
            "for t in trades:\n"
            '    by_symbol[t["symbol"]].append(t["profit"])\n'
            "# (You CAN do it as a dict comprehension with a nested list comp,\n"
            "#  but a defaultdict loop is far more readable. Knowing when NOT to\n"
            "#  use a comprehension is part of the skill.)"
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def lesson_dataclasses(story, styles, doc_width, sc):
    story.append(Paragraph("Lesson 12 &mdash; Dataclasses", styles["h1"]))
    story.append(Paragraph("The idea", styles["h2"]))
    story.append(Paragraph(
        "A <font face='Courier'>@dataclass</font> auto-generates "
        "<font face='Courier'>__init__</font>, "
        "<font face='Courier'>__repr__</font>, and "
        "<font face='Courier'>__eq__</font> from a class's annotated "
        "fields. It removes the boilerplate from <b>plain data</b> "
        "objects. There are two rules to remember:", styles["body"],
    ))
    story.append(bullet(
        "Use <font face='Courier'>field(default_factory=list)</font> "
        "for mutable defaults. <b>Never</b> write "
        "<font face='Courier'>= []</font> at class scope &mdash; that "
        "one list gets shared across every instance and you'll spend a "
        "long afternoon figuring out why.", styles))
    story.append(bullet(
        "<font face='Courier'>frozen=True</font> makes instances "
        "immutable and hashable &mdash; they can be put in sets and "
        "used as dict keys.", styles))
    story.append(Paragraph("Real code from the book", styles["h2"]))
    story.append(Paragraph(
        "The MT5HedgingEngine project leans heavily on SQLAlchemy ORM "
        "models for its persistent objects, so it doesn't use "
        "<font face='Courier'>@dataclass</font> for those. But the same "
        "shape comes up constantly for <b>transient</b> objects. Here's "
        "what a <font face='Courier'>Trade</font> dataclass would look "
        "like, modeled on the trade dictionaries the project actually "
        "passes around:", styles["body"],
    ))
    story.append(code(
        "from dataclasses import dataclass, field\n"
        "from datetime import datetime\n"
        "\n"
        "@dataclass\n"
        "class Trade:\n"
        "    symbol:     str\n"
        "    volume:     float\n"
        "    side:       str                                  # 'buy' or 'sell'\n"
        "    open_price: float\n"
        "    open_time:  datetime\n"
        '    comment:    str = ""                             # default value\n'
        "    tags:       list[str] = field(default_factory=list)   # mutable default\n"
        "    is_open:    bool = True\n"
        "\n"
        't = Trade("EURUSD", 0.10, "buy", 1.0834, datetime.utcnow())\n'
        "print(t)\n"
        "# Trade(symbol='EURUSD', volume=0.1, side='buy', open_price=1.0834,\n"
        "#       open_time=..., comment='', tags=[], is_open=True)\n"
        "\n"
        "# Equality is by field value, automatically:\n"
        't2 = Trade("EURUSD", 0.10, "buy", 1.0834, t.open_time)\n'
        "print(t == t2)   # True"
    ))
    story.append(Paragraph("Walkthrough", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "The <font face='Courier'>@dataclass</font> decorator inspects "
        "the class body, finds every field with a type annotation, and "
        "writes <font face='Courier'>__init__(self, symbol, volume, side, ...)</font> "
        "for you. Saving 5&ndash;10 lines per class adds up.", styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>__repr__</font> is also generated, so "
        "<font face='Courier'>print(t)</font> produces the readable "
        "output above instead of "
        "<font face='Courier'>&lt;Trade object at 0x...&gt;</font>. "
        "This alone is worth the decorator.", styles))
    story.append(numbered_step(sc.next(),
        "<font face='Courier'>field(default_factory=list)</font> calls "
        "<font face='Courier'>list()</font> <b>once per instance</b> to "
        "produce a fresh empty list. Compare to the bug below.",
        styles))
    story.append(Paragraph("Try it yourself", styles["h2"]))
    story.append(callout([
        Paragraph(
            "<b>Exercise &mdash; see the mutable-default trap</b>",
            styles["callout_heading_orange"],
        ),
        Paragraph(
            "Run this. The output is one of Python's classic gotchas, "
            "and <font face='Courier'>@dataclass</font> actively "
            "protects you from it:", styles["callout_body"],
        ),
        code(
            "# THE BUG (works for one-off classes, breaks for dataclasses)\n"
            "class Bag:\n"
            "    def __init__(self, items=[]):     # ← shared default!\n"
            "        self.items = items\n"
            "\n"
            "a = Bag()\n"
            'a.items.append("apple")\n'
            "b = Bag()\n"
            "print(b.items)            # ['apple'] — wat\n"
            "\n"
            "# THE FIX (regular class)\n"
            "class Bag:\n"
            "    def __init__(self, items=None):\n"
            "        self.items = items if items is not None else []\n"
            "\n"
            "# THE DATACLASS WAY (concise, can't get it wrong)\n"
            "from dataclasses import dataclass, field\n"
            "\n"
            "@dataclass\n"
            "class Bag:\n"
            "    items: list = field(default_factory=list)\n"
            "\n"
            'a = Bag(); a.items.append("apple")\n'
            "b = Bag()\n"
            "print(b.items)            # []  — independent"
        ),
        Paragraph(
            "<b>Bonus:</b> add <font face='Courier'>frozen=True</font> "
            "to the <font face='Courier'>@dataclass</font> decorator and "
            "try assigning to <font face='Courier'>a.items</font>. "
            "You'll get a "
            "<font face='Courier'>FrozenInstanceError</font> &mdash; "
            "the instance is now immutable and can be used in a "
            "<font face='Courier'>set()</font> or as a dict key.",
            styles["callout_body"],
        ),
    ], doc_width, kind="orange"))
    story.append(PageBreak())


def closing_chapter(story, styles, doc_width, sc):
    story.append(Paragraph("Where to go next", styles["h1"]))
    story.append(Paragraph(
        "You've now seen the twelve concepts that show up most heavily "
        "in real Python codebases. To make the knowledge stick, "
        "<b>build something</b>. A small CLI tool, a script that scrapes "
        "one of your own data sources, a Flask app that does anything at "
        "all. The patterns in this guide will start to feel like "
        "instinct only when you reach for them yourself.", styles["body"],
    ))
    story.append(Paragraph(
        "Concepts I deliberately skipped", styles["h2"],
    ))
    story.append(Paragraph(
        "The original book also covers these &mdash; they're worth "
        "circling back to once the twelve above are comfortable:",
        styles["body"],
    ))
    story.append(bullet(
        "<b>Async / await</b> &mdash; coroutines for I/O-bound "
        "concurrency. Most useful when you're making lots of HTTP "
        "requests or websocket reads.", styles))
    story.append(bullet(
        "<b>Lambdas</b> &mdash; single-expression anonymous functions. "
        "Useful with "
        "<font face='Courier'>sorted(..., key=lambda x: x.field)</font>, "
        "and not much else. If your lambda needs more than one "
        "expression, write a <font face='Courier'>def</font> instead.",
        styles))
    story.append(bullet(
        "<b>Dunder methods</b> beyond "
        "<font face='Courier'>__init__</font> &mdash; "
        "<font face='Courier'>__repr__</font>, "
        "<font face='Courier'>__eq__</font>, "
        "<font face='Courier'>__len__</font>, "
        "<font face='Courier'>__iter__</font>, "
        "<font face='Courier'>__getitem__</font>. Defining these lets "
        "your classes integrate with built-in syntax "
        "(<font face='Courier'>len(obj)</font>, "
        "<font face='Courier'>for x in obj:</font>, "
        "<font face='Courier'>obj[key]</font>).", styles))
    story.append(bullet(
        "<b>@classmethod and @staticmethod</b> &mdash; alternate "
        "constructors and namespace-only functions inside a class.",
        styles))
    story.append(bullet(
        "<b>Module-level state</b> &mdash; the global-ish caches and "
        "singletons. Powerful, easy to misuse, makes tests harder. "
        "Reach for it sparingly.", styles))
    story.append(Paragraph("How to keep practising", styles["h2"]))
    story.append(numbered_step(sc.next(),
        "<b>Read code that's better than yours.</b> The MT5HedgingEngine "
        "reference book you started with is one good source. So is any "
        "well-maintained library on PyPI &mdash; pick something you use "
        "(<font face='Courier'>requests</font>, "
        "<font face='Courier'>flask</font>, "
        "<font face='Courier'>rich</font>) and click through to its "
        "source.", styles))
    story.append(numbered_step(sc.next(),
        "<b>Add type hints to a script you've already written.</b> Then "
        "run <font face='Courier'>mypy</font> against it. The errors "
        "<font face='Courier'>mypy</font> raises will teach you things "
        "about your own code you didn't know.", styles))
    story.append(numbered_step(sc.next(),
        "<b>Refactor a function into a class. Then refactor a class into "
        "a dataclass.</b> Feeling the difference is how the rationale "
        "for each becomes intuition.", styles))
    story.append(numbered_step(sc.next(),
        "<b>Build the smallest possible web app.</b> Five lines of "
        "Flask, one route, one template. Then add a second route with "
        "a decorator stack. Then make the route depend on a database "
        "session via a <font face='Courier'>@contextmanager</font> "
        "generator. By the end you'll have used six of the twelve "
        "lessons in one project.", styles))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "<i>Good luck. The fact that you're reading something this "
        "dense at all is the main predictor of getting good &mdash; "
        "keep going.</i>",
        ParagraphStyle("close", parent=styles["body"],
                       alignment=1, textColor=colors.HexColor("#4a5568")),
    ))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_story(styles, doc_width):
    story: list = []
    sc = StepCounter()
    cover(story, styles, doc_width)
    how_to_use(story, styles, doc_width)
    lesson_modules(story, styles, doc_width, sc)
    lesson_classes(story, styles, doc_width, sc)
    lesson_inheritance(story, styles, doc_width, sc)
    lesson_fstrings(story, styles, doc_width, sc)
    lesson_typehints(story, styles, doc_width, sc)
    lesson_decorators(story, styles, doc_width, sc)
    lesson_properties(story, styles, doc_width, sc)
    lesson_context_managers(story, styles, doc_width, sc)
    lesson_generators(story, styles, doc_width, sc)
    lesson_exceptions(story, styles, doc_width, sc)
    lesson_comprehensions(story, styles, doc_width, sc)
    lesson_dataclasses(story, styles, doc_width, sc)
    closing_chapter(story, styles, doc_width, sc)
    return story


def main():
    out = REPO_ROOT / "PYTHON_GREATEST_HITS.pdf"
    doc = BaseDocTemplate(
        str(out), pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.85 * inch, bottomMargin=0.7 * inch,
        title="Python: The Greatest Hits",
        author="Claude Code",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
    )
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])

    styles = make_styles()
    story = build_story(styles, doc.width)
    print(f"Building PDF with {len(story)} flowables...")
    doc.build(story)
    size = out.stat().st_size / (1024 * 1024)
    print(f"Wrote {out} ({size:.2f} MB)")


if __name__ == "__main__":
    main()
