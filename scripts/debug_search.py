import sys
import requests
import lxml.html

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}
res = requests.get('https://www.ithome.com.tw/search/node/勒索軟體', headers=headers)
doc = lxml.html.fromstring(res.content)
print('Page Title:', doc.findtext('.//title'))

# Look at search results or titles
links = doc.xpath('//ol[contains(@class, "search-results")]//a') or doc.xpath('//h3/a') or doc.xpath('//a[contains(@href, "/news/")]')
print(f"Total links found: {len(links)}")
for l in links[:15]:
    href = l.get('href', '')
    text = l.text_content().strip()
    if '/news/' in href:
        print(f"Link: {text} -> {href}")
