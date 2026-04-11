"""Generate colorful presentation-quality PDF for Quality Roadmap"""
from fpdf import FPDF


class RoadmapPDF(FPDF):
    # Brand colors
    NAVY = (15, 32, 65)
    BLUE = (30, 100, 200)
    LIGHT_BLUE = (70, 140, 230)
    GREEN = (34, 170, 85)
    YELLOW = (245, 180, 30)
    RED = (220, 53, 69)
    ORANGE = (255, 130, 50)
    PURPLE = (120, 70, 180)
    TEAL = (0, 170, 170)
    DARK_BG = (22, 33, 62)
    WHITE = (255, 255, 255)
    LIGHT_GRAY = (245, 247, 252)
    MID_GRAY = (180, 185, 195)

    def header(self):
        if self.page_no() > 1:
            self.set_fill_color(*self.NAVY)
            self.rect(0, 0, 210, 12, 'F')
            self.set_font('Helvetica', 'B', 7)
            self.set_text_color(*self.WHITE)
            self.set_xy(10, 2)
            self.cell(95, 8, 'VPF FUTURES  |  2-Week Quality Improvement Plan', align='L')
            self.cell(95, 8, f'Page {self.page_no()}', align='R')
            self.set_xy(10, 14)

    def footer(self):
        self.set_y(-12)
        self.set_fill_color(*self.NAVY)
        self.rect(0, self.h - 12, 210, 12, 'F')
        self.set_font('Helvetica', 'I', 7)
        self.set_text_color(*self.MID_GRAY)
        self.set_xy(10, self.h - 10)
        self.cell(0, 8, 'Confidential -- VPF Futures Internal Document  |  March 2026', align='C')

    def section_banner(self, title, color=None):
        if color is None:
            color = self.BLUE
        if self.get_y() > 240:
            self.add_page()
        self.ln(6)
        self.set_fill_color(*color)
        self.set_text_color(*self.WHITE)
        self.set_font('Helvetica', 'B', 14)
        self.rect(10, self.get_y(), 190, 11, 'F')
        self.set_xy(16, self.get_y() + 1)
        self.cell(0, 9, title)
        self.set_text_color(0, 0, 0)
        self.set_xy(10, self.get_y() + 12)
        self.ln(2)

    def sub_header(self, title, color=None):
        if color is None:
            color = self.BLUE
        if self.get_y() > 255:
            self.add_page()
        self.ln(3)
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(*color)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*color)
        self.set_line_width(0.6)
        self.line(10, self.get_y(), 80, self.get_y())
        self.set_line_width(0.2)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def sub_sub_header(self, title, color=None):
        if color is None:
            color = self.NAVY
        if self.get_y() > 260:
            self.add_page()
        self.ln(2)
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*color)
        self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def body(self, text):
        self.set_font('Helvetica', '', 9)
        self.set_text_color(40, 40, 50)
        self.multi_cell(0, 5, text)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def bold_body(self, text):
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(40, 40, 50)
        self.multi_cell(0, 5, text)
        self.set_font('Helvetica', '', 9)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def bullet(self, text, color=None, indent=12):
        if color is None:
            color = self.BLUE
        self.set_font('Helvetica', '', 9)
        self.set_text_color(40, 40, 50)
        x = self.l_margin + indent
        self.set_x(x)
        y = self.get_y() + 2
        self.set_fill_color(*color)
        self.ellipse(x - 1, y, 2.5, 2.5, 'F')
        self.set_x(x + 4)
        w = self.w - self.r_margin - x - 4
        self.multi_cell(w, 5, text)
        self.set_text_color(0, 0, 0)

    def info_card(self, icon_text, title, value, bg_color, text_color=None):
        if text_color is None:
            text_color = self.WHITE
        w = 60
        h = 22
        x = self.get_x()
        y = self.get_y()
        self.set_fill_color(*bg_color)
        self.rect(x, y, w, h, 'F')
        self.set_font('Helvetica', 'B', 8)
        self.set_text_color(*text_color)
        self.set_xy(x + 3, y + 2)
        self.cell(w - 6, 6, icon_text)
        self.set_font('Helvetica', 'B', 12)
        self.set_xy(x + 3, y + 10)
        self.cell(w - 6, 10, value)
        self.set_xy(x + w + 5, y)
        self.set_text_color(0, 0, 0)

    def add_table(self, headers, rows, col_widths=None, header_color=None):
        if header_color is None:
            header_color = self.NAVY
        if not col_widths:
            total = 190
            col_widths = [total / len(headers)] * len(headers)

        if self.get_y() > 245:
            self.add_page()

        self.set_font('Helvetica', 'B', 8)
        self.set_fill_color(*header_color)
        self.set_text_color(*self.WHITE)
        self.set_draw_color(*self.MID_GRAY)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, ' ' + h, border=1, fill=True)
        self.ln()

        self.set_font('Helvetica', '', 8)
        self.set_text_color(30, 30, 40)
        alt = False
        for row in rows:
            max_lines = 1
            for i, cell_text in enumerate(row):
                lines = self.multi_cell(col_widths[i], 5, cell_text, dry_run=True, output='LINES')
                max_lines = max(max_lines, len(lines))
            row_h = max(7, max_lines * 5)

            if self.get_y() + row_h > 270:
                self.add_page()
                self.set_font('Helvetica', 'B', 8)
                self.set_fill_color(*header_color)
                self.set_text_color(*self.WHITE)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 7, ' ' + h, border=1, fill=True)
                self.ln()
                self.set_font('Helvetica', '', 8)
                self.set_text_color(30, 30, 40)

            if alt:
                self.set_fill_color(235, 240, 252)
            else:
                self.set_fill_color(*self.WHITE)

            y_start = self.get_y()
            x_start = self.get_x()
            for i, cell_text in enumerate(row):
                x = x_start + sum(col_widths[:i])
                self.set_xy(x, y_start)
                self.multi_cell(col_widths[i], 5, ' ' + cell_text, border=0, fill=True)
            y_end = self.get_y()
            actual_h = y_end - y_start
            self.set_draw_color(210, 215, 225)
            for i in range(len(row)):
                x = x_start + sum(col_widths[:i])
                self.rect(x, y_start, col_widths[i], actual_h)
            self.set_xy(x_start, y_start + actual_h)
            alt = not alt
        self.ln(3)

    def code_block(self, text):
        self.set_font('Courier', '', 8)
        self.set_fill_color(240, 242, 248)
        lines = text.strip().split('\n')
        block_h = len(lines) * 4.5 + 8
        if self.get_y() + block_h > 270:
            self.add_page()
        y0 = self.get_y()
        self.set_fill_color(*self.BLUE)
        self.rect(10, y0, 2.5, block_h, 'F')
        self.set_fill_color(240, 242, 248)
        self.rect(12.5, y0, 187.5, block_h, 'F')
        self.ln(4)
        self.set_text_color(50, 55, 70)
        for line in lines:
            self.set_x(16)
            self.cell(0, 4.5, line, new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        self.set_font('Helvetica', '', 9)
        self.set_text_color(0, 0, 0)

    def checkbox(self, text, color=None):
        if color is None:
            color = self.GREEN
        self.set_font('Helvetica', '', 9)
        x = self.l_margin + 12
        self.set_x(x)
        y = self.get_y() + 1
        self.set_draw_color(*color)
        self.set_line_width(0.4)
        self.rect(x, y, 3.5, 3.5)
        self.set_line_width(0.2)
        self.set_x(x + 6)
        w = self.w - self.r_margin - x - 6
        self.set_text_color(40, 40, 50)
        self.multi_cell(w, 5, text)
        self.set_text_color(0, 0, 0)

    def layer_card(self, num, title, desc, pct, color):
        if self.get_y() > 255:
            self.add_page()
        y = self.get_y()
        self.set_fill_color(*color)
        self.rect(10, y, 190, 16, 'F')
        self.set_fill_color(255, 255, 255)
        self.ellipse(14, y + 3, 10, 10, 'F')
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(*color)
        self.set_xy(14, y + 4)
        self.cell(10, 8, str(num), align='C')
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(*self.WHITE)
        self.set_xy(28, y + 1)
        self.cell(100, 7, title)
        self.set_font('Helvetica', 'B', 14)
        self.set_xy(160, y + 1)
        self.cell(35, 7, pct, align='R')
        self.set_font('Helvetica', '', 8)
        self.set_xy(28, y + 8)
        self.cell(160, 6, desc)
        self.set_text_color(0, 0, 0)
        self.set_xy(10, y + 18)


# ============================================================
# BUILD THE PDF
# ============================================================

pdf = RoadmapPDF()
pdf.set_auto_page_break(auto=True, margin=18)

# ---- COVER PAGE ----
pdf.add_page()
pdf.set_fill_color(*RoadmapPDF.DARK_BG)
pdf.rect(0, 0, 210, 297, 'F')

pdf.set_fill_color(*RoadmapPDF.BLUE)
pdf.rect(0, 90, 210, 4, 'F')

pdf.set_y(50)
pdf.set_font('Helvetica', '', 13)
pdf.set_text_color(*RoadmapPDF.LIGHT_BLUE)
pdf.cell(0, 8, 'VPF FUTURES', align='C', new_x="LMARGIN", new_y="NEXT")

pdf.set_font('Helvetica', 'B', 30)
pdf.set_text_color(*RoadmapPDF.WHITE)
pdf.cell(0, 16, '2-Week Quality', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 16, 'Improvement Plan', align='C', new_x="LMARGIN", new_y="NEXT")

pdf.ln(15)

# Info cards
pdf.set_y(110)
cards = [
    ('TEAM', '8 Admins', RoadmapPDF.BLUE),
    ('TEAM', '14 Traders', RoadmapPDF.GREEN),
    ('CLIENTS', '70 Active', RoadmapPDF.PURPLE),
]
x_start = 25
for i, (label, val, color) in enumerate(cards):
    x = x_start + i * 58
    pdf.set_fill_color(*color)
    pdf.rect(x, 110, 50, 28, 'F')
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(220, 225, 240)
    pdf.set_xy(x + 4, 112)
    pdf.cell(42, 6, label)
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*RoadmapPDF.WHITE)
    pdf.set_xy(x + 4, 122)
    pdf.cell(42, 10, val)

