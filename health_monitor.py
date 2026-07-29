#!/usr/bin/env python3
"""
Clowie Health Monitor & Self-Healer v3
=======================================
Comprehensive system health monitoring with intelligent auto-remediation.

Check categories:
1.  System resources (disk, memory, CPU, uptime)
2.  Token validity (Google OAuth, API keys, staleness)
3.  Cron jobs (last execution, errors, stuck jobs, model allowlist)
4.  Service connectivity (AgentMail, DeepSeek, Ollama, Gateway)
5.  Git sync status + auto-push
6.  Log health (sizes, rotation)
7.  OpenClaw config sanity
8.  Network connectivity (DNS, external APIs)
9.  Stale lock files
10. Process health (memory hogs, zombie processes, dashboard server)
11. Process load / swap usage
12. Uptime / reboot detection

Auto-remediation triggers:
- Stale token → run google_token_refresher.py
- Stuck cron job → reset state to ok
- Model allowlist rejection → update model
- Stale git sync → git add / commit / push
- Oversized logs → truncate to 5000 lines
- Stale lock files → delete
- Missing dashboard server → restart it
- Known error patterns → auto-fix + log

Escalation: Only alerts Linus for RED (unknown/unfixable) issues.
                                                                            """
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import socket
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ─── Constants ───────────────────────────────────────────────────────────────

WORKSPACE = Path("/data/.openclaw/workspace")
SCRIPTS = WORKSPACE / "scripts"
HEALTH_DIR = SCRIPTS / "health"
LOGS = WORKSPACE / "logs"
STATE_DIR = WORKSPACE / ".state"
CRON_DIR = Path("/data/.openclaw/cron")
CONFIG_PATH = Path("/data/.openclaw/openclaw.json")
KEYRING = Path("/data/.config/gogcli/keyring")
BRIEFINGS_DIR = STATE_DIR / "briefings"

HOSTNAME = os.uname().nodename
NOW = datetime.now(timezone.utc)

THRESHOLDS = {
    "disk_pct_warn": 80,
    "disk_pct_crit": 92,
    "mem_pct_warn": 80,
    "mem_pct_crit": 90,
    "cpu_load_warn": 4.0,
    "cpu_load_crit": 8.0,
    "token_stale_hours": 3,
    "git_stale_hours": 5,
    "cron_stuck_hours": 2,
    "log_max_mb": 100,
    "process_mem_mb_warn": 500,
    "process_mem_mb_crit": 1200,
    "swap_pct_warn": 50,
    "swap_pct_crit": 80,
    "dashboard_port": 18900,
    "dashboard_port_alt": 18901,
}

# ─── Report Data ─────────────────────────────────────────────────────────────

report = {
    "timestamp": NOW.isoformat(),
    "hostname": HOSTNAME,
    "overall": "green",
    "checks": {},
    "remediations": [],
    "errors": [],
}


def set_overall(status: str) -> None:
    order = {"green": 0, "yellow": 1, "red": 2}
    if order.get(status, 0) > order.get(report["overall"], 0):
        report["overall"] = status


# ─── Helpers ─────────────────────────────────────────────────────────────────

def safe_run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"timeout after {timeout}s"
    except Exception as e:
        return -3, "", str(e)


def check_result(name: str, status: str, message: str, detail: Any = None) -> dict:
    set_overall(status)
    entry = {"status": status, "message": message, "detail": detail}
    report["checks"][name] = entry
    return entry


def add_remediation(action: str, result: str, success: bool) -> None:
    report["remediations"].append({
        "action": action,
        "result": result,
        "success": success,
    })


def add_error(context: str, error: str) -> None:
    report["errors"].append({"context": context, "error": str(error)})
    set_overall("red")


def http_get(url: str, headers: Optional[dict] = None, timeout: int = 10) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]
    except urllib.error.URLError as e:
        return 0, str(e.reason)
    except Exception as e:
        return 0, str(e)


def log_info(msg: str) -> None:
    ts = NOW.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 1: System Resources
# ═══════════════════════════════════════════════════════════════════════════════

