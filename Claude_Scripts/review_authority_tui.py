#!/usr/bin/env python3
"""
Terminal reviewer for authority_list_draft.csv variant cleanup.

The canonical name is display-only. Review focuses only on the variants list:
- Up/Down: move between authority rows
- Left/Right: move between variants in the current row
- d/x/Delete: remove selected variant from the working copy
- u: undo last removal
- s: save
- q: quit

The source CSV is never overwritten. The app writes:
- a working CSV with edited variants
- a small JSON state file for resume support
"""

from __future__ import annotations

import argparse
import csv
import curses
import difflib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INPUT = Path(__file__).resolve().parent / "outputs" / "authority_list_draft.csv"
DEFAULT_WORKING = Path(__file__).resolve().parent / "outputs" / "authority_list_working.csv"
DEFAULT_STATE = Path(__file__).resolve().parent / "outputs" / "authority_review_state.json"


@dataclass
class RemovalAction:
    row_index: int
    variant_index: int
    variant_value: str


class AuthorityReviewer:
    def __init__(self, rows: list[dict], fieldnames: list[str], working_path: Path, state_path: Path):
        self.rows = rows
        self.fieldnames = fieldnames
        self.working_path = working_path
        self.state_path = state_path
        self.row_index = 0
        self.variant_index = 0
        self.status = ""
        self.undo_stack: list[RemovalAction] = []
        self.pending_matches: list[tuple[int, str]] = []

    @staticmethod
    def split_variants(raw: str) -> list[str]:
        if not raw:
            return []
        return [part.strip() for part in raw.split("|") if part.strip()]

    @staticmethod
    def join_variants(values: list[str]) -> str:
        return " | ".join(values)

    def variants_for_row(self, idx: int) -> list[str]:
        return self.split_variants(self.rows[idx].get("variants", ""))

    def canonical_for_row(self, idx: int) -> str:
        row = self.rows[idx]
        return (
            row.get("canonical_normalized", "").strip()
            or row.get("canonical_provisional", "").strip()
            or "[no canonical name]"
        )

    def current_variants(self) -> list[str]:
        return self.variants_for_row(self.row_index)

    def clamp_selection(self) -> None:
        if not self.rows:
            self.row_index = 0
            self.variant_index = 0
            return

        self.row_index = max(0, min(self.row_index, len(self.rows) - 1))
        variants = self.current_variants()
        if not variants:
            self.variant_index = 0
        else:
            self.variant_index = max(0, min(self.variant_index, len(variants) - 1))

    def move_row(self, delta: int) -> None:
        self.row_index += delta
        self.clamp_selection()
        self.save_state()

    def move_variant(self, delta: int) -> None:
        variants = self.current_variants()
        if not variants:
            self.variant_index = 0
            return
        self.variant_index = max(0, min(self.variant_index + delta, len(variants) - 1))
        self.save_state()

    def remove_current_variant(self) -> None:
        variants = self.current_variants()
        if not variants:
            self.status = "No variants to remove on this row."
            return

        removed = variants.pop(self.variant_index)
        self.rows[self.row_index]["variants"] = self.join_variants(variants)
        self.undo_stack.append(
            RemovalAction(
                row_index=self.row_index,
                variant_index=self.variant_index,
                variant_value=removed,
            )
        )
        if self.variant_index >= len(variants):
            self.variant_index = max(0, len(variants) - 1)
        self.save_all()
        self.status = f"Removed variant: {removed}"

    def undo(self) -> None:
        if not self.undo_stack:
            self.status = "Nothing to undo."
            return

        action = self.undo_stack.pop()
        variants = self.variants_for_row(action.row_index)
        insert_at = max(0, min(action.variant_index, len(variants)))
        variants.insert(insert_at, action.variant_value)
        self.rows[action.row_index]["variants"] = self.join_variants(variants)
        self.row_index = action.row_index
        self.variant_index = insert_at
        self.save_all()
        self.status = f"Restored variant: {action.variant_value}"

    def save_csv(self) -> None:
        self.working_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.working_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(self.rows)

    def save_state(self) -> None:
        payload = {
            "working_csv": str(self.working_path),
            "current_row_index": self.row_index,
            "current_variant_index": self.variant_index,
        }
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def save_all(self) -> None:
        self.save_csv()
        self.save_state()

    def load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            self.status = "State file unreadable; starting at top."
            return

        self.row_index = int(payload.get("current_row_index", 0))
        self.variant_index = int(payload.get("current_variant_index", 0))
        self.clamp_selection()

    def canonical_index(self) -> dict[str, int]:
        index = {}
        for idx, _row in enumerate(self.rows):
            key = self.canonical_for_row(idx).casefold()
            if key and key not in index:
                index[key] = idx
        return index

    def jump_to_row(self, idx: int) -> None:
        self.row_index = idx
        self.variant_index = 0
        self.clamp_selection()
        self.save_state()

    def search(self, query: str) -> bool:
        query = query.strip()
        if not query:
            self.status = "Search cancelled."
            self.pending_matches = []
            return False

        canonical_map = self.canonical_index()
        exact = canonical_map.get(query.casefold())
        if exact is not None:
            self.jump_to_row(exact)
            self.pending_matches = []
            self.status = f"Jumped to canonical name: {self.canonical_for_row(exact)}"
            return True

        names = [self.canonical_for_row(i) for i in range(len(self.rows))]
        matches = difflib.get_close_matches(query, names, n=5, cutoff=0.6)
        if not matches:
            self.pending_matches = []
            self.status = f"No canonical name match for: {query}"
            return False

        self.pending_matches = []
        used = set()
        for name in matches:
            folded = name.casefold()
            idx = canonical_map.get(folded)
            if idx is not None and idx not in used:
                self.pending_matches.append((idx, name))
                used.add(idx)
        self.status = "No exact match. Choose similar name with 1-5, or Esc to cancel."
        return False

    def choose_pending_match(self, choice: int) -> bool:
        if not self.pending_matches:
            return False
        if choice < 1 or choice > len(self.pending_matches):
            self.status = f"Choose a number between 1 and {len(self.pending_matches)}."
            return True
        idx, name = self.pending_matches[choice - 1]
        self.jump_to_row(idx)
        self.pending_matches = []
        self.status = f"Jumped to similar match: {name}"
        return True

    def clear_pending_matches(self) -> None:
        if self.pending_matches:
            self.pending_matches = []
            self.status = "Cleared suggested matches."


