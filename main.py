"""
上市櫃資安事件與股價衝擊分析系統 (Cybersecurity Stock Impact Pipeline)
專案主執行入口 (CLI Entrypoint)
"""
import sys
import os
import argparse

# 將 src 加入模組搜尋路徑
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from pipeline import run_pipeline

def main():
    parser = argparse.ArgumentParser(
        description="iThome 上市櫃資安事件與股價衝擊分析系統 (Event Study Pipeline)"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help="爬取 iThome 資安重訊列表的頁數 (預設: 2 頁，約 20-30 篇事件)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(ROOT_DIR, "data"),
        help="分析成果輸出資料夾路徑 (預設: ./data/)"
    )

    args = parser.parse_args()
    run_pipeline(max_pages=args.pages, output_dir=args.output)

if __name__ == "__main__":
    main()
