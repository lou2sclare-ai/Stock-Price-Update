from src.qa import run

def settings(): return {"qa":{"max_abs_daily_change_pct":40}}

def test_pass():
    rows=[{"country":"KR","exchange":"KRX","ticker":"000001","company_name":"A","price":100,"price_change_pct":1.2,"research_status":"UNDEFINED"}]
    assert run(rows,settings())["status"]=="PASS"

def test_duplicate_fails():
    r={"country":"KR","exchange":"KRX","ticker":"000001","company_name":"A","price":100,"price_change_pct":1.2,"research_status":"UNDEFINED"}
    assert run([r,r.copy()],settings())["status"]=="FAIL"
