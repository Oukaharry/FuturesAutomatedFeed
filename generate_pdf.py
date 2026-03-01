"""
generate_pdf.py
----------------
Generates TECH_STACK_BOOK.pdf — a comprehensive technical reference book
for the MT5 Futures Hedging Dashboard system.

Usage:
    python generate_pdf.py

Requires: reportlab
    pip install reportlab
"""

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, HRFlowable, KeepTogether, ListFlowable, ListItem
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.pdfgen import canvas
import datetime

# ─────────────────────────────────────────────
#  COLOUR PALETTE  (dark-tech theme)
# ─────────────────────────────────────────────
C_BG          = colors.HexColor("#0f1117")   # page bg  (not used — white pages)
C_NAVY        = colors.HexColor("#0d1b2a")   # chapter header bg
C_BLUE        = colors.HexColor("#1e3a5f")   # section header bg
C_ACCENT      = colors.HexColor("#60a5fa")   # accent / link colour
C_GREEN       = colors.HexColor("#4ade80")
C_PINK        = colors.HexColor("#fb7185")
C_PURPLE      = colors.HexColor("#c084fc")
C_GOLD        = colors.HexColor("#fcd34d")
C_CODE_BG     = colors.HexColor("#1e2030")   # code block background
C_CODE_FG     = colors.HexColor("#cdd6f4")   # code block text
C_GREY        = colors.HexColor("#94a3b8")
C_DARK_GREY   = colors.HexColor("#334155")
C_WHITE       = colors.white
C_BLACK       = colors.black
C_TABLE_HEAD  = colors.HexColor("#1e3a5f")
C_ROW_EVEN    = colors.HexColor("#f1f5f9")
C_ROW_ODD     = colors.white

OUTPUT_FILE = "TECH_STACK_BOOK.pdf"
PAGE_W, PAGE_H = A4

# ─────────────────────────────────────────────
#  STYLES
# ─────────────────────────────────────────────
base_styles = getSampleStyleSheet()

def _style(name, parent="Normal", **kwargs):
    s = ParagraphStyle(name, parent=base_styles[parent], **kwargs)
    return s

STYLES = {
    # Cover
    "cover_title": _style("cover_title", "Title",
        fontSize=34, leading=42, textColor=C_NAVY,
        spaceAfter=16, alignment=TA_CENTER, fontName="Helvetica-Bold"),
    "cover_subtitle": _style("cover_subtitle",
        fontSize=16, leading=22, textColor=C_BLUE,
        spaceAfter=8, alignment=TA_CENTER),
    "cover_meta": _style("cover_meta",
        fontSize=11, textColor=C_GREY, alignment=TA_CENTER),

    # Headings
    "ch_heading": _style("ch_heading",
        fontSize=22, leading=28, fontName="Helvetica-Bold",
        textColor=C_WHITE, spaceAfter=6, spaceBefore=0,
        backColor=C_NAVY, borderPad=8),
    "section": _style("section",
        fontSize=14, leading=20, fontName="Helvetica-Bold",
        textColor=C_WHITE, backColor=C_BLUE,
        spaceBefore=14, spaceAfter=4, borderPad=6),
    "subsection": _style("subsection",
        fontSize=12, leading=18, fontName="Helvetica-Bold",
        textColor=C_NAVY, spaceBefore=10, spaceAfter=4,
        borderWidth=0, borderPad=0),
    "toc_h1": _style("toc_h1",
        fontSize=13, fontName="Helvetica-Bold",
        textColor=C_NAVY, leftIndent=0, spaceBefore=6),
    "toc_h2": _style("toc_h2",
        fontSize=11, textColor=C_BLUE, leftIndent=16, spaceBefore=2),

    # Body
    "body": _style("body", "Normal",
        fontSize=10.5, leading=16, textColor=colors.HexColor("#1e293b"),
        spaceAfter=6, alignment=TA_JUSTIFY),
    "body_bullet": _style("body_bullet", "Normal",
        fontSize=10.5, leading=15, textColor=colors.HexColor("#1e293b"),
        spaceAfter=3, leftIndent=14, firstLineIndent=-14),

    # Code
    "code": _style("code",
        fontName="Courier", fontSize=8.5, leading=12,
        textColor=C_CODE_FG, backColor=C_CODE_BG,
        borderPad=10, spaceAfter=10, spaceBefore=6,
        leftIndent=6, rightIndent=6),
    "code_label": _style("code_label",
        fontName="Courier-Bold", fontSize=8, textColor=C_ACCENT,
        spaceAfter=2, spaceBefore=6),

    # Table
    "table_header": _style("table_header",
        fontName="Helvetica-Bold", fontSize=9.5,
        textColor=C_WHITE, alignment=TA_CENTER),
    "table_cell": _style("table_cell",
        fontSize=9, leading=13, textColor=colors.HexColor("#1e293b")),
    "table_cell_mono": _style("table_cell_mono",
        fontName="Courier", fontSize=8.5, leading=12,
        textColor=colors.HexColor("#1e293b")),

    # Callout box
    "callout": _style("callout",
        fontSize=10, leading=15, textColor=colors.HexColor("#1e293b"),
        backColor=colors.HexColor("#eff6ff"),
        borderColor=C_ACCENT, borderWidth=1, borderPad=8,
        spaceAfter=10, leftIndent=10, rightIndent=10),

    # Caption / note
    "caption": _style("caption",
        fontSize=8.5, textColor=C_GREY, alignment=TA_CENTER,
        spaceAfter=6),
}

# ─────────────────────────────────────────────
#  HEADER / FOOTER CANVAS
# ─────────────────────────────────────────────
BOOK_TITLE = "MT5 Futures Hedging Dashboard — Technical Reference"
BUILD_DATE = datetime.date.today().strftime("%B %d, %Y")

def _draw_header_footer(canvas_obj, doc):
    canvas_obj.saveState()
    w, h = PAGE_W, PAGE_H

    # ── Header bar ──
    canvas_obj.setFillColor(C_NAVY)
    canvas_obj.rect(0, h - 1.1*cm, w, 1.1*cm, fill=1, stroke=0)
    canvas_obj.setFont("Helvetica-Bold", 8)
    canvas_obj.setFillColor(C_WHITE)
    canvas_obj.drawString(1.5*cm, h - 0.75*cm, BOOK_TITLE)
    canvas_obj.drawRightString(w - 1.5*cm, h - 0.75*cm, BUILD_DATE)

    # ── Footer bar ──
    canvas_obj.setFillColor(C_DARK_GREY)
    canvas_obj.rect(0, 0, w, 0.9*cm, fill=1, stroke=0)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(C_WHITE)
    canvas_obj.drawCentredString(w / 2, 0.3*cm, f"Page {doc.page}")
    canvas_obj.drawString(1.5*cm, 0.3*cm, "© 2025 Oukaharry — Confidential")
    canvas_obj.drawRightString(w - 1.5*cm, 0.3*cm, "github.com/Oukaharry/FuturesAutomatedFeed")
    canvas_obj.restoreState()

def _first_page(canvas_obj, doc):
    # Cover page — no header/footer
    pass

# ─────────────────────────────────────────────
#  HELPER BUILDERS
# ─────────────────────────────────────────────
def HR():
    return HRFlowable(width="100%", thickness=1, color=C_DARK_GREY,
                      spaceAfter=8, spaceBefore=8)

