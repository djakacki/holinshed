"""
STEP 4: Build clean, deduplicated NER lists from items_ner.json.
Outputs two CSV files:
  • persons_list.csv  — all unique person name strings + frequency
  • places_list.csv   — all unique place name strings + frequency

Also produces a combined summary report.
"""

import csv
import json
import re
from collections import Counter
from pathlib import Path

INPUT_NER       = Path("./items_ner.json")
OUT_PERSONS_CSV = Path("./outputs/persons_list.csv")
OUT_PLACES_CSV  = Path("./outputs/places_list.csv")
OUT_REPORT      = Path("./outputs/ner_summary_report.txt")

Path("./outputs").mkdir(parents=True, exist_ok=True)


def normalise(name: str) -> str:
    """Light normalisation for deduplication grouping (does not alter output)."""
    return re.sub(r"\s+", " ", name.strip()).lower()


def build_counter(items: list[dict], field: str) -> tuple[Counter, dict]:
    """
    Count raw occurrences of each name.
    Returns (Counter of normalised→count, dict of normalised→canonical form).
    """
    counter  = Counter()
    canon    = {}            # normalised → most-seen surface form
    surf_cnt = Counter()     # normalised + surface → count (to pick canonical)

    for item in items:
        for name in item.get(field, []):
            name = name.strip()
            if not name:
                continue
            norm = normalise(name)
            counter[norm] += 1
            surf_cnt[(norm, name)] += 1

    # Pick canonical surface form (most frequent, then alphabetical)
    for (norm, surface), cnt in surf_cnt.items():
        if norm not in canon or cnt > surf_cnt[(norm, canon[norm])]:
            canon[norm] = surface

    return counter, canon


def write_csv(path: str, counter: Counter, canon: dict, label: str):
    """Write sorted CSV: canonical_name, count, normalised_key."""
    rows = sorted(
        [
            (canon[norm], count, norm)
            for norm, count in counter.items()
        ],
        key=lambda r: (-r[1], r[0])     # sort by count desc, then name asc
    )
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([label, "count", "normalised_key"])
        writer.writerows(rows)
    return rows


def main():
    with open(INPUT_NER, encoding="utf-8") as f:
        items = json.load(f)

    person_counter, person_canon = build_counter(items, "persons")
    place_counter,  place_canon  = build_counter(items, "places")

    person_rows = write_csv(OUT_PERSONS_CSV, person_counter, person_canon, "person_name")
    place_rows  = write_csv(OUT_PLACES_CSV,  place_counter,  place_canon,  "place_name")

    # ── Summary report ────────────────────────────────────────────────────────
    total_items   = len(items)
    items_w_pers  = sum(1 for it in items if it.get("persons"))
    items_w_place = sum(1 for it in items if it.get("places"))
    total_pers_mentions = sum(len(it.get("persons", [])) for it in items)
    total_plc_mentions  = sum(len(it.get("places",  [])) for it in items)

    report_lines = [
        "=" * 60,
        "  Holinshed Chronicles — NER Summary Report",
        "=" * 60,
        "",
        f"Total index items processed : {total_items:,}",
        f"Items with ≥1 person name   : {items_w_pers:,}  ({100*items_w_pers/total_items:.1f}%)",
        f"Items with ≥1 place name    : {items_w_place:,}  ({100*items_w_place/total_items:.1f}%)",
        "",
        f"Total person name mentions  : {total_pers_mentions:,}",
        f"Unique person names         : {len(person_rows):,}",
        "",
        f"Total place name mentions   : {total_plc_mentions:,}",
        f"Unique place names          : {len(place_rows):,}",
        "",
        "-" * 60,
        "  Top 30 Persons by Frequency",
        "-" * 60,
    ]
    for name, count, _ in person_rows[:30]:
        report_lines.append(f"  {count:4d}  {name}")

    report_lines += [
        "",
        "-" * 60,
        "  Top 30 Places by Frequency",
        "-" * 60,
    ]
    for name, count, _ in place_rows[:30]:
        report_lines.append(f"  {count:4d}  {name}")

    report_lines += ["", "=" * 60]
    report_text = "\n".join(report_lines)

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(report_text)
    print(f"\n✓  persons_list.csv  → {OUT_PERSONS_CSV}")
    print(f"✓  places_list.csv   → {OUT_PLACES_CSV}")
    print(f"✓  ner_summary_report.txt → {OUT_REPORT}")


if __name__ == "__main__":
    main()
