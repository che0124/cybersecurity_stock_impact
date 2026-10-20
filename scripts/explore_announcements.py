import sys
import requests
import lxml.html
import urllib.parse

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

tag = "資安重訊"
url = f"https://www.ithome.com.tw/tags/{urllib.parse.quote(tag)}"

for page in range(3):
    page_url = f"{url}?page={page}"
    res = requests.get(page_url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
    print(f"=== Page {page}: {len(items)} items ===")
    seen = set()
    for it in items:
        title = it.xpath('.//p[contains(@class, "title")]/a/text()')
        href = it.xpath('.//p[contains(@class, "title")]/a/@href')
        date = it.xpath('.//p[contains(@class, "post-at")]/text()')
        if title and href:
            t = title[0].strip()
            h = href[0].strip()
            d = date[0].strip() if date else ""
            if h not in seen:
                seen.add(h)
                print(f"[{d}] {t} -> https://www.ithome.com.tw{h}")
