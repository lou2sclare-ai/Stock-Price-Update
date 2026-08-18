from __future__ import annotations
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

NAVY="0B1F3A"; NAVY2="173A70"; BLUE="2F61D5"; LIGHT="EAF2FF"; PALE="F7F9FC"; WHITE="FFFFFF"; GRAY="64748B"; GREEN="008000"; RED="C00000"; ORANGE="F59E0B"; LINE="DCE4EE"
THIN = Side(style="thin", color=LINE)
SECTOR_LABELS={
    "SHIPBUILDING":"조선",
    "DEFENSE":"방산",
    "POWER_EQUIPMENT":"전력기기",
    "CONSTRUCTION_EQUIPMENT":"건설장비",
    "MACHINERY":"기계",
}
SECTOR_ORDER={k:i for i,k in enumerate(SECTOR_LABELS)}


def _is_kr(r: dict) -> bool:
    return str(r.get("country") or "").upper()=="KR"


def _status_label(s):
    return "Coverage" if s=="COVERAGE" else ("NR" if s=="NR" else "미정")


def _country_label(v):
    return "대한민국" if str(v or "").upper()=="KR" else (v or "-")


def _sorted(rows):
    return sorted(rows,key=lambda r:(SECTOR_ORDER.get(r.get("research_sector"),99),0 if _is_kr(r) else 1,-float(r.get("market_cap") or 0),str(r.get("company_name") or "")))


def _title(ws, last_col, title, subtitle):
    ws.sheet_view.showGridLines=False
    ws.row_dimensions[1].height=31
    ws.row_dimensions[2].height=19
    ws["A1"]=title
    ws["A1"].font=Font(name="Arial",size=19,bold=True,color=WHITE)
    ws["A1"].fill=PatternFill("solid",fgColor=NAVY)
    ws["A1"].alignment=Alignment(vertical="center")
    ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=last_col)
    ws["A2"]=subtitle
    ws["A2"].font=Font(name="Arial",size=9,color="D6E4F5")
    ws["A2"].fill=PatternFill("solid",fgColor=NAVY)
    ws.merge_cells(start_row=2,start_column=1,end_row=2,end_column=last_col)


def _header(cell, text):
    cell.value=text
    cell.font=Font(name="Arial",size=9,bold=True,color=WHITE)
    cell.fill=PatternFill("solid",fgColor=NAVY2)
    cell.alignment=Alignment(horizontal="center",vertical="center")
    cell.border=Border(bottom=Side(style="thin",color="FFFFFF"))


def _make_table_sheet(ws, rows, qa=None, title="섹터별 주가 모니터", subtitle=""):
    headers=["섹터","구분","국가","회사","Ticker","거래소","리서치 상태","종가","전일종가","등락","등락률","TP","Upside","데이터 기준","직전거래일","가격 출처"]
    _title(ws,len(headers),title,subtitle)
    ws.row_dimensions[3].height=8
    for c,h in enumerate(headers,1): _header(ws.cell(4,c),h)
    ws.cell(4,1).comment=Comment("국내 Universe 분류 원천: NAVER Finance 업종분류 (https://finance.naver.com). 해외 Universe 분류 원천: TradingView Screener (https://www.tradingview.com).","OpenAI")
    ws.cell(4,16).comment=Comment("국내 가격은 KRX 계열 데이터를 사용하고, 해외 가격은 TradingView Screener 최신 정규장 스냅샷을 우선 사용합니다.","OpenAI")
    for i,r in enumerate(_sorted(rows),5):
        sector=SECTOR_LABELS.get(r.get("research_sector"),r.get("research_sector") or "-")
        basis=r.get("price_date") or ("최신 스냅샷" if not _is_kr(r) else "-")
        vals=[sector,"국내" if _is_kr(r) else "해외",_country_label(r.get("country")),r.get("company_name"),r.get("ticker"),r.get("exchange"),_status_label(r.get("research_status")),r.get("price"),r.get("previous_close"),r.get("price_change"),(r.get("price_change_pct")/100 if r.get("price_change_pct") is not None else None),r.get("target_price"),None,basis,r.get("previous_trading_date"),r.get("price_source")]
        for c,v in enumerate(vals,1):
            cell=ws.cell(i,c,v)
            cell.font=Font(name="Arial",size=9,color="000000")
            cell.alignment=Alignment(vertical="center",horizontal="right" if c in (8,9,10,11,12,13) else "left")
            if i%2==0: cell.fill=PatternFill("solid",fgColor=PALE)
        if r.get("target_price") and r.get("price"):
            ws.cell(i,13,f"=IFERROR(L{i}/H{i}-1,\"\")")
        for c in (8,9,10,12): ws.cell(i,c).number_format='#,##0.###;[Red](#,##0.###);-'
        for c in (11,13): ws.cell(i,c).number_format='0.0%;[Red](0.0%);-'
        if r.get("research_status")=="COVERAGE":
            ws.cell(i,7).fill=PatternFill("solid",fgColor="E8F0FF")
            ws.cell(i,7).font=Font(name="Arial",size=9,bold=True,color="214FB7")
        elif r.get("research_status")=="NR":
            ws.cell(i,7).fill=PatternFill("solid",fgColor="EEF0F3")
        if r.get("research_sector") in SECTOR_LABELS:
            ws.cell(i,1).font=Font(name="Arial",size=9,bold=True,color=NAVY2)
    widths=[12,8,14,38,13,11,13,14,14,14,11,14,11,15,14,22]
    for i,w in enumerate(widths,1): ws.column_dimensions[get_column_letter(i)].width=w
    ws.freeze_panes="H5"
    ws.auto_filter.ref=f"A4:P{max(5,4+len(rows))}"
    ws.sheet_view.zoomScale=90
    if rows:
        last=4+len(rows)
        for col in ("K","M"):
            ws.conditional_formatting.add(f"{col}5:{col}{last}",CellIsRule(operator="greaterThan",formula=["0"],font=Font(color=BLUE,bold=True)))
            ws.conditional_formatting.add(f"{col}5:{col}{last}",CellIsRule(operator="lessThan",formula=["0"],font=Font(color=RED,bold=True)))
        ws.conditional_formatting.add(f"J5:J{last}",CellIsRule(operator="greaterThan",formula=["0"],font=Font(color=BLUE,bold=True)))
        ws.conditional_formatting.add(f"J5:J{last}",CellIsRule(operator="lessThan",formula=["0"],font=Font(color=RED,bold=True)))