def SP(h=6):
    return Spacer(1, h)

def chapter(title, anchor=None):
    """Full-width chapter heading on its own line."""
    txt = title.upper()
    if anchor:
        txt = f'<a name="{anchor}"/>' + txt
    return [
        PageBreak(),
        Paragraph(txt, STYLES["ch_heading"]),
        SP(4),
        HR(),
    ]

def section(title, anchor=None):
    txt = title
    if anchor:
        txt = f'<a name="{anchor}"/>' + txt
    return Paragraph(txt, STYLES["section"])

def subsection(title):
    return Paragraph(title, STYLES["subsection"])

def body(text):
    return Paragraph(text, STYLES["body"])

def bullet_list(items):
    """Return a ListFlowable of bullet items."""
    return ListFlowable(
        [ListItem(Paragraph(i, STYLES["body_bullet"]), leftIndent=18,
                  bulletColor=C_ACCENT) for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=6,
    )

def code_block(label, code_text):
    """Monospace code block with a label."""
    safe = (code_text
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\t", "    "))
    return [
        Paragraph(f"▸  {label}", STYLES["code_label"]),
        Paragraph(f"<font name='Courier'>{safe}</font>", STYLES["code"]),
    ]

def data_table(headers, rows, col_widths=None):
    """Styled data table with alternating row colours."""
    n_cols = len(headers)
    if col_widths is None:
        available = PAGE_W - 3*cm
        col_widths = [available / n_cols] * n_cols

    table_data = [[Paragraph(h, STYLES["table_header"]) for h in headers]]
    for i, row in enumerate(rows):
        bg = C_ROW_EVEN if i % 2 == 0 else C_ROW_ODD
        style = STYLES["table_cell_mono"] if any(
            c in h.lower() for h in headers for c in ("command", "env", "module", "table")
        ) else STYLES["table_cell"]
        table_data.append(
            [Paragraph(str(cell), style) for cell in row]
        )

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        # Header
        ("BACKGROUND",  (0, 0), (-1, 0), C_TABLE_HEAD),
        ("TEXTCOLOR",   (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 9),
        ("ALIGN",       (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",  (0, 0), (-1, 0), 6),
        # Body
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 1), (-1, -1), 9),
        ("ALIGN",       (0, 1), (-1, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Alternating rows
        *[("BACKGROUND", (0, i+1), (-1, i+1),
           C_ROW_EVEN if i % 2 == 0 else C_ROW_ODD)
          for i in range(len(rows))],
        # Grid
        ("GRID",        (0, 0), (-1, -1), 0.4, C_DARK_GREY),
        ("LINEBEFORE",  (0, 0), (0, -1),  0.8, C_ACCENT),
    ]))
    return t

def callout(text):
    return Paragraph(f"ℹ  {text}", STYLES["callout"])

# ─────────────────────────────────────────────
#  DOCUMENT CLASS  (supports TOC bookmarks)
# ─────────────────────────────────────────────
class BookDoc(BaseDocTemplate):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(
            1.5*cm, 1.2*cm,
            PAGE_W - 3*cm, PAGE_H - 2.8*cm,
            id="normal"
        )
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=_first_page),
            PageTemplate(id="body",  frames=[frame], onPage=_draw_header_footer),
        ])

    def afterFlowable(self, flowable):
        """Register headings with TOC and PDF bookmarks."""
        if isinstance(flowable, Paragraph):
            style = flowable.style.name
            txt = flowable.getPlainText()
            if style == "ch_heading":
                key = txt.lower().replace(" ", "_")
                self.canv.bookmarkPage(key)
                self.notify("TOCEntry", (0, txt, self.page, key))
            elif style == "section":
                key = "sec_" + txt.lower().replace(" ", "_")
                self.canv.bookmarkPage(key)
                self.notify("TOCEntry", (1, txt, self.page, key))

# ─────────────────────────────────────────────
#  CONTENT BUILDERS
# ─────────────────────────────────────────────

def build_cover(story):
    story.append(SP(80))
    story.append(Paragraph("MT5 Futures Hedging Dashboard", STYLES["cover_title"]))
    story.append(Paragraph("Technical Reference & Architecture Book", STYLES["cover_subtitle"]))
    story.append(SP(12))
    story.append(HR())
    story.append(SP(12))
    story.append(Paragraph(
        "A deep-dive into the Flask backend, SQLite data layer, single-page JavaScript "
        "frontend, MetaTrader 5 desktop connector, and production deployment strategy "
        "powering a multi-tier proprietary trading management platform.",
        STYLES["body"]
    ))
    story.append(SP(20))
    story.append(Paragraph(f"Version 1.2.0  ·  {BUILD_DATE}", STYLES["cover_meta"]))
    story.append(Paragraph("github.com/Oukaharry/FuturesAutomatedFeed", STYLES["cover_meta"]))
    story.append(Paragraph("Author: Oukaharry  ·  Branch: main", STYLES["cover_meta"]))


def build_toc(story, toc):
    story.append(PageBreak())
    story.append(Paragraph("TABLE OF CONTENTS", STYLES["ch_heading"]))
    story.append(HR())
    story.append(toc)


def build_ch1_overview(story):
    story += chapter("Chapter 1: System Overview", "ch1")

    story.append(section("1.1  What This System Does"))
    story.append(body(
        "The <b>MT5 Futures Hedging Dashboard</b> is a full-stack web application that "
        "aggregates, tracks, and visualises the proprietary trading activities of multiple "
        "traders across several prop-firm evaluation pipelines. It pulls live data from "
        "MetaTrader 5 trading accounts, stores it in a structured database, and exposes "
        "that data through a role-based web dashboard and a secured REST API."
    ))
    story.append(SP())
    story.append(body(
        "The system supports a four-tier hierarchy: "
        "<b>Super Admin → Admin → Trader → Client</b>. "
        "Each tier has progressively scoped access rights enforced at both the route level "
        "(via decorator guards) and the database query level."
    ))

    story.append(section("1.2  Architecture Diagram"))
    story.append(data_table(
        ["Layer", "Technology", "Role"],
        [
            ["Desktop App", "Python + MetaTrader5 API", "Extracts live MT5 data, pushes to dashboard via API"],
            ["Web Backend", "Flask 3 + Gunicorn", "REST API, session management, role-based access control"],
            ["Database", "SQLite (dev) / PostgreSQL (prod)", "Persistent storage of client data, audit log, history"],
            ["Frontend", "Vanilla JS + CSS3", "Single-page dashboard, inline editing, infinite scroll"],
            ["Auth", "PBKDF2-SHA256 sessions + API keys", "Cookie sessions for UI; X-API-Key header for apps"],
            ["Deployment", "Ubuntu VPS + Nginx + Gunicorn", "Reverse-proxy, SSL termination, process management"],
        ],
        col_widths=[3*cm, 5.5*cm, 8.5*cm]
    ))

    story.append(section("1.3  User Roles & Permissions"))
    story.append(data_table(
        ["Role", "Login Method", "Can See", "Can Edit"],
        [
            ["super_admin", "Password (PBKDF2)", "All admins, traders, clients", "Everything"],
            ["admin", "Password (PBKDF2)", "Own traders + clients", "Trader/client data"],
            ["trader", "Password (PBKDF2)", "Own clients only", "Client evaluations"],
            ["client", "Email + Password", "Own data only", "Prop Day notes only"],
            ["API (Trader App)", "X-API-Key header", "Scoped to trader's clients", "Push MT5 data"],
        ],
        col_widths=[2.5*cm, 3.5*cm, 5*cm, 4.5*cm]
    ))

    story.append(section("1.4  Data Flow"))
    story.append(body(
        "1. The <b>Trader Companion</b> desktop app connects to a live MT5 terminal and "
        "extracts deals, positions, account balances, and evaluation states at a configurable "
        "interval (typically every 60 seconds)."
    ))
    story.append(body(
        "2. The data is serialised to JSON and POSTed to <code>/api/update_data</code> "
        "on the Flask server using an <b>X-API-Key</b> header for authentication."
    ))
    story.append(body(
        "3. The server merges the incoming payload with existing client data, preserving "
        "soft-deleted evaluation rows and dashboard-side edits, then saves to the database "
        "and writes a versioned snapshot to the audit/history tables."
    ))
    story.append(body(
        "4. The web dashboard polls <code>/api/get_data?client_id=…</code> and renders "
        "the data into a rich HTML table with sticky headers, inline editing, "
        "and an expandable financials panel."
    ))


