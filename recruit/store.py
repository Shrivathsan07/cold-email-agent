"""
CSV-backed state. Everything the system remembers lives in data/ as plain CSV
so you can open it in Excel, fix it by hand, and diff it in git.

  jobs.csv          the full listing cache, rebuilt by every sync (gitignored,
                    it is ~900KB and churns daily)
  job_state.csv     the small durable half of the above: when you first saw a
                    listing and what you decided about it. Committed, so the
                    scheduled runs keep their memory.
  applications.csv  the pipeline: what you applied to and where it stands
  contacts.csv      people you want to reach or have reached
  leetcode_log.csv  every attempt, which drives the spaced-repetition schedule
"""

import csv
import json
from datetime import date, datetime

from . import settings

JOB_STATE_FIELDS = ["id", "first_seen", "status", "company", "title", "notes"]

JOB_FIELDS = [
    "id", "company", "company_canonical", "tier", "track", "title", "url",
    "locations", "level", "level_detected", "category", "posted", "first_seen",
    "last_seen", "salary", "sponsorship", "degrees", "faang_flag", "source",
    "source_label", "score", "reasons", "status", "notes",
]
# status values: new | shortlisted | applied | dismissed | expired

APPLICATION_FIELDS = [
    "job_id", "company", "title", "track", "tier", "url", "applied_on",
    "stage", "last_touch", "next_action", "next_action_on", "referral",
    "oa_deadline", "notes",
]
# stage values: applied | oa | phone | onsite | offer | rejected | ghosted | withdrawn

CONTACT_FIELDS = [
    "contact_id", "company", "name", "title", "kind", "linkedin", "email",
    "source", "job_id", "status", "first_contact", "last_contact", "followups",
    "replied", "notes",
]
# kind values: recruiter | hiring_manager | engineer | pm | alum | referral
# status values: to_find | found | queued | reached_out | replied | call | referred | dead

LEETCODE_FIELDS = [
    "date", "slug", "title", "pattern", "difficulty", "rating", "minutes",
    "interval_days", "due_on", "reps", "notes",
]
# rating values: solved | hint | struggled | failed


def _read(path, fields):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for field in fields:
            row.setdefault(field, "")
    return rows


def _write(path, fields, rows):
    settings.ensure_data_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})
    tmp.replace(path)


# ------------------------------------------------------------------- jobs
def load_jobs():
    return _read(settings.JOBS_CSV, JOB_FIELDS)


def save_jobs(rows):
    _write(settings.JOBS_CSV, JOB_FIELDS, rows)


def load_job_state():
    return {r["id"]: r for r in _read(settings.JOB_STATE_CSV, JOB_STATE_FIELDS) if r.get("id")}


def save_job_state(state_by_id):
    rows = sorted(state_by_id.values(), key=lambda r: (r.get("first_seen", ""), r.get("id", "")))
    _write(settings.JOB_STATE_CSV, JOB_STATE_FIELDS, rows)


def upsert_jobs(scored_jobs):
    """Merge a fresh scored pull into jobs.csv.

    Returns (new_rows, updated_rows). A job already marked applied/dismissed
    keeps its status; only its score and last_seen refresh.
    """
    today = date.today().isoformat()
    state = load_job_state()
    rows, new_rows = [], []

    for job in scored_jobs:
        prior = state.get(job["id"])
        row = {f: job.get(f, "") for f in JOB_FIELDS if f in job}
        row["id"] = job["id"]
        row["last_seen"] = today
        if prior is None:
            row["first_seen"] = today
            row["status"] = "new"
            row["notes"] = ""
            new_rows.append(row)
        else:
            row["first_seen"] = prior.get("first_seen") or today
            row["status"] = prior.get("status") or "new"
            row["notes"] = prior.get("notes", "")
        rows.append(row)
        state[job["id"]] = {
            "id": job["id"],
            "first_seen": row["first_seen"],
            "status": row["status"],
            "company": row.get("company_canonical") or row.get("company", ""),
            "title": row.get("title", ""),
            "notes": row["notes"],
        }

    # Anything the boards stopped listing is closed. Keep decisions you made.
    fresh_ids = {j["id"] for j in scored_jobs}
    for job_id, entry in state.items():
        if job_id not in fresh_ids and entry.get("status") in ("new", "shortlisted"):
            entry["status"] = "expired"

    save_jobs(rows)
    save_job_state(state)
    return new_rows, len(rows) - len(new_rows)


