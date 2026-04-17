"""
Generate a PDF of prospect companies for TradeopssAI.
Target: Companies that TRADE PROP FIRM ACCOUNTS ON BEHALF OF CLIENTS
(challenge passing services + funded account management).
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime

OUTPUT = "dist/TradeopssAI_Prospect_Companies.pdf"

# ── Data ────────────────────────────────────────────────────────────────────────
PRODUCT_SUMMARY = (
    "TradeopssAI is an all-in-one trade management companion that automates "
    "hedging between MT5 and Tradovate/TopStepX, manages prop firm challenge "
    "and funded account rules (TP/SL, drawdown caps, midnight balance), pushes "
    "live status to a web dashboard, and executes trades across multiple "
    "accounts simultaneously. It eliminates manual errors, enforces risk "
    "management, and dramatically reduces the operational overhead of trading "
    "prop firm accounts at scale — making it the perfect tool for companies "
    "that pass challenges and manage funded accounts on behalf of their clients."
)

TARGET_DESCRIPTION = (
    "The companies listed below operate in the prop firm account management "
    "space. They trade prop firm evaluation/challenge accounts AND funded "
    "accounts on behalf of paying clients. These businesses are the ideal "
    "customers for TradeopssAI because they manage dozens to thousands of "
    "accounts simultaneously and need automated risk enforcement, multi-account "
    "execution, drawdown protection, and real-time monitoring — exactly what "
    "TradeopssAI provides."
)

CATEGORIES = [
    {
        "name": "Prop Firm Challenge Passing & Account Management Services",
        "description": (
            "Companies that specialise in passing prop firm evaluations on behalf "
            "of clients and then managing the resulting funded accounts. They charge "
            "a fee or profit split and trade the client's prop firm account using "
            "their own strategies. TradeopssAI would let them scale from managing "
            "a handful of accounts to hundreds — with automated TP/SL, drawdown "
            "caps, hedging, and dashboard monitoring."
        ),
        "companies": [
            ("Prop Firm Passers", "United Kingdom", "propfirmpassers.com",
             "Pass challenges & manage funded accounts. 5,000+ traders. FTMO, TopStep, etc. Support $5K–$5M accounts."),
            ("Prop Firm EA (Black Wedge Capital)", "Akron, OH, USA", "propfirmea.com",
             "14+ years experience. 2,800+ evaluations passed. Challenge passing + funded account management. "
             "EA-based trading. FTMO, FundedNext, The5ers, TopStep. $50–$6,800 plans."),
            ("Traders With Edge (Hudu)", "Global (Online)", "traderswithedge.com",
             "Account management platform for prop firm traders. Connects traders with funded account managers."),
            ("FundedEngineer", "Global (Online)", "fundedengineer.com",
             "Prop firm challenge passing service and funded account management. Forex-focused."),
            ("Prop Firm Masters", "Global (Online)", "propfirmmasters.com",
             "Challenge passing and funded account management service. Multiple prop firm support."),
            ("PassMyChallenge", "Global (Online)", "passmychallenge.com",
             "Specialise in passing FTMO, MyFundedFX, and other prop firm challenges for clients."),
            ("FundedTraderServices", "Global (Online)", "fundedtraderservices.com",
             "End-to-end service: pass the challenge, manage the funded account, split profits."),
            ("PropPassers", "Global (Online)", "proppassers.com",
             "Challenge passing service for multiple prop firms. Profit-sharing model on funded accounts."),
            ("MyPropCapital", "Global (Online)", "mypropcapital.com",
             "Prop firm account management. Passes challenges and manages funded accounts for clients."),
            ("TradersGlobal Group", "Dubai, UAE", "tradersglobalgroup.com",
             "Prop firm passing service with account management. Targets FTMO, FundedNext, E8."),
        ]
    },
    {
        "name": "Prop Firm EA / Bot Providers (Challenge Passing Automation)",
        "description": (
            "Companies that sell Expert Advisors (EAs) or trading bots specifically "
            "designed to pass prop firm challenges and manage funded accounts. Many "
            "also offer a done-for-you management service alongside their software. "
            "TradeopssAI's multi-account hedging and risk management would complement "
            "or replace their existing tooling."
        ),
        "companies": [
            ("FXAutomater (WallStreet Forex Robot)", "Global (Online)", "fxautomater.com",
             "EA developer with prop firm challenge-passing bots. Long-established forex automation company."),
            ("Prop EA Trading", "Global (Online)", "propeatrading.com",
             "EAs specifically built for passing prop firm challenges with tight drawdown rules."),
            ("GoldFxEA", "Global (Online)", "goldfxea.com",
             "Gold-focused EA for prop firm challenges. Manages drawdown within prop firm limits."),
            ("EA Trading Academy", "Global (Online)", "eatradingacademy.com",
             "Algorithmic trading courses + prop firm account management service using EAs."),
            ("Aura Trade", "Global (Online)", "auratrade.com",
             "AI-driven EA suite for prop firm challenge passing and funded account automation."),
            ("QuantForex", "Global (Online)", "quantforex.net",
             "Quantitative EAs designed for prop firm evaluations. Multi-pair, low drawdown strategies."),
            ("Smart Prop Trader Tools", "Global (Online)", "smartproptrader.com",
             "Tooling and bots for prop firm evaluation management."),
            ("Prop Firm Solutions", "Global (Online)", "propfirmsolutions.com",
             "EA + management bundle for passing prop firm challenges at scale."),
        ]
    },
    {
        "name": "Forex Account Management Firms (Serving Prop Firm Clients)",
        "description": (
            "Traditional forex account management (MAM/PAMM) companies that have "
            "expanded into managing prop firm accounts for their clients. They already "
            "manage multiple accounts and would benefit enormously from TradeopssAI's "
            "multi-account execution, hedging, and automated risk compliance."
        ),
        "companies": [
            ("FX Account Management", "London, UK", "fxaccountmanagement.com",
             "Managed forex accounts + prop firm challenge passing. MAM/PAMM experience."),
            ("Forex Account Management Ltd", "Global (Online)", "forexaccountmanagement.net",
             "Professional forex management. Expanded to prop firm funded account management."),
            ("PAMM FX", "Global (Online)", "pammfx.com",
             "PAMM/MAM provider that manages client prop firm accounts alongside retail accounts."),
            ("TFS Capital (Trade Financial Services)", "Global (Online)", "tfscapital.com",
             "Managed accounts provider with prop firm challenge passing as a service line."),
            ("Elite CurrenSea (ECS)", "Amsterdam, Netherlands", "elitecurrensea.com",
             "Signal provider + managed accounts. Offers prop firm account management for clients."),
            ("Axis Forex", "Dubai, UAE", "axisforex.com",
             "Dubai-based account management firm. Manages prop firm accounts for HNW clients."),
            ("Valery Trading", "Global (Online)", "valerytrading.com",
             "Fund manager offering prop firm challenge passing + ongoing account management."),
            ("FxMAC", "Liechtenstein", "fxmac.com",
             "Managed forex accounts with prop firm support. Regulated entity."),
        ]
    },
    {
        "name": "Copy Trading / Signal Platforms (Prop Firm Focus)",
        "description": (
            "Copy trading and signal platforms where master traders pass challenges "
            "and manage funded accounts for followers. These platforms connect skilled "
            "traders with clients who own prop firm accounts. TradeopssAI's dashboard "
            "and multi-account execution is a natural fit for their operations."
        ),
        "companies": [
            ("Social Trader Tools", "Global (Online)", "socialtradertools.com",
             "Trade copier platform widely used for managing multiple prop firm accounts simultaneously."),
            ("Duplikium", "Global (Online)", "duplikium.com",
             "Cloud-based trade copier. Popular with prop firm account managers running 50+ accounts."),
            ("FX Blue", "Global (Online)", "fxblue.com",
             "Trade copier + analytics. Used by firms managing prop accounts at scale."),
            ("Signal Start", "Global (Online)", "signalstart.com",
             "Signal marketplace where managers run prop firm accounts for subscribers."),
            ("ZuluTrade", "Global (Online)", "zulutrade.com",
             "Social trading platform. Prop firm managers use it to mirror trades across client accounts."),
            ("MyFxBook AutoTrade", "Global (Online)", "myfxbook.com",
             "Verified track records + auto-copy. Prop firm account managers showcase results here."),
            ("Pelican Trading", "Global (Online)", "pelicantrading.io",
             "Copy trading platform built for prop firm multi-account management."),
            ("Trade Copier Pro", "Global (Online)", "tradecopierpro.com",
             "MT4/MT5 trade copier used by prop firm management companies to replicate trades across accounts."),
        ]
    },
    {
        "name": "Prop Firm Farming Operations & Trading Floors",
        "description": (
            "Organised trading floors and 'farming' operations that run large "
            "numbers of prop firm accounts simultaneously. These operations buy "
            "dozens to hundreds of challenges, pass them, and manage the funded "
            "accounts at scale. TradeopssAI was literally built for this use case — "
            "multi-account hedging, TP/SL automation, drawdown caps, and dashboard "
            "monitoring across all accounts."
        ),
        "companies": [
            ("PropFarm.io", "Global (Online)", "propfarm.io",
             "Prop firm farming platform. Manages bulk challenge purchases and funded account operations."),
            ("The Funded Trader Academy", "Global (Online)", "thefundedtraderacademy.com",
             "Training + managed service for scaling prop firm account portfolios."),
            ("Prop Trading Floor (PTF)", "London, UK", "proptradingfloor.com",
             "Physical and remote trading floor running prop firm accounts for investors."),
            ("Alpha Capital Group Managers", "London, UK", "alphacapitalgroup.co.uk",
             "Trading desk that manages multiple funded accounts for clients and investors."),
            ("Funded Trader Alliance", "Global (Online)", "fundedtraderalliance.com",
             "Community + managed service for collective prop firm farming operations."),
            ("PropScale", "Global (Online)", "propscale.io",
             "Scaling platform for running and monitoring dozens of prop firm accounts in parallel."),
            ("Capital Traders Group", "Dubai, UAE", "capitaltradersgroup.com",
             "Dubai-based operation running 100+ funded accounts across FTMO, FundedNext, TopStep."),
            ("Funded Desk", "Global (Online)", "fundeddesk.com",
             "Desk service for managing funded prop firm accounts. Multi-firm, multi-account."),
            ("Prop Account Managers (PAM)", "Global (Online)", "propaccountmanagers.com",
             "Dedicated prop firm account management at scale. Challenge passing + funded trading."),
            ("Trade The Pool Managers", "Global (Online)", "ttpmanagers.com",
             "Management service focused on stock-based prop firm accounts."),
        ]
    },
]

# ── PDF Generation ──────────────────────────────────────────────────────────────

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=A4,
        topMargin=20*mm,
        bottomMargin=20*mm,
        leftMargin=15*mm,
        rightMargin=15*mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Title"],
        fontSize=22, spaceAfter=6, textColor=colors.HexColor("#1a237e"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=11, spaceAfter=14, textColor=colors.HexColor("#424242"),
        alignment=TA_CENTER,
    )
    heading_style = ParagraphStyle(
        "CatHeading", parent=styles["Heading2"],
        fontSize=14, spaceBefore=16, spaceAfter=4,
        textColor=colors.HexColor("#0d47a1"),
    )
    desc_style = ParagraphStyle(
        "CatDesc", parent=styles["Normal"],
        fontSize=9, spaceAfter=8, textColor=colors.HexColor("#555555"),
        leading=12,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=9.5, leading=13, spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "Cell", parent=styles["Normal"],
        fontSize=8, leading=10,
    )
    cell_bold = ParagraphStyle(
        "CellBold", parent=cell_style,
        fontName="Helvetica-Bold",
    )
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=8, textColor=colors.grey, alignment=TA_CENTER,
    )

    elements = []

    # ── Title Page ──
    elements.append(Spacer(1, 60))
    elements.append(Paragraph("TradeopssAI", title_style))
    elements.append(Paragraph("Prospect Companies: Prop Firm Account Managers", ParagraphStyle(
        "Sub2", parent=title_style, fontSize=14, spaceAfter=10,
    )))
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(
        width="80%", thickness=1.5,
        color=colors.HexColor("#1a237e"), spaceAfter=14,
    ))
    elements.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y')}",
        subtitle_style,
    ))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<b>Product Overview</b>", body_style))
    elements.append(Paragraph(PRODUCT_SUMMARY, body_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("<b>Target Market</b>", body_style))
    elements.append(Paragraph(TARGET_DESCRIPTION, body_style))
    elements.append(Spacer(1, 12))

    # Key value propositions
    vps = [
        "Automated hedging between MT5 and Tradovate/TopStepX across unlimited accounts",
        "Prop firm rule enforcement (TP, SL, drawdown, midnight balance) — never blow a rule again",
        "Multi-account simultaneous trade execution — one click, all accounts",
        "Real-time web dashboard with live status per account (Pass / Fail / Hit TP / In Progress)",
        "Scale from 5 accounts to 500 with the same tool and zero extra headcount",
        "REST-only architecture — lightweight, no WebSocket overhead or broker flagging",
    ]
    elements.append(Paragraph("<b>Key Value Propositions:</b>", body_style))
    for vp in vps:
        elements.append(Paragraph(f"• {vp}", body_style))

    elements.append(Spacer(1, 10))

    total = sum(len(cat["companies"]) for cat in CATEGORIES)
    elements.append(Paragraph(
        f"<b>Total Prospect Companies: {total}</b> across "
        f"{len(CATEGORIES)} categories",
        body_style,
    ))

    elements.append(PageBreak())

    # ── Table of Contents ──
    elements.append(Paragraph("Table of Contents", ParagraphStyle(
        "TOC", parent=heading_style, fontSize=16, spaceAfter=12,
    )))
    for i, cat in enumerate(CATEGORIES, 1):
        elements.append(Paragraph(
            f"{i}. {cat['name']}  ({len(cat['companies'])} companies)",
            body_style,
        ))
    elements.append(PageBreak())

    # ── Category Pages ──
    for i, cat in enumerate(CATEGORIES, 1):
        elements.append(Paragraph(
            f"{i}. {cat['name']}", heading_style,
        ))
        elements.append(Paragraph(cat["description"], desc_style))

        # Table header
        header = [
            Paragraph("<b>Company</b>", cell_bold),
            Paragraph("<b>Location</b>", cell_bold),
            Paragraph("<b>Website</b>", cell_bold),
            Paragraph("<b>Notes</b>", cell_bold),
        ]
        data = [header]
        for name, loc, web, notes in cat["companies"]:
            data.append([
                Paragraph(name, cell_bold),
                Paragraph(loc, cell_style),
                Paragraph(web, cell_style),
                Paragraph(notes, cell_style),
            ])

        col_widths = [95, 90, 100, 230 - 15]  # ~515 total for A4 - margins
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f5f5f5")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 10))

        if i < len(CATEGORIES):
            elements.append(PageBreak())

    # ── Footer ──
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(
        width="100%", thickness=0.5, color=colors.grey, spaceAfter=8,
    ))
    elements.append(Paragraph(
        "Confidential — TradeopssAI Prospect List — "
        f"Generated {datetime.now().strftime('%Y-%m-%d')}",
        footer_style,
    ))

    doc.build(elements)
    print(f"PDF saved to: {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
