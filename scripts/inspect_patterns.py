import sys
import requests
import lxml.html
import urllib.parse
import re

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

def inspect_patterns():
    tag_url = f"https://www.ithome.com.tw/tags/{urllib.parse.quote('資安重訊')}"
    res = requests.get(tag_url, headers=headers)
    doc = lxml.html.fromstring(res.content)
    links = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]//p[contains(@class, "title")]/a/@href')
    
    print(f"Checking {len(links)} article links...")
    for link in links[:10]:
        if not link.startswith('http'):
            link = f"https://www.ithome.com.tw{link}"
        art_res = requests.get(link, headers=headers)
        art_doc = lxml.html.fromstring(art_res.content)
        title = art_doc.xpath('//h1[contains(@class, "page-header")]/text()')
        t = title[0].strip() if title else ""
        paras = art_doc.xpath('//div[contains(@class, "content")]//p')
        text = " ".join([p.text_content().strip() for p in paras if p.text_content().strip()])
        
        # Look for stock codes e.g. （2450）、(3293)
        code_match = re.findall(r'[（\(](\d{4})[）\)]', text)
        print(f"\nTitle: {t}")
        print(f"Stock code matched: {code_match}")
        
        # Look for dates in text
        # e.g. 9月29日, 2026年9月7日, 8月12日
        dates_in_text = re.findall(r'(\d{1,4}年)?(\d{1,2})月(\d{1,2})[日號]', text)
        print(f"Dates mentioned: {dates_in_text[:5]}")
        print("Text snippet:", text[:180])

if __name__ == '__main__':
    inspect_patterns()
