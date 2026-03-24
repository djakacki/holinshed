"""
STEP 3: Write <persName> / <placeName> tags back into the TEI XML.
Reads items_ner.json (output of Step 2) and the original XML,
then produces a fully-tagged TEI file.

Strategy:
  - For each <item>, inject TEI tags by finding each entity string
    within the item's text content using a case-insensitive search.
  - Entities that appear inside <hi> children are handled gracefully.
  - A run-log (step3_log.json) records every substitution for audit.
"""

import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

INPUT_XML   = Path("./Holinshed_vol4_index_ta.xml")
INPUT_NER   = Path("./items_ner.json")
OUTPUT_XML  = Path("./Holinshed_vol4_tagged.xml")
LOG_FILE    = Path("./step3_log.json")

TEI_NS  = "http://www.tei-c.org/ns/1.0"
TEI_PFX = f"{{{TEI_NS}}}"

ET.register_namespace("",    TEI_NS)
ET.register_namespace("tei", TEI_NS)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_full_text(elem) -> str:
    """Flatten all text inside an element (including tails of children)."""
    parts = [elem.text or ""]
    for child in elem:
        parts.append(get_full_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def make_entity_elem(tag: str, name_text: str) -> ET.Element:
    """Create a <persName> or <placeName> element."""
    el = ET.Element(f"{TEI_PFX}{tag}")
    el.text = name_text
    return el


def tag_text_segment(text: str, entities: list[tuple[str, str]]) -> list:
    """
    Given a plain text string and a list of (name, tag) tuples,
    return a list of alternating strings and (name, tag) pairs
    representing the tokenised, entity-annotated text.
    Longest match first to avoid partial overlaps.
    """
    if not text or not entities:
        return [text]

    # Sort longest first to handle overlapping names
    entities_sorted = sorted(entities, key=lambda x: -len(x[0]))

    # Build a regex that matches any of the entity strings (word-boundary aware)
    pattern = "|".join(
        r"(?<!\w)" + re.escape(ent[0]) + r"(?!\w)"
        for ent in entities_sorted
    )
    # Map lowercased name → (original, tag)
    name_map = {ent[0].lower(): ent for ent in entities_sorted}

    result = []
    last = 0
    for m in re.finditer(pattern, text, flags=re.IGNORECASE):
        if m.start() > last:
            result.append(text[last:m.start()])
        matched_lower = m.group(0).lower()
        ent = name_map.get(matched_lower)
        if ent:
            result.append((m.group(0), ent[1]))   # (surface form, tag name)
        last = m.end()
    if last < len(text):
        result.append(text[last:])
    return result


def rebuild_item(item_elem, entities: list[tuple[str, str]], log_entry: dict):
    """
    Replace item_elem's text/children in-place to inject entity tags.
    Works on the simple case (text-only item) and falls back gracefully
    for items with <hi> children by tagging only the .text portion.
    """
    if not entities:
        return

    # Simple case: item has no child elements
    children = list(item_elem)
    if not children:
        raw = item_elem.text or ""
        tokens = tag_text_segment(raw, entities)
        if len(tokens) == 1 and isinstance(tokens[0], str):
            return  # nothing matched

        item_elem.text = ""
        prev_el = None
        for token in tokens:
            if isinstance(token, str):
                if prev_el is None:
                    item_elem.text = (item_elem.text or "") + token
                else:
                    prev_el.tail = (prev_el.tail or "") + token
            else:
                surface, tag = token
                el = make_entity_elem(tag, surface)
                el.tail = ""
                item_elem.append(el)
                log_entry["tagged"].append({"text": surface, "tag": tag})
                prev_el = el
        return

    # Complex case: item has children (e.g. <hi rend="sup">)
    # Tag only item_elem.text (before first child)
    raw = item_elem.text or ""
    tokens = tag_text_segment(raw, entities)
    if len(tokens) > 1 or any(isinstance(t, tuple) for t in tokens):
        item_elem.text = ""
        inserted = []
        for token in tokens:
            if isinstance(token, str):
                inserted.append(token)
            else:
                surface, tag = token
                el = make_entity_elem(tag, surface)
                el.tail = ""
                inserted.append(el)
                log_entry["tagged"].append({"text": surface, "tag": tag})

        # Prepend the new nodes before existing children
        # (ElementTree doesn't support insert-before easily; rebuild child list)
        orig_children = list(item_elem)
        for child in orig_children:
            item_elem.remove(child)

        item_elem.text = ""
        prev = None
        for tok in inserted:
            if isinstance(tok, str):
                if prev is None:
                    item_elem.text = (item_elem.text or "") + tok
                else:
                    prev.tail = (prev.tail or "") + tok
            else:
                item_elem.append(tok)
                prev = tok

        # Re-attach original children after inserted nodes
        if orig_children:
            if prev is None:
                # No entity elements added, just text — first original child follows text
                pass
            else:
                # Attach first original child's leading text to last inserted el tail
                pass
            for child in orig_children:
                item_elem.append(child)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Load NER data
    with open(INPUT_NER, encoding="utf-8") as f:
        ner_items = json.load(f)

    # Build id → ner lookup
    ner_map = {item["id"]: item for item in ner_items}

    # Parse the original XML (preserving namespace)
    ET.register_namespace("",    TEI_NS)
    tree = ET.parse(INPUT_XML)
    root = tree.getroot()

    raw_items  = root.findall(f".//{TEI_PFX}item")
    total      = len(raw_items)
    log        = []

    tagged_items    = 0
    person_tags     = 0
    place_tags      = 0

    for idx, item_elem in enumerate(raw_items):
        ner = ner_map.get(idx, {})
        persons = ner.get("persons", [])
        places  = ner.get("places",  [])

        entities = (
            [(p, "persName") for p in persons if p] +
            [(p, "placeName") for p in places  if p]
        )

        log_entry = {"id": idx, "tagged": []}

        if entities:
            rebuild_item(item_elem, entities, log_entry)
            if log_entry["tagged"]:
                tagged_items += 1
                person_tags  += sum(1 for t in log_entry["tagged"] if t["tag"] == "persName")
                place_tags   += sum(1 for t in log_entry["tagged"] if t["tag"] == "placeName")

        log.append(log_entry)

    # Write output XML
    Path(OUTPUT_XML).parent.mkdir(parents=True, exist_ok=True)

    # Preserve XML declaration and processing instructions by writing manually
    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=False)

    # Re-attach the original prologue (XML decl + processing instructions)
    prologue_lines = []
    with open(INPUT_XML, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("<?xml") or stripped.startswith("<?xml-model") \
               or stripped.startswith("<?xml-stylesheet"):
                prologue_lines.append(line.rstrip())
            elif stripped.startswith("<TEI"):
                break

    with open(OUTPUT_XML, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        for line in prologue_lines[1:]:   # skip the original <?xml ?> — already written
            f.write(line + "\n")
        f.write(xml_str)

    # Save log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"✓  Tagged XML written → {OUTPUT_XML}")
    print(f"\nTagging summary:")
    print(f"  Items processed      : {total}")
    print(f"  Items with tags      : {tagged_items} ({100*tagged_items/total:.1f}%)")
    print(f"  <persName> inserted  : {person_tags}")
    print(f"  <placeName> inserted : {place_tags}")
    print(f"  Audit log            → {LOG_FILE}")

    # Spot-check
    print("\nSpot-check (first 5 tagged items):")
    shown = 0
    for entry in log:
        if entry["tagged"] and shown < 5:
            idx = entry["id"]
            print(f"  [{idx:5d}]  {ner_map[idx]['clean']}")
            for t in entry["tagged"]:
                print(f"           → <{t['tag']}>{t['text']}</{t['tag']}>")
            shown += 1


if __name__ == "__main__":
    main()
