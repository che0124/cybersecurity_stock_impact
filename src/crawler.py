"""
iThome 資安重訊與事件爬蟲模組
"""
import urllib.parse
import requests
import lxml.html
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def crawl_ithome_announcements(max_pages=2, tag="資安重訊"):
    """
    爬取 iThome 指定標籤下的資安事件新聞列表與內文
    """
    base_tag_url = f"https://www.ithome.com.tw/tags/{urllib.parse.quote(tag)}"
    articles = []
    seen_urls = set()

    for page in range(max_pages):
        page_url = f"{base_tag_url}?page={page}"
        print(f"[Crawler] 抓取第 {page + 1} 頁列表: {page_url}")
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                print(f"[Crawler] 取得頁面失敗，HTTP 狀態碼: {resp.status_code}")
                continue
            
            doc = lxml.html.fromstring(resp.content)
            items = doc.xpath('//div[contains(@class, "view-content")]//div[contains(@class, "item")]')
            
            for it in items:
                title_nodes = it.xpath('.//p[contains(@class, "title")]/a')
                date_nodes = it.xpath('.//p[contains(@class, "post-at")]')
                
                if not title_nodes:
                    continue
                
                title = title_nodes[0].text_content().strip()
                href = title_nodes[0].get('href', '').strip()
                if not href.startswith('http'):
                    href = f"https://www.ithome.com.tw{href}"
                    
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                
                date_str = date_nodes[0].text_content().strip() if date_nodes else ""
                
                # 排除研討會/外部廣告連結
                if "ithome.com.tw/news/" not in href:
                    continue
                
                articles.append({
                    "title": title,
                    "url": href,
                    "published_at": date_str
                })
        except Exception as e:
            print(f"[Crawler] 抓取頁面發生錯誤: {e}")
            
    print(f"[Crawler] 共抓取到 {len(articles)} 篇候選新聞，開始解析內文...")
    
    # 逐篇抓取內文
    full_articles = []
    for idx, art in enumerate(articles):
        try:
            time.sleep(0.3)  # 禮貌延遲
            res = requests.get(art['url'], headers=HEADERS, timeout=10)
            if res.status_code == 200:
                adoc = lxml.html.fromstring(res.content)
                paras = adoc.xpath('//div[contains(@class, "content")]//p')
                text_list = [p.text_content().strip() for p in paras if p.text_content().strip()]
                
                # 排除文末固定訂閱宣傳語
                filtered_text = [
                    p for p in text_list 
                    if not p.startswith("擔心錯過") and not p.startswith("iThome Security") and not p.startswith("相關報導")
                ]
                art['content'] = "\n".join(filtered_text)
                full_articles.append(art)
                print(f"  [{idx+1}/{len(articles)}] 成功解析: {art['title'][:25]}...")
        except Exception as err:
            print(f"  [Error] 無法讀取內文 {art['url']}: {err}")
            
    return full_articles

if __name__ == '__main__':
    data = crawl_ithome_announcements(max_pages=1)
    print(f"\n抓取完成，共 {len(data)} 篇資安事件報導")