def build_ch2_backend(story):
    story += chapter("Chapter 2: Flask Backend", "ch2")

    story.append(section("2.1  Application Bootstrap"))
    story.append(body(
        "The Flask application lives in <b>dashboard/app.py</b> (~4 400 lines). "
        "On startup it initialises the database, starts the midnight watermark "
        "scheduler, configures rate limiting via <b>Flask-Limiter</b>, and sets a "
        "cryptographically random secret key for sessions."
    ))
    story += code_block("dashboard/app.py — app initialisation", """\
app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["10000 per day", "2000 per hour"],
    storage_uri="memory://"
)

# Start Midnight Watermark Scheduler
from dashboard.scheduler import start_scheduler
start_scheduler()
""")

    story.append(section("2.2  Authentication Decorators"))
    story.append(body(
        "Four decorators guard every route.  They are composed using Python's "
        "<code>functools.wraps</code> to preserve the original function metadata."
    ))

    story.append(subsection("require_api_key"))
    story.append(body(
        "Extracts the <code>X-API-Key</code> header, validates it against the database, "
        "injects the resolved <code>request.api_user</code> context, and logs the access."
    ))
    story += code_block("dashboard/app.py — require_api_key decorator", """\
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        client_ip = get_remote_address()

        if not api_key:
            log_action('API_ACCESS_DENIED', 'unknown', 'no_key',
                       client_ip, 'Missing API key', False)
            return jsonify({"status": "error",
                            "message": "API key required"}), 401

        user_info = validate_api_key(api_key)
        if not user_info:
            log_action('API_ACCESS_DENIED', 'unknown', api_key[:12],
                       client_ip, 'Invalid API key', False)
            return jsonify({"status": "error",
                            "message": "Invalid API key"}), 403

        request.api_user = user_info
        log_action('API_ACCESS', 'trader', user_info.get('trader', 'unknown'),
                   client_ip, f"Endpoint: {request.endpoint}")
        return f(*args, **kwargs)
    return decorated_function
""")

    story.append(subsection("require_role(*allowed_roles)"))
    story.append(body(
        "Session-cookie based role gate.  Reads the <code>session_token</code> cookie, "
        "validates it, and checks <code>user_type</code> against a whitelist of "
        "allowed roles.  Returns HTTP 403 on mismatch."
    ))
    story += code_block("dashboard/app.py — require_role decorator", """\
def require_role(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            session_token = request.cookies.get('session_token')
            if not session_token:
                return jsonify({"status": "error",
                                "message": "Authentication required"}), 401

            session_info = validate_session(session_token)
            if not session_info:
                return jsonify({"status": "error",
                                "message": "Invalid or expired session"}), 401

            user_type = session_info.get('user_type')
            if user_type not in allowed_roles:
                log_action('ACCESS_DENIED', user_type,
                           session_info.get('user_identifier'),
                           get_remote_address(),
                           f"Required roles: {allowed_roles}", False)
                return jsonify({"status": "error",
                                "message": "Access denied."}), 403

            request.session_user = session_info
            return f(*args, **kwargs)
        return decorated_function
    return decorator
""")

    story.append(section("2.3  Key API Endpoints"))
    story.append(data_table(
        ["Method", "Endpoint", "Auth", "Description"],
        [
            ["GET",  "/api/get_data",       "Session / API Key", "Fetch client JSON data"],
            ["POST", "/api/update_data",    "Session / API Key", "Push new MT5 snapshot"],
            ["POST", "/api/login",          "None (public)",     "Username+password login, returns session cookie"],
            ["POST", "/api/auth/login",     "None (public)",     "Unified multi-role login endpoint"],
            ["POST", "/api/rollback",       "Session",           "Rollback client data to a previous version"],
            ["POST", "/api/notes",          "Session",           "Save / delete inline cell notes"],
            ["GET",  "/api/history",        "Session",           "List version history for a client"],
            ["POST", "/api/generate_key",   "Admin Password",    "Generate a new API key for a trader"],
            ["GET",  "/api/audit_log",      "Session (admin+)",  "Return recent audit log entries"],
        ],
        col_widths=[1.5*cm, 4.5*cm, 3.5*cm, 6.5*cm]
    ))

    story.append(section("2.4  /api/get_data — Data Retrieval"))
    story.append(body(
        "This endpoint serves as the primary data source for the dashboard. "
        "It accepts both session cookies (for browser clients) and API-key headers "
        "(for the trader companion app), resolves the caller's identity, checks "
        "access permissions with <code>can_access_client()</code>, and enriches "
        "the raw JSON with inline notes and computed historical MT5 totals before "
        "returning the response."
    ))
    story += code_block("dashboard/app.py — get_data() (condensed)", """\
@app.route('/api/get_data')
def get_data():
    session_token = request.cookies.get('session_token')
    api_key = request.headers.get('X-API-Key')

    # --- resolve caller identity ---
    if session_token:
        session_info = validate_session(session_token)
        user_type = session_info['user_type']
        user_identifier = session_info['user_identifier']
    elif api_key:
        key_info = validate_api_key(api_key)
        user_type = 'api'
        user_identifier = key_info['owner']
    else:
        return jsonify({"status": "error", "message": "Auth required"}), 401

    client_id = request.args.get('client_id')
    if not can_access_client(user_type, user_identifier, client_id):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    data = get_client_data(client_id)
    # Inject visual notes
    notes = get_client_notes(client_id)
    for i, ev in enumerate(data.get('evaluations', [])):
        if i in notes:
            ev['_notes'] = notes[i]

    data['status'] = 'success'
    return jsonify(data)
""")

    story.append(section("2.5  /api/update_data — Dual-Auth Merge"))
    story.append(body(
        "The update endpoint performs a server-side merge strategy: incoming data is "
        "layered on top of existing data so that missing keys (e.g. the dashboard user "
        "did not send <code>deals</code>) default to their current stored values. "
        "A versioned snapshot is written to the history table after every successful save."
    ))
    story += code_block("dashboard/app.py — update_data() core merge logic", """\
@app.route('/api/update_data', methods=['POST'])
@limiter.limit("60 per minute")
def update_data():
    data = request.json
    existing_data = get_client_data(client_id) or {}

    evaluations = normalize_evaluations(
        data.get('evaluations', existing_data.get('evaluations', []))
    )

    client_data = {
        'deals':      data.get('deals',      existing_data.get('deals',      [])),
        'positions':  data.get('positions',  existing_data.get('positions',  [])),
        'account':    data.get('account',    existing_data.get('account',    {})),
        'evaluations': evaluations,
        'statistics': data.get('statistics', existing_data.get('statistics', {})),
        # ... other fields merged similarly
    }

    success, version = save_client_data_with_history(
        client_id, client_data,
        action='UPDATE',
        changed_by=user_identifier,
        changed_by_type=user_type,
        ip_address=get_remote_address(),
        change_source='dashboard_edit',
        change_description=f'Manual edit by {user_type}'
    )

    return jsonify({"status": "success", "version": version})
""")

    story.append(section("2.6  Route Structure"))
    story.append(body(
        "Routes are organised into logical groups. All routes serving HTML pages "
        "are decorated with <code>@require_session</code> for redirect-to-login "
        "behaviour, while JSON API routes return structured error objects."
    ))
    story.append(data_table(
        ["Route Pattern", "Template", "Access"],
        [
            ["/", "login.html", "Public"],
            ["/super_admin", "super_admin.html", "super_admin only"],
            ["/admin/<admin_name>", "admin_dashboard.html", "admin / super_admin"],
            ["/trader/<trader_name>", "index.html", "trader / admin / super_admin"],
            ["/dashboard/<client_id>", "index.html", "client (own data only)"],
            ["/financial_overview", "financial_overview.html", "super_admin only"],
        ],
        col_widths=[5*cm, 5*cm, 5*cm]
    ))

    story.append(section("2.7  Account Signature Matching"))
    story.append(body(
        "MT5 deal comments often contain truncated account numbers "
        "(e.g. <code>FNFT...59574</code>). The server resolves these to evaluation rows "
        "using a signature-based algorithm that extracts the first-4 and last-4/5 digits "
        "normalised to lowercase."
    ))
    story += code_block("dashboard/app.py — get_account_signature()", """\
def get_account_signature(account_number):
    account_str = str(account_number).strip()

    # Truncated format: PREFIX...SUFFIX  e.g.  FNFT...59574
    if '...' in account_str:
        parts = account_str.split('...')
        prefix = parts[0][:4] if len(parts[0]) >= 4 else parts[0]
        suffix = parts[1]          # keep full suffix
        return (prefix + suffix).lower()

    # Standard: first 4 + last 4
    if len(account_str) < 8:
        return account_str.lower()
    return (account_str[:4] + account_str[-4:]).lower()
""")


