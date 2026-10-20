import sys
import requests
import lxml.html
import re
import json

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def crawl_security_news(max_pages=5):
    articles = []
    seen_urls = set()
    
    for page in range(max_pages):
        url = f"https://www.ithome.com.tw/security?page={page}"
        print(f"Crawling page {page}: {url}...")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"Status code {res.status_code}")
                continue
            doc = lxml.html.fromstring(res.content)
            items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
            for it in items:
                title_nodes = it.xpath('.//p[contains(@class, "title")]/a')
                date_nodes = it.xpath('.//p[contains(@class, "post-at")]')
                summary_nodes = it.xpath('.//p[contains(@class, "summary")]')
                
                if not title_nodes:
                    continue
                title = title_nodes[0].text_content().strip()
                link = title_nodes[0].get('href', '').strip()
                if not link.startswith('http'):
                    link = f"https://www.ithome.com.tw{link}"
                
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                
                date_str = date_nodes[0].text_content().strip() if date_nodes else ""
                summary = summary_nodes[0].text_content().strip() if summary_nodes else ""
                
                articles.append({
                    "title": title,
                    "url": link,
                    "date": date_str,
                    "summary": summary
                })
        except Exception as e:
            print(f"Error crawling page {page}: {e}")
            
    print(f"Total unique articles collected: {len(articles)}")
    return articles

if __name__ == '__main__':
    articles = crawl_security_news(max_pages=3)
    # Filter articles likely mentioning Taiwan companies, ransomware, or incidents
    keywords = ["重訊", "上市", "櫃", "臺灣", "攻擊", "勒索", "入侵", "外洩", "駭客", "中斷"]
    matched = []
    for a in articles:
        text = a['title'] + " " + a['summary']
        if any(k in text for k in keywords):
            matched.append(a)
    print(f"Matched keyword articles: {len(matched)}")
    for m in matched[:10]:
        print(f"[{m['date']}] {m['title']}")
        print(f"  URL: {m['url']}")
