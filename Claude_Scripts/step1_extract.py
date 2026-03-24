"""
STEP 1: Extract and clean <item> text from Holinshed TEI XML.
Outputs a JSON file with item index, raw XML, and cleaned text.
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

INPUT_FILE  = Path("./Holinshed_vol4_index_ta.xml")
OUTPUT_FILE = Path("./items_clean.json")

TEI_NS = "http://www.tei-c.org/ns/1.0"

# ── Regex to strip trailing page/line references ────────────────────────────
# Matches patterns like:  610.9.  |  pag. 1154. col. 1. line. 2.  |  1725.20.
REF_PATTERN = re.compile(
    r'\s*(?:pag\.\s*)?\d+[\.\,]\d+(?:[\.\,]\d+)*'   # numeric refs
    r'(?:\s*(?:col|line|b|a)\.\s*\d+)*'              # optional col/line labels
    r'[\.\s]*$',
    re.IGNORECASE
)


def get_item_text(elem):
    """Recursively gather text from an element, collapsing <hi> etc."""
    parts = [elem.text or ""]
    for child in elem:
        # Recurse into child (handles <hi rend="sup"> etc.)
        parts.append(get_item_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def clean_text(raw: str) -> str:
    """Normalise whitespace, unescape entities, strip page refs."""
    text = raw.replace("\n", " ").replace("\t", " ")
    text = re.sub(r'\s+', ' ', text).strip()
    text = REF_PATTERN.sub("", text).strip()
    # Remove trailing punctuation left behind
    text = text.rstrip(".,;: ")
    return text


def main():
    tree = ET.parse(str(INPUT_FILE))
    root = tree.getroot()

    items_out = []
    raw_items = root.findall(f".//{{{TEI_NS}}}item")

    for idx, item in enumerate(raw_items):
        raw_xml  = ET.tostring(item, encoding="unicode")
        raw_text = get_item_text(item)
        cleaned  = clean_text(raw_text)

        items_out.append({
            "id":       idx,
            "raw_xml":  raw_xml.strip(),
            "raw_text": raw_text.strip(),
            "clean":    cleaned,
            # Placeholder fields filled by Step 2
            "persons":  [],
            "places":   [],
            "tagged_xml": ""
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(items_out, f, ensure_ascii=False, indent=2)

    print(f"✓  Extracted {len(items_out)} items → {OUTPUT_FILE}")

    # Quick sanity sample
    print("\nSample cleaned items:")
    for item in items_out[48:53]:
        print(f"  [{item['id']:5d}]  {item['clean']}")


if __name__ == "__main__":
    main()
