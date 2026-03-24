"""
STEP 2: LLM-powered NER over extracted items.
Sends items to Claude in batches and extracts PERSON / PLACE entities.
Outputs are written back into items_clean.json.

Features:
  • Batches of BATCH_SIZE items per API call  (~340 calls for 10 k items)
  • Incremental save after each batch — safe to resume after interruption
  • Progress bar via tqdm (falls back gracefully if not installed)
  • Dry-run mode to test on a small slice without spending tokens
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
INPUT_FILE    = Path("./items_clean.json")
OUTPUT_FILE   = Path("./items_ner.json")
PROGRESS_FILE = Path("./ner_progress.json")   # tracks last completed batch

MODEL         = "claude-sonnet-4-20250514"
BATCH_SIZE    = 30          # items per API call
MAX_TOKENS    = 2048
RETRY_LIMIT   = 3
RETRY_DELAY   = 5           # seconds between retries

DRY_RUN       = False       # set True to process only first 3 batches
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert in Early Modern English history and Named Entity Recognition.
You will receive a numbered list of index entries from Holinshed's Chronicles (1577).
For each entry, identify all PERSON names and PLACE names present.

IMPORTANT RULES:
- Names may use Early Modern English spelling (e.g. "Adelstane" = Athelstan, "Irelande" = Ireland).
- Return ONLY the name strings as they appear in the source text — do not modernise spelling.
- Titles and roles (King, Archbishop, Lord, Abbot) attached to a name are NOT part of the name itself.
- Do not include generic nouns like "Abbey", "Church", "Citie" unless they are part of a proper name.
- If an entry has no identifiable person or place, return empty arrays.

Respond with a JSON array, one object per entry, in this exact schema:
[
  {
    "id": <integer matching the entry id>,
    "persons": ["Name1", "Name2"],
    "places": ["Place1", "Place2"]
  },
  ...
]
Respond with ONLY the JSON array — no prose, no markdown fences."""


def get_api_key() -> str:
    """Resolve the Anthropic API key from env or a local file."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        key_file = os.path.join(os.path.dirname(__file__), ".anthropic_key")
        if os.path.exists(key_file):
            key = open(key_file).read().strip()
    if not key:
        sys.exit(
            "ERROR: No API key found.\n"
            "  Set ANTHROPIC_API_KEY environment variable, or\n"
            "  create a file called .anthropic_key next to this script."
        )
    return key


def call_api(prompt_text: str) -> str:
    """Call the Anthropic Messages API and return the response text."""
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
            err_body = e.read().decode("utf-8")
            if e.code == 529 or e.code == 429:          # overload / rate-limit
                wait = RETRY_DELAY * attempt
                print(f"    ⚠  HTTP {e.code} — waiting {wait}s (attempt {attempt}/{RETRY_LIMIT})")
                time.sleep(wait)
            else:
                raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
        except Exception as exc:
            if attempt == RETRY_LIMIT:
                raise
            print(f"    ⚠  Error: {exc} — retrying ({attempt}/{RETRY_LIMIT})")
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Exceeded retry limit")


def parse_ner_response(text: str) -> list[dict]:
    """Parse Claude's JSON response, stripping any stray markdown fences."""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ✗  JSON parse error: {e}")
        print(f"       Raw response (first 400 chars): {text[:400]}")
        return []


def build_prompt(batch: list[dict]) -> str:
    lines = []
    for item in batch:
        lines.append(f"[{item['id']}] {item['clean']}")
    return "\n".join(lines)


def load_progress() -> int:
    """Return the index of the first unprocessed item (0 if starting fresh)."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f).get("next_item", 0)
    return 0


def save_progress(next_item: int):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"next_item": next_item}, f)


def main():
    # ── Load items ───────────────────────────────────────────────────────────
    with open(INPUT_FILE, encoding="utf-8") as f:
        items = json.load(f)

    total = len(items)
    start = load_progress()

    if start >= total:
        print("✓  All items already processed. Delete ner_progress.json to rerun.")
        return

    print(f"Holinshed NER Pipeline")
    print(f"  Items total : {total}")
    print(f"  Resuming at : item {start}")
    print(f"  Batch size  : {BATCH_SIZE}")
    batches_remaining = (total - start + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  Batches left: {batches_remaining}")
    if DRY_RUN:
        print("  *** DRY RUN — processing first 3 batches only ***")
    print()

    # ── Build id → list index lookup ─────────────────────────────────────────
    id_to_idx = {item["id"]: i for i, item in enumerate(items)}

    # ── Process batches ───────────────────────────────────────────────────────
    batch_count = 0
    i = start

    while i < total:
        if DRY_RUN and batch_count >= 3:
            print("Dry run complete.")
            break

        batch = items[i : i + BATCH_SIZE]
        prompt = build_prompt(batch)

        print(f"  Batch {batch_count+1:4d} | items {i}–{i+len(batch)-1} ...", end=" ", flush=True)
        t0 = time.time()

        try:
            response_text = call_api(prompt)
            ner_results   = parse_ner_response(response_text)
        except Exception as exc:
            print(f"\n  ✗  Fatal error at item {i}: {exc}")
            print("     Progress saved — re-run the script to resume.")
            save_progress(i)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            sys.exit(1)

        # Merge results back into items list
        matched = 0
        for result in ner_results:
            item_id = result.get("id")
            if item_id is not None and item_id in id_to_idx:
                idx = id_to_idx[item_id]
                items[idx]["persons"] = result.get("persons", [])
                items[idx]["places"]  = result.get("places", [])
                matched += 1

        elapsed = time.time() - t0
        print(f"done in {elapsed:.1f}s | {matched}/{len(batch)} matched")

        i += BATCH_SIZE
        batch_count += 1
        save_progress(i)

        # Save after every batch so progress is never lost
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"\n✓  NER complete. Results saved → {OUTPUT_FILE}")

    # ── Summary stats ─────────────────────────────────────────────────────────
    persons_found = sum(len(it["persons"]) for it in items)
    places_found  = sum(len(it["places"])  for it in items)
    empty         = sum(1 for it in items if not it["persons"] and not it["places"])
    print(f"\nSummary:")
    print(f"  Person mentions : {persons_found}")
    print(f"  Place  mentions : {places_found}")
    print(f"  Items with no entities: {empty} ({100*empty/total:.1f}%)")


if __name__ == "__main__":
    main()
