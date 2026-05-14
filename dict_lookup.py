#!/usr/bin/env python3
"""
dict_lookup.py  —  Interactive MFA dictionary lookup

Type a word to see its ARPAbet pronunciation(s).
Type 'quit' or press Ctrl+C to exit.

Usage:
    python3 dict_lookup.py
    python3 dict_lookup.py --dict /path/to/english_us_arpa.dict
"""

import argparse
import os
import re
import sys
from collections import defaultdict

DEFAULT_DICT_PATHS = [
    os.path.expanduser("~/Documents/MFA/pretrained_models/dictionary/english_us_arpa.dict"),
    os.path.expanduser("~/.local/share/montreal-forced-aligner/pretrained_models/dictionary/english_us_arpa.dict"),
]


def find_dict() -> str | None:
    for path in DEFAULT_DICT_PATHS:
        if os.path.isfile(path):
            return path
    return None


def load_dictionary(dict_path: str) -> defaultdict:
    """Return {word: [pronunciation, …]} with all variants."""
    entries = defaultdict(list)
    with open(dict_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            word = parts[0].lower()
            # Strip variant suffix e.g. "hello(2)" → "hello"
            word = re.sub(r"\(\d+\)$", "", word)
            pronunciation = " ".join(parts[1:])
            entries[word].append(pronunciation)
    return entries


def main():
    parser = argparse.ArgumentParser(description="Interactive MFA dictionary lookup")
    parser.add_argument("--dict", default=None,
        help="Path to the MFA dictionary file (auto-detected if not given)")
    args = parser.parse_args()

    dict_path = args.dict or find_dict()
    if not dict_path:
        sys.exit(
            "Dictionary not found in default locations.\n"
            "Pass --dict /path/to/english_us_arpa.dict"
        )
    if not os.path.isfile(dict_path):
        sys.exit(f"Dictionary file not found: '{dict_path}'")

    print(f"Loading dictionary from:\n  {dict_path}\n")
    entries = load_dictionary(dict_path)
    print(f"  {len(entries):,} words loaded.\n")
    print("Type a word to look it up. Type 'quit' to exit.\n")

    while True:
        try:
            word = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not word:
            continue
        if word in ("quit", "exit", "q"):
            break

        pronunciations = entries.get(word)
        if pronunciations:
            for p in pronunciations:
                print(f"  {word}  →  {p}")
        else:
            print(f"  '{word}' not found — MFA will assign 'spn' (spoken noise)")


if __name__ == "__main__":
    main()
