"""
STEP 6: Cluster variant spellings of the same name using fuzzy matching.

Uses RapidFuzz to group surface forms that are likely the same name
(e.g. "Adelstane", "Adelstan", "Athelstan" → one cluster).

Strategy:
  1. Group names by first character (reduces comparison space dramatically).
  2. Within each group, use token_sort_ratio + partial_ratio to score similarity.
  3. Build clusters via union-find: any pair scoring ≥ THRESHOLD joins the same cluster.
  4. Within each cluster, pick the most-frequent form as the provisional canonical.

Outputs:
  • clusters.json — each cluster: {cluster_id, type, members[], canonical_provisional}
"""

import json
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz

INPUT_COUNTS   = Path("./corpus_counts.json")
OUTPUT_CLUSTERS = Path("./clusters.json")

# Similarity threshold (0–100). 85 is a good starting point for Early Modern English.
# Lower = more aggressive merging (more false positives).
# Higher = more conservative (more split clusters).
THRESHOLD = 82

# Minimum total frequency for a name to be included (filters out NER noise)
MIN_FREQ = 1


# ── Union-Find ────────────────────────────────────────────────────────────────
class UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self):
        groups = defaultdict(list)
        for k in self.parent:
            groups[self.find(k)].append(k)
        return dict(groups)


def similarity(a: str, b: str) -> float:
    """Combined similarity score weighted toward token sort."""
    return 0.6 * fuzz.token_sort_ratio(a, b) + 0.4 * fuzz.partial_ratio(a, b)


def cluster_names(names: list[str], counts: dict) -> list[list[str]]:
    """Return clusters of name keys."""
    if not names:
        return []

    uf = UnionFind(names)

    # Group by first letter to reduce O(n²) comparisons
    by_first = defaultdict(list)
    for n in names:
        by_first[n[0].lower()].append(n)

    # Also group first-letter variants (e.g. 'i'/'j', 'u'/'v') — common in Early Modern
    EQUIV = {"j": "i", "v": "u", "y": "i"}
    merged_groups = defaultdict(list)
    for letter, group in by_first.items():
        canon_letter = EQUIV.get(letter, letter)
        merged_groups[canon_letter].extend(group)

    comparisons = 0
    merges = 0
    for letter, group in merged_groups.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                score = similarity(a, b)
                comparisons += 1
                if score >= THRESHOLD:
                    uf.union(a, b)
                    merges += 1

    print(f"    Comparisons: {comparisons:,}  |  Merges: {merges:,}")
    return list(uf.groups().values())


def pick_canonical(members: list[str], counts: dict) -> str:
    """Pick the most frequent member as provisional canonical."""
    return max(members, key=lambda m: counts.get(m, {}).get("total", 0))


def main():
    with open(INPUT_COUNTS, encoding="utf-8") as f:
        counts = json.load(f)

    # Split by entity type
    persons = [k for k, v in counts.items() if v["type"] == "person" and v["total"] >= MIN_FREQ]
    places  = [k for k, v in counts.items() if v["type"] == "place"  and v["total"] >= MIN_FREQ]

    print(f"Clustering persons ({len(persons):,} unique forms)...")
    person_clusters_raw = cluster_names(persons, counts)

    print(f"Clustering places  ({len(places):,} unique forms)...")
    place_clusters_raw  = cluster_names(places,  counts)

    clusters_out = []
    cid = 0

    for cluster_type, raw_clusters in [("person", person_clusters_raw), ("place", place_clusters_raw)]:
        for members_keys in raw_clusters:
            # Recover surface forms from keys
            members_surfaces = list({counts[k]["surface"] for k in members_keys if k in counts})
            canonical_key    = pick_canonical(members_keys, counts)
            canonical_surface = counts[canonical_key]["surface"]

            # Collect source files and total frequency
            total_freq = sum(counts[k]["total"] for k in members_keys if k in counts)
            sources    = {}
            for k in members_keys:
                for src, cnt in counts.get(k, {}).get("sources", {}).items():
                    sources[src] = sources.get(src, 0) + cnt

            clusters_out.append({
                "cluster_id":          cid,
                "type":                cluster_type,
                "canonical_provisional": canonical_surface,
                "canonical_normalized":  "",     # filled by Step 7 (LLM)
                "authority_ref":         "",     # filled manually or via Step 7
                "variants":              sorted(members_surfaces),
                "total_frequency":       total_freq,
                "sources":               sources
            })
            cid += 1

    # Sort by frequency descending
    clusters_out.sort(key=lambda c: -c["total_frequency"])

    with open(OUTPUT_CLUSTERS, "w", encoding="utf-8") as f:
        json.dump(clusters_out, f, ensure_ascii=False, indent=2)

    n_persons = sum(1 for c in clusters_out if c["type"] == "person")
    n_places  = sum(1 for c in clusters_out if c["type"] == "place")
    multi_var = sum(1 for c in clusters_out if len(c["variants"]) > 1)

    print(f"\n✓  {len(clusters_out):,} clusters total")
    print(f"   Person clusters : {n_persons:,}")
    print(f"   Place  clusters : {n_places:,}")
    print(f"   Multi-variant   : {multi_var:,} clusters have >1 spelling")
    print(f"   → {OUTPUT_CLUSTERS}")

    # Preview interesting multi-variant clusters
    print("\nSample multi-variant clusters:")
    shown = 0
    for c in clusters_out:
        if len(c["variants"]) > 1 and shown < 8:
            print(f"  [{c['type']:6s}] provisional='{c['canonical_provisional']}'  "
                  f"freq={c['total_frequency']}  variants={c['variants']}")
            shown += 1


if __name__ == "__main__":
    main()