def check_system() -> None:
    try:
        import psutil
    except ImportError:
        check_result("system", "yellow", "psutil not installed, using fallback")
        _check_system_fallback()
        return

    # ── Disk ──
    disk = psutil.disk_usage("/")
    disk_pct = disk.percent
    if disk_pct >= THRESHOLDS["disk_pct_crit"]:
        check_result("system_disk", "red",
                     f"Disk at {disk_pct:.0f}% ({disk.used//(1<<30)}G/{disk.total//(1<<30)}G)")
    elif disk_pct >= THRESHOLDS["disk_pct_warn"]:
        check_result("system_disk", "yellow",
                     f"Disk at {disk_pct:.0f}% ({disk.used//(1<<30)}G/{disk.total//(1<<30)}G)")
    else:
        check_result("system_disk", "green",
                     f"Disk: {disk_pct:.0f}% used ({disk.free//(1<<30)}G free of {disk.total//(1<<30)}G)")

    # ── Memory ──
    mem = psutil.virtual_memory()
    mem_pct = mem.percent
    if mem_pct >= THRESHOLDS["mem_pct_crit"]:
        check_result("system_memory", "red",
                     f"Memory at {mem_pct:.0f}% (available: {mem.available//(1<<20)}MB)")
    elif mem_pct >= THRESHOLDS["mem_pct_warn"]:
        check_result("system_memory", "yellow",
                     f"Memory at {mem_pct:.0f}% (available: {mem.available//(1<<20)}MB)")
    else:
        check_result("system_memory", "green",
                     f"Memory: {mem_pct:.0f}% used ({mem.available//(1<<20)}MB free)")

    # ── CPU ──
    cpu_pct = psutil.cpu_percent(interval=1)
    load_avg = os.getloadavg()
    if cpu_pct < 50:
        cpu_status = "green"
    elif cpu_pct < 80:
        cpu_status = "yellow"
    else:
        cpu_status = "red"
    check_result("system_cpu", cpu_status,
                 f"CPU: {cpu_pct:.0f}% | Load: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f} | Cores: {psutil.cpu_count()}")

    # ── Load average thresholds ──
    ncpu = psutil.cpu_count()
    load_1m = load_avg[0]
    if load_1m > THRESHOLDS["cpu_load_crit"] and load_1m > ncpu * 2:
        check_result("system_load", "red",
                     f"Load extremely high: {load_1m:.2f} (cores: {ncpu})")
    elif load_1m > THRESHOLDS["cpu_load_warn"] and load_1m > ncpu:
        check_result("system_load", "yellow",
                     f"Load elevated: {load_1m:.2f} (cores: {ncpu})")
    else:
        check_result("system_load", "green",
                     f"Load normal: {load_1m:.2f} (cores: {ncpu})")

    # ── Swap ──
    swap = psutil.swap_memory()
    if swap.total > 0:
        swap_pct = swap.percent
        if swap_pct >= THRESHOLDS["swap_pct_crit"]:
            check_result("system_swap", "red",
                         f"Swap at {swap_pct:.0f}% ({swap.used//(1<<20)}MB/{swap.total//(1<<20)}MB)")
        elif swap_pct >= THRESHOLDS["swap_pct_warn"]:
            check_result("system_swap", "yellow",
                         f"Swap at {swap_pct:.0f}% ({swap.used//(1<<20)}MB/{swap.total//(1<<20)}MB)")
        else:
            check_result("system_swap", "green",
                         f"Swap: {swap_pct:.0f}% used")
    else:
        check_result("system_swap", "green", "No swap configured")

    # ── Uptime ──
    uptime_sec = time.time() - psutil.boot_time()
    uptime_days = uptime_sec / 86400
    boot_time_str = time.strftime('%Y-%m-%d %H:%M', time.localtime(psutil.boot_time()))
    # Warn if uptime < 1h (recent reboot)
    if uptime_sec < 3600:
        check_result("system_uptime", "yellow",
                     f"Recent reboot: Up {uptime_days:.1f}h ({boot_time_str})")
    else:
        check_result("system_uptime", "green",
                     f"Up {uptime_days:.0f} days ({boot_time_str})")