def load_rows(input_path: Path, working_path: Path) -> tuple[list[dict], list[str], Path]:
    source_path = working_path if working_path.exists() else input_path
    with open(source_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if not fieldnames:
        raise ValueError(f"No CSV header found in {source_path}")
    return rows, fieldnames, source_path


def add_line(window, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    if y < 0 or width <= 0:
        return
    clipped = text[: max(0, width - 1)]
    try:
        window.addnstr(y, x, clipped, width - 1, attr)
    except curses.error:
        pass


def wrap_lines(text: str, width: int) -> list[str]:
    if width <= 1:
        return [text[:1]]
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False) or [""]


def wrap_footer_chunks(chunks: list[str], width: int) -> list[str]:
    if width <= 1:
        return chunks[:]

    lines: list[str] = []
    current = ""
    for chunk in chunks:
        if not current:
            current = chunk
            continue
        candidate = f"{current}  {chunk}"
        if len(candidate) <= width - 1:
            current = candidate
        else:
            lines.append(current)
            current = chunk
    if current:
        lines.append(current)
    return lines or [""]


def render(stdscr, reviewer: AuthorityReviewer) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    row = reviewer.rows[reviewer.row_index] if reviewer.rows else {}
    variants = reviewer.current_variants()
    canonical = reviewer.canonical_for_row(reviewer.row_index) if reviewer.rows else "[no rows]"

    title_attr = curses.A_BOLD
    selected_attr = curses.A_REVERSE | curses.A_BOLD

    y = 0
    add_line(stdscr, y, 0, "Holinshed Authority Variant Reviewer", width, title_attr)
    y += 1

    progress = (
        f"Row {reviewer.row_index + 1}/{len(reviewer.rows)}"
        if reviewer.rows
        else "Row 0/0"
    )
    add_line(stdscr, y, 0, f"{progress}   Variants: {len(variants)}", width)
    y += 1

    add_line(stdscr, y, 0, f"Type: {row.get('type', '')}", width)
    y += 1
    add_line(stdscr, y, 0, f"Canonical: {canonical}", width, curses.A_BOLD)
    y += 1
    add_line(stdscr, y, 0, f"Provisional: {row.get('canonical_provisional', '')}", width)
    y += 1
    add_line(stdscr, y, 0, f"Cluster ID: {row.get('cluster_id', '')}   Frequency: {row.get('total_frequency', '')}", width)
    y += 2

    add_line(stdscr, y, 0, "Variants", width, curses.A_UNDERLINE)
    y += 1

    if not variants:
        add_line(stdscr, y, 2, "[no variants remain]", width)
        y += 1
    else:
        for idx, variant in enumerate(variants):
            if y >= height - 6:
                add_line(stdscr, y, 2, "...", width)
                y += 1
                break
            prefix = ">" if idx == reviewer.variant_index else " "
            attr = selected_attr if idx == reviewer.variant_index else 0
            add_line(stdscr, y, 2, f"{prefix} {variant}", width - 2, attr)
            y += 1

    if y < height - 4:
        add_line(stdscr, y, 0, "Confidence", width, curses.A_UNDERLINE)
        y += 1
        confidence = (row.get("confidence", "") or "").strip() or "None"
        add_line(stdscr, y, 0, confidence, width)
        y += 1

    if y < height - 4:
        add_line(stdscr, y, 0, "Identification", width, curses.A_UNDERLINE)
        y += 1
        identification = (row.get("identification", "") or "").strip() or "None"
        for line in wrap_lines(identification, width - 1):
            if y >= height - 3:
                break
            add_line(stdscr, y, 0, line, width)
            y += 1

    if reviewer.pending_matches and y < height - 4:
        add_line(stdscr, y, 0, "Similar Canonical Names", width, curses.A_UNDERLINE)
        y += 1
        for idx, (_row_idx, name) in enumerate(reviewer.pending_matches, start=1):
            if y >= height - 3:
                break
            add_line(stdscr, y, 0, f"{idx}. {name}", width)
            y += 1

    help_chunks = [
        "Up/Down: variants",
        "Left/Right: rows",
        "x/Delete: remove",
        "z: undo",
        "s: save",
        "/: search",
        "g: goto line",
        "Esc/q: quit",
    ]
    status_line = reviewer.status or f"Working copy: {reviewer.working_path.name}"

    help_lines = wrap_footer_chunks(help_chunks, max(1, width - 1))
    footer_rows = min(len(help_lines), 2)
    first_help_y = max(0, height - 1 - footer_rows)

    for offset, line in enumerate(help_lines[-footer_rows:]):
        add_line(stdscr, first_help_y + offset, 0, line, width, curses.A_DIM)

    add_line(stdscr, height - 1, 0, status_line, width, curses.A_REVERSE)
    stdscr.refresh()


def main_loop(stdscr, reviewer: AuthorityReviewer) -> None:
    curses.curs_set(0)
    stdscr.keypad(True)
    stdscr.timeout(100)

    while True:
        reviewer.clamp_selection()
        render(stdscr, reviewer)
        key = stdscr.getch()
        if key == -1:
            continue
        if key == 27:
            if reviewer.pending_matches:
                reviewer.clear_pending_matches()
                continue
            reviewer.save_all()
            reviewer.status = "Saved and quitting."
            break
        if reviewer.pending_matches and ord("1") <= key <= ord("5"):
            if reviewer.choose_pending_match(key - ord("0")):
                continue
        if key in (ord("q"), ord("Q")):
            reviewer.save_all()
            reviewer.status = "Saved and quitting."
            break
        if key in (curses.KEY_UP, ord("k")):
            reviewer.move_variant(-1)
            continue
        if key in (curses.KEY_DOWN, ord("j")):
            reviewer.move_variant(1)
            continue
        if key in (curses.KEY_LEFT, ord("h")):
            reviewer.move_row(-1)
            continue
        if key in (curses.KEY_RIGHT, ord("l")):
            reviewer.move_row(1)
            continue
        if key == curses.KEY_PPAGE:
            reviewer.move_variant(-20)
            continue
        if key == curses.KEY_NPAGE:
            reviewer.move_variant(20)
            continue
        if key in (ord("x"), ord("X"), curses.KEY_DC):
            reviewer.remove_current_variant()
            continue
        if key in (ord("z"), ord("Z")):
            reviewer.undo()
            continue
        if key in (ord("s"), ord("S")):
            reviewer.save_all()
            reviewer.status = f"Saved working copy to {reviewer.working_path.name}"
            continue
        if key == ord("/"):
            reviewer.clear_pending_matches()
            query = prompt_user(stdscr, "Search canonical name: ")
            reviewer.search(query)
            continue
        if key in (ord("g"), ord("G")):
            reviewer.clear_pending_matches()
            query = prompt_user(stdscr, "Go to row number: ")
            goto_row(reviewer, query)
            continue
        reviewer.status = f"Unhandled key: {key}"


def prompt_user(stdscr, prompt: str) -> str:
    height, width = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.timeout(-1)
    stdscr.move(height - 1, 0)
    stdscr.clrtoeol()
    add_line(stdscr, height - 1, 0, prompt, width, curses.A_REVERSE)
    stdscr.refresh()
    try:
        raw = stdscr.getstr(height - 1, min(len(prompt), width - 1), max(1, width - len(prompt) - 1))
        return raw.decode("utf-8").strip()
    except curses.error:
        return ""
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.timeout(100)


def goto_row(reviewer: AuthorityReviewer, query: str) -> None:
    query = query.strip()
    if not query:
        reviewer.status = "Goto cancelled."
        return
    try:
        row_number = int(query)
    except ValueError:
        reviewer.status = f"Invalid row number: {query}"
        return
    if row_number < 1 or row_number > len(reviewer.rows):
        reviewer.status = f"Row must be between 1 and {len(reviewer.rows)}."
        return
    reviewer.jump_to_row(row_number - 1)
    reviewer.status = f"Jumped to row {row_number}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review and remove authority-list variants in a TUI.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Source authority CSV")
    parser.add_argument("--working", type=Path, default=DEFAULT_WORKING, help="Working copy CSV")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="Resume state JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.input.exists() and not args.working.exists():
        raise SystemExit(f"Neither input nor working CSV exists: {args.input}")

    rows, fieldnames, loaded_from = load_rows(args.input, args.working)
    reviewer = AuthorityReviewer(rows, fieldnames, args.working, args.state)
    reviewer.load_state()
    reviewer.status = f"Loaded {len(rows)} rows from {loaded_from.name}"

    if not args.working.exists():
        reviewer.save_all()

    curses.wrapper(main_loop, reviewer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
