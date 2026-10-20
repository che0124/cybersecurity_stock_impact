import sys
import requests
import lxml.html

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

def inspect_article(url):
    res = requests.get(url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    title = doc.xpath('//h1[contains(@class, "page-header")]/text()') or doc.xpath('//h1/text()')
    date = doc.xpath('//span[contains(@class, "created")]/text()') or doc.xpath('//div[contains(@class, "post-at")]/text()')
    content = doc.xpath('//div[contains(@class, "content")]//p/text()') or doc.xpath('//article//p/text()')
    
    print("URL:", url)
    print("Title:", title[0].strip() if title else "")
    print("Date:", date[0].strip() if date else "")
    print("Content preview:")
    full_text = "\n".join([p.strip() for p in content if p.strip()])
    print(full_text[:600])

if __name__ == '__main__':
    inspect_article('https://www.ithome.com.tw/news/179381')
