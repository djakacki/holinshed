#!/usr/bin/env python3
"""
Script to find names in TEI XML files, capture surrounding context,
track line numbers, and export to CSV
"""

import csv
import re
from typing import List, Tuple


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
    
    # Create regex patterns for each name (case-insensitive)
    patterns = {name: re.compile(re.escape(name), re.IGNORECASE) for name in names}
    
    # Read file line by line
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            # Search for each name in the current line
            for name, pattern in patterns.items():
                for match in pattern.finditer(line):
                    start = match.start()
                    end = match.end()

                    # Define what characters bound the context
                    boundary_chars = set(" \t\n<>.,;:!?()[]{}\"/")

                    # Get left context
                    left_start_temp = max(0, start - context_length) # Add logic to detect xml tags in the context length and move left start to outside of it
                    left_start = left_start_temp

                    for i in range(left_start_temp - 1, -1, -1):
                        ch = line[i]
                        if ch in boundary_chars:
                            # stop at boundary and start right after it
                            left_start = i + 1
                            break

                        left_start = i  # extend one char left each time

                    left_context = line[left_start:start].lstrip()
                    
                    # Get the matched name
                    matched_name = line[start:end]
                    
                    # Get right context
                    right_end_temp = min(len(line), end + context_length)
                    right_end = right_end_temp

                    for i in range(right_end_temp, len(line)):
                        ch = line[i]
                        if ch in boundary_chars:
                            # stop at boundary
                            right_end = i
                            break

                        right_end = i  # extend one char right each time

                    right_context = line[end:right_end].rstrip()
                    
                    # Clean up contexts (remove newlines for display)
                    left_clean = left_context.replace('\n', ' ').replace('\r', '')
                    right_clean = right_context.replace('\n', ' ').replace('\r', '')
                    
                    results.append({
                        'line_number': line_num,
                        'name': matched_name,
                        'left_context': left_clean,
                        'right_context': right_clean,
                        'full_context': left_clean + matched_name + right_clean
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
        print("No results to export!")
        return
    
    fieldnames = ['line_number', 'name', 'left_context', 'right_context', 'full_context']
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"Results exported to: {output_file}")


def main():
    # Input file
    xml_file = './holinshed_elizabeth_excerpt_analysis_s.xml'
    
    # Names to search for
    #names_to_find = ["Elizabeth"]
    
    # Context length (characters on each side)
    context_length = 5
    
    print(f"Searching for names: {', '.join(names_to_find)}")
    print(f"Context length: {context_length} characters on each side\n")
    
    # Find all occurrences
    results = find_names_in_file(xml_file, names_to_find, context_length)
    
    print(f"Found {len(results)} total occurrence(s)\n")
    
    # Show first 10 results as preview
    print("Preview of first 10 results:")
    print("-" * 80)
    for i, result in enumerate(results[:10], 1):
        print(f"{i}. Line {result['line_number']}: '{result['full_context']}'")
    
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
    
    multiple_names = ["Elizabeth", "England", "Ireland", "Essex", "Queene"]
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
