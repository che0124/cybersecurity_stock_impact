import requests
import json

headers = {'User-Agent': 'Mozilla/5.0'}
url = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=2450.TW,3293.TWO"
r = requests.get(url, headers=headers)
print("Quote status:", r.status_code)
if r.status_code == 200:
    results = r.json().get('quoteResponse', {}).get('result', [])
    for res in results:
        print("Symbol:", res.get('symbol'))
        print("  ShortName:", res.get('shortName'))
        print("  MarketCap:", res.get('marketCap'))
        print("  TrailingPE:", res.get('trailingPE'))
        print("  ForwardPE:", res.get('forwardPE'))
        print("  PriceToBook:", res.get('priceToBook'))
        print("  52w Range:", res.get('fiftyTwoWeekRange'))
