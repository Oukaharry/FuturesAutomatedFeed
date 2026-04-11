import re
from fpdf import FPDF

with open('QUALITY_ROADMAP.md', 'r', encoding='utf-8') as f:
    raw_lines = f.readlines()

def sanitize(text):
    """Replace Unicode chars that latin-1 core fonts can't handle."""
    replacements = {
        '\u2014': '--',   # em dash
        '\u2013': '-',    # en dash
        '\u2018': "'",    # left single quote
        '\u2019': "'",    # right single quote
        '\u201c': '"',    # left double quote
        '\u201d': '"',    # right double quote
        '\u2026': '...',  # ellipsis
        '\u2022': '*',    # bullet
        '\u2153': '1/3',  # fraction
        '\u2154': '2/3',
        '\u2155': '1/5',
        '\u2156': '2/5',
        '\u2157': '3/5',
        '\u2158': '4/5',
        '\u2159': '1/6',
        '\u215a': '5/6',
        '\u00b7': '.',    # middle dot
        '\u2192': '->',   # right arrow
        '\u2190': '<-',   # left arrow
        '\u2193': 'v',    # down arrow
        '\u2191': '^',    # up arrow
        '\u2502': '|',    # box drawing
        '\u251c': '|--',  # box drawing
        '\u2514': '\\--', # box drawing
        '\u2500': '-',    # box drawing horizontal
        '\u25bc': 'v',    # down triangle
        '\u25b6': '>',    # right triangle
        '\u2713': 'Y',    # check mark
        '\u2717': 'X',    # cross mark
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Catch any remaining non-latin1 chars
    return text.encode('latin-1', errors='replace').decode('latin-1')

# Sanitize all lines upfront
lines = [sanitize(l) for l in raw_lines]

class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font('Helvetica', 'I', 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 5, f'VPF Futures Quality Improvement Plan', align='C')
            self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def section_title(self, text):
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(30, 64, 175)
        self.cell(0, 10, text, new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(59, 130, 246)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, text):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(30, 58, 95)
        self.cell(0, 9, text, new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(147, 197, 253)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def sub_sub_title(self, text):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(51, 65, 85)
        self.cell(0, 8, text, new_x='LMARGIN', new_y='NEXT')
        self.ln(2)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 41, 59)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def bold_text(self, text):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(30, 58, 95)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def code_block(self, text):
        self.set_fill_color(15, 23, 42)
        self.set_text_color(226, 232, 240)
        self.set_font('Courier', '', 8.5)
        y_start = self.get_y()
        self.multi_cell(0, 4.5, text, fill=True)
        self.ln(3)
        self.set_text_color(30, 41, 59)

    def bullet(self, text, indent=0):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 41, 59)
        x = 12 + indent
        self.set_x(x)
        self.cell(5, 5.5, '-')
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def checkbox(self, text, indent=0):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 41, 59)
        x = 12 + indent
        self.set_x(x)
        self.set_draw_color(148, 163, 184)
        self.rect(self.get_x(), self.get_y() + 1, 3.5, 3.5)
        self.set_x(x + 6)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def render_table(self, headers, rows):
        if self.get_y() > 250:
            self.add_page()
        col_count = len(headers)
        page_w = 190
        col_w = page_w / col_count
        # Header
        self.set_font('Helvetica', 'B', 8)
        self.set_fill_color(30, 64, 175)
        self.set_text_color(255, 255, 255)
        for h in headers:
            self.cell(col_w, 7, h.strip(), border=1, fill=True, align='L')
        self.ln()
        # Rows
        self.set_font('Helvetica', '', 8)
        self.set_text_color(30, 41, 59)
        for i, row in enumerate(rows):
            if self.get_y() > 270:
                self.add_page()
                self.set_font('Helvetica', 'B', 8)
                self.set_fill_color(30, 64, 175)
                self.set_text_color(255, 255, 255)
                for h in headers:
                    self.cell(col_w, 7, h.strip(), border=1, fill=True, align='L')
                self.ln()
                self.set_font('Helvetica', '', 8)
                self.set_text_color(30, 41, 59)
            if i % 2 == 1:
                self.set_fill_color(241, 245, 249)
            else:
                self.set_fill_color(255, 255, 255)
            for cell_text in row:
                self.cell(col_w, 6, cell_text.strip()[:50], border=1, fill=True, align='L')
            self.ln()
        self.ln(3)

pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=20)
pdf.add_page()

# Title
pdf.set_font('Helvetica', 'B', 22)
pdf.set_text_color(30, 64, 175)
pdf.cell(0, 12, 'VPF Futures', new_x='LMARGIN', new_y='NEXT', align='C')
pdf.set_font('Helvetica', 'B', 16)
pdf.cell(0, 10, '2-Week Quality Improvement Plan', new_x='LMARGIN', new_y='NEXT', align='C')
pdf.ln(5)
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(100, 116, 139)
pdf.cell(0, 6, 'Start Date: March 24, 2026', new_x='LMARGIN', new_y='NEXT', align='C')
pdf.cell(0, 6, 'Team: 8 Admins . 14 Traders . 70 Clients . QA Team', new_x='LMARGIN', new_y='NEXT', align='C')
pdf.cell(0, 6, 'Goal: 100% data accuracy and zero client complaints caused by internal errors', new_x='LMARGIN', new_y='NEXT', align='C')
pdf.ln(5)
pdf.set_draw_color(226, 232, 240)
pdf.line(10, pdf.get_y(), 200, pdf.get_y())
pdf.ln(5)

# Process remaining lines
i = 6  # Skip header lines we already rendered
in_code = False
code_buf = []
in_table = False
table_headers = []
table_rows = []

def flush_table():
    global in_table, table_headers, table_rows
    if table_headers and table_rows:
        pdf.render_table(table_headers, table_rows)
    in_table = False
    table_headers = []
    table_rows = []

while i < len(lines):
    line = lines[i].rstrip('\n')
    i += 1

    # Code blocks
    if line.strip().startswith('```'):
        if in_code:
            pdf.code_block('\n'.join(code_buf))
            code_buf = []
            in_code = False
        else:
            if in_table:
                flush_table()
            in_code = True
        continue
    if in_code:
        code_buf.append(line)
        continue

    # Table rows
    if '|' in line and line.strip().startswith('|'):
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if all(re.match(r'^[-:]+$', c) for c in cells):
            continue  # separator row
        if not in_table:
            in_table = True
            table_headers = cells
        else:
            table_rows.append(cells)
        continue
    elif in_table:
        flush_table()

    stripped = line.strip()

    # Empty line
    if not stripped:
        continue

    # Horizontal rule
    if stripped == '---':
        pdf.set_draw_color(226, 232, 240)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)
        continue

    # Headers
    if stripped.startswith('# '):
        pdf.section_title(stripped[2:])
        continue
    if stripped.startswith('## '):
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.sub_title(stripped[3:])
        continue
    if stripped.startswith('### '):
        pdf.sub_sub_title(stripped[4:])
        continue

    # Bold line
    if stripped.startswith('**') and stripped.endswith('**'):
        pdf.bold_text(stripped.strip('*'))
        continue
    if stripped.startswith('**') and '**' in stripped[2:]:
        # Mixed bold like **What:** ...
        pdf.bold_text(stripped.replace('**', ''))
        continue

    # Checkbox
    if stripped.startswith('- [ ] ') or stripped.startswith('- [x] '):
        pdf.checkbox(stripped[6:])
        continue

    # Bullet
    if stripped.startswith('- ') or stripped.startswith('* '):
        pdf.bullet(stripped[2:])
        continue

    # Numbered list
    m = re.match(r'^(\d+)\.\s+(.*)', stripped)
    if m:
        pdf.bullet(f"{m.group(1)}. {m.group(2)}")
        continue

    # Regular text (strip markdown formatting)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', stripped)
    text = re.sub(r'`(.*?)`', r'\1', text)
    if text.startswith('*') and text.endswith('*'):
        pdf.set_font('Helvetica', 'I', 10)
        pdf.set_text_color(100, 116, 139)
        pdf.multi_cell(0, 5.5, text.strip('*'))
        pdf.ln(2)
    else:
        pdf.body_text(text)

# Flush any remaining table
if in_table:
    flush_table()

pdf.output('QUALITY_ROADMAP.pdf')
print('PDF created successfully: QUALITY_ROADMAP.pdf')
