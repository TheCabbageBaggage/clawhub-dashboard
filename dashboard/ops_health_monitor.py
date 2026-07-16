#!/usr/bin/env python3
"""
Operations Hub Health Monitor
Generates dashboard/data/status.json with live status for all monitored systems.
Run every 5 minutes via cron or systemd timer.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("/data/.openclaw/workspace")
STATUS_FILE = WORKSPACE / "dashboard" / "data" / "status.json"
NOW = datetime.now(timezone.utc)


def file_age_hours(path: Path) -> float | None:
    """Return age of newest file in directory (or single file) in hours, or None if missing."""
    if not path.exists():
        return None
    if path.is_dir():
        files = list(path.glob("*.md")) + list(path.glob("*.json")) + list(path.glob("*.pkl"))
        if not files:
            return None
        newest = max(f.stat().st_mtime for f in files)
    else:
        newest = path.stat().st_mtime
    return (NOW.timestamp() - newest) / 3600


def check_dreaming() -> dict:
    """Check dreaming system: light/, rem/, deep/ last file ages."""
    base = WORKSPACE / "memory" / "dreaming"
    result = {"status": "green", "components": {}}
    for layer in ["light", "rem", "deep"]:
        layer_path = base / layer
        age = file_age_hours(layer_path)
        if age is None:
            result["components"][layer] = {"age_hours": None, "status": "red", "label": "No files"}
            result["status"] = "red"
        elif age > 72:  # >3 days stale
            result["components"][layer] = {"age_hours": round(age, 1), "status": "red", "label": f"Stale ({round(age)}h)"}
            result["status"] = "red"
        elif age > 48:
            result["components"][layer] = {"age_hours": round(age, 1), "status": "yellow", "label": f"Delayed ({round(age)}h)"}
            if result["status"] == "green":
                result["status"] = "yellow"
        else:
            result["components"][layer] = {"age_hours": round(age, 1), "status": "green", "label": f"Fresh ({round(age)}h)"}
    return result


def check_newsletter_vps() -> dict:
    """Check SSH connectivity to newsletter VPS."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes", "ubuntu@158.180.60.61", "echo OK"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and "OK" in r.stdout:
            return {"status": "green", "label": "Reachable", "detail": "SSH OK"}
        else:
            return {"status": "red", "label": "Unreachable", "detail": r.stderr.strip()[:200]}
    except subprocess.TimeoutExpired:
        return {"status": "red", "label": "Timeout", "detail": "SSH timeout after 10s"}
    except Exception as e:
        return {"status": "red", "label": "Error", "detail": str(e)[:200]}


def check_memory_size() -> dict:
    """Check MEMORY.md file size."""
    mem = WORKSPACE / "MEMORY.md"
    if not mem.exists():
        return {"status": "red", "label": "Missing", "size_bytes": 0}
    size = mem.stat().st_size
    if size > 50_000:
        return {"status": "red", "label": f"Too large ({size:,}B)", "size_bytes": size}
    elif size > 30_000:
        return {"status": "yellow", "label": f"Growing ({size:,}B)", "size_bytes": size}
    else:
        return {"status": "green", "label": f"Healthy ({size:,}B)", "size_bytes": size}


def check_learnings() -> dict:
    """Check learnings pipeline."""
    path = WORKSPACE / ".learnings" / "LEARNINGS.md"
    age = file_age_hours(path)
    if age is None:
        return {"status": "red", "label": "Missing", "age_hours": None}
    if age > 168:  # >1 week
        return {"status": "red", "label": f"Stale ({round(age)}h)", "age_hours": round(age, 1)}
    elif age > 72:
        return {"status": "yellow", "label": f"Delayed ({round(age)}h)", "age_hours": round(age, 1)}
    else:
        return {"status": "green", "label": f"Active ({round(age)}h)", "age_hours": round(age, 1)}


def check_ontology() -> dict:
    """Check ontology graph age."""
    path = WORKSPACE / "ontology" / "graph-engine" / "graph.pkl"
    age = file_age_hours(path)
    size = path.stat().st_size if path.exists() else 0
    if age is None:
        return {"status": "red", "label": "Missing", "age_hours": None, "size_bytes": 0}
    if age > 48:
        return {"status": "red", "label": f"Stale ({round(age)}h)", "age_hours": round(age, 1), "size_bytes": size}
    elif age > 24:
        return {"status": "yellow", "label": f"Delayed ({round(age)}h)", "age_hours": round(age, 1), "size_bytes": size}
    else:
        return {"status": "green", "label": f"Fresh ({round(age)}h)", "age_hours": round(age, 1), "size_bytes": size}


def check_health_monitor() -> dict:
    """Check last health monitor run."""
    log = WORKSPACE / "logs" / "health-monitor.log"
    report = WORKSPACE / "scripts" / "health" / "last_report.json"
    age = file_age_hours(report) or file_age_hours(log)
    if age is None:
        return {"status": "red", "label": "No data", "age_hours": None}
    if age > 12:
        return {"status": "red", "label": f"Stale ({round(age)}h)", "age_hours": round(age, 1)}
    elif age > 6:
        return {"status": "yellow", "label": f"Delayed ({round(age)}h)", "age_hours": round(age, 1)}
    else:
        return {"status": "green", "label": f"Recent ({round(age)}h)", "age_hours": round(age, 1)}