def build(rows: list[dict], qa: dict, path: str):
    rows=_sorted(rows)
    domestic=[r for r in rows if _is_kr(r)]
    global_rows=[r for r in rows if not _is_kr(r)]
    wb=Workbook()
    ws=wb.active;ws.title="Dashboard"
    subtitle=f"QA {qa['status']} | 전체 {len(rows):,}개 | 국내 {len(domestic):,}개 | 해외 {len(global_rows):,}개 | 생성 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    _make_table_sheet(ws,rows,qa,"섹터별 주가 모니터",subtitle)

    kd=wb.create_sheet("국내")
    _make_table_sheet(kd,domestic,qa,"국내 주가 모니터",f"NAVER 업종 Universe / KRX 가격 | {len(domestic):,}개")
    kg=wb.create_sheet("해외")
    _make_table_sheet(kg,global_rows,qa,"해외 주가 모니터",f"TradingView Primary common shares | {len(global_rows):,}개")

    u=wb.create_sheet("Universe");u.sheet_view.showGridLines=False
    uh=["company_name","ticker","country","exchange","currency","source","source_sector","source_industry","research_sector","research_status","target_price","target_currency","last_report_date","active","review_note"]
    for c,h in enumerate(uh,1): _header(u.cell(1,c),h)
    for i,r in enumerate(rows,2):
        for c,h in enumerate(uh,1):
            cell=u.cell(i,c,r.get(h,""));cell.font=Font(name="Arial",size=9)
            if i%2==0: cell.fill=PatternFill("solid",fgColor=PALE)
    u.freeze_panes="A2";u.auto_filter.ref=f"A1:O{max(2,1+len(rows))}";u.sheet_view.zoomScale=85
    for c in range(1,16):u.column_dimensions[get_column_letter(c)].width=18
    u.column_dimensions["A"].width=38;u.column_dimensions["H"].width=34;u.column_dimensions["O"].width=54

    q=wb.create_sheet("QA");q.sheet_view.showGridLines=False
    q["A1"]="QA STATUS";q["B1"]=qa["status"]
    for cell in (q["A1"],q["B1"]):cell.font=Font(bold=True,color=WHITE);cell.fill=PatternFill("solid",fgColor=NAVY)
    q["B1"].fill=PatternFill("solid",fgColor=RED if qa["status"]=="FAIL" else (ORANGE if qa["status"]=="REVIEW" else BLUE))
    summary=[("전체 종목",qa.get("row_count")),("국내 종목",qa.get("domestic_count")),("가격 누락",qa.get("missing_price_count")),("수집 오류",qa.get("fetch_error_count"))]
    row=3
    for label,value in summary:
        q.cell(row,1,label);q.cell(row,2,value);row+=1
    row+=1
    for level,items in (("ERROR",qa.get("errors",[])),("WARNING",qa.get("warnings",[]))):
        for msg in items:
            q.cell(row,1,level);q.cell(row,2,msg)
            if level=="ERROR": q.cell(row,1).fill=PatternFill("solid",fgColor="FDECEC")
            else: q.cell(row,1).fill=PatternFill("solid",fgColor="FFF4D8")
            row+=1
    q.column_dimensions["A"].width=18;q.column_dimensions["B"].width=110

    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);wb.save(p)
