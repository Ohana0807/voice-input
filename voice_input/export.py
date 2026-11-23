"""分析結果を Excel / Word に書き出す。"""

from __future__ import annotations

from pathlib import Path

from .analyzer import AnalysisResult


def _evidence_text(item) -> str:
    return "\n".join(f"[{e.time}] {e.point}" if e.time else f"・{e.point}" for e in item.evidence)


def export_excel(result: AnalysisResult, path: str | Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "分析結果"
    font = "Yu Gothic"
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    meta = [
        ("対象", result.source_label),
        ("テンプレート", result.template_name),
        ("分析日時", result.created.strftime("%Y-%m-%d %H:%M")),
    ]
    for r, (k, v) in enumerate(meta, 1):
        ws.cell(r, 1, k).font = Font(name=font, bold=True)
        ws.cell(r, 2, v).font = Font(name=font)

    header_row = len(meta) + 2
    headers = ["項目", "まとめ", "根拠（時刻・発言の要点）"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(header_row, c, h)
        cell.font = Font(name=font, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="44546A")
        cell.alignment = Alignment(vertical="center")
        cell.border = border

    for r, item in enumerate(result.items, header_row + 1):
        values = [item.name, item.summary, _evidence_text(item)]
        for c, v in enumerate(values, 1):
            cell = ws.cell(r, c, v)
            cell.font = Font(name=font, bold=(c == 1))
            cell.alignment = wrap
            cell.border = border

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 60
    ws.freeze_panes = ws.cell(header_row + 1, 1)

    ts = wb.create_sheet("文字起こし")
    ts.column_dimensions["A"].width = 120
    for r, line in enumerate(result.transcript.splitlines(), 1):
        cell = ts.cell(r, 1, line)
        cell.font = Font(name=font)
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    wb.save(str(path))


def export_word(result: AnalysisResult, path: str | Path) -> None:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    jp_font = "Yu Gothic"
    for style_name in ("Normal", "Title", "Heading 1", "Heading 2", "List Bullet"):
        st = doc.styles[style_name]
        st.font.name = jp_font
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = rpr.makeelement(qn("w:rFonts"), {})
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
            rfonts.set(qn(attr), jp_font)
    doc.styles["Normal"].font.size = Pt(10.5)

    doc.add_heading("ヒアリング分析結果", level=0)
    meta = doc.add_paragraph()
    meta.add_run(f"対象：{result.source_label}\n").font.size = Pt(9.5)
    meta.add_run(f"テンプレート：{result.template_name}\n").font.size = Pt(9.5)
    meta.add_run(f"分析日時：{result.created.strftime('%Y-%m-%d %H:%M')}").font.size = Pt(9.5)

    doc.add_heading("概要", level=1)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text = "項目", "まとめ"
    for c in hdr:
        for r in c.paragraphs[0].runs:
            r.bold = True
    for item in result.items:
        row = table.add_row().cells
        row[0].text = item.name
        row[1].text = item.summary
    for row in table.rows:
        row.cells[0].width = Pt(110)
        row.cells[1].width = Pt(340)

    doc.add_heading("項目ごとの詳細", level=1)
    for item in result.items:
        doc.add_heading(item.name, level=2)
        if item.description:
            p = doc.add_paragraph()
            run = p.add_run(item.description)
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x76, 0x76, 0x76)
        doc.add_paragraph(item.summary)
        for e in item.evidence:
            doc.add_paragraph(f"[{e.time}] {e.point}" if e.time else e.point, style="List Bullet")

    doc.add_page_break()
    doc.add_heading("文字起こし", level=1)
    for line in result.transcript.splitlines():
        if line.strip():
            p = doc.add_paragraph(line)
            p.paragraph_format.space_after = Pt(2)

    doc.save(str(path))
