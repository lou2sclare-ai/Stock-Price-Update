import unittest

from src.universe import naver


class NaverParserTests(unittest.TestCase):
    def test_industry_link_parses_no_before_type(self):
        html = '<a href="/sise/sise_group_detail.naver?no=291&type=upjong">조선</a>'
        links = naver._industry_links_from_html(html)
        self.assertIn("조선", links)
        self.assertIn("no=291", links["조선"])

    def test_industry_link_parses_type_before_no(self):
        html = '<a href="/sise/sise_group_detail.naver?type=upjong&no=291">조선</a>'
        links = naver._industry_links_from_html(html)
        self.assertIn("조선", links)

    def test_stock_link_parses_code_in_any_query_position(self):
        html = '<a href="/item/main.naver?foo=1&code=012450">한화에어로스페이스</a>'
        rows = naver._stocks_from_html(html, "우주항공과국방")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "012450")
        self.assertEqual(rows[0]["company_name"], "한화에어로스페이스")

    def test_required_research_industries_have_fallback_urls(self):
        links = naver._fallback_industry_links()
        for name in ["조선", "우주항공과국방", "전기장비", "전기제품", "기계"]:
            self.assertIn(name, links)
            self.assertIn("type=upjong", links[name])


if __name__ == "__main__":
    unittest.main()
