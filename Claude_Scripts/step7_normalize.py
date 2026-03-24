"""
STEP 7: LLM-powered normalization of name clusters.

For each cluster of variant spellings, asks Claude to:
  1. Suggest a canonical modern English form of the name.
  2. Provide a brief identification (who/what is this?).
  3. Suggest a likely VIAF or ODNB ID where applicable (persons).
  4. Flag cases where it cannot confidently identify the entity.

Outputs:
  • clusters_normalized.json — clusters with canonical_normalized and authority_ref filled
  • authority_list_draft.csv — the final authority list ready for editorial review
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

INPUT_CLUSTERS  = Path("./clusters.json")
OUTPUT_CLUSTERS = Path("./clusters_normalized.json")
OUTPUT_AUTHORITY = Path("./outputs/authority_list_draft.csv")
PROGRESS_FILE   = Path("./norm_progress.json")

MODEL       = "claude-sonnet-4-20250514"
MAX_TOKENS  = 2048
BATCH_SIZE  = 20     # clusters per call
RETRY_LIMIT = 3
RETRY_DELAY = 5

SYSTEM_PROMPT = """You are an expert in medieval and Early Modern British history, with deep knowledge of
Holinshed's Chronicles (1577) and its historical figures and places.

You will receive clusters of variant spellings from a 16th-century index. Each cluster represents
what is likely a single person or place, recorded in Early Modern English orthography.

For each cluster, provide:
1. canonical_normalized: the standard modern English form of the name.
   - For persons: use the most widely accepted modern spelling (e.g. "Athelstan" not "Adelstane").
   - For places: use the modern English name if it still exists, or the accepted historical form.
2. identification: a brief (1 sentence) identification of who/what this is.
3. authority_ref: a VIAF URI for persons (format: "viaf:NNNNNNN"), or Getty TGN for places
   (format: "tgn:NNNNNNN") if you are confident. Leave blank ("") if uncertain.
4. confidence: "high", "medium", or "low" — how confident you are in the identification.