def build_ch3_database(story):
    story += chapter("Chapter 3: Database Layer", "ch3")

    story.append(section("3.1  Engine & Connection Strategy"))
    story.append(body(
        "The database module (<b>dashboard/database.py</b>, ~1 300 lines) uses Python's "
        "standard <code>sqlite3</code> library in development, with a thin abstraction "
        "layer that can be swapped for <code>psycopg2</code> (PostgreSQL) in production "
        "by changing a single environment variable."
    ))
    story.append(body(
        "All connections are obtained via a context manager (<code>get_connection()</code>) "
        "that sets <code>row_factory = sqlite3.Row</code> for named-column access and "
        "enables WAL journal mode for better concurrent read performance."
    ))

    story.append(section("3.2  Schema Reference"))
    story.append(subsection("user_credentials"))
    story += code_block("dashboard/database.py — user_credentials table DDL", """\
CREATE TABLE IF NOT EXISTS user_credentials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL,
    email           TEXT,
    password_hash   TEXT    NOT NULL,
    salt            TEXT    NOT NULL,
    user_type       TEXT    NOT NULL,   -- super_admin | admin | trader | client
    parent_admin    TEXT,               -- hierarchy link
    parent_trader   TEXT,               -- hierarchy link
    is_active       INTEGER DEFAULT 1,
    must_change_password INTEGER DEFAULT 0,
    last_login      TEXT,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now')),
    UNIQUE(username, user_type)
)
""")

    story.append(subsection("clients_data"))
    story += code_block("dashboard/database.py — clients_data table DDL", """\
CREATE TABLE IF NOT EXISTS clients_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL UNIQUE,
    deals       TEXT    DEFAULT '[]',      -- JSON array
    positions   TEXT    DEFAULT '[]',      -- JSON array
    account     TEXT    DEFAULT '{}',      -- JSON object
    evaluations TEXT    DEFAULT '[]',      -- JSON array (main eval sheet rows)
    updated_at  TEXT    DEFAULT (datetime('now'))
)
""")

    story.append(subsection("audit_log"))
    story += code_block("dashboard/database.py — audit_log table DDL", """\
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    action      TEXT    NOT NULL,          -- e.g. 'DATA_UPDATE', 'LOGIN', 'ROLLBACK'
    user_type   TEXT,
    user_identifier TEXT,
    ip_address  TEXT,
    description TEXT,
    success     INTEGER DEFAULT 1,
    client_id   TEXT
)
""")

    story.append(subsection("data_history (version snapshots)"))
    story += code_block("dashboard/database.py — data_history table DDL", """\
CREATE TABLE IF NOT EXISTS data_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT    NOT NULL,
    version         INTEGER NOT NULL,
    data_snapshot   TEXT    NOT NULL,      -- full JSON snapshot
    action          TEXT,
    changed_by      TEXT,
    changed_by_type TEXT,
    ip_address      TEXT,
    change_source   TEXT,
    change_description TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
)
""")

    story.append(subsection("daily_watermarks & waterlog_periods"))
    story += code_block("dashboard/database.py — watermark tables DDL", """\
CREATE TABLE IF NOT EXISTS daily_watermarks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL,
    eval_index  INTEGER NOT NULL,
    date        TEXT    NOT NULL,
    balance     REAL,
    drawdown_pct REAL,
    created_at  TEXT    DEFAULT (datetime('now')),
    UNIQUE(client_id, eval_index, date)
);

CREATE TABLE IF NOT EXISTS waterlog_periods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL,
    eval_index  INTEGER NOT NULL,
    start_date  TEXT    NOT NULL,
    end_date    TEXT,
    peak_balance REAL,
    trough_balance REAL,
    max_drawdown_pct REAL,
    status      TEXT    DEFAULT 'open'
);
""")

    story.append(section("3.3  Password Security"))
    story.append(body(
        "Passwords are hashed using PBKDF2-HMAC-SHA256 with 100 000 iterations and a "
        "cryptographically random 32-byte salt generated by <code>secrets.token_hex(32)</code>. "
        "Comparison uses <code>secrets.compare_digest()</code> to prevent timing attacks."
    ))
    story += code_block("dashboard/database.py — hash_password / verify_password", """\
import secrets, hashlib

def hash_password(password: str, salt: str = None) -> tuple:
    if salt is None:
        salt = secrets.token_hex(32)              # 64-char hex string
    password_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000                                   # OWASP-recommended iteration count
    ).hex()
    return password_hash, salt

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, stored_hash)  # constant-time
""")

    story.append(section("3.4  Login Verification Flow"))
    story += code_block("dashboard/database.py — verify_user_password() (condensed)", """\
def verify_user_password(username, password, user_type):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, password_hash, salt,
                   user_type, parent_admin, parent_trader, must_change_password
            FROM user_credentials
            WHERE username = ? AND user_type = ? AND is_active = 1
        ''', (username, user_type))
        row = cursor.fetchone()

        if row is None:
            return None                        # user not found
        if not verify_password(password, row['password_hash'], row['salt']):
            return None                        # wrong password

        # Stamp last_login
        cursor.execute(
            'UPDATE user_credentials SET last_login = ? WHERE id = ?',
            (datetime.now().isoformat(), row['id'])
        )
        conn.commit()

        return {
            'id': row['id'], 'username': row['username'],
            'email': row['email'], 'user_type': row['user_type'],
            'parent_admin': row['parent_admin'],
            'parent_trader': row['parent_trader'],
            'must_change_password': bool(row['must_change_password'])
        }
""")

    story.append(section("3.5  Versioned History & Rollback"))
    story.append(body(
        "Every data mutation triggers <code>save_client_data_with_history()</code>, "
        "which writes a full JSON snapshot to <code>data_history</code> with an "
        "incrementing version counter.  The dashboard's version history panel lists "
        "these snapshots, and any version can be restored via <code>/api/rollback</code>."
    ))
    story.append(callout(
        "Rollback is non-destructive: the restored snapshot itself becomes version N+1, "
        "so the full history is always preserved and any rollback can itself be rolled back."
    ))

    story.append(section("3.6  Soft Delete Pattern"))
    story.append(body(
        "Evaluation rows deleted from the dashboard are marked with a "
        "<code>_deleted: true</code> flag in the JSON array rather than being physically "
        "removed.  This means concurrent pushes from the Trader Companion app cannot "
        "accidentally resurrect deleted rows."
    ))
    story += code_block("dashboard/templates/index.html — soft delete (JS)", """\
// Mark as soft-deleted instead of splicing the array
currentData.evaluations[index]._deleted = true;

// Render loop skips deleted rows
rowsToRender = currentData.evaluations.filter(
    ev => !ev._deleted
);
""")


