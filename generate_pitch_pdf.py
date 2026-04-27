"""Generate a client-facing sales pitch PDF for TradeOps AI."""
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, Image, ListFlowable, ListItem, Flowable,
)
from reportlab.pdfgen import canvas
from datetime import datetime

# Brand palette
BRAND_NAVY = HexColor("#0B1733")
BRAND_BLUE = HexColor("#1E40AF")
BRAND_CYAN = HexColor("#06B6D4")
BRAND_GOLD = HexColor("#F59E0B")
BRAND_GREEN = HexColor("#10B981")
BRAND_GREY = HexColor("#475569")
BRAND_LIGHT = HexColor("#F1F5F9")
BRAND_BG = HexColor("#0F172A")

OUTPUT = "TradeOps_AI_Client_Pitch.pdf"

# ───────────────────────── styles ─────────────────────────
base = getSampleStyleSheet()

H_TITLE = ParagraphStyle(
    "TitleX", parent=base["Title"], fontName="Helvetica-Bold",
    fontSize=42, leading=48, textColor=white, alignment=TA_CENTER, spaceAfter=14,
)
H_SUB = ParagraphStyle(
    "SubX", parent=base["Normal"], fontName="Helvetica",
    fontSize=16, leading=22, textColor=BRAND_CYAN, alignment=TA_CENTER, spaceAfter=8,
)
H_TAG = ParagraphStyle(
    "TagX", parent=base["Normal"], fontName="Helvetica-Oblique",
    fontSize=12, leading=18, textColor=HexColor("#CBD5E1"), alignment=TA_CENTER,
)
H1 = ParagraphStyle(
    "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
    fontSize=22, leading=28, textColor=BRAND_NAVY, spaceBefore=4, spaceAfter=8,
)
H2 = ParagraphStyle(
    "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
    fontSize=14, leading=18, textColor=BRAND_BLUE, spaceBefore=10, spaceAfter=4,
)
BODY = ParagraphStyle(
    "Body", parent=base["BodyText"], fontName="Helvetica",
    fontSize=11, leading=16, textColor=HexColor("#1F2937"),
    alignment=TA_JUSTIFY, spaceAfter=6,
)
BODY_C = ParagraphStyle(
    "BodyC", parent=BODY, alignment=TA_CENTER,
)
LEAD = ParagraphStyle(
    "Lead", parent=BODY, fontSize=12.5, leading=18, textColor=HexColor("#0F172A"),
)
QUOTE = ParagraphStyle(
    "Quote", parent=BODY, fontName="Helvetica-Oblique", fontSize=11.5,
    leading=17, textColor=BRAND_GREY, leftIndent=18, rightIndent=18,
    borderPadding=10,
)
KPI_NUM = ParagraphStyle(
    "KPI", parent=base["Normal"], fontName="Helvetica-Bold",
    fontSize=28, leading=32, textColor=BRAND_BLUE, alignment=TA_CENTER,
)
KPI_LBL = ParagraphStyle(
    "KPIL", parent=base["Normal"], fontName="Helvetica",
    fontSize=10, leading=13, textColor=BRAND_GREY, alignment=TA_CENTER,
)
SECTION_PILL = ParagraphStyle(
    "Pill", parent=base["Normal"], fontName="Helvetica-Bold",
    fontSize=9, leading=12, textColor=BRAND_CYAN, alignment=TA_LEFT, spaceAfter=2,
)
WHITE_BOLD = ParagraphStyle(
    "WB", parent=base["Normal"], fontName="Helvetica-Bold",
    fontSize=12, leading=16, textColor=white, alignment=TA_CENTER,
)


