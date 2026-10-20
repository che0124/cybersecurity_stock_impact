import sys
import requests
import json

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

def test_resolve_ticker(code):
    for suffix in ['.TW', '.TWO']:
        sym = f"{code}{suffix}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        try:
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
                name = meta.get('shortName') or meta.get('longName') or sym
                price = meta.get('regularMarketPrice')
                currency = meta.get('currency')
                return sym, name, price, currency
        except Exception:
            pass
    return None, None, None, None

test_codes = ['6741', '4953', '6128', '4175', '3293', '3130', '1259', '2450', '8462']

for c in test_codes:
    sym, name, price, curr = test_resolve_ticker(c)
    print(f"Code: {c} -> Symbol: {sym}, Name: {name}, Current Price: {price} {curr}")
