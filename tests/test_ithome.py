import urllib.parse
import requests
import lxml.html

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def test_fetch_tag(tag):
    url = f"https://www.ithome.com.tw/tags/{urllib.parse.quote(tag)}"
    resp = requests.get(url, headers=headers, timeout=10)
    doc = lxml.html.fromstring(resp.content)
    items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
    print(f"=== Tag: {tag} ({len(items)} items) ===")
    for item in items[:5]:
        title_el = item.xpath('.//p[contains(@class, "title")]/a')
        date_el = item.xpath('.//p[contains(@class, "post-at")]')
        summary_el = item.xpath('.//p[contains(@class, "summary")]')
        if title_el:
            t = title_el[0].text_content().strip()
            href = title_el[0].get('href')
            d = date_el[0].text_content().strip() if date_el else ""
            s = summary_el[0].text_content().strip() if summary_el else ""
            print(f"Date: {d}")
            print(f"Title: {t}")
            print(f"URL: https://www.ithome.com.tw{href}")
            print(f"Summary: {s[:60]}...")
            print("-" * 40)

if __name__ == '__main__':
    for tag in ["重大訊息", "臺灣資安週報"]:
        test_fetch_tag(tag)
