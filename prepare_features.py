"""Record explicit feature evidence from UMD summaries for previously uncoded events."""

import csv
import re

from analyze import DATA, FEATURES, PADDED_RECORD, ROOT, read_csv

PATTERNS = (
    r"(?:operations?|services?|production|network|systems?|website|functionality)\b.{0,45}\b(?:disrupt(?:ed|ion)|shut down|suspend(?:ed)?|offline|unavailable|outage)|\b(?:outage|disruption)\b",
    r"\bransomware (?:attack|incident|activity|infection)\b|\b(?:encrypted|encryption)\b.{0,35}\b(?:systems?|files|servers|applications)\b",
    r"\b(?:exfiltrat\w*|data theft)\b|\b(?:stole|stolen|leaked|exposed|accessed)\b.{0,55}\b(?:data|records|files|information)\b|\b(?:data|records|files|information)\b.{0,45}\b(?:stolen|leaked|exposed|exfiltrated|accessed by unauthorized)\b",
)
NEGATIONS = (
    r"\b(?:operations?|services?|production)\s+(?:continued|remained unaffected|were not affected|were not disrupted)\b|\b(?:reported|confirmed) no (?:operational |service )?disruption\b",
    r"\b(?:not a ransomware (?:attack|incident)|did not involve ransomware|no ransomware was (?:used|involved))\b",
    r"\b(?:no (?:customer |personal |employee )?(?:data|information) (?:was |were )?(?:accessed|stolen|exfiltrated|exposed)|did not (?:access|steal|exfiltrate|expose) (?:any )?(?:data|information))\b",
)
UNCERTAIN = re.compile(
    r"\b(?:claim\w*|alleg\w*|unconfirm\w*|potential\w*|suspect\w*|possibly|may|might|could|"
    r"no evidence|not known|denied|did not|was not|were not|without|"
    r"before .{0,35} (?:is|are|would be) leaked|no operational outage|not operational outage|"
    r"no operational disruption)\b", re.I
)


def description(record, source):
    # The padded export places description immediately before the source URL.
    source_at = record.rfind(source)
    if source_at < 0:
        return ""
    before = record[:source_at]
    split = re.search(r",\s*\"?\s*$", before)
    ends = [match.start() for match in re.finditer(",", before[3290:3318])]
    if not split or not ends:
        return ""
    start = 3290 + min(ends, key=lambda index: abs(index - 11))
    return before[start + 1:split.start()].strip().strip('"').replace('""', '"')


def classify(text, positive, negative):
    hits = {}
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(negative, sentence, re.I):
            hits.setdefault("0", sentence.strip())
        elif re.search(positive, sentence, re.I) and not UNCERTAIN.search(sentence):
            hits.setdefault("1", sentence.strip())
    if "1" in hits:
        return "1", hits["1"]
    return "0", hits.get("0", "")


def main():
    path = DATA / "events.csv"
    events = read_csv(path)
    raw = (ROOT / "cyber_events_2026-11-13.csv").read_text(encoding="utf-8-sig")
    start_pattern = re.compile(PADDED_RECORD.pattern, re.M)
    starts = list(start_pattern.finditer(raw))
    records = {match[1]: raw[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(raw)]
               for i, match in enumerate(starts)}
    for row in events:
        row.setdefault("feature_basis", "legacy_selected_source")
        for key, _ in FEATURES:
            row.setdefault(key + "_evidence", "")
        if row["feature_basis"] == "legacy_selected_source" and any(row[key] for key, _ in FEATURES):
            for key, _ in FEATURES:
                row[key] = row[key] or "0"
            continue
        text = description(records.get(row["source_slug"], ""), row["source_url"])
        row["feature_basis"] = "umd_summary_explicit_rules"
        row["feature_source"] = row["source_url"]
        for (key, _), positive, negative in zip(FEATURES, PATTERNS, NEGATIONS, strict=True):
            row[key], row[key + "_evidence"] = classify(text, positive, negative)
    staged = path.with_suffix(".csv.tmp")
    with staged.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    staged.replace(path)


if __name__ == "__main__":
    main()
