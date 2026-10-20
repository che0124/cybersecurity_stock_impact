"""
企業財務與股價行情整合模組
"""
import requests
import datetime
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 快取證交所與櫃買中心財務資料
_FINANCIAL_CACHE = {}

def load_financial_ratios():
    """從台灣證交所 (TWSE) 與櫃買中心 (TPEx) 官方 OpenAPI 載入本益比、殖利率與淨值比"""
    global _FINANCIAL_CACHE
    if _FINANCIAL_CACHE:
        return _FINANCIAL_CACHE

    data = {}
    # 1. TWSE 上市股票
    try:
        twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
        r = requests.get(twse_url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            for item in r.json():
                code = item.get('Code')
                data[code] = {
                    "market": "TWSE (上市)",
                    "pe_ratio": item.get('PEratio') or "N/A",
                    "dividend_yield": item.get('DividendYield') or "N/A",
                    "pb_ratio": item.get('PBratio') or "N/A"
                }
    except Exception as e:
        print(f"[MarketData] 載入 TWSE 財務資料提示: {e}")

    # 2. TPEx 上櫃股票
    try:
        tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
        r = requests.get(tpex_url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            for item in r.json():
                code = item.get('SecuritiesCompanyCode')
                data[code] = {
                    "market": "TPEx (上櫃)",
                    "pe_ratio": item.get('PriceEarningRatio') or "N/A",
                    "dividend_yield": item.get('YieldRatio') or "N/A",
                    "pb_ratio": item.get('PriceBookRatio') or "N/A"
                }
    except Exception as e:
        print(f"[MarketData] 載入 TPEx 財務資料提示: {e}")

    _FINANCIAL_CACHE = data
    return _FINANCIAL_CACHE

def resolve_ticker(stock_code):
    """判斷股票代碼屬於上市 (.TW) 或上櫃 (.TWO)"""
    for suffix in [".TW", ".TWO"]:
        sym = f"{stock_code}{suffix}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        try:
            r = requests.get(url, headers=HEADERS, timeout=4)
            if r.status_code == 200:
                result = r.json().get('chart', {}).get('result', [])
                if result:
                    meta = result[0].get('meta', {})
                    return sym, meta
        except Exception:
            pass
    return None, None

def fetch_chart_history(symbol, start_date_str, end_date_str):
    """透過 Yahoo Finance API 取得指定日期區間之日線 OHLCV"""
    try:
        s_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        e_dt = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
    except Exception:
        return []

    p1 = int(s_dt.timestamp())
    p2 = int((e_dt + datetime.timedelta(days=1)).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200:
            return []
        data = r.json()
        result = data.get('chart', {}).get('result', [])
        if not result:
            return []
        
        timestamps = result[0].get('timestamp', [])
        indicators = result[0].get('indicators', {}).get('quote', [{}])[0]
        closes = indicators.get('close', [])
        volumes = indicators.get('volume', [])
        
        records = []
        for ts, c, v in zip(timestamps, closes, volumes):
            if c is not None:
                dt_str = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
                records.append({'date': dt_str, 'close': round(c, 2), 'volume': v or 0})
        return records
    except Exception as e:
        print(f"[MarketData] 獲取 {symbol} 行情異常: {e}")
        return []

def evaluate_incident_impact(stock_code, disclosure_date):
    """
    結合財務資料、個股股價與大盤指數，評估資安事件公開前後的股價衝擊
    """
    if not stock_code:
        return {"error": "缺少股票代號"}

    fin_all = load_financial_ratios()
    fin_info = fin_all.get(stock_code, {
        "market": "未知",
        "pe_ratio": "N/A",
        "dividend_yield": "N/A",
        "pb_ratio": "N/A"
    })

    symbol, meta = resolve_ticker(stock_code)
    if not symbol:
        return {
            "financials": fin_info,
            "error": f"無法解析股票代碼 {stock_code} 的市場行情"
        }

    # 52 週高低價與當前收盤
    fifty_two_week_high = meta.get('fiftyTwoWeekHigh')
    fifty_two_week_low = meta.get('fiftyTwoWeekLow')
    current_price = meta.get('regularMarketPrice')

    # 設定事件分析期間：揭露日前後各 25 天
    try:
        d_dt = datetime.datetime.strptime(disclosure_date, "%Y-%m-%d")
    except Exception:
        d_dt = datetime.datetime.now()

    start_date = (d_dt - datetime.timedelta(days=35)).strftime("%Y-%m-%d")
    end_date = (d_dt + datetime.timedelta(days=20)).strftime("%Y-%m-%d")

    # 抓取個股與大盤 (^TWII) 日線
    stock_history = fetch_chart_history(symbol, start_date, end_date)
    taiex_history = fetch_chart_history("%5ETWII", start_date, end_date)

    if not stock_history:
        return {
            "symbol": symbol,
            "financials": fin_info,
            "current_price": current_price,
            "52w_high": fifty_two_week_high,
            "52w_low": fifty_two_week_low,
            "error": "無歷史股價資料"
        }

    # 找出事件日 (t=0) 的交易日位置
    dates = [x['date'] for x in stock_history]
    t0_idx = None
    for idx, dt in enumerate(dates):
        if dt >= disclosure_date:
            t0_idx = idx
            break

    impact_stats = {}
    if t0_idx is not None and t0_idx > 0:
        event_dt = dates[t0_idx]
        p_prev = stock_history[t0_idx - 1]['close']
        p_t0 = stock_history[t0_idx]['close']
        
        # 1 天報酬
        ret_1d = round(((p_t0 - p_prev) / p_prev) * 100, 2)
        
        # 3 天累計報酬 (若資料足夠)
        p_t3 = stock_history[min(t0_idx + 2, len(stock_history) - 1)]['close']
        ret_3d = round(((p_t3 - p_prev) / p_prev) * 100, 2)
        
        # 事前 3 天走勢 (檢驗消息提前外洩 Leakage)
        p_pre3 = stock_history[max(0, t0_idx - 3)]['close']
        ret_pre3 = round(((p_prev - p_pre3) / p_pre3) * 100, 2)

        # 計算成交量變化 (事件日成交量 vs. 事前平均成交量)
        pre_volumes = [x['volume'] for x in stock_history[max(0, t0_idx - 10): t0_idx]]
        avg_vol = sum(pre_volumes) / len(pre_volumes) if pre_volumes else 1
        vol_multiple = round(stock_history[t0_idx]['volume'] / avg_vol, 2) if avg_vol > 0 else 1.0

        # 計算大盤同期報酬以求出超額報酬 (Abnormal Return)
        taiex_dates = [x['date'] for x in taiex_history]
        m_t0_idx = None
        for idx, dt in enumerate(taiex_dates):
            if dt >= disclosure_date:
                m_t0_idx = idx
                break

        abnormal_ret_1d = None
        abnormal_ret_3d = None
        if m_t0_idx is not None and m_t0_idx > 0:
            m_prev = taiex_history[m_t0_idx - 1]['close']
            m_t0 = taiex_history[m_t0_idx]['close']
            m_ret_1d = ((m_t0 - m_prev) / m_prev) * 100
            abnormal_ret_1d = round(ret_1d - m_ret_1d, 2)

            m_t3 = taiex_history[min(m_t0_idx + 2, len(taiex_history) - 1)]['close']
            m_ret_3d = ((m_t3 - m_prev) / m_prev) * 100
            abnormal_ret_3d = round(ret_3d - m_ret_3d, 2)

        impact_stats = {
            "trading_day_t0": event_dt,
            "price_before_event": p_prev,
            "price_on_event": p_t0,
            "raw_return_1d": f"{ret_1d}%",
            "raw_return_3d": f"{ret_3d}%",
            "pre_leakage_return_3d": f"{ret_pre3}%",
            "abnormal_return_1d": f"{abnormal_ret_1d}%" if abnormal_ret_1d is not None else "N/A",
            "abnormal_return_3d": f"{abnormal_ret_3d}%" if abnormal_ret_3d is not None else "N/A",
            "volume_shock_multiple": f"{vol_multiple}x"
        }

    return {
        "symbol": symbol,
        "company_name": meta.get('shortName', ''),
        "current_price": current_price,
        "52w_high": fifty_two_week_high,
        "52w_low": fifty_two_week_low,
        "financials": fin_info,
        "event_impact": impact_stats
    }

if __name__ == '__main__':
    res = evaluate_incident_impact("2450", "2026-09-29")
    import json
    print(json.dumps(res, indent=2, ensure_ascii=False))
