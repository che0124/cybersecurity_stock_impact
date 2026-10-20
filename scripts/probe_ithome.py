import sys
import requests
import lxml.html
import json

sys.stdout.reconfigure(encoding='utf-8')

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def probe_security_page():
    url = "https://www.ithome.com.tw/security"
    res = requests.get(url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    
    # Check top articles
    items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
    print(f"Total items found on {url}: {len(items)}")
    for i, it in enumerate(items[:15]):
        t = it.xpath('.//p[contains(@class, "title")]/a/text()')
        u = it.xpath('.//p[contains(@class, "title")]/a/@href')
        d = it.xpath('.//p[contains(@class, "post-at")]/text()')
        title = t[0].strip() if t else ""
        link = u[0].strip() if u else ""
        date = d[0].strip() if d else ""
        if title:
            print(f"[{i+1}] {date} | {title} | https://www.ithome.com.tw{link}")

if __name__ == '__main__':
    probe_security_page()
