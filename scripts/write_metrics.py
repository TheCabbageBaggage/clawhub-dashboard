#!/usr/bin/env python3
"""
Update dashboard/data/metrics.json with live data from system.json and other sources.
Also fills containers.json from docker ps if it's empty/missing.

Usage: python3 scripts/write_metrics.py [--data-dir DIR]
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "dashboard" / "data"


def read_json(path: Path, default=None):
    """Read a JSON file, return default on failure."""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def write_json(path: Path, data):
    """Write data as JSON to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_docker_containers():
    """Try to get container info from docker ps --format json."""
    containers = []
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # docker ps --format json outputs one JSON object per line
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    container = json.loads(line)
                    containers.append({
                        "name": container.get("Names", container.get("name", "unknown")),
                        "image": container.get("Image", container.get("image", "unknown")),
                        "status": container.get("Status", container.get("status", "unknown")),
                        "state": container.get("State", container.get("state", "running")),
                    })
                except json.JSONDecodeError:
                    continue
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return containers


def build_metrics(data_dir: Path) -> dict:
    """Build the metrics.json structure from live data."""
    now = datetime.now(timezone.utc).isoformat()

    # Read live system data
    system = read_json(data_dir / "system.json", {})
    ollama_usage = read_json(data_dir / "ollama-usage.json", {})
    security = read_json(data_dir / "security.json", {})
    storage = read_json(data_dir / "storage.json", {})

    # Build metrics
    metrics = {
        "system": {
            "last_check": now,
            "status": "healthy",
            "uptime_seconds": system.get("uptime_seconds", 0),
            "cpu_load": system.get("cpu_load", 0),
            "memory": system.get("memory", {}),
            "disk": system.get("disk", {}),
        },
        "scraping": {
            "last_success": None,
            "last_attempt": None,
            "articles_scraped": 0,
            "success_rate": 0.0,
            "avg_duration_seconds": 0,
        },
        "newsletters": {
            "daily_ai_tech_news": {
                "last_generated": None,
                "articles": 0,
            },
            "ai_management_bulletin": {
                "last_generated": None,
                "articles": 0,
            },
            "ai_security_update": {
                "last_generated": None,
                "articles": 0,
            },
        },
        "email": {
            "last_sent": None,
            "success_rate": 0.0,
            "total_sent": 0,
        },
        "performance": {
            "avg_scrape_time": 0,
            "avg_generation_time": 0,
            "avg_email_time": 0,
        },
        "ollama_usage": {
            "session": ollama_usage.get("session", {}),
            "weekly": ollama_usage.get("weekly", {}),
            "cost_4weeks": ollama_usage.get("cost_4weeks", 0),
            "models": ollama_usage.get("models", []),
        },
        "security": {
            "open_ports": security.get("open_ports", []),
            "monarx": security.get("monarx", {}),
        },
        "storage": {
            "used_gb": storage.get("used_gb", 0),
            "total_gb": storage.get("total_gb", 0),
            "last_sync": storage.get("last_sync", None),
        },
    }

    return metrics


def fill_containers(data_dir: Path):
    """If containers.json is empty or missing, fill from docker ps."""
    containers_path = data_dir / "containers.json"

    # Check if containers.json exists and has data
    existing = read_json(containers_path, None)
    if existing and isinstance(existing, list) and len(existing) > 0:
        return  # Already has data, don't overwrite

    containers = get_docker_containers()
    if containers:
        write_json(containers_path, containers)
        print(f"Filled containers.json with {len(containers)} containers")
    else:
        # Write empty list so we don't retry every run
        write_json(containers_path, [])
        print("No containers found from docker ps, wrote empty list")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update metrics.json with live data")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Data directory")
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir.exists():
        print(f"Data directory does not exist: {data_dir}", file=sys.stderr)
        sys.exit(1)

    # Build and write metrics.json
    metrics = build_metrics(data_dir)
    write_json(data_dir / "metrics.json", metrics)
    print(f"Updated metrics.json (timestamp: {metrics['system']['last_check']})")

    # Fill containers.json if empty
    fill_containers(data_dir)


if __name__ == "__main__":
    main()