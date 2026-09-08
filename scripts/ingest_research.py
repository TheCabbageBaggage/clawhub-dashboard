#!/usr/bin/env python3
"""
Ingest research items from dashboard/data/research_inbox/ into research_catalog.json.

Each inbox file is a JSON with: {title, category, summary, source_url, tags[]}
- Validates required fields
- Generates id (slug from title)
- Adds date (today ISO), type ("MD" or "LINK" based on source_url)
- Skips duplicates (same id)
- Moves processed files to research_inbox/processed/

Usage: python3 scripts/ingest_research.py [--inbox DIR] [--catalog FILE]
"""

import json
import os
import re
import sys
import shutil
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INBOX = REPO_ROOT / "dashboard" / "data" / "research_inbox"
DEFAULT_CATALOG = REPO_ROOT / "dashboard" / "data" / "research_catalog.json"
PROCESSED_DIR = DEFAULT_INBOX / "processed"

REQUIRED_FIELDS = ["title", "category", "summary"]


def slugify(title: str) -> str:
    """Convert title to URL-friendly slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:120]  # cap length


def validate_inbox_file(data: dict, filename: str) -> list:
    """Validate required fields. Returns list of error messages."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in data or not data[field]:
            errors.append(f"Missing required field: {field}")
    if "tags" in data and not isinstance(data["tags"], list):
        errors.append("tags must be a list")
    return errors


def determine_type(source_url: str | None) -> str:
    """Determine type: LINK if source_url is present, else MD."""
    if source_url and source_url.strip():
        return "LINK"
    return "MD"


def load_catalog(catalog_path: Path) -> list:
    """Load existing catalog or return empty list."""
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load catalog ({e}), starting fresh", file=sys.stderr)
    return []


def save_catalog(catalog: list, catalog_path: Path) -> None:
    """Save catalog to file."""
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def process_inbox(inbox_dir: Path, catalog_path: Path) -> tuple[int, int, int]:
    """
    Process all JSON files in inbox_dir.
    Returns (processed, skipped, errors) counts.
    """
    processed_dir = inbox_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    catalog = load_catalog(catalog_path)
    existing_ids = {entry["id"] for entry in catalog if "id" in entry}

    processed = 0
    skipped = 0
    errors = 0

    inbox_files = sorted(inbox_dir.glob("*.json"))
    # Exclude files in processed/ subdirectory (already sorted out by glob on inbox_dir level)

    for filepath in inbox_files:
        if filepath.parent.name == "processed":
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading {filepath.name}: {e}", file=sys.stderr)
            errors += 1
            continue

        # Validate
        validation_errors = validate_inbox_file(data, filepath.name)
        if validation_errors:
            print(f"Validation error in {filepath.name}: {'; '.join(validation_errors)}", file=sys.stderr)
            errors += 1
            continue

        # Generate id and entry
        entry_id = slugify(data["title"])
        if not entry_id:
            print(f"Error: slugified id is empty for {filepath.name}", file=sys.stderr)
            errors += 1
            continue

        # Skip duplicates
        if entry_id in existing_ids:
            print(f"Skipping duplicate: {entry_id} (from {filepath.name})")
            skipped += 1
            # Still move to processed so it doesn't block future runs
            dest = processed_dir / filepath.name
            if not dest.exists():
                shutil.move(str(filepath), str(dest))
            else:
                filepath.unlink(missing_ok=True)
            continue

        # Build catalog entry
        entry = {
            "id": entry_id,
            "title": data["title"],
            "category": data["category"],
            "date": date.today().isoformat(),
            "summary": data["summary"],
            "type": determine_type(data.get("source_url")),
        }
        if data.get("source_url"):
            entry["source_url"] = data["source_url"]
        if data.get("tags"):
            entry["tags"] = data["tags"]

        catalog.append(entry)
        existing_ids.add(entry_id)

        # Move to processed
        dest = processed_dir / filepath.name
        if not dest.exists():
            shutil.move(str(filepath), str(dest))
        else:
            filepath.unlink(missing_ok=True)

        processed += 1

    if processed > 0:
        save_catalog(catalog, catalog_path)

    return processed, skipped, errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ingest research items from inbox into catalog")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX, help="Inbox directory")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Catalog file path")
    args = parser.parse_args()

    inbox_dir = args.inbox
    catalog_path = args.catalog

    if not inbox_dir.exists():
        print(f"Inbox directory does not exist: {inbox_dir}", file=sys.stderr)
        sys.exit(1)

    processed, skipped, errors = process_inbox(inbox_dir, catalog_path)
    print(f"Processed: {processed}, Skipped (duplicates): {skipped}, Errors: {errors}")

    if errors > 0 and processed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()