def set_job_status(job_id, status, notes=""):
    rows = load_jobs()
    target = None
    for row in rows:
        if row["id"] == job_id or row["id"].startswith(job_id):
            row["status"] = status
            if notes:
                row["notes"] = notes
            target = row
            break
    if target is None:
        return None
    save_jobs(rows)

    state = load_job_state()
    entry = state.setdefault(target["id"], {
        "id": target["id"],
        "first_seen": target.get("first_seen") or date.today().isoformat(),
    })
    entry["status"] = status
    entry["company"] = target.get("company_canonical") or target.get("company", "")
    entry["title"] = target.get("title", "")
    if notes:
        entry["notes"] = notes
    save_job_state(state)
    return target


def find_job(job_id):
    for row in load_jobs():
        if row["id"] == job_id or row["id"].startswith(job_id):
            return row
    return None


# ----------------------------------------------------------- applications
def load_applications():
    return _read(settings.APPLICATIONS_CSV, APPLICATION_FIELDS)


def save_applications(rows):
    _write(settings.APPLICATIONS_CSV, APPLICATION_FIELDS, rows)


def add_application(job, applied_on=None, notes="", referral=""):
    rows = load_applications()
    if any(r["job_id"] == job["id"] for r in rows):
        return None
    applied_on = applied_on or date.today().isoformat()
    row = {
        "job_id": job["id"],
        "company": job.get("company_canonical") or job.get("company", ""),
        "title": job.get("title", ""),
        "track": job.get("track", ""),
        "tier": job.get("tier", ""),
        "url": job.get("url", ""),
        "applied_on": applied_on,
        "stage": "applied",
        "last_touch": applied_on,
        "next_action": "wait",
        "next_action_on": "",
        "referral": referral,
        "oa_deadline": "",
        "notes": notes,
    }
    rows.append(row)
    save_applications(rows)
    return row


def update_application(job_id, **fields):
    rows = load_applications()
    for row in rows:
        if row["job_id"] == job_id or row["job_id"].startswith(job_id):
            row.update({k: v for k, v in fields.items() if v is not None})
            row["last_touch"] = date.today().isoformat()
            save_applications(rows)
            return row
    return None


# --------------------------------------------------------------- contacts
def load_contacts():
    return _read(settings.CONTACTS_CSV, CONTACT_FIELDS)


def save_contacts(rows):
    _write(settings.CONTACTS_CSV, CONTACT_FIELDS, rows)


def add_contact(**fields):
    rows = load_contacts()
    company = fields.get("company", "")
    name = fields.get("name", "")
    for row in rows:
        if row["company"].lower() == company.lower() and row["name"].lower() == name.lower() and name:
            return None
    contact_id = f"c{len(rows) + 1:04d}"
    row = {f: "" for f in CONTACT_FIELDS}
    row.update(fields)
    row["contact_id"] = contact_id
    row.setdefault("status", "found")
    rows.append(row)
    save_contacts(rows)
    return row


def update_contact(contact_id, **fields):
    rows = load_contacts()
    for row in rows:
        if row["contact_id"] == contact_id:
            row.update({k: v for k, v in fields.items() if v is not None})
            save_contacts(rows)
            return row
    return None


# --------------------------------------------------------------- leetcode
def load_leetcode():
    return _read(settings.LEETCODE_CSV, LEETCODE_FIELDS)


def save_leetcode(rows):
    _write(settings.LEETCODE_CSV, LEETCODE_FIELDS, rows)


def append_leetcode(row):
    rows = load_leetcode()
    rows.append(row)
    save_leetcode(rows)
    return row


# ------------------------------------------------------------------ state
def load_state():
    if not settings.STATE_JSON.exists():
        return {}
    try:
        return json.loads(settings.STATE_JSON.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state):
    settings.ensure_data_dir()
    settings.STATE_JSON.write_text(json.dumps(state, indent=1, sort_keys=True))


def days_since(iso_date):
    if not iso_date:
        return None
    try:
        return (date.today() - datetime.fromisoformat(iso_date).date()).days
    except Exception:  # noqa: BLE001
        return None