def build_ch4_frontend(story):
    story += chapter("Chapter 4: Frontend Application", "ch4")

    story.append(section("4.1  Architecture Choice"))
    story.append(body(
        "The entire UI is delivered as a single HTML file — "
        "<b>dashboard/templates/index.html</b> (~4 300 lines).  "
        "No JavaScript framework or build tool is used; all interactivity is implemented "
        "in vanilla ES6+ code embedded directly in the template. "
        "This choice eliminates build complexity and makes the app trivially deployable "
        "as a Jinja2 template served by Flask."
    ))

    story.append(section("4.2  Layout Structure"))
    story.append(data_table(
        ["DOM Element", "CSS Class / ID", "Role"],
        [
            ["<header>", ".header-title-bar + .header-controls-bar", "Sticky two-row header: logo/title + tabs/controls"],
            ["<main>", "#main-content", "Scrollable content area below the header"],
            ["<table>", "#eval-table", "Main evaluations data grid (~60+ columns)"],
            ["<thead>", "—", "Three sticky header rows: group labels, column names, filters"],
            ["<tbody>", "#eval-tbody", "Rendered evaluation rows (paginated, 50/page)"],
            ["<div>", "#eval-load-more-bar", "'Show More' pagination trigger bar"],
            ["<div>", "#section-sticky-label", "Floating pill inside EVAL INFO header showing current scroll section"],
        ],
        col_widths=[3*cm, 5.5*cm, 7.5*cm]
    ))

    story.append(section("4.3  Sticky Header System"))
    story.append(body(
        "The table uses a three-tier sticky-header system implemented entirely in CSS. "
        "Each tier is positioned with a different <code>top</code> offset so all three "
        "rows remain visible when the user scrolls down through rows."
    ))
    story += code_block("dashboard/static/css/style.css — sticky header tiers", """\
/* Row 1: Section group labels (EVAL INFO, EVAL PHASE, etc.) */
thead tr:nth-child(1) th {
    position: sticky;
    top: 0;
    z-index: 3000;
}

/* Row 2: Column names */
thead tr:nth-child(2) th {
    position: sticky;
    top: 42px;    /* height of row 1 */
    z-index: 2000;
}

/* Row 3: Column filter inputs */
thead tr:nth-child(3) th {
    position: sticky;
    top: 84px;    /* row 1 + row 2 heights */
    z-index: 1500;
}

/* Full-page header also sticky */
header {
    position: sticky;
    top: 0;
    z-index: 5000;
    flex-direction: column;
}
""")

    story.append(section("4.4  Scroll Section Indicator (Pill Badge)"))
    story.append(body(
        "A coloured pill badge inside the EVAL INFO group header updates in real-time "
        "as the user scrolls the table horizontally, showing which logical section is "
        "currently in view (e.g. EVAL INFO, EVAL PHASE, FUNDED PHASE, FARMING)."
    ))
    story += code_block("dashboard/templates/index.html — updateScrollIndicator()", """\
const sectionLabelMap = {
    'eval-info':   { label: 'EVAL INFO',   color: '#60a5fa' }, // blue
    'eval-phase':  { label: 'EVAL PHASE',  color: '#4ade80' }, // green
    'funded-phase':{ label: 'FUNDED PHASE',color: '#fb7185' }, // pink-red
    'farming':     { label: 'FARMING',     color: '#c084fc' }, // purple
};

function updateScrollIndicator() {
    const pill = document.getElementById('section-sticky-label');
    if (!pill) return;

    const tableRect = evalTable.getBoundingClientRect();
    const viewCenter = tableRect.left + tableRect.width / 2;

    // Find which group header overlaps the centre of the viewport
    for (const [key, config] of Object.entries(sectionLabelMap)) {
        const header = document.querySelector(`th[data-section="${key}"]`);
        if (!header) continue;
        const r = header.getBoundingClientRect();
        if (r.left <= viewCenter && r.right >= viewCenter) {
            pill.textContent = config.label;
            pill.style.background = config.color + '33';   // 20% opacity fill
            pill.style.color      = config.color;
            pill.style.borderColor= config.color;
            break;
        }
    }
}

// Attach to both scroll axes
evalTable.closest('.table-wrapper')
    .addEventListener('scroll', updateScrollIndicator, { passive: true });
""")

    story.append(section("4.5  Pagination Strategy"))
    story.append(body(
        "Evaluation rows are rendered in pages of 50 to avoid DOM congestion on "
        "accounts with hundreds of evaluations.  A sticky 'Show More' bar at the "
        "bottom of the table loads the next batch without any network request — "
        "all data is already resident in the JavaScript <code>currentData</code> object."
    ))
    story += code_block("dashboard/templates/index.html — pagination globals", """\
let evalPage = 1;
const EVAL_PAGE_SIZE = 50;

function renderEvaluationsTable(data, append = false) {
    if (!append) evalPage = 1;

    const all = (data.evaluations || [])
        .filter(ev => !ev._deleted)
        .sort((a, b) => b.originalIndex - a.originalIndex); // newest first

    const slice = all.slice(0, evalPage * EVAL_PAGE_SIZE);

    // ... build and insert table rows ...

    // Show / hide the 'load more' bar
    const bar  = document.getElementById('eval-load-more-bar');
    const more = all.length > slice.length;
    bar.style.display = more ? 'flex' : 'none';
    if (more) {
        bar.querySelector('.load-more-count').textContent =
            `${all.length - slice.length} more`;
    }
}

function loadMoreEvaluations() {
    evalPage++;
    renderEvaluationsTable(currentData, true);
}
""")

    story.append(section("4.6  Inline Editing & Save Flow"))
    story.append(body(
        "Each cell that can be edited triggers a <code>saveData()</code> call which "
        "PATCHes the entire current state back to the server. The function throttles "
        "saves to avoid hammering the API on rapid keystrokes using a debounce timer."
    ))
    story += code_block("dashboard/templates/index.html — saveData() (condensed)", """\
let saveTimer = null;

function saveData(changeDescription = 'Cell edit') {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
        const payload = {
            ...currentData,
            client_id: currentClientId,
            action_type: 'UPDATE',
            change_description: changeDescription
        };

        const resp = await fetch('/api/update_data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const result = await resp.json();
        if (result.status === 'success') {
            showToast('Saved ✓', 'success');
            currentVersion = result.version;
        } else {
            showToast('Save failed: ' + result.message, 'error');
        }
    }, 600);   // 600 ms debounce
}
""")

    story.append(section("4.7  Brand Colour System"))
    story.append(body(
        "Each prop firm has a distinct brand accent colour applied to evaluation rows "
        "and UI indicators, making it instantly clear which firm is associated with "
        "each account row."
    ))
    story.append(data_table(
        ["Prop Firm", "Brand Colour", "Hex", "Applied To"],
        [
            ["Topstep",    "Yellow / Gold",  "#fcd34d", "Row accent, badges, indicators"],
            ["Lucid",      "Black / Slate",  "#334155", "Row accent, muted tones"],
            ["Alpha",      "Green",          "#4ade80", "Row accent, profit indicators"],
            ["FTMO",       "Blue",           "#60a5fa", "Row accent"],
            ["My Forex Funds", "Orange",     "#fb923c", "Row accent"],
        ],
        col_widths=[3.5*cm, 3.5*cm, 3*cm, 5.5*cm]
    ))


