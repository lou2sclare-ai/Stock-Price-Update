from __future__ import annotations
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

NAVY="0B1F3A"; BLUE="1D4ED8"; LIGHT="EAF2FF"; PALE="F5F8FC"; WHITE="FFFFFF"; GRAY="64748B"; GREEN="008000"; RED="C00000"; ORANGE="F59E0B"
THIN = Side(style="thin", color="D7E0EA")


def _title(ws, title, subtitle):
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 28
    ws["A1"] = title
    ws["A1"].font = Font(name="Arial", size=18, bold=True, color=WHITE)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.merge_cells("A1:N1")
    ws["A2"] = subtitle
    ws["A2"].font = Font(name="Arial", size=9, color=GRAY)
    ws.merge_cells("A2:N2")


def build(rows: list[dict], qa: dict, path: str):
    wb=Workbook(); ws=wb.active; ws.title="Dashboard"
    _title(ws,"STOCK SECTOR DASHBOARD", f"QA: {qa['status']} | Rows: {qa['row_count']}")
    headers=["섹터","국가","회사","Ticker","거래소","상태","종가","전일종가","등락","등락률","TP","Upside","가격기준일","직전거래일"]
    for c,h in enumerate(headers,1):
        cell=ws.cell(4,c,h); cell.font=Font(name="Arial",size=9,bold=True,color=WHITE); cell.fill=PatternFill("solid",fgColor=BLUE); cell.alignment=Alignment(horizontal="center")
    for i,r in enumerate(rows,5):
        vals=[r.get("research_sector"),r.get("country"),r.get("company_name"),r.get("ticker"),r.get("exchange"),r.get("research_status"),r.get("price"),r.get("previous_close"),r.get("price_change"), (r.get("price_change_pct")/100 if r.get("price_change_pct") is not None else None),r.get("target_price"),None,r.get("price_date"),r.get("previous_trading_date")]
        for c,v in enumerate(vals,1): ws.cell(i,c,v)
        if r.get("target_price") and r.get("price"):
            ws.cell(i,12, f"=IFERROR(K{i}/G{i}-1,\"\")")
        for c in range(1,15):
            cell=ws.cell(i,c); cell.font=Font(name="Arial Narrow",size=9,color=GREEN if c in (7,8,13,14) else "000000");
            if i%2==0: cell.fill=PatternFill("solid",fgColor=PALE)
        for c in (7,8,9,11): ws.cell(i,c).number_format='#,##0;[Red](#,##0);-'
        for c in (10,12): ws.cell(i,c).number_format='0.0%;[Red](0.0%);-'
    widths=[15,8,28,13,10,13,14,14,14,11,14,11,13,13]
    for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
    ws.freeze_panes="G5"; ws.auto_filter.ref=f"A4:N{max(5,4+len(rows))}"
    if rows:
        ws.conditional_formatting.add(f"J5:J{4+len(rows)}", CellIsRule(operator="greaterThan", formula=["0"], font=Font(color=BLUE,bold=True)))
        ws.conditional_formatting.add(f"J5:J{4+len(rows)}", CellIsRule(operator="lessThan", formula=["0"], font=Font(color=RED,bold=True)))
    # Universe
    u=wb.create_sheet("Universe"); u.sheet_view.showGridLines=False
    uh=["company_name","ticker","country","exchange","currency","source","source_sector","source_industry","research_sector","research_status","target_price","target_currency","last_report_date","active","review_note"]
    for c,h in enumerate(uh,1):
        cell=u.cell(1,c,h); cell.fill=PatternFill("solid",fgColor=NAVY); cell.font=Font(color=WHITE,bold=True,size=9)
    for i,r in enumerate(rows,2):
        for c,h in enumerate(uh,1): u.cell(i,c,r.get(h,""))
    u.freeze_panes="A2"; u.auto_filter.ref=f"A1:O{max(2,1+len(rows))}"
    for c in range(1,16): u.column_dimensions[get_column_letter(c)].width=18
    u.column_dimensions["A"].width=28
    # QA
    q=wb.create_sheet("QA"); q.sheet_view.showGridLines=False
    q["A1"]="QA STATUS"; q["B1"]=qa["status"]
    q["A1"].font=Font(bold=True,color=WHITE); q["A1"].fill=PatternFill("solid",fgColor=NAVY)
    q["B1"].font=Font(bold=True,color=WHITE); q["B1"].fill=PatternFill("solid",fgColor=RED if qa["status"]=="FAIL" else (ORANGE if qa["status"]=="REVIEW" else BLUE))
    row=3
    for level,items in (("ERROR",qa["errors"]),("WARNING",qa["warnings"])):
        for msg in items:
            q.cell(row,1,level); q.cell(row,2,msg); row+=1
    q.column_dimensions["A"].width=15; q.column_dimensions["B"].width=100
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); wb.save(p)