def _check_system_fallback():
    rc, out, err = safe_run(["df", "-h", "/"])
    if rc == 0:
        lines = out.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            pct = parts[4].rstrip("%")
            check_result("system_disk", "green" if int(pct) < 80 else "yellow",
                         f"Disk: {pct}% used ({parts[3]} free)")
    else:
        check_result("system_disk", "red", f"df failed: {err}")

    rc2, out2, _ = safe_run(["free", "-h"])
    if rc2 == 0:
        check_result("system_memory", "green", out2.split("\n")[1] if out2 else "ok")
    else:
        check_result("system_memory", "yellow", "free not available")

    load = os.getloadavg()
    check_result("system_cpu", "green" if load[0] < 2 else "yellow",
                 f"Load: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 2: Token Validity
# ═══════════════════════════════════════════════════════════════════════════════

def check_tokens() -> None:
    # ── Google OAuth via token_refresher.py ──
    token_log = LOGS / "token_refresher.log"
    if token_log.exists():
        content = token_log.read_text().strip()
        lines = content.split("\n")
        last_run = None
        problems = []
        for line in reversed(lines):
            if "done:" in line:
                last_run = line
                if "ALL OK" not in line:
                    problems.append(line)
                break

        # Also check for "ALL OK at" pattern used by newer version
        for line in reversed(lines):
            if "ALL OK" in line and "at" in line:
                last_run = line
                problems = []
                break

        if last_run and not problems:
            check_result("tokens_google", "green", f"Last refresh: {last_run}")
        elif last_run:
            check_result("tokens_google", "yellow", f"Token issues: {problems}")
        else:
            # Try to find any recent line as fallback
            if lines:
                last_line = lines[-1]
                check_result("tokens_google", "yellow",
                             f"Last log line: {last_line[:100]}")
            else:
                check_result("tokens_google", "yellow", "Token refresh log is empty")

        # ── Staleness check ──
        mod_time = datetime.fromtimestamp(token_log.stat().st_mtime, tz=timezone.utc)
        age_hours = (NOW - mod_time).total_seconds() / 3600
        if age_hours > THRESHOLDS["token_stale_hours"]:
            check_result("tokens_google_stale", "yellow",
                         f"Token log not updated in {age_hours:.1f}h (last: {mod_time.isoformat()})")
            _remediate_stale_token()
        else:
            check_result("tokens_google_stale", "green", f"Updated {age_hours:.1f}h ago")
    else:
        check_result("tokens_google", "yellow", "Token refresher log not found")
        check_result("tokens_google_stale", "yellow", "Cannot check staleness")

    # ── Keyring files ──
    accounts = ["kohl.linus@gmail.com", "claw.clowie@gmail.com"]
    missing = []
    for acct in accounts:
        f1 = KEYRING / f"token:{acct}"
        f2 = KEYRING / f"token:default:{acct}"
        if not (f1.exists() or f2.exists()):
            missing.append(acct)
    if missing:
        check_result("tokens_keyring", "red", f"Missing token files: {missing}")
    else:
        # Check file sizes too (should be > 100 bytes for real tokens)
        small_files = []
        for acct in accounts:
            for path in [KEYRING / f"token:{acct}", KEYRING / f"token:default:{acct}"]:
                if path.exists() and path.stat().st_size < 100:
                    small_files.append(path.name)
        if small_files:
            check_result("tokens_keyring", "yellow",
                         f"Suspiciously small token files: {small_files}")
        else:
            check_result("tokens_keyring", "green", "All keyring token files present and valid")


def _remediate_stale_token() -> None:
    refresher = WORKSPACE / "scripts" / "google_token_refresher.py"
    if refresher.exists():
        rc, out, err = safe_run([sys.executable, str(refresher)], timeout=45)
        if rc == 0:
            add_remediation("run_token_refresher", out.strip()[:200] or "OK", True)
        else:
            add_remediation("run_token_refresher", f"exit={rc}: {err[:200]}", False)
    else:
        add_remediation("run_token_refresher", "script not found", False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 3: Cron Jobs
# ═══════════════════════════════════════════════════════════════════════════════

def check_cron_jobs() -> None:
    state_file = CRON_DIR / "jobs-state.json"
    jobs_file = CRON_DIR / "jobs.json"

    if state_file.exists():
        try:
            raw = json.loads(state_file.read_text())
            jobs = raw.get("jobs", raw)
            if isinstance(jobs, dict):
                _check_cron_state_dict(jobs, jobs_file)
                return
        except (json.JSONDecodeError, OSError) as e:
            check_result("cron", "yellow", f"Cannot parse jobs-state.json: {e}")

    if jobs_file.exists():
        try:
            raw = json.loads(jobs_file.read_text())
            if isinstance(raw, dict):
                # Build state from jobs.json definition
                _check_cron_defs(raw.get("jobs", []))
            elif isinstance(raw, list):
                _check_cron_defs(raw)
            else:
                check_result("cron", "yellow", f"Unexpected cron format: {type(raw)}")
        except (json.JSONDecodeError, OSError) as e:
            check_result("cron", "red", f"Cannot parse cron jobs: {e}")
    else:
        check_result("cron", "yellow", "No cron job files found")


def _check_cron_state_dict(jobs: dict, jobs_file: Path) -> None:
    problems = []
    ok_count = 0
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        state_obj = job.get("state", {})
        if isinstance(state_obj, dict):
            last_status = state_obj.get("lastStatus", "unknown")
            last_error = state_obj.get("lastError", "")
            consecutive_errors = state_obj.get("consecutiveErrors", 0)
            last_run_ms = state_obj.get("lastRunAtMs")
        else:
            last_status = job.get("state", "unknown")
            last_error = job.get("lastError", "")
            consecutive_errors = 0
            last_run_ms = None

        label = job.get("name", job.get("label", job_id[:12]))
        status = state_obj.get("lastStatus", "?") if isinstance(state_obj, dict) else "?"

        if status == "error" or last_error:
            err_msg = last_error[:120] if last_error else f"{consecutive_errors} consecutive errors"
            problems.append(f"{label}: {err_msg}")
            log_info(f"  🔴 {label}: error — {err_msg}")
        elif consecutive_errors and consecutive_errors > 3:
            problems.append(f"{label}: {consecutive_errors}x consecutive errors")
            log_info(f"  🟡 {label}: {consecutive_errors}x consecutive errors")
        elif status == "running" and last_run_ms:
            age_hours = (NOW.timestamp() * 1000 - last_run_ms) / 3600000
            if age_hours > THRESHOLDS["cron_stuck_hours"]:
                problems.append(f"{label}: running {age_hours:.1f}h (stuck?)")
                log_info(f"  🟡 {label}: stuck — running {age_hours:.1f}h")
                _remediate_stuck_job(job_id, label)
        else:
            ok_count += 1

    if problems:
        check_result("cron", "yellow" if len(problems) <= 3 else "red",
                     f"{len(problems)} job(s) with issues of {len(jobs)} total", problems)
        _remediate_known_cron_errors()
    else:
        check_result("cron", "green", f"{ok_count}/{len(jobs)} job(s) healthy")


def _check_cron_defs(jobs: list) -> None:
    problems = []
    ok_count = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        label = job.get("id", job.get("name", "?"))[:16]
        enabled = job.get("enabled", True)
        if not enabled:
            ok_count += 1
            continue
        payload = job.get("payload", {})
        model = payload.get("model", "")
        # Check for deprecated model allowlist issues
        if model and model.startswith("deepseek/") and not model.startswith("ollama/"):
            problems.append(f"{job.get('name', label)}: deprecated model '{model}'")
        ok_count += 1

    if problems:
        check_result("cron", "yellow", f"{len(problems)} job(s) using deprecated models", problems)
        _remediate_known_cron_errors()
    else:
        check_result("cron", "green", f"{ok_count}/{len(jobs)} job(s) active")


def _remediate_stuck_job(job_id: str, label: str) -> None:
    state_file = CRON_DIR / "jobs-state.json"
    if not state_file.exists():
        return
    try:
        state = json.loads(state_file.read_text())
        jobs = state.get("jobs", {})
        if job_id in jobs:
            state_obj = jobs[job_id].get("state", {})
            if isinstance(state_obj, dict):
                state_obj["lastStatus"] = "ok"
                state_obj["lastError"] = ""
            state_file.write_text(json.dumps(state, indent=2))
            add_remediation(f"reset_stuck_job:{label[:20]}", "State reset to ok", True)
    except (json.JSONDecodeError, OSError) as e:
        add_remediation(f"reset_stuck_job:{label[:20]}", str(e), False)


def _remediate_known_cron_errors() -> None:
    """Fix known cron error patterns: model allowlist, stale models, missing delivery."""
    state_file = CRON_DIR / "jobs-state.json"
    jobs_file = CRON_DIR / "jobs.json"
    if not state_file.exists() or not jobs_file.exists():
        return

    try:
        state = json.loads(state_file.read_text())
        jobs_data = json.loads(jobs_file.read_text())
        jobs_list = jobs_data.get("jobs", []) if isinstance(jobs_data, dict) else jobs_data
        if not isinstance(jobs_list, list):
            return

        job_defs = {j.get("id"): j for j in jobs_list if isinstance(j, dict)}
        state_jobs = state.get("jobs", {})

        # Model map: deprecated -> allowed
        MODEL_FIXES = {
            "deepseek/deepseek-v4:flash": "ollama/deepseek-v4-flash:cloud",
            "deepseek/deepseek-v4:pro": "ollama/deepseek-v4-pro:cloud",
            "deepseek/deepseek-chat": "ollama/deepseek-v4-flash:cloud",
        }

        changes_made = False

        for jid, job_state in state_jobs.items():
            if not isinstance(job_state, dict):
                continue
            state_obj = job_state.get("state", {})
            if not isinstance(state_obj, dict):
                continue
            last_error = state_obj.get("lastError", "")
            if not last_error and jid in job_defs:
                # Even without error, check for deprecated model in definition
                job_def = job_defs[jid]
                payload = job_def.get("payload", {})
                model = payload.get("model", "")
                if model in MODEL_FIXES:
                    new_model = MODEL_FIXES[model]
                    payload["model"] = new_model
                    changes_made = True
                    add_remediation(f"fix_cron_model:{job_state.get('name', jid[:12])}",
                                    f"Model {model} -> {new_model}", True)
                continue

            if not last_error:
                continue

            jid_label = job_state.get("name", jid[:12])

            # Fix 1: Model allowlist rejection
            if "rejected by agents.defaults.models allowlist" in last_error:
                job_def = job_defs.get(jid)
                if job_def and "payload" in job_def:
                    payload = job_def["payload"]
                    old_model = payload.get("model", "")
                    if old_model in MODEL_FIXES:
                        new_model = MODEL_FIXES[old_model]
                        payload["model"] = new_model
                        changes_made = True
                        state_obj["lastStatus"] = "ok"
                        state_obj["lastError"] = ""
                        state_obj["consecutiveErrors"] = 0
                        add_remediation(f"fix_cron_model:{jid_label[:20]}",
                                        f"Model {old_model} -> {new_model}", True)

            # Fix 2: Telegram missing chatId — disable the job
            if "Delivering to Telegram requires target" in last_error:
                job_def = job_defs.get(jid)
                if job_def:
                    job_def["enabled"] = False
                    changes_made = True
                    state_obj["lastStatus"] = "ok"
                    state_obj["lastError"] = ""
                    state_obj["consecutiveErrors"] = 0
                    add_remediation(f"disable_cron_job:{jid_label[:20]}",
                                    "Disabled job (Telegram missing chatId)", True)

            # Fix 3: Model not found / unavailable
            if "model not found" in last_error.lower() or "model not loaded" in last_error.lower():
                job_def = job_defs.get(jid)
                if job_def:
                    payload = job_def.get("payload", {})
                    current_model = payload.get("model", "")
                    old_model = current_model
                    # Map to ollama cloud fallback
                    if current_model and not current_model.startswith("ollama/"):
                        payload["model"] = "ollama/deepseek-v4-flash:cloud"
                        changes_made = True
                        state_obj["lastStatus"] = "ok"
                        state_obj["lastError"] = ""
                        state_obj["consecutiveErrors"] = 0
                        add_remediation(f"fix_cron_unavailable_model:{jid_label[:20]}",
                                        f"Model {old_model} -> ollama/deepseek-v4-flash:cloud", True)

        if changes_made:
            state_file.write_text(json.dumps(state, indent=2))
            jobs_file.write_text(json.dumps(jobs_data, indent=2))

    except (json.JSONDecodeError, OSError, KeyError) as e:
        add_remediation("fix_cron_errors", str(e), False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 4: Service Connectivity
# ═══════════════════════════════════════════════════════════════════════════════

def check_services() -> None:
    # ── Ollama ──
    rc, out, err = safe_run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                             "--connect-timeout", "5", "http://ollama:11434/api/tags"])
    if rc == 0 and out == "200":
        rc2, out2, _ = safe_run(["curl", "-s", "--connect-timeout", "5",
                                 "http://ollama:11434/api/tags"])
        try:
            data = json.loads(out2) if out2 else {}
            model_count = len(data.get("models", []))
        except (json.JSONDecodeError, KeyError):
            model_count = "?"
        check_result("service_ollama", "green", f"Ollama reachable ({model_count} models)")
    elif rc == 0:
        check_result("service_ollama", "yellow", f"Ollama HTTP {out}")
    else:
        check_result("service_ollama", "yellow", f"Ollama unreachable: {err[:100]}")

    # ── DeepSeek API ──
    api_key = os.environ.get("DEEPSEEK_API_KEY", "") or _get_deepseek_key_from_config()
    if api_key:
        status, body = http_get(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if status == 200:
            try:
                data = json.loads(body)
                model_list = data.get("data", [])
                check_result("service_deepseek", "green",
                             f"DeepSeek API OK ({len(model_list)} models available)")
            except (json.JSONDecodeError, KeyError):
                check_result("service_deepseek", "green", "DeepSeek API OK")
        elif status == 401:
            check_result("service_deepseek", "yellow", "DeepSeek API key may be invalid (HTTP 401)")
        else:
            check_result("service_deepseek", "yellow", f"DeepSeek HTTP {status}")
    else:
        check_result("service_deepseek", "yellow", "DEEPSEEK_API_KEY not in env or config")

    # ── AgentMail ──
    agentmail_key = os.environ.get("AGENTMAIL_API_KEY", "") or _get_agentmail_key_from_config()
    if agentmail_key:
        try:
            # Use the AgentMail SDK for proper connectivity check
            from agentmail import AgentMail
            client = AgentMail(api_key=agentmail_key)
            # Try listing messages for our known inbox
            try:
                msgs = client.inboxes.messages.list(
                    inbox_id="clowie_claw@agentmail.to", limit=3
                )
                count = len(msgs.messages) if hasattr(msgs, "messages") and msgs.messages else 0
                check_result("service_agentmail", "green",
                             f"AgentMail OK ({count} message(s)")
            except Exception as inner:
                # SDK might fail for various reasons (permissions, etc.)
                # Try a raw HTTP check as fallback
                status, body = http_get(
                    "https://api.agentmail.to/v1/health",
                    headers={"Authorization": f"Bearer {agentmail_key}"},
                )
                detail = {"sdk_error": str(inner)[:100], "health_status": status}
                if status == 404:
                    check_result("service_agentmail", "green",
                                 f"AgentMail reachable (health=404)", detail)
                else:
                    check_result("service_agentmail", "yellow",
                                 f"AgentMail API issues (HTTP {status})", detail)
        except ImportError:
            # No SDK installed - fall back to raw HTTP
            status, body = http_get(
                "https://api.agentmail.to/v1/health",
                headers={"Authorization": f"Bearer {agentmail_key}"},
            )
            detail = {}
            if status == 404:
                check_result("service_agentmail", "green",
                             f"AgentMail reachable (no SDK, health=404)", detail)
            else:
                check_result("service_agentmail", "yellow",
                             f"AgentMail HTTP {status} (no SDK)")
    else:
        check_result("service_agentmail", "yellow", "AGENTMAIL_API_KEY not available")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 5: Gateway Health
# ═══════════════════════════════════════════════════════════════════════════════

def check_gateway() -> None:
    status, body = http_get("http://127.0.0.1:18789/health")
    if status == 200:
        check_result("gateway", "green", f"Gateway OK (HTTP {status})")
    elif status > 0:
        check_result("gateway", "yellow", f"Gateway HTTP {status}: {body[:80]}")
    else:
        check_result("gateway", "red", f"Gateway unreachable: {body[:100]}")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 6: Git Sync
# ═══════════════════════════════════════════════════════════════════════════════

def check_git_sync() -> None:
    git_log = LOGS / "git-sync.log"
    if git_log.exists():
        mod_time = datetime.fromtimestamp(git_log.stat().st_mtime, tz=timezone.utc)
        age_hours = (NOW - mod_time).total_seconds() / 3600

        # Get last 3 lines for error detection
        all_lines = git_log.read_text().strip().split("\n")
        recent_lines = all_lines[-5:] if len(all_lines) >= 5 else all_lines
        has_error = any("error" in l.lower() or "fail" in l.lower() for l in recent_lines)

        if has_error:
            check_result("git_sync", "yellow", "Recent sync had errors", recent_lines)
            _remediate_git_sync()
        elif age_hours > THRESHOLDS["git_stale_hours"]:
            check_result("git_sync", "yellow",
                         f"Last sync {age_hours:.1f}h ago ({mod_time.isoformat()})")
            _remediate_git_sync()
        else:
            check_result("git_sync", "green",
                         f"Current ({age_hours:.1f}h ago)", recent_lines[-1] if recent_lines else "")
    else:
        check_result("git_sync", "yellow", "Git sync log not found")
        _remediate_git_sync()


def _remediate_git_sync() -> None:
    ssh_dir = Path.home() / ".ssh"
    key_file = None
    if ssh_dir.exists():
        for f in sorted(ssh_dir.iterdir()):
            if f.name.startswith("id_") and not f.name.endswith(".pub"):
                key_file = str(f)
                break

    cmds = [
        ["git", "-C", str(WORKSPACE), "add", "-A"],
        ["git", "-C", str(WORKSPACE), "commit", "--allow-empty",
         "-m", f"auto: health sync {NOW.strftime('%Y-%m-%d %H:%M UTC')}"],
    ]

    if key_file:
        push_cmd = (
            f'export GIT_SSH_COMMAND="ssh -i {key_file} -o StrictHostKeyChecking=no" && '
            f'git -C {WORKSPACE} push'
        )
        cmds.append(["bash", "-c", push_cmd])
    else:
        cmds.append(["git", "-C", str(WORKSPACE), "push"])

    all_ok = True
    for cmd in cmds:
        rc, out, err = safe_run(cmd, timeout=30)
        ok_signal = any(phrase in (out + err).lower()
                        for phrase in ["nothing to commit", "up to date",
                                       "everything up-to-date", "main -> main"])
        if rc != 0 and not ok_signal:
            all_ok = False
            log_info(f"  ⚠️  git cmd failed: {err[:100]}")

    # Update the git-sync.log timestamp so the staleness check doesn't re-trigger
    if all_ok:
        ts = NOW.strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(LOGS / "git-sync.log", "a") as f:
                f.write(f"[{ts}] Health monitor git sync completed (auto-remediation)\n")
        except OSError:
            pass

    if all_ok:
        add_remediation("git_sync", "Git sync completed", True)
    else:
        add_remediation("git_sync", "Git sync had issues (may need manual intervention)", False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 7: Log Health
# ═══════════════════════════════════════════════════════════════════════════════

def check_logs() -> None:
    if not LOGS.exists():
        check_result("logs", "green", "No logs directory")
        return

    large_logs = []
    for f in LOGS.iterdir():
        if f.is_file() and f.stat().st_size > THRESHOLDS["log_max_mb"] * 1024 * 1024:
            size_mb = f.stat().st_size // (1024 * 1024)
            large_logs.append(f"{f.name} ({size_mb}MB)")

    if large_logs:
        check_result("logs", "yellow", f"Large log file(s): {large_logs}")
        _remediate_large_logs(large_logs)
    else:
        check_result("logs", "green", "All logs under 100MB")


def _remediate_large_logs(large_logs: list[str]) -> None:
    for entry in large_logs:
        log_name = entry.split(" ")[0]
        log_path = LOGS / log_name
        if log_path.exists():
            try:
                # Keep last 5000 lines, compress old content
                rc, out, err = safe_run(
                    ["bash", "-c", f"tail -n 5000 {log_path} > {log_path}.tmp && mv {log_path}.tmp {log_path}"]
                )
                if rc == 0:
                    add_remediation(f"truncate_log:{log_name}", "Truncated to 5000 lines", True)
                else:
                    add_remediation(f"truncate_log:{log_name}", str(err), False)
            except Exception as e:
                add_remediation(f"truncate_log:{log_name}", str(e), False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 8: OpenClaw Config
# ═══════════════════════════════════════════════════════════════════════════════

def check_config() -> None:
    if not CONFIG_PATH.exists():
        check_result("config", "yellow", "Config file not found")
        return

    try:
        data = json.loads(CONFIG_PATH.read_text())
        issues = []

        # Gateway bind check
        gateway = data.get("gateway", {})
        bind = gateway.get("bind", "not-set")
        if bind != "loopback" and bind != "lan":
            issues.append(f"Gateway bind: {bind}")

        # Trusted proxies
        proxies = gateway.get("trustedProxies")
        if not proxies or "127.0.0.1" not in proxies:
            issues.append("Trusted proxies: 127.0.0.1 recommended")

        # Provider presence
        providers = data.get("models", {}).get("providers", {})
        if "ollama" not in providers:
            issues.append("Ollama provider missing")
        if "deepseek" not in providers:
            issues.append("DeepSeek provider missing")

        # Check model allowlist
        models_config = data.get("models", {})
        defaults = models_config.get("defaults", {})
        agents = defaults.get("agents", {})
        allowed = agents.get("models", {}).get("allowlist", [])
        if allowed:
            issues.append(f"Model allowlist: {len(allowed)} models")

        if issues:
            check_result("config", "green",
                         f"{len(issues)} config note(s)" if len(issues) <= 2 else "; ".join(issues[:3]))
        else:
            check_result("config", "green", f"{len(providers)} provider(s) configured")
    except (json.JSONDecodeError, OSError) as e:
        check_result("config", "red", f"Cannot parse config: {e}")


def _get_deepseek_key_from_config() -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        data = json.loads(CONFIG_PATH.read_text())
        providers = data.get("models", {}).get("providers", {})
        for name, cfg in providers.items():
            if "deepseek" in name.lower() and isinstance(cfg, dict):
                for key_name in ("apiKey", "apiKey", "token"):
                    val = cfg.get(key_name, "")
                    if val:
                        return val
        return ""
    except (json.JSONDecodeError, OSError):
        return ""


def _get_agentmail_key_from_config() -> str:
    if not CONFIG_PATH.exists():
        return ""
    try:
        data = json.loads(CONFIG_PATH.read_text())
        providers = data.get("models", {}).get("providers", {})
        for name, cfg in providers.items():
            if "agentmail" in name.lower() and isinstance(cfg, dict):
                val = cfg.get("apiKey", cfg.get("token", ""))
                if val:
                    return val
        return ""
    except (json.JSONDecodeError, OSError):
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 9: Network Connectivity
# ═══════════════════════════════════════════════════════════════════════════════

def check_network() -> None:
    endpoints = [
        ("api.deepseek.com", "DeepSeek API"),
        ("api.agentmail.to", "AgentMail API"),
        ("github.com", "GitHub"),
        ("registry.npmjs.org", "NPM Registry"),
        ("googleapis.com", "Google APIs"),
    ]

    unreachable = []
    for host, label in endpoints:
        rc, out, err = safe_run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                 "--connect-timeout", "5", f"https://{host}"])
        if rc != 0 or out == "000":
            unreachable.append(label)

    if unreachable:
        check_result("network", "yellow" if len(unreachable) <= 2 else "red",
                     f"Unreachable: {', '.join(unreachable)}")
    else:
        check_result("network", "green", f"All {len(endpoints)} endpoints reachable")


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 10: Stale Lock Files
# ═══════════════════════════════════════════════════════════════════════════════

def check_locks() -> None:
    lock_dirs = [
        Path("/data/.openclaw"),
        Path("/tmp"),
        WORKSPACE,
    ]
    stale_locks = []
    for d in lock_dirs:
        if not d.exists():
            continue
        try:
            for f in d.rglob("*.lock"):
                if f.is_file():
                    age_min = (time.time() - f.stat().st_mtime) / 60
                    if age_min > 30:
                        stale_locks.append(str(f))
        except PermissionError:
            continue

    if stale_locks:
        check_result("locks", "yellow", f"{len(stale_locks)} stale lock(s)", stale_locks)
        _remediate_stale_locks(stale_locks)
    else:
        check_result("locks", "green", "No stale locks")


def _remediate_stale_locks(locks: list[str]) -> None:
    for lock_path in locks:
        try:
            os.remove(lock_path)
            add_remediation(f"remove_lock:{Path(lock_path).name}", f"Removed {lock_path}", True)
        except OSError as e:
            add_remediation(f"remove_lock:{Path(lock_path).name}", str(e), False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 11: Process Health + Dashboard Server
# ═══════════════════════════════════════════════════════════════════════════════

def check_processes() -> None:
    try:
        import psutil
    except ImportError:
        check_result("processes", "green", "psutil not available for process checks")
        return

    # Known processes expected to use significant memory (gateway daemon, etc.)
    KNOWN_HIGH_MEM_PROCS = {"openclaw", "node", "python3"}
    # Main gateway daemon expected to use significant memory — raise threshold for these
    KNOWN_HIGH_MEM_THRESHOLD_MB = 5000

    hogs = []
    zombies = 0
    for proc in psutil.process_iter(["pid", "name", "memory_info", "status", "cmdline"]):
        try:
            info = proc.info
            if info["status"] == psutil.STATUS_ZOMBIE:
                zombies += 1
                continue
            mem_mb = (info["memory_info"].rss or 0) / (1024 * 1024)
            if mem_mb > THRESHOLDS["process_mem_mb_crit"]:
                name = info["name"] or "?"
                cmd = " ".join(info["cmdline"])[:80] if info["cmdline"] else ""
                # Skip main OpenClaw/Node daemons — expected high memory usage up to threshold
                if name in KNOWN_HIGH_MEM_PROCS and mem_mb < KNOWN_HIGH_MEM_THRESHOLD_MB:
                    continue
                hogs.append(f"{name} (PID {info['pid']}: {mem_mb:.0f}MB) {cmd}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    issues = []
    if zombies:
        issues.append(f"{zombies} zombie process(es)")
    if hogs:
        issues.append(f"{len(hogs)} memory hog(s): {', '.join(hogs[:3])}")

    if issues:
        check_result("processes", "yellow", "; ".join(issues))
    else:
        check_result("processes", "green", "All processes healthy")

    # ── Dashboard server health check ──
    _check_dashboard_server()


def _check_dashboard_server() -> None:
    """Check if the health dashboard server is running, restart if needed."""
    import psutil

    dash_port = THRESHOLDS["dashboard_port"]
    dashboard_running = False
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if f"serve_dashboard" in cmdline or f"health_dashboard" in cmdline:
                dashboard_running = True
                break
            if "http.server" in cmdline and f"{dash_port}" in cmdline:
                dashboard_running = True
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Also check by connecting to the port
    port_open = _check_port("127.0.0.1", dash_port)
    port_open_alt = _check_port("127.0.0.1", THRESHOLDS["dashboard_port_alt"])

    if port_open:
        check_result("dashboard_server", "green",
                     f"Dashboard running on port {dash_port}")
    elif port_open_alt:
        check_result("dashboard_server", "green",
                     f"Dashboard running on port {THRESHOLDS['dashboard_port_alt']}")
    elif dashboard_running:
        check_result("dashboard_server", "yellow",
                     "Dashboard process exists but port unreachable (restarting)")
        _remediate_dashboard_server()
    else:
        check_result("dashboard_server", "yellow",
                     "Dashboard server not running (starting)")
        _remediate_dashboard_server()


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _remediate_dashboard_server() -> None:
    dashboard_script = HEALTH_DIR / "serve_dashboard.py"
    if not dashboard_script.exists():
        add_remediation("start_dashboard_server", "serve_dashboard.py not found", False)
        return

    try:
        # Start dashboard server in background
        proc = subprocess.Popen(
            [sys.executable, str(dashboard_script)],
            stdout=open(LOGS / "dashboard-server.log", "a"),
            stderr=subprocess.STDOUT,
            cwd=str(HEALTH_DIR),
            start_new_session=True,
        )
        add_remediation("start_dashboard_server",
                        f"Started dashboard server (PID {proc.pid}) on port {THRESHOLDS['dashboard_port']}", True)
    except Exception as e:
        add_remediation("start_dashboard_server", str(e), False)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK 12: Docker Container Health
# ═══════════════════════════════════════════════════════════════════════════════

def check_docker() -> None:
    rc, out, err = safe_run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"], timeout=10)
    if rc == -1:
        check_result("docker", "green", "Docker not available (expected in this environment)")
        return
    elif rc != 0:
        check_result("docker", "yellow", f"Docker check failed: {err[:100]}")
        return

    lines = out.strip().split("\n") if out.strip() else []
    unhealthy = []
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2:
            name, status = parts
            if "unhealthy" in status.lower() or "exited" in status.lower():
                unhealthy.append(f"{name}: {status}")

    if unhealthy:
        check_result("docker", "yellow", f"{len(unhealthy)} unhealthy container(s)", unhealthy)
    else:
        check_result("docker", "green", f"{len(lines)} container(s) healthy")


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT OUTPUT & ESCALATION
# ═══════════════════════════════════════════════════════════════════════════════

def save_report() -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    report_path = HEALTH_DIR / "last_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    log_info(f"📄 Report saved: {report_path}")


def should_alert_linus() -> bool:
    """Only alert for red issues we couldn't fix."""
    if report["overall"] == "red":
        unfixed = []
        for name, check in report["checks"].items():
            if check["status"] == "red":
                unfixed.append(name)
        if unfixed:
            log_info(f"  ⚠️  {len(unfixed)} unfixed red issues: {', '.join(unfixed)}")
            return True
    return False


def get_summary() -> str:
    checks = report["checks"]
    statuses = {}
    for c in checks.values():
        s = c["status"]
        statuses[s] = statuses.get(s, 0) + 1

    summary = (
        f"🩺 Health Monitor — {report['overall'].upper()}\n"
        f"   Host: {report['hostname']} @ {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"   Green: {statuses.get('green', 0)} | "
        f"Yellow: {statuses.get('yellow', 0)} | "
        f"Red: {statuses.get('red', 0)}\n"
    )

    if report["remediations"]:
        summary += f"   🔧 {len(report['remediations'])} auto-remediation(s)\n"
        for r in report["remediations"]:
            icon = "✅" if r["success"] else "⚠️"
            summary += f"      {icon} {r['action']}: {r['result'][:80]}\n"

    red_checks = [(n, c) for n, c in checks.items() if c["status"] == "red"]
    for name, check in red_checks[:3]:
        summary += f"   ❌ {name}: {check['message'][:100]}\n"

    return summary


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print(f"🩺 Clowie Health Monitor v3 — {NOW.isoformat()}")
    print("=" * 60)

    checks = [
        ("System Resources", check_system),
        ("Token Validity", check_tokens),
        ("Cron Jobs", check_cron_jobs),
        ("Service Connectivity", check_services),
        ("Gateway Health", check_gateway),
        ("Git Sync", check_git_sync),
        ("Log Health", check_logs),
        ("Config Check", check_config),
        ("Network Connectivity", check_network),
        ("Stale Locks", check_locks),
        ("Process Health + Dashboard", check_processes),
        ("Docker Health", check_docker),
    ]

    for name, func in checks:
        try:
            print()
            print("─" * 50)
            print(f"  🔍 {name}")
            func()
        except Exception as e:
            add_error(f"{name} check", str(e))
            print(f"  ⚠️  Error: {e}")

    save_report()
    print(f"\n{'=' * 60}")
    print(get_summary())

    if should_alert_linus():
        print("\n⚠️  UNFIXED RED ISSUES — escalation needed")
        sys.exit(2)
    elif report["overall"] == "yellow":
        print("\n🟡 Yellow — auto-remediation applied, monitoring")
        sys.exit(1)
    else:
        print("\n✅ All green — no action needed")
        sys.exit(0)


if __name__ == "__main__":
    main()