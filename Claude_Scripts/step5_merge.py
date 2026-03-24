"""
STEP 5: Merge NER outputs from multiple Holinshed files into a single corpus.

For each input file you ran steps 1–4 on, point this script at its
items_ner.json. It produces:
  • corpus_names.json  — every name mention across all files, with provenance
  • corpus_counts.json — per-name counts split by entity type and source file

Usage:
    Edit NER_FILES below to list all your per-volume NER JSON files,
    giving each a short label (used in the authority list).
"""

import json
from collections import defaultdict
from pathlib import Path

# ── Configure your input files here ──────────────────────────────────────────
NER_FILES = {
    "vol4_index": Path("./items_ner.json"),
    # Add more volumes as you process them, e.g.:
    # "vol1_index": "/path/to/vol1/items_ner.json",
    # "vol2_index": "/path/to/vol2/items_ner.json",
}
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_CORPUS   = Path("./corpus_names.json")
OUTPUT_COUNTS   = Path("./corpus_counts.json")


def main():
    # corpus_names: list of {surface, type, source, item_id, context}
    corpus_names = []

    # counts: {surface_lower: {type, sources: {vol: count}, total}}
    counts = defaultdict(lambda: {
        "surface": "",
        "type": "",
        "sources": defaultdict(int),
        "total": 0
    })

    for vol_label, ner_path in NER_FILES.items():
        if not Path(ner_path).exists():
            print(f"  ⚠  Not found, skipping: {ner_path}")
            continue

        with open(ner_path, encoding="utf-8") as f:
            items = json.load(f)

        vol_persons = 0
        vol_places  = 0

        for item in items:
            context = item.get("clean", "")
            item_id = item.get("id", -1)

            for name in item.get("persons", []):
                name = name.strip()
                if not name:
                    continue
                corpus_names.append({
                    "surface": name,
                    "type":    "person",
                    "source":  vol_label,
                    "item_id": item_id,
                    "context": context
                })
                key = name.lower()
                counts[key]["surface"] = counts[key]["surface"] or name
                counts[key]["type"]    = "person"
                counts[key]["sources"][vol_label] += 1
                counts[key]["total"] += 1
                vol_persons += 1

            for name in item.get("places", []):
                name = name.strip()
                if not name:
                    continue
                corpus_names.append({
                    "surface": name,
                    "type":    "place",
                    "source":  vol_label,
                    "item_id": item_id,
                    "context": context
                })
                key = name.lower()
                counts[key]["surface"] = counts[key]["surface"] or name
                counts[key]["type"]    = "place"
                counts[key]["sources"][vol_label] += 1
                counts[key]["total"] += 1
                vol_places += 1

        print(f"  {vol_label}: {vol_persons} person mentions, {vol_places} place mentions")

    # Convert defaultdicts to plain dicts for JSON serialisation
    counts_out = {}
    for key, val in counts.items():
        counts_out[key] = {
            "surface": val["surface"],
            "type":    val["type"],
            "sources": dict(val["sources"]),
            "total":   val["total"]
        }

    with open(OUTPUT_CORPUS, "w", encoding="utf-8") as f:
        json.dump(corpus_names, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_COUNTS, "w", encoding="utf-8") as f:
        json.dump(counts_out, f, ensure_ascii=False, indent=2)

    print(f"\n✓  {len(corpus_names):,} total name mentions across {len(NER_FILES)} file(s)")
    print(f"   {len(counts_out):,} unique surface forms")
    print(f"   corpus_names.json  → {OUTPUT_CORPUS}")
    print(f"   corpus_counts.json → {OUTPUT_COUNTS}")


if __name__ == "__main__":
    main()