# Goal
pdf.set_y(155)
pdf.set_font('Helvetica', 'B', 11)
pdf.set_text_color(*RoadmapPDF.YELLOW)
pdf.cell(0, 8, 'GOAL', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.set_font('Helvetica', '', 12)
pdf.set_text_color(*RoadmapPDF.WHITE)
pdf.cell(0, 8, '100% data accuracy and zero client complaints', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, 'caused by internal errors', align='C', new_x="LMARGIN", new_y="NEXT")

# Timeline bar
pdf.set_y(195)
pdf.set_fill_color(*RoadmapPDF.BLUE)
pdf.rect(30, 195, 75, 0.5, 'F')
pdf.set_fill_color(*RoadmapPDF.GREEN)
pdf.rect(105, 195, 75, 0.5, 'F')

pdf.set_font('Helvetica', 'B', 9)
pdf.set_text_color(*RoadmapPDF.LIGHT_BLUE)
pdf.set_xy(30, 198)
pdf.cell(75, 6, 'WEEK 1: Detect & Surface')
pdf.set_text_color(*RoadmapPDF.GREEN)
pdf.cell(75, 6, 'WEEK 2: Prevent & Enforce')

pdf.set_font('Helvetica', '', 8)
pdf.set_text_color(*RoadmapPDF.MID_GRAY)
pdf.set_xy(30, 206)
pdf.cell(75, 6, 'Mar 19 - Mar 25, 2026')
pdf.cell(75, 6, 'Mar 26 - Apr 1, 2026')

# Footer
pdf.set_y(240)
pdf.set_font('Helvetica', 'I', 8)
pdf.set_text_color(*RoadmapPDF.MID_GRAY)
pdf.cell(0, 6, 'Confidential -- Internal Document', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 6, 'Document Version 1.0 -- March 19, 2026', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 6, 'Prepared by VPF Operations Team', align='C', new_x="LMARGIN", new_y="NEXT")

# ---- PAGE 2: WHY THIS MATTERS ----
pdf.add_page()
pdf.section_banner('WHY THIS MATTERS -- Evidence From the Field', RoadmapPDF.RED)
pdf.body('The following issues have been documented from real client complaints and internal observations. Each one represents a service failure the quality system must eliminate.')
pdf.ln(2)

evidence = [
    ['1', 'Hedge Net not calculating after status changes', 'Stale/empty financial data', 'FIXED'],
    ['2', '28-hour Discord response time', 'Client publicly questioning reliability', 'OPEN'],
    ['3', 'Client cross-referencing with others', 'Trust deficit in the team', 'OPEN'],
    ['4', 'Eval row deleted without explanation', 'Client says it "smells fishy"', 'OPEN'],
    ['5', 'Dashboard not updated for entire day', 'Client catches it before us', 'OPEN'],
    ['6', 'Traders missing trades / out of time', 'Downtime = lost profit days', 'OPEN'],
    ['7', 'Wrong values in manual entry fields', 'False calculations, bad EV', 'OPEN'],
    ['8', 'Notes stale/missing on active accounts', 'Clients don\'t know status', 'OPEN'],
    ['9', 'Hedge Day shows previous day marker', 'Proof of missed trades', 'OPEN'],
    ['10', 'No way for clients to verify data', 'Zero transparency', 'OPEN'],
]
pdf.add_table(
    ['#', 'Issue Observed', 'Client Impact', 'Status'],
    evidence,
    [8, 82, 68, 32],
    header_color=RoadmapPDF.RED
)

# ---- 4-LAYER SYSTEM ----
pdf.section_banner('THE 4-LAYER QUALITY SYSTEM', RoadmapPDF.NAVY)
pdf.body('Every client\'s data passes through minimum 3 independent checks. Nothing can slip through without someone being held accountable.')
pdf.ln(4)

pdf.layer_card(1, 'SYSTEM (Automated)', 'Runs on ALL 70 clients daily -- catches missing fields, stale data, missed pushes', '70%', RoadmapPDF.BLUE)
pdf.layer_card(2, 'PROCESS (Checklists)', 'Trader & admin daily sign-off -- human confirms completeness', '20%', RoadmapPDF.GREEN)
pdf.layer_card(3, 'HUMAN QA (Spot-Checks)', 'Random client reviews -- verifies accuracy & note quality', '10%', RoadmapPDF.ORANGE)
pdf.layer_card(4, 'ACCOUNTABILITY (Tracking)', 'Weekly scorecards, escalation chain -- makes everything stick', '', RoadmapPDF.PURPLE)

pdf.ln(3)
pdf.bold_body('The Guarantee: No client can be forgotten because:')
pdf.bullet('The automated scan checks ALL 70 clients every single day', RoadmapPDF.BLUE)
pdf.bullet('The checklist forces traders to confirm EVERY client before sign-off', RoadmapPDF.GREEN)
pdf.bullet('QA rotates through random clients so every one gets spot-checked within 2 weeks', RoadmapPDF.ORANGE)

# ---- WEEK 1 ----
pdf.add_page()
pdf.section_banner('WEEK 1 -- DETECT & SURFACE  (Mar 19-25)', RoadmapPDF.BLUE)

pdf.sub_header('Day 1-2 (Wed-Thu Mar 19-20): Automated Daily Quality Scan', RoadmapPDF.BLUE)
pdf.body('Backend scan checks every client nightly and flags all SOP violations. Per-trader report posted to their Slack QA channel every morning.')
pdf.ln(1)

scan_checks = [
    ['Missing Date Started', 'Trader S6b', 'First trade placed but no start date'],
    ['Missing Date Ended', 'Trader S7', 'Fail/Complete but no end date'],
    ['Empty Fee / Account Size', 'Trader S9', 'Manual entry fields left blank'],
    ['Empty Activation Fee (funded)', 'Trader S9', 'Funded row missing activation fee'],
    ['Active account, no note', 'Trader S8', 'Not Fail/Complete without current note'],
    ['Note older than 24 hours', 'Trader S8', 'Stale note, trader hasn\'t reviewed'],
    ['Negative Hedge Net, no note', 'Trader S7d', 'Loss not explained per SOP'],
    ['Payout status, no tracking note', 'Trader S4e', 'No timestamped payout follow-up'],
    ['Farming note wrong format', 'Trader S4d', 'Missing "X/Y - date" pattern'],
    ['No MT5 push in 24h (weekday)', 'Trader S5', 'Missed trades -- active client'],
    ['Status blank on non-empty row', 'Trader S6b', 'Row has data but no status'],
    ['Stale Hedge Day marker', 'Workflow', '"Wed" still present on Thursday'],
    ['Account # blank on active row', 'Trader S4g', 'Account number not filled in'],
]
pdf.add_table(['Quality Check', 'SOP Ref', 'What It Catches'], scan_checks, [58, 28, 104], RoadmapPDF.BLUE)

pdf.sub_header('Day 3-4 (Fri-Sat Mar 21-22): Quality Dashboard Tab', RoadmapPDF.BLUE)
pdf.body('New "Data Quality" tab on the super admin page providing full visibility:')
pdf.bullet('Health score per client: GREEN (100%) | YELLOW (80-99%) | RED (<80%)', RoadmapPDF.GREEN)
pdf.bullet('Breakdown by trader -- each admin sees their 2 traders at a glance', RoadmapPDF.BLUE)
pdf.bullet('Click any flag to jump directly to the client\'s eval row', RoadmapPDF.BLUE)
pdf.bullet('Filters: "Show missing dates" / "Show stale notes" / "Show missed trades"', RoadmapPDF.BLUE)
pdf.bullet('Summary cards: Total issues today, issues by category, trend vs yesterday', RoadmapPDF.BLUE)

pdf.sub_header('Day 5 (Sun Mar 23): Quick Wins -- Security + Visibility', RoadmapPDF.BLUE)

pdf.sub_sub_header('5a. Restrict Delete to Super Admin Only', RoadmapPDF.RED)
pdf.body('Only super admins can delete evaluation rows. Prevents the "Row 397 missing" incident. All deletions logged with who, what, and when.')

pdf.sub_sub_header('5b. "Last Activity" Indicators', RoadmapPDF.ORANGE)
pdf.bullet('"Last MT5 Push: 6h ago" on each client\'s dashboard header', RoadmapPDF.ORANGE)
pdf.bullet('"Last Edit: 2d ago by Steve" -- identifies abandoned clients', RoadmapPDF.ORANGE)
pdf.bullet('Warning badge if >24h since last push on a weekday', RoadmapPDF.RED)

pdf.sub_sub_header('5c. CSV Download Button', RoadmapPDF.GREEN)
pdf.body('Clients and all users can download full evaluation data as CSV to independently verify all calculations.')
pdf.bullet('ALL fields: Prop Firm, Account Size, Dates, Fees, Statuses, Hedge Results, Payouts, Days, Notes', RoadmapPDF.GREEN)
pdf.bullet('Includes calculated statistics (EV, net profit, etc.)', RoadmapPDF.GREEN)

pdf.sub_header('Day 6-7 (Mon-Tue Mar 24-25): Save-Time Validation', RoadmapPDF.BLUE)
pdf.body('When a trader/admin saves, the system highlights all data quality issues before data is committed:')
pdf.bullet('Warning banner: "3 issues: Date Started missing on row 2, Fee empty on row 5"', RoadmapPDF.YELLOW)
pdf.bullet('Problem cells highlighted in red', RoadmapPDF.RED)
pdf.bullet('Does NOT block save -- data might not be available yet', RoadmapPDF.GREEN)
pdf.bullet('Every dismissed warning logged with timestamp + user for QA audit', RoadmapPDF.PURPLE)
pdf.bullet('Special warning if Hedge Net is negative and no note exists', RoadmapPDF.RED)

# ---- WEEK 2 ----
pdf.add_page()
pdf.section_banner('WEEK 2 -- PREVENT & ENFORCE  (Mar 26 - Apr 1)', RoadmapPDF.GREEN)

pdf.sub_header('Day 8-9 (Wed-Thu Mar 26-27): Daily Checklists', RoadmapPDF.GREEN)
pdf.body('Built-in checklists in the dashboard. Logged with timestamp. System cross-checks claims against automated findings.')
pdf.ln(1)

pdf.bold_body('Trader Daily Sign-Off Checklist:')
trader_checks = [
    ['1', 'All accounts visible on Tradovate AND dashboard', 'Cross-platform visual check'],
    ['2', 'MT5 name matches client name on hedging accts', 'Identity verification'],
    ['3', 'Tradovate balance matches sheet (within $100)', 'Cross-platform comparison'],
    ['4', 'Checked forexfactory.com for red-zone news', 'External source review'],
    ['5', 'Verified trades against correct blueprint', 'Judgment call'],
    ['6', 'Confirmed MT5 opposite trade executed', 'Real-time hedge verification'],
    ['7', 'Every active account has updated note', 'Content quality check'],
    ['8', 'Traded ALL accounts -- none skipped', 'Completeness confirmation'],
    ['9', 'All numbers exact to the cent, no rounding', 'Accuracy intent'],
]
pdf.add_table(['#', 'Checkpoint', 'Why It\'s Manual'], trader_checks, [8, 100, 82], RoadmapPDF.GREEN)

pdf.bold_body('Admin Daily Sign-Off Checklist:')
admin_checks = [
    ['1', 'All challenges needed for tomorrow are purchased'],
    ['2', 'All failed account subscriptions are cancelled'],
    ['3', 'All master agreements are signed'],
    ['4', 'All eligible payouts are requested'],
    ['5', 'All client emails checked for notifications'],
    ['6', 'All Discord messages replied to'],
    ['7', 'Daily summary sent to EVERY client'],
    ['8', 'All clients are within challenge limit'],
]
pdf.add_table(['#', 'Checkpoint'], admin_checks, [8, 182], RoadmapPDF.TEAL)

pdf.ln(1)
# Yellow callout box
y_box = pdf.get_y()
pdf.set_fill_color(*RoadmapPDF.YELLOW)
pdf.rect(10, y_box, 190, 14, 'F')
pdf.set_font('Helvetica', 'B', 9)
pdf.set_text_color(*RoadmapPDF.NAVY)
pdf.set_xy(14, y_box + 2)
pdf.cell(0, 5, 'CROSS-CHECK RULE')
pdf.set_font('Helvetica', '', 8)
pdf.set_xy(14, y_box + 7)
pdf.cell(0, 5, 'If a trader checks "I traded ALL accounts" but the system detected no MT5 push -> automatic QA flag.')
pdf.set_text_color(0, 0, 0)
pdf.set_y(y_box + 16)

pdf.sub_header('Day 10 (Fri Mar 28): Weekly Scorecard', RoadmapPDF.GREEN)
pdf.body('Per-trader metrics posted every Monday to #admins-traders:')
scorecard = [
    ['% clients with 100% complete data', 'Automated quality scan'],
    ['Missed trade days this week', 'Stale Hedge Day markers + no MT5 push'],
    ['Stale notes (>24h on active accounts)', 'Quality scan results'],
    ['QA flags raised this week', 'Scan + spot-checks combined'],
    ['Checklists submitted every trading day', 'Checklist submission log'],
    ['Overall Quality Score', 'Weighted average of all above'],
]
pdf.add_table(['Metric', 'Data Source'], scorecard, [95, 95], RoadmapPDF.GREEN)

pdf.sub_header('Day 11 (Sat Mar 29): Auto-Generated Daily Summary', RoadmapPDF.GREEN)
pdf.body('Auto-generate 80-90% of the Admin Daily Summary from dashboard data. Admin reviews, tweaks, and posts to Discord. Saves 15-20 min per client per day.')
summary = [
    ['1. Challenge Purchase Status', 'Eval count by firm vs limits', 'Semi-auto'],
    ['2. Renewal / Cancellation', 'Recently-failed accounts', 'Auto'],
    ['3. Trading / Operational Delays', 'N/A', 'Manual'],
    ['4. Payout Requests', 'Evals with Status = Payout', 'Auto'],
    ['5. Payout Confirmation', 'Recently confirmed payouts', 'Auto'],
    ['6. Client Action Items', 'Derived from above sections', 'Semi-auto'],
]
pdf.add_table(['Summary Section', 'Data Source', 'Type'], summary, [60, 85, 45], RoadmapPDF.TEAL)

pdf.sub_header('Day 12-14 (Sun-Tue Mar 30 - Apr 1): CSV Re-Import + Polish', RoadmapPDF.GREEN)
pdf.body('Allow bulk data correction by importing CSV back through the companion app:')
pdf.bullet('File picker for CSV upload in the companion app', RoadmapPDF.GREEN)
pdf.bullet('Validation: Check column headers match expected fields, flag mismatches', RoadmapPDF.GREEN)
pdf.bullet('Merge logic: Match rows by Account # -> update existing or add new', RoadmapPDF.GREEN)
pdf.bullet('Available to anyone connected to the client via the companion app', RoadmapPDF.GREEN)

# ---- QA MANUAL PROCEDURES ----
pdf.add_page()
pdf.section_banner('QA TEAM -- MANUAL PROCEDURES', RoadmapPDF.PURPLE)
pdf.body('These procedures cannot be automated and require consistent daily execution by the QA team.')

pdf.sub_header('Daily QA Routine', RoadmapPDF.PURPLE)

pdf.sub_sub_header('Morning (after automated scan at 2AM EAT):', RoadmapPDF.PURPLE)
pdf.bullet('Review automated quality report in Data Quality dashboard tab', RoadmapPDF.PURPLE)
pdf.bullet('Prioritize red flags -- assign to trader\'s Slack channel', RoadmapPDF.RED)
pdf.bullet('Spot-check 3 random clients per trader (rotate daily)', RoadmapPDF.PURPLE)
pdf.bullet('Verify notes are current AND meaningful (not generic filler)', RoadmapPDF.PURPLE)
pdf.bullet('Verify hedge results look reasonable (not copy-paste errors)', RoadmapPDF.PURPLE)
pdf.bullet('Cross-check that status progression makes sense', RoadmapPDF.PURPLE)
pdf.bullet('Review each trader\'s daily sign-off checklist -- flag discrepancies', RoadmapPDF.RED)
pdf.ln(1)

pdf.sub_sub_header('Evening (after market close):', RoadmapPDF.PURPLE)
pdf.bullet('Confirm every trader submitted their daily checklist', RoadmapPDF.PURPLE)
pdf.bullet('Confirm every admin submitted their daily checklist', RoadmapPDF.PURPLE)
pdf.bullet('Non-submission -> immediate Slack escalation to their admin', RoadmapPDF.RED)
pdf.bullet('Review "missed trades" list -- confirm explanations are valid', RoadmapPDF.PURPLE)
pdf.ln(1)

pdf.sub_sub_header('Weekly Deep Audit (Friday/Weekend):', RoadmapPDF.PURPLE)
pdf.bullet('Pick 2 clients per trader for full row-by-row review', RoadmapPDF.PURPLE)
pdf.bullet('Every eval row: dates present, statuses correct, notes current', RoadmapPDF.PURPLE)
pdf.bullet('Every hedge result: value looks reasonable', RoadmapPDF.PURPLE)
pdf.bullet('Every payout: amount exact to the cent, note with confirmation', RoadmapPDF.PURPLE)
pdf.bullet('Admin review: All 7 daily summaries sent? All action items followed up?', RoadmapPDF.PURPLE)
pdf.bullet('Compare trader quality scores week-over-week -- identify trends', RoadmapPDF.PURPLE)

pdf.sub_header('Client Handoff Protocol', RoadmapPDF.ORANGE)
pdf.body('When a client is reassigned to a new trader or admin:')
pdf.bullet('Outgoing person creates handoff note with status of every active account', RoadmapPDF.ORANGE)
pdf.bullet('New person reviews ALL client notes within 24 hours', RoadmapPDF.ORANGE)
pdf.bullet('New person posts introduction in client\'s Discord within 24 hours', RoadmapPDF.ORANGE)
pdf.bullet('QA spot-checks the client daily for the first week after transition', RoadmapPDF.ORANGE)

# ---- ESCALATION ----
pdf.ln(2)
pdf.section_banner('ESCALATION CHAIN', RoadmapPDF.RED)

pdf.sub_sub_header('Internal Data Issues:', RoadmapPDF.RED)
pdf.code_block("""Issue detected by automated scan or QA
         |
         v
Trader's Slack QA channel (callout posted)
         | (not fixed within 4 hours)
         v
Admin notified in #admins-traders
         | (not fixed within 24 hours)
         v
Harry / Philip notified directly""")

pdf.sub_sub_header('Client-Facing Issues:', RoadmapPDF.RED)
pdf.code_block("""Client messages in Discord
         | (no response within 4 hours)
         v
QA flags in admin's Slack channel
         | (still no response within 8 hours)
         v
Harry / Philip notified + reassignment considered""")

# ---- IMPLEMENTATION CHECKLIST ----
pdf.add_page()
pdf.section_banner('IMPLEMENTATION CHECKLIST', RoadmapPDF.NAVY)

pdf.sub_header('Week 1 Deliverables (Mar 19-25)', RoadmapPDF.BLUE)
for item in [
    'Automated daily quality scan (backend + scheduled job)',
    'Quality scan Slack notifications (per-trader channels)',
    'Super admin Data Quality dashboard tab',
    'Restrict evaluation delete to super_admin only',
    '"Last Activity" indicators on client dashboards',
    'CSV Download button for clients',
    'Save-time validation warnings (frontend)',
]:
    pdf.checkbox(item, RoadmapPDF.BLUE)
pdf.ln(3)

pdf.sub_header('Week 2 Deliverables (Mar 26 - Apr 1)', RoadmapPDF.GREEN)
for item in [
    'Trader daily checklist (UI + logging)',
    'Admin daily checklist (UI + logging)',
    'Cross-check: checklist claims vs. automated findings',
    'Weekly trader scorecard generator',
    'Auto-generated daily summary draft for admins',
    'CSV Re-import via companion app',
]:
    pdf.checkbox(item, RoadmapPDF.GREEN)
pdf.ln(3)

pdf.sub_header('Process Deliverables (QA Team -- No Code)', RoadmapPDF.PURPLE)
for item in [
    'QA daily routine documented and assigned',
    'QA weekly deep audit schedule created (rotating clients)',
    'Client handoff protocol implemented',
    'Escalation chain communicated to all admins and traders',
    'Weekly team meeting established to review scorecards',
]:
    pdf.checkbox(item, RoadmapPDF.PURPLE)

# ---- SUCCESS METRICS ----
pdf.ln(5)
pdf.section_banner('SUCCESS METRICS (After 2 Weeks)', RoadmapPDF.NAVY)
pdf.body('These are the measurable targets that define whether the quality sprint was successful:')
pdf.ln(2)

metrics = [
    ['Clients with 100% complete eval data', '~60%', '95%+'],
    ['Avg missed trade days / trader / week', '2-3', '0'],
    ['Notes updated <24h on active accounts', '~70%', '100%'],
    ['Daily summaries sent every day', '~80%', '100%'],
    ['Client complaints about data accuracy', 'Weekly', 'Zero'],
    ['Average Discord response time', '12-28h', '<4h'],
    ['Trader daily checklists submitted', 'N/A (new)', '100%'],
]
pdf.add_table(['Metric', 'Current (Est.)', 'Target'], metrics, [90, 50, 50], RoadmapPDF.NAVY)

# ---- FINAL NOTE ----
pdf.ln(10)
y = pdf.get_y()
if y + 35 > 270:
    pdf.add_page()
    y = pdf.get_y()
pdf.set_fill_color(*RoadmapPDF.LIGHT_GRAY)
pdf.rect(10, y, 190, 30, 'F')
pdf.set_fill_color(*RoadmapPDF.BLUE)
pdf.rect(10, y, 3, 30, 'F')
pdf.set_font('Helvetica', 'I', 9)
pdf.set_text_color(80, 80, 100)
pdf.set_xy(18, y + 4)
pdf.cell(0, 6, 'Document Version 1.0 -- March 19, 2026')
pdf.set_xy(18, y + 11)
pdf.cell(0, 6, 'Sprint Duration: March 19 - April 1, 2026')
pdf.set_xy(18, y + 18)
pdf.cell(0, 6, 'Next Review: April 2, 2026 (end of 2-week sprint)')
pdf.set_text_color(0, 0, 0)

# Save
output = r'c:\Users\harry\Music\MT5HedgingEngine\VPF_Quality_Improvement_Plan.pdf'
pdf.output(output)
print(f'PDF saved to: {output}')
