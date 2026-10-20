import sys
import requests
import lxml.html
import urllib.parse

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def search_ithome(keyword):
    encoded = urllib.parse.quote(keyword)
    url = f"https://www.ithome.com.tw/search/node/{encoded}"
    res = requests.get(url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    
    # search results items
    items = doc.xpath('//ol[contains(@class, "search-results")]/li') or doc.xpath('//div[contains(@class, "search-result")]') or doc.xpath('//div[contains(@class, "item")]')
    print(f"Keyword '{keyword}' -> items count: {len(items)}")
    for it in items[:6]:
        title = it.xpath('.//h3/a/text()') or it.xpath('.//a/text()')
        link = it.xpath('.//h3/a/@href') or it.xpath('.//a/@href')
        snippet = it.xpath('.//p[contains(@class, "search-snippet")]/text()') or it.xpath('.//div[contains(@class, "snippet")]/text()')
        t = title[0].strip() if title else ""
        l = link[0].strip() if link else ""
        s = snippet[0].strip() if snippet else ""
        print(f"Title: {t}")
        print(f"Link: {l}")
        print(f"Snippet: {s[:80]}")
        print("-" * 30)

if __name__ == '__main__':
    search_ithome("上市 資安 重大訊息")
    search_ithome("勒索軟體 上市")