Respond ONLY with a JSON array, one object per cluster, in this exact schema:
[
  {
    "cluster_id": <integer>,
    "canonical_normalized": "Modern Name",
    "identification": "Brief identification sentence.",
    "authority_ref": "viaf:NNNNNNN or tgn:NNNNNNN or empty string",
    "confidence": "high|medium|low"
  },
  ...
]
No prose, no markdown fences."""


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        key_file = Path(__file__).parent / ".anthropic_key"
        if key_file.exists():
            key = key_file.read_text().strip()
    if not key:
        sys.exit("ERROR: Set ANTHROPIC_API_KEY environment variable.")
    return key


def call_api(prompt_text: str) -> str:
    payload = json.dumps({
        "model":      MODEL,
        "max_tokens": MAX_TOKENS,
        "system":     SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": prompt_text}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key":         get_api_key(),
        },
        method="POST"
    )
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body["content"][0]["text"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 529):
                wait = RETRY_DELAY * attempt
                print(f"    ⚠  HTTP {e.code} — waiting {wait}s")
                time.sleep(wait)
            else:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e
        except Exception as exc:
            if attempt == RETRY_LIMIT:
                raise
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Exceeded retry limit")


def parse_response(text: str) -> list[dict]:
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ✗  JSON parse error: {e}\n    Raw: {text[:300]}")
        return []


def build_prompt(batch: list[dict]) -> str:
    lines = []
    for c in batch:
        variants_str = " | ".join(c["variants"])
        lines.append(
            f"cluster_id={c['cluster_id']}  type={c['type']}  "
            f"freq={c['total_frequency']}\n"
            f"  variants: {variants_str}\n"
            f"  provisional: {c['canonical_provisional']}"
        )
    return "\n\n".join(lines)


def load_progress() -> int:
    if Path(PROGRESS_FILE).exists():
        return json.load(open(PROGRESS_FILE)).get("next", 0)
    return 0


def save_progress(n: int):
    json.dump({"next": n}, open(PROGRESS_FILE, "w"))


def write_authority_csv(clusters: list[dict]):
    """Write the authority list CSV from normalized clusters."""
    rows = []
    for c in clusters:
        rows.append({
            "cluster_id":            c["cluster_id"],
            "type":                  c["type"],
            "canonical_normalized":  c.get("canonical_normalized") or c["canonical_provisional"],
            "canonical_provisional": c["canonical_provisional"],
            "variants":              " | ".join(c["variants"]),
            "total_frequency":       c["total_frequency"],
            "sources":               " | ".join(
                                        f"{k}:{v}" for k, v in c.get("sources", {}).items()
                                     ),
            "identification":        c.get("identification", ""),
            "authority_ref":         c.get("authority_ref", ""),
            "confidence":            c.get("confidence", ""),
        })

    # Sort: persons first, then places; within each by frequency desc
    rows.sort(key=lambda r: (0 if r["type"] == "person" else 1, -r["total_frequency"]))

    fieldnames = [
        "cluster_id", "type", "canonical_normalized", "canonical_provisional",
        "variants", "total_frequency", "sources",
        "identification", "authority_ref", "confidence"
    ]
    with open(OUTPUT_AUTHORITY, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    with open(INPUT_CLUSTERS, encoding="utf-8") as f:
        clusters = json.load(f)

    total   = len(clusters)
    start   = load_progress()
    id_to_idx = {c["cluster_id"]: i for i, c in enumerate(clusters)}

    print(f"Holinshed Normalization Pipeline")
    print(f"  Clusters total : {total:,}")
    print(f"  Resuming at    : cluster index {start}")
    print(f"  Batch size     : {BATCH_SIZE}")
    print()

    i = start
    batch_num = 0

    while i < total:
        batch = clusters[i : i + BATCH_SIZE]
        prompt = build_prompt(batch)

        print(f"  Batch {batch_num+1:4d} | clusters {i}–{i+len(batch)-1} ...", end=" ", flush=True)
        t0 = time.time()

        try:
            response_text = call_api(prompt)
            results       = parse_response(response_text)
        except Exception as exc:
            print(f"\n  ✗  Fatal error at cluster {i}: {exc}")
            save_progress(i)
            with open(OUTPUT_CLUSTERS, "w", encoding="utf-8") as f:
                json.dump(clusters, f, ensure_ascii=False, indent=2)
            sys.exit(1)

        matched = 0
        for result in results:
            cid = result.get("cluster_id")
            if cid is not None and cid in id_to_idx:
                idx = id_to_idx[cid]
                clusters[idx]["canonical_normalized"] = result.get("canonical_normalized", "")
                clusters[idx]["identification"]       = result.get("identification", "")
                clusters[idx]["authority_ref"]        = result.get("authority_ref", "")
                clusters[idx]["confidence"]           = result.get("confidence", "")
                matched += 1

        elapsed = time.time() - t0
        print(f"done in {elapsed:.1f}s | {matched}/{len(batch)} matched")

        i += BATCH_SIZE
        batch_num += 1
        save_progress(i)

        with open(OUTPUT_CLUSTERS, "w", encoding="utf-8") as f:
            json.dump(clusters, f, ensure_ascii=False, indent=2)

    print(f"\n✓  Normalization complete → {OUTPUT_CLUSTERS}")

    # Write authority list CSV
    write_authority_csv(clusters)
    print(f"✓  Authority list draft  → {OUTPUT_AUTHORITY}")

    # Summary
    high_conf   = sum(1 for c in clusters if c.get("confidence") == "high")
    med_conf    = sum(1 for c in clusters if c.get("confidence") == "medium")
    has_auth    = sum(1 for c in clusters if c.get("authority_ref"))
    print(f"\nConfidence summary:")
    print(f"  High   : {high_conf:,}")
    print(f"  Medium : {med_conf:,}")
    print(f"  Low    : {total - high_conf - med_conf:,}")
    print(f"  Authority refs assigned: {has_auth:,}")


if __name__ == "__main__":
    main()