# ───────────────────────── decorators ─────────────────────────
def cover_page(canv, doc):
    canv.saveState()
    w, h = LETTER
    canv.setFillColor(BRAND_BG)
    canv.rect(0, 0, w, h, fill=1, stroke=0)
    # accent bar
    canv.setFillColor(BRAND_CYAN)
    canv.rect(0, h - 1.1 * inch, w, 0.08 * inch, fill=1, stroke=0)
    canv.setFillColor(BRAND_GOLD)
    canv.rect(0, 0.9 * inch, w, 0.06 * inch, fill=1, stroke=0)
    # footer
    canv.setFont("Helvetica", 9)
    canv.setFillColor(HexColor("#94A3B8"))
    canv.drawCentredString(w / 2, 0.55 * inch,
                           f"Confidential client briefing  •  {datetime.now().strftime('%B %Y')}")
    canv.restoreState()


def content_page(canv, doc):
    canv.saveState()
    w, h = LETTER
    # subtle header band
    canv.setFillColor(BRAND_NAVY)
    canv.rect(0, h - 0.6 * inch, w, 0.6 * inch, fill=1, stroke=0)
    canv.setFillColor(BRAND_CYAN)
    canv.rect(0, h - 0.62 * inch, w, 0.02 * inch, fill=1, stroke=0)
    canv.setFont("Helvetica-Bold", 11)
    canv.setFillColor(white)
    canv.drawString(0.6 * inch, h - 0.4 * inch, "TradeOps AI")
    canv.setFont("Helvetica", 9)
    canv.setFillColor(HexColor("#CBD5E1"))
    canv.drawRightString(w - 0.6 * inch, h - 0.4 * inch, "Client Pitch  •  Confidential")
    # page number
    canv.setFont("Helvetica", 9)
    canv.setFillColor(BRAND_GREY)
    canv.drawRightString(w - 0.6 * inch, 0.4 * inch, f"Page {doc.page}")
    canv.drawString(0.6 * inch, 0.4 * inch, "tradeopss.com")
    canv.restoreState()


# ───────────────────────── helpers ─────────────────────────
def kpi_card(number, label, color=BRAND_BLUE):
    num_style = ParagraphStyle(
        "kn", parent=KPI_NUM, textColor=color, fontSize=26, leading=30,
    )
    inner = Table(
        [[Paragraph(number, num_style)],
         [Paragraph(label, KPI_LBL)]],
        colWidths=[1.7 * inch], rowHeights=[0.55 * inch, 0.45 * inch],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return inner


def feature_row(icon, title, body):
    icon_p = Paragraph(
        f'<font color="#06B6D4" size="18"><b>{icon}</b></font>',
        ParagraphStyle("ic", parent=BODY, alignment=TA_CENTER),
    )
    title_p = Paragraph(f"<b>{title}</b>", ParagraphStyle(
        "ft", parent=BODY, fontSize=12, textColor=BRAND_NAVY, spaceAfter=2,
    ))
    body_p = Paragraph(body, BODY)
    inner = Table(
        [[icon_p, [title_p, body_p]]],
        colWidths=[0.55 * inch, 5.95 * inch],
    )
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#E2E8F0")),
    ]))
    return inner


def section_band(label, title):
    label_p = Paragraph(label.upper(), SECTION_PILL)
    title_p = Paragraph(title, H1)
    return [label_p, title_p, Spacer(1, 4)]


