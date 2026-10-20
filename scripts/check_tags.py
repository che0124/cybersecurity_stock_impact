import sys
import requests
import lxml.html
import urllib.parse

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

test_tags = ["資安重訊", "資料外洩", "勒索軟體", "臺灣資安週報", "駭客攻擊", "供應鏈攻擊"]

for t in test_tags:
    url = f"https://www.ithome.com.tw/tags/{urllib.parse.quote(t)}"
    res = requests.get(url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
    titles = [i.xpath('.//p[contains(@class, "title")]/a/text()')[0].strip() for i in items if i.xpath('.//p[contains(@class, "title")]/a/text()')]
    print(f"Tag: '{t}' -> {len(items)} items. Examples: {titles[:3]}")