def build_ch5_trader_companion(story):
    story += chapter("Chapter 5: Trader Companion Desktop App", "ch5")

    story.append(section("5.1  Purpose"))
    story.append(body(
        "The <b>Trader Companion</b> is a Windows-native Python application built with "
        "Tkinter that runs continuously alongside a MetaTrader 5 terminal. "
        "It uses the official <code>MetaTrader5</code> Python package to fetch live "
        "trading data and push it to the dashboard server every 60 seconds."
    ))

    story.append(section("5.2  MT5 Data Extraction"))
    story += code_block("trader_companion/trader_app.py — live data fetch (pattern)", """\
import MetaTrader5 as mt5

def fetch_mt5_data(self):
    if not mt5.initialize():
        self.log('MT5 init failed')
        return None

    # Account summary
    account_info = mt5.account_info()._asdict()

    # All historical deals (closed trades)
    deals = mt5.history_deals_get(
        datetime(2020, 1, 1),
        datetime.now()
    )
    deals_list = [d._asdict() for d in deals] if deals else []

    # Open positions
    positions = mt5.positions_get()
    positions_list = [p._asdict() for p in positions] if positions else []

    mt5.shutdown()
    return {
        'account': account_info,
        'deals': deals_list,
        'positions': positions_list
    }
""")

    story.append(section("5.3  Evaluation Matching Algorithm"))
    story.append(body(
        "The most complex part of the Trader Companion is matching MT5 deal comments "
        "(which contain truncated account numbers) to rows in the user's evaluation "
        "spreadsheet. The matching uses a multi-strategy fallback: exact match → "
        "signature match (first4+last4 digits) → last-N-digits match."
    ))
    story.append(data_table(
        ["Strategy", "Input", "Match Condition"],
        [
            ["1. Exact",   "Full account string",    "account_str == eval['Account #']"],
            ["2. Signature", "First4 + Last4 digits", "signature(deal) == signature(eval['Account #'])"],
            ["3. Last-N",  "Last 5 digits",          "deal[-5:] == eval['Account #'][-5:]"],
            ["4. Prefix",  "First 4 chars",          "Used only for firm-specific disambiguation"],
        ],
        col_widths=[2.5*cm, 4.5*cm, 9*cm]
    ))

    story.append(section("5.4  Push Protocol"))
    story.append(body(
        "After processing, the app sends a POST request to <code>/api/update_data</code> "
        "with the full payload including deals, positions, and updated evaluations. "
        "Regular pushes send <code>evaluations: []</code>, preserving server-side edits. "
        "Hedging sync pushes first fetch the current evaluations, update the hedge-related "
        "fields, then push the merged result."
    ))
    story += code_block("trader_companion/trader_app.py — push call (pattern)", """\
def push_to_server(self, data: dict, include_evaluations: bool = False):
    if not include_evaluations:
        data['evaluations'] = []    # preserve server-side eval edits

    response = requests.post(
        f"{self.server_url}/api/update_data",
        json=data,
        headers={'X-API-Key': self.api_key},
        timeout=30
    )
    result = response.json()
    if result.get('status') == 'success':
        self.log(f"Pushed. Server version: {result.get('version')}")
    else:
        self.log(f"Push failed: {result.get('message')}")
""")

    story.append(section("5.5  Desktop Build (PyInstaller)"))
    story.append(body(
        "The app is distributed as a standalone <code>.exe</code> using PyInstaller. "
        "The spec file bundles all Python dependencies, the Tkinter runtime, and "
        "any required assets into a single-file executable that end users can run "
        "on Windows without installing Python or any packages."
    ))
    story.append(data_table(
        ["Spec File", "Version", "Entry Point"],
        [
            ["Trader_Companion_v1.2.0.spec", "1.2.0", "trader_companion/trader_app.py"],
            ["BallerQuotes_Trader_Companion_v1.2.0.spec", "1.2.0", "trader_companion/baller_app.py"],
        ],
        col_widths=[7*cm, 3*cm, 6*cm]
    ))
    story += code_block("Build command", """\
# From workspace root, with PyInstaller installed:
pyinstaller Trader_Companion_v1.2.0.spec --clean
# Output: dist/Trader_Companion_v1.2.0/Trader_Companion_v1.2.0.exe
""")