def check_morning_briefing() -> dict:
    """Check if morning briefing was sent today."""
    today = NOW.strftime("%Y-%m-%d")
    briefing = WORKSPACE / ".state" / "briefings" / f"{today}-briefing.json"
    if briefing.exists():
        return {"status": "green", "label": "Sent today", "detail": f"Briefing for {today}"}
    # Check if there's a memory file for today (might indicate activity)
    mem_today = WORKSPACE / "memory" / f"{today}.md"
    if mem_today.exists():
        return {"status": "yellow", "label": "Pending?", "detail": "Memory exists but no briefing file"}
    return {"status": "yellow", "label": "Not sent", "detail": "No briefing for today"}


def check_github_sync() -> dict:
    """Check last GitHub commit."""
    try:
        r = subprocess.run(
            ["git", "log", "--format=%H %aI %s", "-1"],
            capture_output=True, text=True, cwd=str(WORKSPACE), timeout=5
        )
        if r.returncode != 0:
            return {"status": "red", "label": "Git error", "detail": r.stderr.strip()[:200]}
        parts = r.stdout.strip().split(" ", 2)
        if len(parts) < 2:
            return {"status": "red", "label": "Parse error", "detail": r.stdout.strip()[:200]}
        commit_hash = parts[0][:8]
        commit_time = datetime.fromisoformat(parts[1])
        age_hours = (NOW - commit_time).total_seconds() / 3600
        msg = parts[2] if len(parts) > 2 else ""
        if age_hours > 24:
            return {"status": "red", "label": f"Stale ({round(age_hours)}h)", "detail": msg[:100], "age_hours": round(age_hours, 1), "commit": commit_hash}
        elif age_hours > 6:
            return {"status": "yellow", "label": f"Delayed ({round(age_hours)}h)", "detail": msg[:100], "age_hours": round(age_hours, 1), "commit": commit_hash}
        else:
            return {"status": "green", "label": f"Recent ({round(age_hours)}h)", "detail": msg[:100], "age_hours": round(age_hours, 1), "commit": commit_hash}
    except Exception as e:
        return {"status": "red", "label": "Error", "detail": str(e)[:200]}


def check_token_refresh() -> dict:
    """Check if OpenClaw gateway is running (proxy for token health)."""
    try:
        r = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            gw = data.get("gateway", {})
            if gw.get("status") == "running" or gw.get("reachable"):
                return {"status": "green", "label": "Gateway active", "detail": "OpenClaw running"}
            return {"status": "yellow", "label": "Gateway issue", "detail": str(gw)[:200]}
        return {"status": "yellow", "label": "Status check failed", "detail": r.stderr.strip()[:200]}
    except Exception as e:
        return {"status": "red", "label": "Error", "detail": str(e)[:200]}


def check_cron_jobs() -> dict:
    """Check if cron jobs are active by reading jobs.json directly."""
    jobs_path = os.path.expanduser("~/.openclaw/cron/jobs.json")
    try:
        if not os.path.exists(jobs_path):
            return {"status": "red", "label": "No jobs file", "detail": "~/.openclaw/cron/jobs.json missing"}
        with open(jobs_path) as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        if not jobs:
            return {"status": "yellow", "label": "No jobs", "detail": "0 jobs configured"}
        active = [j for j in jobs if j.get("enabled", True)]
        disabled = len(jobs) - len(active)
        # Build detail: list active job names
        job_names = [j.get("name", "?")[:40] for j in active]
        detail = ", ".join(job_names[:5]) + ("..." if len(job_names) > 5 else "")
        if disabled == 0:
            return {"status": "green", "label": f"{len(active)} active", "detail": detail}
        else:
            return {"status": "yellow", "label": f"{len(active)}/{len(jobs)} active", "detail": f"{disabled} disabled. {detail}"}
    except Exception as e:
        return {"status": "red", "label": "Read error", "detail": str(e)[:200]}


def compute_overall(checks: dict) -> str:
    """Compute overall system status."""
    statuses = []
    for key, check in checks.items():
        if isinstance(check, dict) and "status" in check:
            statuses.append(check["status"])
        elif isinstance(check, dict) and "components" in check:
            # Dreaming has nested components
            statuses.append(check.get("status", "green"))
    if "red" in statuses:
        return "red"
    if statuses.count("yellow") >= 3:
        return "yellow"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def main():
    checks = {
        "dreaming": check_dreaming(),
        "newsletter_vps": check_newsletter_vps(),
        "memory_size": check_memory_size(),
        "learnings": check_learnings(),
        "ontology": check_ontology(),
        "health_monitor": check_health_monitor(),
        "morning_briefing": check_morning_briefing(),
        "github_sync": check_github_sync(),
        "token_refresh": check_token_refresh(),
        "cron_jobs": check_cron_jobs(),
    }

    overall = compute_overall(checks)

    report = {
        "timestamp": NOW.isoformat(),
        "timestamp_human": NOW.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "overall": overall,
        "checks": checks,
    }

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    print(f"{emoji.get(overall, '⚪')} Status: {overall.upper()} — {NOW.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    for name, check in checks.items():
        s = check.get("status", "?")
        label = check.get("label", "?")
        print(f"  {emoji.get(s, '⚪')} {name}: {label}")
    print(f"\n📄 Saved to {STATUS_FILE}")


if __name__ == "__main__":
    main()
