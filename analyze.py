"""Rebuild the US event study from the curated events and observed prices."""

import argparse
import csv
import math
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FEATURES = (
    ("operational_disruption_disclosed", "營運中斷披露"),
    ("ransomware_disclosed", "勒索披露"),
    ("data_exposure_disclosed", "資料外洩披露"),
)
FINANCIAL = (("ln_market_cap_proxy", "估算市值（自然對數）"), ("pb_proxy", "估算股價淨值比"))
PADDED_RECORD = re.compile(
    r"^([a-zA-Z0-9]{16}),\s*[01],\s*[^,]*,\s*([^,]*),"
)
QUADRATURE_NODES, QUADRATURE_WEIGHTS = np.polynomial.legendre.leggauss(96)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def original_records(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        header = handle.readline()
        if header.startswith("slug,"):
            handle.seek(0)
            return {row["slug"]: (row["reported_date"], row["source_url"]) for row in csv.DictReader(handle)}

        # The supplied export pads fields to fixed widths and leaves text
        # commas unquoted. Read only the stable record prefix and match by slug.
        if header.split(",", 1)[0].strip() != "slug":
            raise ValueError("Unrecognized event export header")
        records = {}
        for line in handle:
            match = PADDED_RECORD.match(line)
            if match:
                slug, reported_date = match.groups()
                records[slug] = (reported_date.strip(), line)
        return records


def market_car(symbol, t0, prices, days, day_index):
    index = day_index[t0]
    pairs = {}
    first = max(1, index - 250)
    for position in range(first, min(len(days), index + 2)):
        previous, current = days[position - 1 : position + 1]
        if all((ticker, day) in prices for ticker in (symbol, "SPY") for day in (previous, current)):
            pairs[position - index] = tuple(
                prices[ticker, current] / prices[ticker, previous] - 1
                for ticker in (symbol, "SPY")
            )
    sample = np.array([pair for offset, pair in pairs.items() if offset <= -31])
    if len(sample) < 120 or any(offset not in pairs for offset in (-1, 0, 1)):
        raise ValueError(f"Incomplete estimation or CAR window for {symbol} on {t0}")
    design = np.column_stack((np.ones(len(sample)), sample[:, 1]))
    params, _, rank, _ = np.linalg.lstsq(design, sample[:, 0], rcond=None)
    if rank != 2:
        raise ValueError(f"Unidentified market model for {symbol} on {t0}")
    alpha, beta = params
    car = sum(100 * (stock - alpha - beta * market) for stock, market in
              (pairs[offset] for offset in (-1, 0, 1)))
    return len(sample), car


def two_sided_t_p(t_stat, dof):
    # Integrate the Student t tail after the substitution x = sqrt(dof) * tan(theta).
    lower = math.atan(abs(t_stat) / math.sqrt(dof))
    half_width = (math.pi / 2 - lower) / 2
    theta = lower + half_width * (1 + QUADRATURE_NODES)
    scale = math.exp(math.lgamma((dof + 1) / 2) - math.lgamma(dof / 2)) / math.sqrt(math.pi)
    return min(1.0, 2 * scale * half_width * np.dot(QUADRATURE_WEIGHTS, np.cos(theta) ** (dof - 1)))


def regression(events, terms):
    if len(events) <= len(terms) + 1:
        return {}
    design = np.array([[1] + [float(row[key]) for key, _ in terms] for row in events])
    car = np.array([row["car_m1_p1_pp"] for row in events])
    n, k = design.shape
    coefficients, _, rank, _ = np.linalg.lstsq(design, car, rcond=None)
    if rank != k:
        return {}
    residuals = car - design @ coefficients
    inverse = np.linalg.inv(design.T @ design)
    weighted = design * residuals[:, None]
    dof = n - k
    correction = n / dof
    covariance = correction * (inverse @ weighted.T @ weighted @ inverse)
    errors = np.sqrt(np.diag(covariance))
    return {
        key: (coefficient, two_sided_t_p(coefficient / error, dof) if error else None)
        for (key, _), coefficient, error in zip(terms, coefficients[1:], errors[1:], strict=True)
    }


def mean_test(values):
    sample = np.asarray(values, dtype=float)
    if len(sample) < 2:
        return None
    mean = sample.mean()
    error = sample.std(ddof=1) / np.sqrt(len(sample))
    if error == 0:
        return None
    p = two_sided_t_p(mean / error, len(sample) - 1)
    return mean, p, p / 2 if mean <= 0 else 1 - p / 2


def mean_row(report, label, values):
    result = mean_test(values)
    if result:
        mean, two_tail, left_tail = result
        report.append(f"| {label} | {len(values)} | {mean:.4f} | {left_tail:.4f} | {two_tail:.4f} |")
    else:
        report.append(f"| {label} | {len(values)} | — | — | — |")


def overlap_mean_p(events, day_index):
    scores = []
    right_edge = -1
    values = [row["car_m1_p1_pp"] for row in events]
    mean = np.mean(values)
    for row in sorted(events, key=lambda event: event["t0"]):
        center = day_index[row["t0"]]
        if center - 1 > right_edge:
            scores.append(0.0)
        scores[-1] += row["car_m1_p1_pp"] - mean
        right_edge = center + 1
    groups = len(scores)
    if groups < 2:
        return groups, None
    error = np.linalg.norm(scores) * np.sqrt(groups / (groups - 1)) / len(events)
    return groups, two_sided_t_p(mean / error, groups - 1) if error else None


def main(export_event_results=False):
    originals = original_records(ROOT / "cyber_events_2026-11-13.csv")
    events = read_csv(DATA / "events.csv")
    if not events:
        raise ValueError("The event sample is empty")
    if len({row["source_slug"] for row in events}) != len(events):
        raise ValueError("The event sample contains duplicate slugs")
    if len({(row["symbol"], row["t0"]) for row in events}) != len(events):
        raise ValueError("The event sample contains duplicate stock sessions")
    review = read_csv(DATA / "listing_review.csv")
    review_by_slug = {row["source_slug"]: row for row in review}
    if len(review_by_slug) != len(review) or review_by_slug.keys() != originals.keys():
        raise ValueError("The listing review does not account for the original events")
    included_slugs = {row["source_slug"] for row in review
                      if row["analysis_status"] == "included_car_sample"}
    if included_slugs != {row["source_slug"] for row in events}:
        raise ValueError("The listing review and CAR sample disagree")
    prices = {(row["symbol"], row["date"]): float(row["adjusted_close"])
              for row in read_csv(DATA / "prices.csv")}
    days = sorted(day for ticker, day in prices if ticker == "SPY")
    day_index = {day: index for index, day in enumerate(days)}
    for row in events:
        slug = row["source_slug"]
        original_date, source = originals[slug]
        if not row["source_url"] or row["source_url"] not in source:
            raise ValueError(f"Original event source differs for {slug}")
        if any(row[key] != review_by_slug[slug][key]
               for key in ("source_url", "announcement_date", "t0")):
            raise ValueError(f"Listing review evidence differs for {slug}")
        row["original_reported_date"] = original_date
        row["estimation_n"], row["car_m1_p1_pp"] = market_car(
            row["symbol"], row["t0"], prices, days, day_index
        )
        row["car_next_session_pp"] = None
        next_index = day_index[row["t0"]] + 1
        if next_index < len(days):
            try:
                _, row["car_next_session_pp"] = market_car(
                    row["symbol"], days[next_index], prices, days, day_index
                )
            except ValueError:
                pass

    n = len(events)
    symbols = len({row["symbol"] for row in events})
    complete = [row for row in events if all(row[key] in ("0", "1") for key, _ in FEATURES)]
    financial = [row for row in complete if all(row.get(key) for key, _ in FINANCIAL)]
    unresolved = sum(row["analysis_status"] == "issuer_mapping_unresolved" for row in review)
    unmatched = sum(row["analysis_status"] == "no_direct_match" for row in review)
    checked = [row for row in events if row.get("confound_status") in
               {"recorded_8k", "no_tagged_8k_found"}]
    clean = [row for row in checked if row["confound_status"] == "no_tagged_8k_found"]
    main_values = [row["car_m1_p1_pp"] for row in events]
    extreme = max(events, key=lambda row: abs(row["car_m1_p1_pp"]))
    report = [
        "# 美國上市公司資安事件與短期股價反應",
        "",
        f"從 University of Maryland Cyber Events Database（UMD）的 {len(originals):,} 筆原始紀錄中，"
        f"目前有 {n} 筆事件（{symbols} 個美股代號）納入三日異常報酬分析。"
        f"股票比對表另有 {unresolved:,} 筆待確認發行公司，以及 {unmatched:,} 筆無直接名稱匹配，"
        "這些紀錄仍可能包含合格事件。",
        "",
        "## RQ1｜資安事件公開前後，平均異常報酬是否為負？",
        "",
        "以整理後的公開報導或公告日作為事件日，休市則順延到下一個 SPY 交易日。"
        "同一股票在同一事件日僅納入一筆。用事件日前第 250 至第 31 個交易日的個股與 SPY 日報酬估計市場模型，"
        "至少需要 120 筆有效配對。累積異常報酬（CAR）加總事件日前一日、當日與後一日的異常報酬。",
        "",
        "主分析採三日 CAR。同表列出三項敏感度檢查，分別檢查事件日順延、單筆極端值和同期申報。",
        "",
        "| 分析 | N | 平均 CAR（百分點） | 左尾 p 值 | 雙尾 p 值 |",
        "|---|---:|---:|---:|---:|",
    ]
    mean_row(report, "主分析 `[-1,+1]`", main_values)
    mean_row(report, "事件日往後一個交易日",
             [row["car_next_session_pp"] for row in events if row["car_next_session_pp"] is not None])
    mean_row(report, f"暫不計入絕對 CAR 最大的事件（{extreme['symbol']}）",
             [row["car_m1_p1_pp"] for row in events if row is not extreme])
    mean_row(report, "已查核且未找到同期指定 8-K", [row["car_m1_p1_pp"] for row in clean])
    report.append("")
    groups, clustered_p = overlap_mean_p(events, day_index)
    if clustered_p is not None:
        report.extend([
            f"依三日視窗重疊情形將事件分成 {groups} 群後，主分析的群聚雙尾 p 值為 **{clustered_p:.4f}**。",
            "",
        ])
    report.extend([
        f"同期 SEC 申報查核涵蓋 {len(checked)} 筆事件，其中 {len(checked) - len(clean)} 筆於三日視窗內"
        "找到含 1.01、2.01、2.02、2.05 或 5.02 項的 8-K 或 8-K/A。"
        "財報、6-K、新聞稿及其他同期消息仍可能影響股價。",
        "",
        "## RQ2｜資安事件的披露特徵與三日異常報酬有何關聯？",
        "",
        "這是探索性分析。以三日 CAR 為依變數，同時納入營運中斷、勒索和資料外洩三項披露。"
        "來源明確披露有發生時編為 1，明確否認或未提及時編為 0。"
        "M1 只納入披露變數。M2 加入事件前估算的對數市值及股價淨值比（P/B）。",
        "",
    ])
    m1 = regression(complete, FEATURES)
    models = [(f"M1 全部已編碼（N={len(complete)}）", m1)]
    if len(complete) != len(financial):
        models.append((f"M1 共同樣本（N={len(financial)}）", regression(financial, FEATURES)))
    m2 = regression(financial, FEATURES + FINANCIAL)
    models.append((f"M2 加入財務控制（N={len(financial)}）", m2))

    report.append("| 變數 | " + " | ".join(title for title, _ in models) + " |")
    report.append("|---|" + "---:|" * len(models))
    for key, label in FEATURES + FINANCIAL:
        cells = []
        for _, estimates in models:
            estimate = estimates.get(key)
            if estimate is None:
                cells.append("—")
            else:
                coefficient, p = estimate
                cells.append(f"{coefficient:.4f}（{p:.4f}）" if p is not None else f"{coefficient:.4f}（—）")
        report.append(f"| {label} | " + " | ".join(cells) + " |")
    report.extend([
        "",
        "各格顯示迴歸係數（以 HC1 標準誤計算的雙尾 p 值）。"
        "披露係數表示其他變數固定時，披露編碼從 0 到 1 對應的 CAR 差異，單位為百分點。",
    ])
    if not all(estimates for _, estimates in models):
        report.extend(["", "樣本不足或解釋變數無法獨立估計的模型以「—」表示。"])
    if m2:
        disclosure_p = [m2[key][1] for key, _ in FEATURES]
        if all(p is not None and p >= .05 for p in disclosure_p):
            report.extend(["", "加入財務控制後，三項披露的個別檢定均未達 5% 顯著水準。"])
        highest_pb = max(financial, key=lambda row: float(row["pb_proxy"]))
        sensitivity = regression([row for row in financial if row is not highest_pb], FEATURES + FINANCIAL)
        if sensitivity and sensitivity["pb_proxy"][1] is not None:
            report.extend([
                "",
                f"暫不計入 P/B 最高的事件（{highest_pb['symbol']}，P/B 為 {float(highest_pb['pb_proxy']):.2f}）後，"
                f"P/B 係數的雙尾 p 值為 {sensitivity['pb_proxy'][1]:.4f}。",
            ])
    legacy = sum(row.get("feature_basis") == "legacy_selected_source" for row in complete)
    umd = sum(row.get("feature_basis") == "umd_summary_explicit_rules" for row in complete)
    counts = "、".join(f"{label} {sum(row[key] == '1' for row in complete)} 筆" for key, label in FEATURES)
    report.extend([
        "",
        "## 解讀限制",
        "",
        f"- 披露為初步編碼，其中 {legacy} 筆沿用個別選定來源，{umd} 筆依 UMD 摘要判讀。"
        f"編為 1 的事件分別為{counts}。UMD 摘要可能納入後續資訊，首次公開內容與盤後發布時點仍待逐筆覆核。",
        f"- 財務欄位齊備的披露樣本為 {len(financial)} 筆，另有 {len(complete) - len(financial)} 筆只納入披露模型。"
        "市值由事件前一交易日的未調整收盤價乘以當時已公開的普通股股數估算，P/B 另使用當時已公開的正股東權益。",
        "- 研究結果適用於目前可比對且有足夠行情的事件。事件時點、樣本篩選及同期公司消息限制因果推論。",
        "",
    ])
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    if export_event_results:
        fields = ("source_slug", "symbol", "t0", "original_reported_date",
                  "estimation_n", "car_m1_p1_pp", "car_next_session_pp")
        with (output / "event_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(events)
    print(f"Analyzed {n} events across {symbols} stock symbols.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-results", action="store_true", help="Also export event-level CAR for auditing.")
    main(export_event_results=parser.parse_args().event_results)
