import sys
import requests
import lxml.html

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

urls = [
    "https://www.ithome.com.tw/news/179288", # 神腦
    "https://www.ithome.com.tw/news/179289", # 鈊象
    "https://www.ithome.com.tw/news/178762"  # 富爾特/格帝
]

for url in urls:
    res = requests.get(url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    title = doc.xpath('//h1[contains(@class, "page-header")]/text()')
    paragraphs = doc.xpath('//div[contains(@class, "content")]//p')
    print("=" * 60)
    print("Title:", title[0].strip() if title else "")
    print("URL:", url)
    for p in paragraphs:
        txt = p.text_content().strip()
        if txt:
            print("  >", txt)
