import sys
import requests
import datetime
import json

sys.stdout.reconfigure(encoding='utf-8')
headers = {'User-Agent': 'Mozilla/5.0'}

def get_stock_data(symbol, period1_ts, period2_ts):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1_ts}&period2={period2_ts}&interval=1d"
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return None
    data = res.json()
    result = data.get('chart', {}).get('result', [])
    if not result:
        return None
    
    timestamps = result[0].get('timestamp', [])
    indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
    closes = indicators.get('close', [])
    volumes = indicators.get('volume', [])
    
    records = []
    for ts, c, v in zip(timestamps, closes, volumes):
        if c is not None:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
            records.append({'date': dt, 'close': round(c, 2), 'volume': v})
    return records

test_symbols = ['2450.TW', '3293.TWO', '6136.TW']

# 2026-08-01 to 2026-10-15
p1 = int(datetime.datetime(2026, 8, 1).timestamp())
p2 = int(datetime.datetime(2026, 10, 15).timestamp())

for sym in test_symbols:
    recs = get_stock_data(sym, p1, p2)
    if recs:
        print(f"=== {sym}: {len(recs)} trading days ===")
        print(f"First 2: {recs[:2]}")
        print(f"Last 2:  {recs[-2:]}")
    else:
        print(f"=== {sym}: Failed to fetch ===")
