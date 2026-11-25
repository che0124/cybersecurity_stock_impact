"""Download public point-in-time financial inputs and add them to the event table."""

import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from analyze import DATA, ROOT, read_csv

FIELDS = ("ln_market_cap_proxy", "pb_proxy", "finance_price_date", "finance_close",
          "finance_shares", "finance_shares_asof", "finance_shares_filed",
          "finance_equity", "finance_equity_asof", "finance_equity_filed",
          "finance_sec_url", "finance_price_url", "finance_status")
NEWS_FIELDS = ("confound_status", "confound_dates", "confound_evidence")
CACHE = ROOT / ".cache" / "financial_controls"


def fetch(url, key, agent):
    path = CACHE / (key + ".json")
    if not path.exists():
        with urlopen(Request(url, headers={"User-Agent": agent}), timeout=18) as response:
            body = response.read()
        json.loads(body)
        path.write_bytes(body)
    return json.loads(path.read_bytes())


def latest(document, namespace, tag, unit, cutoff):
    rows = document.get("facts", {}).get(namespace, {}).get(tag, {}).get("units", {}).get(unit, [])
    valid = [row for row in rows if row.get("end") and row.get("filed")
             and row["end"] < cutoff and row["filed"] < cutoff and "start" not in row
             and isinstance(row.get("val"), (int, float))]
    return max(valid, key=lambda row: (row["end"], row["filed"]), default={})


def finance(row, previous, agent):
    from math import log

    values = dict.fromkeys(FIELDS, "")
    if not row["cik"]:
        return {**values, "finance_status": "issuer_cik_missing"}
    cik = str(int(row["cik"])).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    values["finance_sec_url"] = url
    cutoff = row["announcement_date"]
    try:
        document = fetch(url, "sec_" + cik, agent)
        shares = latest(document, "dei", "EntityCommonStockSharesOutstanding", "shares", cutoff)
        equity = latest(document, "us-gaap", "StockholdersEquity", "USD", cutoff)
        for prefix, fact in (("shares", shares), ("equity", equity)):
            if fact:
                values.update({f"finance_{prefix}": fact["val"], f"finance_{prefix}_asof": fact["end"],
                               f"finance_{prefix}_filed": fact["filed"]})
        if shares.get("val", 0) <= 0 or equity.get("val", 0) <= 0:
            return {**values, "finance_status": "missing_or_nonpositive_disclosed_inputs"}
        first = date.fromisoformat(previous)
        start = int(datetime.combine(first, datetime.min.time(), timezone.utc).timestamp())
        end = start + int(timedelta(days=1).total_seconds())
        symbol = row["symbol"]
        chart_url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
                     f"?period1={start}&period2={end}&interval=1d")
        values["finance_price_url"] = chart_url
        chart = fetch(chart_url, f"close_{symbol}_{previous}", "Mozilla/5.0")["chart"]["result"][0]
        meta = chart["meta"]
        if meta["currency"] != "USD" or meta["symbol"] != symbol:
            return {**values, "finance_status": "unexpected_price_currency_or_symbol"}
        quotes = chart["indicators"]["quote"][0]["close"]
        prices = {datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(): value
                  for stamp, value in zip(chart["timestamp"], quotes, strict=True)}
        close = prices.get(previous)
        if close is None or close <= 0:
            return {**values, "finance_status": "previous_close_missing"}
        cap = close * shares["val"]
        return {**values, "finance_price_date": previous, "finance_close": close,
                "ln_market_cap_proxy": log(cap), "pb_proxy": cap / equity["val"],
                "finance_status": "estimated_proxy"}
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        return {**values, "finance_status": "source_unavailable_" + type(error).__name__}


def filing_check(row, window, agent):
    if not row["cik"]:
        return dict(confound_status="issuer_cik_missing", confound_dates="", confound_evidence="")
    cik = str(int(row["cik"])).zfill(10)
    if row.get("confound_status") in {"recorded_8k", "no_tagged_8k_found"}:
        return {field: row[field] for field in NEWS_FIELDS}
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        filings = fetch(url, "submissions_" + cik, agent)["filings"]
        recent = filings["recent"]
        indexes = [recent]
        recent_dates = recent["filingDate"]
        if not recent_dates or min(recent_dates) > window[0]:
            for archive in filings.get("files", []):
                if archive["filingFrom"] <= window[-1] and archive["filingTo"] >= window[0]:
                    name = archive["name"]
                    indexes.append(fetch(
                        f"https://data.sec.gov/submissions/{name}", "archive_" + name, agent,
                    ))
        if not any(day <= window[0] for index in indexes for day in index["filingDate"]):
            # EDGAR's oldest listed filing can postdate the window for a new registrant.
            return dict(confound_status="recent_filing_history_incomplete", confound_dates="",
                        confound_evidence=url)
        hits = set()
        for index in indexes:
            for filing, form, items, accession, document in zip(
                index["filingDate"], index["form"], index["items"], index["accessionNumber"],
                index["primaryDocument"], strict=True
            ):
                if window[0] <= filing <= window[-1] and form in {"8-K", "8-K/A"} and (
                    {"1.01", "2.01", "2.02", "2.05", "5.02"} & {item.strip() for item in items.split(",")}
                ):
                    link = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"
                    hits.add((filing, link))
        return dict(confound_status="recorded_8k" if hits else "no_tagged_8k_found",
                    confound_dates="|".join(sorted({day for day, _ in hits})),
                    confound_evidence="|".join(link for _, link in sorted(hits)) or url)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return dict(confound_status="submissions_unavailable", confound_dates="", confound_evidence=url)


def main():
    from bisect import bisect_left
    from collections import Counter

    CACHE.mkdir(parents=True, exist_ok=True)
    path = DATA / "events.csv"
    events = read_csv(path)
    days = sorted(row["date"] for row in read_csv(DATA / "prices.csv") if row["symbol"] == "SPY")
    agent = os.environ.get("SEC_USER_AGENT", "Academic Cyber Event Study")
    day_index = {day: index for index, day in enumerate(days)}

    def prepare(row):
        if row.get("finance_status") == "estimated_proxy":
            controls = {field: row[field] for field in FIELDS}
        else:
            index = bisect_left(days, row["announcement_date"])
            controls = finance(row, days[index - 1], agent) if index else {
                **dict.fromkeys(FIELDS, ""), "finance_status": "previous_session_missing"
            }
        center = day_index[row["t0"]]
        window = days[max(0, center - 1):center + 2]
        return {**controls, **filing_check(row, window, agent)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        for row, controls in zip(events, pool.map(prepare, events), strict=True):
            row.update(controls)
    staged = path.with_suffix(".csv.tmp")
    with staged.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    staged.replace(path)
    print(dict(Counter(row["finance_status"] for row in events)))


if __name__ == "__main__":
    main()
