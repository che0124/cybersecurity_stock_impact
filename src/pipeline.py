"""
資安事件與股價衝擊整合分析管線 (End-to-End Pipeline)
"""
import sys
import json
import csv
import os

# 確保 src 目錄在 sys.path 中，支援直接執行與模組呼叫
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from crawler import crawl_ithome_announcements
from extractor import extract_incident_details
from market_data import evaluate_incident_impact

sys.stdout.reconfigure(encoding='utf-8')

def run_pipeline(max_pages=2, output_dir=None):
    if output_dir is None:
        output_dir = os.path.join(_PROJECT_ROOT, "data")
    os.makedirs(output_dir, exist_ok=True)
    print("=" * 70)
    print("  🚀 iThome 上市櫃資安事件與股價衝擊分析管線 啟動中...")
    print("=" * 70)

    # 1. 爬取 iThome 資安重訊文章
    raw_articles = crawl_ithome_announcements(max_pages=max_pages, tag="資安重訊")
    print(f"\n[Pipeline] 成功取得 {len(raw_articles)} 篇資安事件報導，進行資訊抽取與分析...")

    dataset = []
    csv_rows = []

    for idx, art in enumerate(raw_articles):
        # 2. 抽取實體與日期、分類攻擊類型
        extracted = extract_incident_details(art)
        stock_code = extracted.get("stock_code")
        company = extracted.get("company_name") or "未知企業"

        print(f"\n[{idx+1}/{len(raw_articles)}] 處理事件: {company} ({stock_code or '未標註代號'}) - {art['title'][:30]}")

        # 3. 若有股票代號，查詢行情與財務指標
        market_info = {}
        if stock_code:
            disc_date = extracted["dates"]["disclosure_date"]
            print(f"  -> 揭露日: {disc_date}，正在拉取股價與財務指標...")
            market_info = evaluate_incident_impact(stock_code, disc_date)

        event_record = {
            "title": art["title"],
            "url": art["url"],
            "reported_date": art["published_at"],
            "stock_code": stock_code,
            "company_name": company,
            "dates": extracted["dates"],
            "attack_categories": extracted["attack_categories"],
            "impact_types": extracted["impact_types"],
            "impact_statement": extracted["impact_statement"],
            "market_data": market_info
        }
        dataset.append(event_record)

        # 整理成 CSV 格式便於後續迴歸分析 (Event Study)
        event_impact = market_info.get("event_impact", {})
        financials = market_info.get("financials", {})

        csv_rows.append({
            "公司名稱": company,
            "股票代碼": stock_code or "",
            "市場別": financials.get("market", ""),
            "侵入發生日": extracted["dates"]["intrusion_date"] or "",
            "內部發現日": extracted["dates"]["discovery_date"] or "",
            "公開揭露日": extracted["dates"]["disclosure_date"] or "",
            "攻擊類型": " / ".join(extracted["attack_categories"]),
            "影響範圍": " / ".join(extracted["impact_types"]),
            "事件日前收盤": event_impact.get("price_before_event", ""),
            "事件日收盤": event_impact.get("price_on_event", ""),
            "次日報酬率(Raw)": event_impact.get("raw_return_1d", ""),
            "3日累計報酬率(Raw)": event_impact.get("raw_return_3d", ""),
            "次日異常報酬率(AR)": event_impact.get("abnormal_return_1d", ""),
            "3日累計異常報酬率(CAR)": event_impact.get("abnormal_return_3d", ""),
            "事前外洩檢驗(CAR[-3,-1])": event_impact.get("pre_leakage_return_3d", ""),
            "成交量放大倍數": event_impact.get("volume_shock_multiple", ""),
            "本益比": financials.get("pe_ratio", ""),
            "殖利率": financials.get("dividend_yield", ""),
            "淨值比": financials.get("pb_ratio", ""),
            "官方聲明摘要": extracted["impact_statement"],
            "報導連結": art["url"]
        })

    # 4. 存檔 JSON 與 CSV
    json_path = os.path.join(output_dir, "cyber_incidents_analysis.json")
    csv_path = os.path.join(output_dir, "cyber_incidents_summary.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

    print("\n" + "=" * 70)
    print("  ✅ 分析完成！資料已成功輸出：")
    print(f"  📄 JSON 結構化檔案: {json_path}")
    print(f"  📊 CSV 數據表 (Excel相容): {csv_path}")
    print("=" * 70)

    # 5. 輸出終端精簡預覽表
    print("\n【資安事件衝擊預覽摘要表】")
    print(f"{'公司':<8} {'代碼':<6} {'揭露日':<11} {'攻擊類型':<20} {'1日AR':<8} {'3日CAR':<8} {'量能放大':<8}")
    print("-" * 75)
    for row in csv_rows:
        if row['股票代碼']:
            c_name = row['公司名稱'][:6]
            c_code = row['股票代碼']
            d_date = row['公開揭露日']
            c_atk = row['攻擊類型'][:18]
            ar_1d = row['次日異常報酬率(AR)'] or "N/A"
            car_3d = row['3日累計異常報酬率(CAR)'] or "N/A"
            vol = row['成交量放大倍數'] or "N/A"
            print(f"{c_name:<8} {c_code:<6} {d_date:<11} {c_atk:<20} {ar_1d:<8} {car_3d:<8} {vol:<8}")

    return dataset

if __name__ == '__main__':
    run_pipeline(max_pages=2)