def two_col(left, right, widths=(3.25 * inch, 3.25 * inch)):
    t = Table([[left, right]], colWidths=list(widths))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def cta_block(text):
    p = Paragraph(text, WHITE_BOLD)
    t = Table([[p]], colWidths=[6.5 * inch], rowHeights=[0.7 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0, white),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


# ───────────────────────── content ─────────────────────────
def build():
    doc = SimpleDocTemplate(
        OUTPUT, pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.85 * inch, bottomMargin=0.7 * inch,
        title="TradeOps AI – Client Pitch",
        author="TradeOps AI",
    )

    story = []

    # ───── COVER ─────
    story.append(Spacer(1, 2.2 * inch))
    story.append(Paragraph("TradeOps&nbsp;AI", H_TITLE))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Capital Preservation, Engineered.", H_SUB))
    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "A defensive operations platform built on one promise: <b>your clients do not lose money</b> "
        "to a missed hedge, a missed payout, a missed renewal, or a missed rule. Ever.",
        H_TAG,
    ))
    story.append(Spacer(1, 1.2 * inch))
    # cover stat strip
    cs = Table(
        [[
            Paragraph('<font color="#10B981" size="22"><b>$0</b></font><br/>'
                      '<font color="#CBD5E1" size="9">Client capital lost to operational error</font>',
                      ParagraphStyle("cs", parent=BODY_C, textColor=white)),
            Paragraph('<font color="#06B6D4" size="22"><b>0</b></font><br/>'
                      '<font color="#CBD5E1" size="9">Accounts breached by an unmirrored hedge</font>',
                      ParagraphStyle("cs", parent=BODY_C, textColor=white)),
            Paragraph('<font color="#F59E0B" size="22"><b>0</b></font><br/>'
                      '<font color="#CBD5E1" size="9">Payouts missed since automation</font>',
                      ParagraphStyle("cs", parent=BODY_C, textColor=white)),
        ]],
        colWidths=[2.4 * inch] * 3,
    )
    cs.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(cs)
    story.append(PageBreak())

    # ───── PAGE 2 — The Problem ─────
    story += section_band("The real risk", "Clients don&rsquo;t lose money on bad trades. They lose it on bad ops.")
    story.append(Paragraph(
        "In a hedged prop-firm model, the trade itself is risk-neutral &mdash; one side wins what "
        "the other loses. <b>Capital is destroyed somewhere else entirely:</b> in the seconds between "
        "a fill on one platform and a manual click on another. In the renewal nobody cancelled. "
        "In the activation fee that vanished from a spreadsheet. In the payout window that closed "
        "on a Friday no one was watching.",
        LEAD,
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Every loss event we have ever investigated traces back to one of these:", BODY))

    pain_items = [
        ListItem(Paragraph("<b>Unmirrored hedge.</b> SL hits on the prop side, the MT5 side runs &mdash; or vice-versa. Account breached, capital gone.", BODY)),
        ListItem(Paragraph("<b>Silent rule breach.</b> Drawdown crossed by a tick, daily loss limit hit overnight, consistency rule failed by $50.", BODY)),
        ListItem(Paragraph("<b>Missed payout window.</b> Five-figure payout request never submitted &mdash; firm resets the timer.", BODY)),
        ListItem(Paragraph("<b>Renewal auto-charge on a dead account.</b> $200&ndash;$700 evaporates monthly, per account, until someone notices.", BODY)),
        ListItem(Paragraph("<b>Phantom internal-transfer rows</b> that corrupt reconciliation and trigger wrong-way decisions.", BODY)),
        ListItem(Paragraph("<b>Manual edits silently overwritten</b> by the next push &mdash; activation fees disappear, statuses revert, payouts vanish.", BODY)),
    ]
    story.append(ListFlowable(pain_items, bulletType="bullet", start="circle",
                              leftIndent=18, bulletColor=BRAND_GOLD))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        '"We have audited six-figure account losses across multiple firms. Not one of them was caused by '
        'a bad trade. Every single one was an ops failure that a machine should have caught."',
        QUOTE,
    ))
    story.append(PageBreak())

    # ───── PAGE 3 — The Solution ─────
    story += section_band("The solution", "A defensive system designed to make losing money impossible.")
    story.append(Paragraph(
        "TradeOps&nbsp;AI is engineered backwards from a single requirement: <b>no client capital is ever "
        "lost to an operational mistake.</b> Every feature exists to remove a known failure mode &mdash; "
        "hedge mismatch, breach, missed payout, lost edit, ghost row, forgotten renewal. The trade can "
        "go either way; the operations can&rsquo;t.",
        LEAD,
    ))
    story.append(Spacer(1, 8))

    kpis = Table(
        [[
            kpi_card("&lt;500ms", "Hedge mirror &mdash; loss exposure<br/>window per trade", BRAND_BLUE),
            kpi_card("$0", "Capital lost to operational<br/>error in production", BRAND_GREEN),
            kpi_card("100%", "Edits, payouts, fees<br/>protected from overwrite", BRAND_GOLD),
        ]],
        colWidths=[2.25 * inch] * 3,
    )
    kpis.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(kpis)
    story.append(Spacer(1, 14))

    story.append(Paragraph("How losses are prevented", H2))
    story.append(feature_row(
        "▣", "Hedge Protector — sub-second SL mirroring",
        "Polls MT5 every 500&nbsp;ms and listens to the Tradovate WebSocket. The instant a stop loss "
        "fills on one side, the matching hedge on the other platform is closed automatically. The "
        "window in which a client can lose money to an unmirrored hedge is measured in milliseconds, "
        "not minutes."
    ))
    story.append(feature_row(
        "▤", "Per-firm breach guards",
        "Drawdown, daily-loss, consistency and hard-stop thresholds enforced per firm before the order "
        "is placed. Funded-start balance modelled correctly per firm (MFFU/TopStep start at $0, not the "
        "funded number) so &ldquo;to make&rdquo; targets reflect real risk, not inflated marketing."
    ))
    story.append(feature_row(
        "◉", "Manual edits that cannot be overwritten",
        "Activation Fees, payouts, statuses and account numbers edited on the dashboard are protected "
        "by row fingerprints. No subsequent push from the trader app, the sheet or any other source "
        "can silently destroy a human decision &mdash; the most common cause of recurring billing loss."
    ))
    story.append(feature_row(
        "◧", "Auto-billing reconciliation — catches every charge",
        "Scrapes each firm&rsquo;s billing history and auto-fills Fee, Activation Fee, Date Purchased "
        "and Account # on the right row. Renewals on dead accounts and double-charges surface within "
        "hours, not at end-of-month when the money is already gone."
    ))
    story.append(PageBreak())

    # ───── PAGE 4 — Feature Catalogue cont. ─────
    story += section_band("Defence in depth", "Every known failure mode has a guard.")

    story.append(feature_row(
        "◇", "Quality scan — finds money about to leak",
        "Continuously audits every active account for missing statuses, blank fees, stale notes &gt;24h, "
        "incorrect weekday markers, missing activation fees on Alpha Futures funded accounts, and 20+ "
        "other compliance checks. Surfaces issues by severity and estimated date so admins fix problems "
        "<i>before</i> they turn into a charge or a breach."
    ))
    story.append(feature_row(
        "◈", "Payout-window watchdog",
        "Eligibility and submission deadlines tracked per firm, per account. The platform alerts &mdash; "
        "and in supported firms, can submit &mdash; before the window closes. A missed payout is now an "
        "impossible event, not a Friday-afternoon scramble."
    ))
    story.append(feature_row(
        "◐", "Internal-transfer &amp; ghost-row protection",
        "MT5 internal transfers are stripped at four layers (cache, push filter, comment parser, dashboard "
        "synthesizer). The phantom -$10,394 row that used to corrupt FundedNext reconciliations &mdash; and "
        "the wrong-direction decisions that followed it &mdash; is impossible by design."
    ))
    story.append(feature_row(
        "◒", "Wipe protection &amp; row preservation",
        "Any save or push that would drop more than 50% of evaluation rows is rejected. Partial pushes "
        "never delete existing rows. The platform fails closed: when in doubt, your data is preserved."
    ))
    story.append(feature_row(
        "◔", "Full audit trail &amp; one-click rollback",
        "Every change to every evaluation snapshotted with user, timestamp and IP. Roll back any client "
        "to any point in time. PostgreSQL-backed, daily backups, prod-to-local restore tooling. If a loss "
        "event occurs, you have the receipts."
    ))
    story.append(feature_row(
        "◈", "Daily client summaries — nothing slips through",
        "The 6-section EAT-midnight summary &mdash; challenge purchases, renewals, delays, payout requests, "
        "confirmations, action items &mdash; assembled automatically from live data. The trader and the admin "
        "both wake up to the same picture; nothing is forgotten because nobody &ldquo;owned&rdquo; it."
    ))
    story.append(PageBreak())

    # ───── PAGE 5 — Architecture / Trust ─────
    story += section_band("How it works", "Three connected pieces, one job.")
    arch_rows = [
        [Paragraph("<b>1. Trader Companion (desktop)</b>", H2),
         Paragraph("PyInstaller-packaged Windows app (~75&nbsp;MB) that lives next "
                   "to MetaTrader 5. It reads MT5 deals, talks to each prop firm via "
                   "their official APIs (or Selenium where no API exists), runs the "
                   "Hedge Protector, and ships data up to the dashboard.", BODY)],
        [Paragraph("<b>2. Push Pipeline (gzip + auth)</b>", H2),
         Paragraph("Authenticated, gzip-compressed push every cycle. Fresh-push "
                   "override + 5-minute TTL cache for performance &mdash; you always see the "
                   "latest data, the dashboard never reverts to a stale snapshot.", BODY)],
        [Paragraph("<b>3. Dashboard (Flask + Postgres)</b>", H2),
         Paragraph("Multi-tier role model (super_admin, admin, BEF admin, trader, "
                   "client). Read-only client portal, full edit for traders, "
                   "configurable financial views for admins. Hosted on tradeopss.com "
                   "with daily Postgres backups.", BODY)],
    ]
    arch = Table(arch_rows, colWidths=[2.2 * inch, 4.3 * inch])
    arch.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(arch)

    story.append(Spacer(1, 14))
    story.append(Paragraph("Security &amp; reliability", H2))
    sec_items = [
        ListItem(Paragraph("API keys + per-session tokens; rate-limited routes (60/min on writes).", BODY)),
        ListItem(Paragraph("Role-based access control with category filters (e.g. BEF admin sees only BEF clients).", BODY)),
        ListItem(Paragraph("Atomic save-with-history: every write produces a new versioned snapshot.", BODY)),
        ListItem(Paragraph("Wipe protection &mdash; saves that would drop &gt;50% of evaluation rows are blocked.", BODY)),
        ListItem(Paragraph("Daily Postgres backups; on-demand prod-to-local restore tooling.", BODY)),
    ]
    story.append(ListFlowable(sec_items, bulletType="bullet", start="square",
                              leftIndent=18, bulletColor=BRAND_GREEN))
    story.append(PageBreak())

    # ───── PAGE 6 — Outcomes ─────
    story += section_band("What this means for your clients", "Every loss vector, closed.")

    outcome_table = Table(
        [
            [Paragraph("<b>Loss vector</b>", WHITE_BOLD),
             Paragraph("<b>How TradeOps&nbsp;AI eliminates it</b>", WHITE_BOLD)],
            [Paragraph("Unmirrored hedge → breached account", BODY),
             Paragraph("Hedge Protector closes the matching side in &lt;500&nbsp;ms. Exposure window collapses to a fraction of a second.", BODY)],
            [Paragraph("Drawdown / daily-loss / consistency breach", BODY),
             Paragraph("Per-firm breach guards reject the order before it is placed. The breach event cannot occur.", BODY)],
            [Paragraph("Missed payout window", BODY),
             Paragraph("Eligibility tracked per firm; alerts fire days before close. Auto-submission where the firm allows.", BODY)],
            [Paragraph("Renewal auto-charge on a dead account", BODY),
             Paragraph("Billing reconciliation flags the charge within hours; cancellation queued before the next cycle.", BODY)],
            [Paragraph("Manual edit silently overwritten by next push", BODY),
             Paragraph("Row-fingerprint merge: dashboard-owned fields are preserved on every push, every time.", BODY)],
            [Paragraph("Phantom internal-transfer rows skewing reconciliation", BODY),
             Paragraph("Four-layer filter strips them at cache, push, comment parser, and dashboard synthesizer.", BODY)],
            [Paragraph("Bulk-delete or wipe of evaluation history", BODY),
             Paragraph("Saves dropping &gt;50% of rows are rejected. Every change versioned and one-click reversible.", BODY)],
        ],
        colWidths=[3.0 * inch, 3.5 * inch],
    )
    outcome_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, BRAND_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
        ("LINEBELOW", (0, 0), (-1, 0), 0, BRAND_NAVY),
    ]))
    story.append(outcome_table)

    story.append(Spacer(1, 14))
    story.append(Paragraph(
        '"The platform pays for itself the first time it stops one breach, one wrong-way hedge, '
        'or one missed payout. Everything after that &mdash; the time saved, the visibility, the '
        'audit trail &mdash; is a bonus."',
        QUOTE,
    ))
    story.append(PageBreak())

    # ───── PAGE 7 — The Numbers (Capital, Payouts, Timeline) ─────
    story += section_band("The numbers", "What it costs, what it pays, when it pays.")
    story.append(Paragraph(
        "Below is the per-account financial model for a standard <b>$50,000 funded futures account</b> "
        "(MFFU / FundedNext blueprint). Hedge capital is the sum of stop-loss exposure carried on the "
        "MT5 hedge side across the full challenge → funded → payout ladder. Payout targets are taken "
        "directly from the live blueprints in the platform.",
        LEAD,
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Per-account economics ($50k account)", H2))
    per_acct = Table(
        [
            ["Item", "Amount", "Notes"],
            ["Account purchase (evaluation + activation)", "~$300", "One-time, billed to account"],
            ["Working hedge capital required", "~$2,500", "Covers active-stage SL exposure"],
            ["Recommended capital with buffer", "~$3,000", "+20% headroom for slippage / news"],
            ["Worst-case ladder loss (all stages SL)", "~$5,000", "Only if every stage stops out"],
            ["Funded payout target (per cycle)", "$2,500 – $3,000", "From live blueprint TPs"],
            ["Client share after 80/20 split", "$2,000 – $2,400", "Net to client per payout"],
            ["Typical payout cycles per account", "4 – 6", "Before reset / new evaluation"],
            ["Lifetime client take per account", "~$8,000 – $14,000", "Compounded across cycles"],
        ],
        colWidths=[2.7 * inch, 1.5 * inch, 2.3 * inch],
    )
    per_acct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, BRAND_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica"),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 1), (1, -1), BRAND_BLUE),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
    ]))
    story.append(per_acct)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Timeline — purchase to first payout", H2))
    timeline = Table(
        [
            ["Day", "Milestone", "Cash position"],
            ["0", "Account purchased; hedge capital deployed on MT5", "−$300 fee, $2,500 working"],
            ["1 – 7", "Challenge phase trades; sub-second hedge mirroring active", "Capital intact, hedged"],
            ["5 – 10", "Evaluation passed; account moves to funded", "Activation fee billed"],
            ["10 – 21", "Funded trades 1–4 executed against blueprint TPs", "Profit accrues on prop side"],
            ["21 – 30", "First payout requested and received", "+$2,000 net to client (80%)"],
            ["~14-day cycle", "Subsequent payouts every 2 weeks while account lives", "+$2,000 per cycle, recurring"],
        ],
        colWidths=[1.0 * inch, 3.3 * inch, 2.2 * inch],
    )
    timeline.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, BRAND_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, -1), BRAND_NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
    ]))
    story.append(timeline)
    story.append(PageBreak())

    # ───── PAGE 8 — Scaling model ─────
    story += section_band("Scaling the model", "Multiply the engine, not the workload.")
    story.append(Paragraph(
        "Because TradeOps&nbsp;AI removes the human from hedging, billing, summaries and rule-checking, "
        "the same trader can run 10 accounts as easily as one. Capital and revenue scale linearly; "
        "operational time does not.",
        LEAD,
    ))
    story.append(Spacer(1, 8))

    scale = Table(
        [
            ["", "1 account", "5 accounts", "10 accounts"],
            ["Hedge capital required", "~$3,000", "~$15,000", "~$30,000"],
            ["Account-purchase cost (one-off)", "~$300", "~$1,500", "~$3,000"],
            ["First payout (Day ~30, client share)", "~$2,000", "~$10,000", "~$20,000"],
            ["Steady-state monthly client take", "~$4,000", "~$20,000", "~$40,000"],
            ["Annualised client take (conservative)", "~$48,000", "~$240,000", "~$480,000"],
            ["Daily ops time without TradeOps AI", "1–2 hrs", "5–8 hrs", "10–15 hrs"],
            ["Daily ops time WITH TradeOps AI", "<5 min", "<15 min", "<30 min"],
        ],
        colWidths=[2.4 * inch, 1.35 * inch, 1.35 * inch, 1.4 * inch],
    )
    scale.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, BRAND_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (1, 1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 1), (-1, 5), BRAND_BLUE),
        ("TEXTCOLOR", (1, 5), (-1, 5), BRAND_GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, HexColor("#E2E8F0")),
        ("BACKGROUND", (0, 5), (-1, 5), HexColor("#ECFDF5")),
    ]))
    story.append(scale)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Payback math", H2))
    story.append(Paragraph(
        "On a single $50k account, the client recovers the entire <b>~$300 purchase cost on the first payout</b> "
        "(typically within 30 days), then receives ~$2,000 net every ~14 days for as long as the account survives. "
        "Across 10 accounts, the client&rsquo;s <b>$33,000 total upfront commitment</b> (capital + fees) is fully "
        "returned inside the first payout cycle, with steady-state monthly net of ~$40,000 thereafter.",
        BODY,
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        '"All of these numbers assume zero operational losses &mdash; missed payouts, breaches, ghost rows, '
        'overwritten edits. Without TradeOps&nbsp;AI those losses historically erase 20&ndash;40% of '
        'the projected take. With it, they round to zero."',
        QUOTE,
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<i>Figures derived from live MFFU and FundedNext $50k blueprints in the platform "
        "(challenge → funded → 4 payout stages). Stop-loss capital assumes standard $1/point/lot "
        "NAS100 CFD pricing on MT5; actuals vary slightly by broker. Payouts assume the firm&rsquo;s "
        "standard 80/20 profit split. All numbers are conservative midpoints, not maximums.</i>",
        ParagraphStyle("foot2", parent=BODY, fontSize=8, leading=11,
                       textColor=BRAND_GREY, alignment=TA_LEFT),
    ))
    story.append(PageBreak())

    # ───── PAGE — Why us ─────
    story += section_band("Why TradeOps&nbsp;AI", "Built by the people doing the work.")
    story.append(Paragraph(
        "TradeOps&nbsp;AI isn&rsquo;t a generic SaaS bolted onto trading. It was built from "
        "the inside &mdash; by an operation managing 100+ funded accounts across 14 traders "
        "and 8 admins &mdash; against a Standard Operating Procedure refined over thousands "
        "of live trades. Every quality-scan rule, every breach guard, every blueprint "
        "exists because we lived the problem first.",
        LEAD,
    ))
    story.append(Spacer(1, 8))

    why_items = [
        ListItem(Paragraph("<b>Battle-tested:</b> in continuous production use against real money, real firms, every trading day.", BODY)),
        ListItem(Paragraph("<b>Firm-aware:</b> every prop firm modelled correctly &mdash; MFFU/TopStep funded balance starts at $0, Tradeify Double Dip routing, Alpha Futures activation enforcement, FundedNext login mapping.", BODY)),
        ListItem(Paragraph("<b>Defensive by default:</b> 4-layer internal-transfer filter, manual-clear sticky guards, placeholder account rejection, fresh-push override.", BODY)),
        ListItem(Paragraph("<b>Transparent:</b> every change versioned, every push logged, every match decision traceable in the dashboard log.", BODY)),
        ListItem(Paragraph("<b>Actively shipped:</b> versioned releases with a written changelog &mdash; the platform you sign on this week is materially better next week.", BODY)),
    ]
    story.append(ListFlowable(why_items, bulletType="bullet", start="square",
                              leftIndent=18, bulletColor=BRAND_BLUE))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Compatibility today", H2))
    compat = Table(
        [
            ["Hedge platform", "MetaTrader 5 (any broker)"],
            ["Prop firms supported", "Tradovate, TopStepX, MFFU, FundedNext, Tradeify, Funding Ticks, Trade Day, Alpha Futures, TopOne Futures"],
            ["Operating system", "Windows 10/11 (companion); browser dashboard works anywhere"],
            ["Hosting", "tradeopss.com (Postgres-backed) or self-hosted on request"],
            ["Onboarding time", "Same-day for one trader; under a week for a full team"],
        ],
        colWidths=[1.7 * inch, 4.8 * inch],
    )
    compat.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), BRAND_NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#E2E8F0")),
    ]))
    story.append(compat)
    story.append(PageBreak())

    # ───── PAGE 8 — Next step / CTA ─────
    story += section_band("Next step", "Prove it on your own accounts in one week.")
    story.append(Paragraph(
        "You don&rsquo;t have to take the &ldquo;clients never lose money&rdquo; promise on faith. "
        "Put your live accounts behind TradeOps&nbsp;AI for one trading week and we will quantify, "
        "in writing, every loss vector that was active in your previous week and how the platform "
        "closed it.",
        LEAD,
    ))
    story.append(Spacer(1, 6))
    next_items = [
        ListItem(Paragraph("<b>Day 1:</b> 30-minute onboarding &mdash; MT5 + first prop firm wired into the companion app, Hedge Protector live.", BODY)),
        ListItem(Paragraph("<b>Day 2&ndash;3:</b> remaining prop firms onboarded; quality scan runs against your full book and flags every existing leak.", BODY)),
        ListItem(Paragraph("<b>Day 4&ndash;7:</b> breach guards, payout watchdog, billing reconciliation and audit trail all active across every account.", BODY)),
        ListItem(Paragraph("<b>End of week:</b> a written loss-vector report &mdash; what was at risk last week, what is no longer at risk, in dollars.", BODY)),
    ]
    story.append(ListFlowable(next_items, bulletType="1", start="1",
                              leftIndent=18, bulletColor=BRAND_BLUE))

    story.append(Spacer(1, 18))
    story.append(cta_block(
        "Stop losing accounts to operations. Start protecting capital by default.<br/>"
        "<font size='10'>Reply to this email or message us on Discord to book your onboarding slot.</font>"
    ))

    story.append(Spacer(1, 18))

    contact = Table(
        [[
            Paragraph("<b>Web</b><br/><font color='#1E40AF'>tradeopss.com</font>", BODY_C),
            Paragraph("<b>Email</b><br/><font color='#1E40AF'>hello@tradeopss.com</font>", BODY_C),
            Paragraph("<b>Discord</b><br/><font color='#1E40AF'>direct invite on request</font>", BODY_C),
        ]],
        colWidths=[2.2 * inch] * 3,
    )
    contact.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(contact)

    story.append(Spacer(1, 22))
    story.append(Paragraph(
        "<i>This document is confidential and intended for the named recipient only. "
        "Figures referenced (account counts, traders, firms) reflect the production "
        "deployment of TradeOps&nbsp;AI as of the document date.</i>",
        ParagraphStyle("foot", parent=BODY, fontSize=8, leading=11,
                       textColor=BRAND_GREY, alignment=TA_CENTER),
    ))

    # build with separate first-page handler
    doc.build(story, onFirstPage=cover_page, onLaterPages=content_page)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    build()
