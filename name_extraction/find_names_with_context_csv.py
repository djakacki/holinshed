#!/usr/bin/env python3
"""
Script to find names in TEI XML files, capture surrounding context,
track line numbers, and export to CSV
"""

import csv
import re
from lxml import etree
from typing import List, Tuple


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

        for name, pattern in patterns.items():
            for match in pattern.finditer(paragraph_text):

                start = match.start()
                end = match.end()

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
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in results:
            writer.writerow(row)

    print(f"Results exported to: {output_file}")



def main():
    # Input file
    xml_file = './holinshed_elizabeth_excerpt_analysis_s.xml'
    
    # Names to search for
    names_to_find = ["Elizabeth"]
    
    # Context length (characters on each side)
    context_length = 15
    
    print(f"Searching for names: {', '.join(names_to_find)}")
    print(f"Context length: {context_length} characters on each side\n")
    
    # Find all occurrences
    results = find_names_in_file(xml_file, names_to_find, context_length)
    
    print(f"Found {len(results)} total occurrence(s)\n")
    
    # Show first 10 results as preview
    print("Preview of first 10 results:")
    print("-" * 80)
    for i, result in enumerate(results[:10], 1):
        print(f"{i}. Paragraph {result['paragraph_number']}: '{result['full_context']}'")
    
    if len(results) > 10:
        print(f"\n... and {len(results) - 10} more results")
    
    # Export to CSV
    output_file = 'name_extraction/name_contexts.csv'
    export_to_csv(results, output_file)
    
    # Also create a summary by name
    print("\n" + "=" * 80)
    print("Summary by name:")
    print("=" * 80)
    
    name_counts = {}
    for result in results:
        name = result['name']
        if name not in name_counts:
            name_counts[name] = 0
        name_counts[name] += 1
    
    for name, count in sorted(name_counts.items()):
        print(f"{name}: {count} occurrence(s)")
    
    # Optional: Search for multiple names and export to separate CSV
    print("\n" + "=" * 80)
    print("Searching for multiple names:")
    print("=" * 80 + "\n")
    
    multiple_names = ["Elizabeth", "Marie", "Ireland", "Essex", "Queene"]
    results_multiple = find_names_in_file(xml_file, multiple_names, context_length)
    
    output_file_multiple = 'name_extraction/multiple_names_contexts.csv'
    export_to_csv(results_multiple, output_file_multiple)
    
    # Summary for multiple names
    name_counts_multiple = {}
    for result in results_multiple:
        name = result['name']
        if name not in name_counts_multiple:
            name_counts_multiple[name] = 0
        name_counts_multiple[name] += 1
    
    for name, count in sorted(name_counts_multiple.items()):
        print(f"{name}: {count} occurrence(s)")


if __name__ == "__main__":
    main()