def build_ch6_financial(story):
    story += chapter("Chapter 6: Financial Calculations Module", "ch6")

    story.append(section("6.1  Overview"))
    story.append(body(
        "<b>dashboard/financial_overview.py</b> is the analytics engine. "
        "It processes raw deal/position data from the database and produces "
        "aggregated financial metrics: running P&L, deposit growth, fee curves, "
        "hedge efficiency, and per-trader performance statistics."
    ))

    story.append(section("6.2  Core Functions"))
    story.append(data_table(
        ["Function", "Output"],
        [
            ["calculate_propfirm_overview()", "Aggregated P&L, deposits, withdrawals per prop firm"],
            ["get_payouts_history()", "Chronological list of payout events"],
            ["get_portfolio_growth_data()", "Time-series of combined portfolio value"],
            ["get_cumulative_deposits()", "Running deposit total over time"],
            ["get_cumulative_trading_profit()", "Running realised profit over time"],
            ["get_cumulative_fees_data()", "Running fee expenditure over time"],
            ["get_cumulative_hedge_data()", "Running hedge result vs. sheet value"],
            ["calculate_trader_stats()", "Per-trader win rate, avg profit, drawdown stats"],
            ["get_client_performance_stats()", "Per-client performance breakdown"],
            ["get_cached_clients_dataset()", "Memoised full dataset across all clients"],
        ],
        col_widths=[7*cm, 9*cm]
    ))

    story.append(section("6.3  Watermark Scheduler"))
    story.append(body(
        "A background thread (<b>dashboard/scheduler.py</b>) wakes at midnight UTC "
        "every day, iterates over all active evaluations, and records a "
        "<b>daily watermark</b> — the end-of-day balance and maximum drawdown — "
        "to the <code>daily_watermarks</code> table. "
        "This enables accurate drawdown tracking across multi-day sessions."
    ))
    story.append(callout(
        "Phase transitions (e.g. Challenge passed → Funded) are detected automatically "
        "by comparing the current balance watermark against phase-definition thresholds "
        "stored in the <code>phase_definitions</code> table."
    ))


def build_ch7_deployment(story):
    story += chapter("Chapter 7: Deployment & Operations", "ch7")

    story.append(section("7.1  Production Stack"))
    story.append(data_table(
        ["Component", "Technology", "Detail"],
        [
            ["OS",         "Ubuntu 22.04 LTS",   "VPS or dedicated server"],
            ["WSGI Server","Gunicorn 21+",        "4 workers, gevent worker class"],
            ["Proxy",      "Nginx",               "SSL termination, static files, rate limiting"],
            ["SSL",        "Let's Encrypt / Certbot", "Auto-renewal via systemd timer"],
            ["DB (prod)",  "PostgreSQL 15",       "Managed instance; SQLite used for dev"],
            ["Process Mgmt","systemd",            "Auto-restart on crash, boot-time start"],
            ["Secrets",    "Environment vars",    "FLASK_SECRET_KEY, DATABASE_URL, etc."],
        ],
        col_widths=[3*cm, 4*cm, 9*cm]
    ))

    story.append(section("7.2  Gunicorn Configuration"))
    story += code_block("gunicorn.conf.py", """\
workers = 4
worker_class = 'gevent'
bind = '127.0.0.1:5000'
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = 'logs/access.log'
errorlog  = 'logs/error.log'
loglevel  = 'info'
""")

    story.append(section("7.3  Nginx Reverse Proxy (sample)"))
    story += code_block("nginx site configuration (condensed)", """\
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias /var/www/dashboard/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}

# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}
""")

    story.append(section("7.4  Environment Variables"))
    story.append(data_table(
        ["Variable", "Required", "Description"],
        [
            ["FLASK_SECRET_KEY",  "Yes", "Random 64-char hex string for session signing"],
            ["DATABASE_URL",      "Prod", "PostgreSQL connection string (postgres://…)"],
            ["FLASK_ENV",         "No",  "'production' disables debug mode"],
            ["RATE_LIMIT_STORAGE","No",  "Redis URI for distributed rate limiting"],
            ["LOG_LEVEL",         "No",  "'DEBUG' | 'INFO' | 'WARNING'"],
        ],
        col_widths=[4.5*cm, 2.5*cm, 9*cm]
    ))

    story.append(section("7.5  Deployment Script"))
    story += code_block("deploy.sh — production deploy (condensed)", """\
#!/bin/bash
set -e

echo "[1/5] Pulling latest code..."
git pull origin main

echo "[2/5] Installing Python dependencies..."
pip install -r requirements-production.txt

echo "[3/5] Running database migrations..."
python migrations.py

echo "[4/5] Collecting static files..."
# (No build step needed — static assets served directly by Nginx)

echo "[5/5] Reloading Gunicorn..."
systemctl reload gunicorn

echo "Deploy complete."
""")

    story.append(section("7.6  Rate Limiting Strategy"))
    story.append(body(
        "Flask-Limiter applies layered rate limits to prevent abuse. "
        "API push endpoints allow higher throughput for the Trader Companion app, "
        "while authentication endpoints are tightly restricted to block brute-force attacks."
    ))
    story.append(data_table(
        ["Endpoint Group", "Limit", "Rationale"],
        [
            ["/api/auth/login",    "5/minute",      "Prevent credential stuffing"],
            ["/api/update_data",   "60/minute",     "Allow frequent MT5 sync pushes"],
            ["/api/get_data",      "120/minute",    "Dashboard polling"],
            ["Default (all others)", "10 000/day, 2 000/hour", "General protection"],
        ],
        col_widths=[5*cm, 3.5*cm, 7.5*cm]
    ))


def build_ch8_security(story):
    story += chapter("Chapter 8: Security Architecture", "ch8")

    story.append(section("8.1  Defence in Depth"))
    story.append(body(
        "Security is implemented at multiple layers: transport (TLS), network (Nginx "
        "rate limiting + firewall), application (RBAC decorators + brute-force lockout), "
        "and data (PBKDF2 password hashing + parameterised SQL queries)."
    ))

    story.append(section("8.2  Brute-Force Protection"))
    story.append(body(
        "The <code>login_attempts</code> table records every failed login. "
        "After 5 consecutive failures from the same IP or for the same username, "
        "the account is locked for 15 minutes. The lockout is checked via "
        "<code>is_account_locked()</code> before any credential verification occurs."
    ))
    story += code_block("dashboard/database.py — login_attempts table", """\
CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier  TEXT    NOT NULL,   -- username or IP
    attempt_time TEXT   NOT NULL,
    success     INTEGER DEFAULT 0
);
""")

    story.append(section("8.3  SQL Injection Prevention"))
    story.append(body(
        "All database queries use parameterised statements (<code>cursor.execute(sql, (param,))</code>). "
        "No string formatting or concatenation is used for SQL construction anywhere in the codebase."
    ))
    story += code_block("dashboard/database.py — parameterised query (example)", """\
# CORRECT — parameterised
cursor.execute(
    'SELECT * FROM user_credentials WHERE username = ? AND user_type = ?',
    (username, user_type)
)

# NEVER done — vulnerable to injection
# cursor.execute(f\"SELECT * FROM user_credentials WHERE username = '{username}'\")
""")

    story.append(section("8.4  Session Management"))
    story.append(body(
        "Sessions are stored in the database as a <code>sessions</code> table. "
        "Each session token is a 64-character hex string generated by "
        "<code>secrets.token_hex(32)</code>. Sessions expire after 24 hours of "
        "inactivity. Tokens are transmitted exclusively via <code>HttpOnly</code> cookies "
        "to prevent JavaScript access."
    ))

    story.append(section("8.5  Audit Log"))
    story.append(body(
        "Every significant action — login, data update, rollback, access denial, "
        "API key generation — is written to the <code>audit_log</code> table with "
        "the timestamp, action type, user identity, IP address, and success flag. "
        "Super admins can query the full audit log via <code>/api/audit_log</code>."
    ))


