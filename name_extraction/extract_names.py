#!/usr/bin/env python3
"""
Script to find names in TEI XML files, capture surrounding context,
track line numbers, and export to CSV
"""

import csv
import re
import sys
from lxml import etree
from typing import List, Tuple
from pathlib import Path


def parse_tei(file_path: str) -> etree._ElementTree:
    parser = etree.XMLParser(remove_comments=True, recover=True)
    return etree.parse(file_path, parser)

def flatten_paragraph_with_mapping(p_elem):
    full_text = []
    index_map = []

    for elem in p_elem.iter():
        if elem.text:
            for ch in elem.text:
                full_text.append(ch)
                index_map.append(elem)

        if elem.tail:
            for ch in elem.tail:
                full_text.append(ch)
                index_map.append(elem)

    return "".join(full_text), index_map

def expand_to_word_boundary(text, start, end, context_length):
    left = max(0, start - context_length)
    right = min(len(text), end + context_length)

    while left > 0 and text[left - 1].isalnum():
        left -= 1

    while right < len(text) and text[right].isalnum():
        right += 1

    return left, right

def get_enclosing_semantic_tag(elem):
    while elem is not None:
        tag_name = etree.QName(elem).localname
        if tag_name in {"persName", "placeName", "orgName"}:
            return {
                "tag": tag_name,
                "attributes": dict(elem.attrib)
            }
        elem = elem.getparent()

    return None


TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

def find_names_in_file(file_path: str, names: List[str], context_length: int = 5) -> List[dict]:
    """
    Find all occurrences of names in a file and capture context and line numbers.
    
    Args:
        file_path: Path to the file to search
        names: List of names to search for
        context_length: Number of characters to capture on each side (default: 5)
    
    Returns:
        List of dictionaries with keys: line_number, name, left_context, right_context, full_context
    """
    results = []

    parser = etree.XMLParser(remove_comments=True, recover=True)
    tree = etree.parse(file_path, parser)
    root = tree.getroot()

    patterns = {
        name: re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        for name in names
    }

    # Iterate per paragraph
    for para_index, p in enumerate(root.xpath(".//tei:p", namespaces=TEI_NS), start=1):

        # Extract clean visible text only
        paragraph_text = "".join(p.itertext())

        candidates = []
        for name, pattern in patterns.items():
            for match in pattern.finditer(paragraph_text):
                start = match.start()
                end = match.end()
                candidates.append({
                    "name": match.group(0),
                    "start_offset": start,
                    "end_offset": end,
                    "match_length": end - start,
                })

        # Prefer the longest match at a given location and suppress shorter
        # overlapping matches such as "Henrie" inside "Henrie the eight".
        candidates.sort(key=lambda c: (c["start_offset"], -c["match_length"], c["name"].casefold()))

        accepted = []
        occupied_spans: List[Tuple[int, int]] = []
        for candidate in candidates:
            start = candidate["start_offset"]
            end = candidate["end_offset"]
            overlaps = any(start < span_end and end > span_start for span_start, span_end in occupied_spans)
            if overlaps:
                continue
            occupied_spans.append((start, end))
            accepted.append(candidate)

        accepted.sort(key=lambda c: c["start_offset"])

        for candidate in accepted:
            start = candidate["start_offset"]
            end = candidate["end_offset"]

            left, right = expand_to_word_boundary(
                paragraph_text, start, end, context_length
            )

            left_context = paragraph_text[left:start].strip()
            matched_name = paragraph_text[start:end]
            right_context = paragraph_text[end:right].strip()

            results.append({
                "paragraph_number": para_index,
                "name": matched_name,
                "start_offset": start,
                "end_offset": end,
                "left_context": left_context,
                "right_context": right_context,
                "full_context": f"{left_context} {matched_name} {right_context}".strip()
            })

    return results


def export_to_csv(results: List[dict], output_file: str):
    """
    Export results to a CSV file.
    
    Args:
        results: List of result dictionaries
        output_file: Path to the output CSV file
    """
    if not results:
        print("No results to export.")
        return

    fieldnames = [
        "paragraph_number",
        "name",
        "start_offset",
        "end_offset",
        "left_context",
        "right_context",
        "full_context"
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, lineterminator='\n')
        writer.writeheader()

        for row in results:
            writer.writerow(row)

    print(f"Results exported to: {output_file}")


def load_names_from_csv(csv_path: Path):
    names = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if row:
                names.append(row[0].strip())
    return names


def main(xml_filename: str, names_csv_filename: str):

    # Resolve paths dynamically
    script_dir = Path(__file__).resolve().parent
    xml_dir = script_dir.parent
    xml_path = xml_dir / xml_filename
    names_csv_path = script_dir / names_csv_filename

    if not xml_path.exists():
        print(f"XML file not found: {xml_path}")
        return

    if not names_csv_path.exists():
        print(f"Names CSV not found: {names_csv_path}")
        return

    # Load names
    names_to_find = load_names_from_csv(names_csv_path)

    if not names_to_find:
        print("No names found in CSV.")
        return

    print(f"Searching in: {xml_path.name}")
    print(f"Loaded {len(names_to_find)} names from {names_csv_path.name}\n")

    # Run extraction
    results = find_names_in_file(str(xml_path), names_to_find)

    print(f"Found {len(results)} total occurrence(s)\n")

    # Preview
    print("Preview of first 10 results:")
    print("-" * 80)
    for i, result in enumerate(results[:10], 1):
        print(f"{i}. Paragraph {result['paragraph_number']}: '{result['full_context']}'")

    if len(results) > 10:
        print(f"\n... and {len(results) - 10} more results")

    # Export results
    output_file = script_dir / f"{xml_path.stem}_name_contexts.csv"
    export_to_csv(results, str(output_file))

    # Summary
    print("\n" + "=" * 80)
    print("Summary by name:")
    print("=" * 80)

    name_counts = {}
    for result in results:
        name = result["name"]
        name_counts[name] = name_counts.get(name, 0) + 1

    for name, count in sorted(name_counts.items()):
        print(f"{name}: {count} occurrence(s)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python extract_names.py <xml_filename> <names_csv_filename>")
    else:
        main(sys.argv[1], sys.argv[2])
