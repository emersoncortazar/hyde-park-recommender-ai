#!/usr/bin/env python3
"""
Purpose: Query the trained recommender for alternative parts.
Parameters: --brand, --part (required); --top-n, --same-brand (optional)
Output: Formatted table of alternatives with confidence tiers
Exit codes: 0=success, 1=error/not found

Usage examples:
  python scripts/query.py --brand "Humphrey Products" --part "E3P"
  python scripts/query.py --brand Parker --part "P32EA4510AABW" --top-n 5
  python scripts/query.py --search-brand "Humphrey"
  python scripts/query.py --search-parts --brand "Parker" --part "P32"
"""

import argparse
import os
import sys

# Windows terminals default to cp1252 which can't encode emoji — force UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import joblib

from src.recommender import RecommenderResult

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "recommender.joblib",
)

TIER_LABEL = {
    "green":  "🟢 GREEN ",
    "yellow": "🟡 YELLOW",
    "red":    "🔴 RED   ",
}
TIER_PCT = {
    "green":  "High confidence",
    "yellow": "Medium confidence",
    "red":    "Low confidence",
}


def _load_model():
    if not os.path.exists(MODEL_PATH):
        print(
            f"Model not found at {MODEL_PATH}.\n"
            "Run:  python scripts/build_index.py",
            file=sys.stderr,
        )
        sys.exit(1)
    return joblib.load(MODEL_PATH)


def _print_result(result: RecommenderResult):
    print(f"\nQuery  : {result.query_brand}  |  {result.query_part_number}")
    print(f"Category: {result.query_category}")
    if result.query_description:
        print(f"Specs  : {result.query_description[:120]}")
    print()

    if result.error:
        print(f"  ERROR: {result.error}")
        return

    if not result.alternatives:
        print("  No alternatives found above confidence threshold.")
        return

    # Column widths
    col_w = {"tier": 9, "sim": 7, "attr": 5, "brand": 22, "pn": 26, "cat": 30, "desc": 60}

    header = (
        f"{'Tier':<{col_w['tier']}}  "
        f"{'TextSim':>{col_w['sim']}}  "
        f"{'Attrs':>{col_w['attr']}}  "
        f"{'Brand':<{col_w['brand']}}  "
        f"{'Part Number':<{col_w['pn']}}  "
        f"{'Category':<{col_w['cat']}}  "
        f"Description"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for alt in result.alternatives:
        tier_str = TIER_LABEL.get(alt.confidence, alt.confidence)
        sim_str = f"{alt.similarity:.0%}"
        attr_str = str(alt.matched_attrs) if alt.matched_attrs else "-"
        brand_str = alt.brand[:col_w['brand']]
        pn_str = alt.part_number[:col_w['pn']]
        cat_str = alt.category[:col_w['cat']]
        desc_str = alt.description[:col_w['desc']]
        same = " [same brand]" if alt.same_brand else ""

        print(
            f"{tier_str}  "
            f"{sim_str:>{col_w['sim']}}  "
            f"{attr_str:>{col_w['attr']}}  "
            f"{brand_str:<{col_w['brand']}}  "
            f"{pn_str:<{col_w['pn']}}  "
            f"{cat_str:<{col_w['cat']}}  "
            f"{desc_str}{same}"
        )
        # Show matched attributes for green/yellow results
        if alt.matched_attrs >= 2 and alt.shared_attr_list:
            print(f"{'':>{col_w['tier']+2+col_w['sim']+2+col_w['attr']+2}}"
                  f"  ↳ matched: {alt.shared_attr_list}")

    print()
    green_ct = sum(1 for a in result.alternatives if a.confidence == "green")
    yellow_ct = sum(1 for a in result.alternatives if a.confidence == "yellow")
    red_ct = sum(1 for a in result.alternatives if a.confidence == "red")
    print(f"  {len(result.alternatives)} alternatives  "
          f"({green_ct} green / {yellow_ct} yellow / {red_ct} red)")


def main():
    parser = argparse.ArgumentParser(description="Part alternative recommender")
    parser.add_argument("--brand", help="Manufacturer / brand name")
    parser.add_argument("--part", help="Manufacturer part number")
    parser.add_argument("--top-n", type=int, default=10, help="Max results (default 10)")
    parser.add_argument("--same-brand", action="store_true",
                        help="Include same-brand alternatives")
    parser.add_argument("--search-brand", metavar="PARTIAL",
                        help="Fuzzy-search brand names")
    parser.add_argument("--search-parts", action="store_true",
                        help="List part numbers matching --brand and --part as prefix")
    args = parser.parse_args()

    rec = _load_model()
    rec.top_n = args.top_n

    if args.search_brand:
        brands = rec.search_brand(args.search_brand)
        print(f"\nBrands matching '{args.search_brand}':")
        for b in brands:
            print(f"  {b}")
        return

    if args.search_parts:
        if not args.brand or not args.part:
            print("--search-parts requires --brand and --part (as prefix)", file=sys.stderr)
            sys.exit(1)
        rows = rec.search_parts(args.brand, args.part)
        if rows.empty:
            print("No matching parts found.")
        else:
            print(rows.to_string(index=False))
        return

    if not args.brand or not args.part:
        parser.print_help()
        sys.exit(1)

    result = rec.recommend(
        brand=args.brand,
        part_number=args.part,
        include_same_brand=args.same_brand,
    )
    _print_result(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