def build_ch9_workflows(story):
    story += chapter("Chapter 9: Developer Workflows", "ch9")

    story.append(section("9.1  Local Development Setup"))
    story += code_block("Setup commands (Windows PowerShell)", """\
# Clone repository
git clone https://github.com/Oukaharry/FuturesAutomatedFeed.git
cd FuturesAutomatedFeed

# Create virtual environment
python -m venv .venv
.venv\\Scripts\\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Initialise database
python -c "from dashboard.database import init_database; init_database()"

# Run development server
python wsgi.py
# → http://localhost:5000
""")

    story.append(section("9.2  Common Debug Scripts"))
    story.append(data_table(
        ["Script", "Purpose"],
        [
            ["debug_fetch.py",        "Test /api/get_data against a running server"],
            ["debug_ev.py",           "Inspect evaluation matching for a specific account"],
            ["debug_phase_logic.py",  "Trace phase-transition detection logic"],
            ["debug_compare.py",      "Diff two client data JSON snapshots"],
            ["debug_waterlog.py",     "Inspect watermark records for a client"],
            ["check_audit.py",        "Print recent audit log entries"],
            ["check_db_table.py",     "Dump any SQLite table to stdout"],
            ["reproduce_match.py",    "Reproduce an account-matching result with test data"],
            ["quick_test.py",         "Run lightweight sanity checks against the server"],
        ],
        col_widths=[5*cm, 11*cm]
    ))

    story.append(section("9.3  Git Workflow"))
    story += code_block("Standard commit workflow", """\
git add -A
git commit -m "feat: descriptive message"
git push origin main

# Check remote status
git log --oneline -5
git status
""")

    story.append(section("9.4  Building the Desktop App"))
    story += code_block("PyInstaller build (from workspace root)", """\
# Ensure PyInstaller is installed
pip install pyinstaller

# Build using the spec file
pyinstaller Trader_Companion_v1.2.0.spec --clean --noconfirm

# Output location
# dist/Trader_Companion_v1.2.0/Trader_Companion_v1.2.0.exe
""")


def build_ch10_api(story):
    story += chapter("Chapter 10: REST API Reference", "ch10")

    story.append(section("10.1  Authentication"))
    story.append(body(
        "The API supports two authentication mechanisms: "
        "(1) <b>Session Cookie</b> — set on login via <code>/api/auth/login</code> and sent "
        "automatically by the browser for all subsequent requests; "
        "(2) <b>API Key</b> — a 32-char hex token sent in the <code>X-API-Key</code> header, "
        "intended for the Trader Companion desktop app and programmatic access."
    ))

    story.append(section("10.2  POST /api/auth/login"))
    story += code_block("Request", """\
POST /api/auth/login
Content-Type: application/json

{
  "username": "trader_harry",
  "password": "s3cur3P@ss",
  "user_type": "trader"
}
""")
    story += code_block("Response (200 OK)", """\
HTTP/1.1 200 OK
Set-Cookie: session_token=abc123...; HttpOnly; SameSite=Strict

{
  "status": "success",
  "user_type": "trader",
  "username": "trader_harry",
  "must_change_password": false
}
""")

    story.append(section("10.3  GET /api/get_data"))
    story += code_block("Request", """\
GET /api/get_data?client_id=harry_client_1
X-API-Key: <your-api-key>       # OR session cookie
""")
    story += code_block("Response schema (200 OK)", """\
{
  "status": "success",
  "deals":      [ { "ticket": 123, "symbol": "NQ", "profit": 150.0, ... } ],
  "positions":  [ { "ticket": 456, "symbol": "ES", "volume": 1.0,  ... } ],
  "account":    { "balance": 125000, "equity": 124800, "login": 9876543 },
  "evaluations":[ { "Firm": "Topstep", "Account #": "TSX123456", ... } ],
  "statistics": { "hedging_review": { ... }, "account_stats": { ... } },
  "last_updated": "2025-01-15T14:32:00"
}
""")

    story.append(section("10.4  POST /api/update_data"))
    story += code_block("Request", """\
POST /api/update_data
Content-Type: application/json
X-API-Key: <your-api-key>

{
  "identity":   { "client": "harry_client_1", "trader": "trader_harry" },
  "deals":      [ ... ],
  "positions":  [ ... ],
  "account":    { ... },
  "evaluations": [],          # empty = keep server-side evaluations
  "statistics": { ... }
}
""")
    story += code_block("Response (200 OK)", """\
{
  "status": "success",
  "message": "Data updated",
  "version": 42              # new version number in history
}
""")

    story.append(section("10.5  POST /api/rollback"))
    story += code_block("Request", """\
POST /api/rollback
Content-Type: application/json
Cookie: session_token=...

{
  "client_id": "harry_client_1",
  "version": 38              # target version to restore
}
""")
    story += code_block("Response (200 OK)", """\
{
  "status":  "success",
  "message": "Rolled back to version 38",
  "new_version": 43          # restoration itself creates a new version
}
""")

    story.append(section("10.6  Error Responses"))
    story.append(data_table(
        ["HTTP Status", "When / Meaning"],
        [
            ["400 Bad Request",    "Missing required fields in request body"],
            ["401 Unauthorized",   "No session cookie and no API key provided"],
            ["403 Forbidden",      "Valid credentials but insufficient permissions for resource"],
            ["404 Not Found",      "Requested client_id exists but has no saved data yet"],
            ["429 Too Many Requests", "Rate limit exceeded (see per-endpoint limits)"],
            ["500 Internal Server Error", "Unhandled exception — check server log"],
        ],
        col_widths=[4.5*cm, 11.5*cm]
    ))


# ─────────────────────────────────────────────
#  MAIN BUILD
# ─────────────────────────────────────────────
def build_pdf():
    doc = BookDoc(
        OUTPUT_FILE,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
        title=BOOK_TITLE,
        author="Oukaharry",
        subject="Technical Reference — MT5 Futures Hedging Dashboard",
    )

    toc = TableOfContents()
    toc.levelStyles = [STYLES["toc_h1"], STYLES["toc_h2"]]
    toc.dotsMinLevel = 0

    story = []

    # ── Cover ─────────────────────────────────
    story.append(PageBreak())   # switch to body template after cover
    build_cover(story)

    # ── TOC ───────────────────────────────────
    build_toc(story, toc)

    # ── Chapters ──────────────────────────────
    build_ch1_overview(story)
    build_ch2_backend(story)
    build_ch3_database(story)
    build_ch4_frontend(story)
    build_ch5_trader_companion(story)
    build_ch6_financial(story)
    build_ch7_deployment(story)
    build_ch8_security(story)
    build_ch9_workflows(story)
    build_ch10_api(story)

    # ── Final page ────────────────────────────
    story.append(PageBreak())
    story.append(SP(80))
    story.append(Paragraph("END OF DOCUMENT", STYLES["cover_title"]))
    story.append(SP(8))
    story.append(Paragraph(
        f"Generated {BUILD_DATE}  ·  github.com/Oukaharry/FuturesAutomatedFeed",
        STYLES["cover_meta"]
    ))

    doc.multiBuild(story)
    print(f"\n✓  PDF written to:  {OUTPUT_FILE}")
    print(f"   Pages built successfully.\n")


if __name__ == "__main__":
    build_pdf()
