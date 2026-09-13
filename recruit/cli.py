"""Command line for the recruiting system. Run: python3 -m recruit --help"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta

from . import leetcode, mailer, outreach, report, score, settings, sources, store

OK, WARN, BAD = "\033[32m", "\033[33m", "\033[31m"
DIM, BOLD, END = "\033[2m", "\033[1m", "\033[0m"


def _c(text, color):
    return f"{color}{text}{END}" if sys.stdout.isatty() else str(text)


# ---------------------------------------------------------------------------
def cmd_sync(args):
    print(_c("Pulling job boards...", BOLD))
    jobs = sources.pull_all(level=settings.LEVEL, verbose=True)
    print(f"\n{len(jobs)} unique active listings pulled.")

    ranked = score.rank(jobs)
    print(f"{len(ranked)} match your tracks, level and filters.")

    new_rows, updated = store.upsert_jobs(ranked)
    print(f"\n{_c(str(len(new_rows)) + ' new', OK)} since last sync, {updated} already known.")

    if new_rows:
        new_rows.sort(key=lambda r: -float(r.get("score") or 0))
        print("\nBest of the new ones:")
        for row in new_rows[:10]:
            print(f"  {float(row['score']):>5.0f}  {row.get('company_canonical', ''):<22} {row.get('title', '')[:56]}")

    state = store.load_state()
    state["last_sync"] = datetime.now().isoformat(timespec="seconds")
    state["last_sync_counts"] = {"pulled": len(jobs), "eligible": len(ranked), "new": len(new_rows)}
    store.save_state(state)
    return 0


def cmd_report(args):
    digest = report.build()
    text = report.render_text(digest)

    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(report.render_html(digest))
        print(f"Wrote {args.html}")

    if args.email:
        if not mailer.configured():
            print(_c("Email not configured. Printing instead.", WARN), file=sys.stderr)
            print(text)
            return 1
        to = mailer.send(report.subject(digest), text, report.render_html(digest))
        print(f"Sent to {to}")
        return 0

    print(text)
    return 0


def cmd_list(args):
    rows = [r for r in store.load_jobs() if r.get("status") in ("new", "shortlisted")]
    if args.track:
        rows = [r for r in rows if r.get("track") == args.track]
    if args.tier:
        rows = [r for r in rows if r.get("tier") == args.tier]
    if args.company:
        needle = args.company.lower()
        rows = [r for r in rows if needle in (r.get("company_canonical", "") + r.get("company", "")).lower()]
    rows.sort(key=lambda r: -float(r.get("score") or 0))
    for row in rows[:args.limit]:
        print(f"{row['id']}  {float(row.get('score') or 0):>5.0f}  {row.get('tier', ''):<6} "
              f"{row.get('track', ''):<4} {row.get('company_canonical', '')[:20]:<20} {row.get('title', '')[:54]}")
    print(f"\n{len(rows)} matching, showing {min(len(rows), args.limit)}.")
    return 0


def cmd_show(args):
    row = store.find_job(args.job_id)
    if not row:
        print(_c("No job with that id.", BAD))
        return 1
    for key, value in row.items():
        if value:
            print(f"  {key:<18} {value}")
    return 0


def cmd_applied(args):
    row = store.find_job(args.job_id)
    if not row:
        print(_c("No job with that id. Run: python3 -m recruit list", BAD))
        return 1
    store.set_job_status(row["id"], "applied")
    app = store.add_application(row, notes=args.notes or "", referral=args.referral or "")
    if app is None:
        print(_c("Already in the pipeline.", WARN))
        return 0
    print(_c(f"Logged: {app['company']} - {app['title']}", OK))
    company = app["company"]
    if not any(c["company"].lower() == company.lower() for c in store.load_contacts()):
        print(f"\nNobody contacted at {company} yet. Worth ten minutes:")
        print(f"  python3 -m recruit people \"{company}\" --track {app['track'] or 'swe'}")
    return 0


def cmd_dismiss(args):
    row = store.set_job_status(args.job_id, "dismissed", args.reason or "")
    print(_c(f"Dismissed {row['title']}" if row else "No job with that id.", WARN if row else BAD))
    return 0 if row else 1


def cmd_shortlist(args):
    row = store.set_job_status(args.job_id, "shortlisted")
    print(_c(f"Shortlisted {row['title']}" if row else "No job with that id.", OK if row else BAD))
    return 0 if row else 1


def cmd_stage(args):
    fields = {"stage": args.stage}
    if args.deadline:
        fields["oa_deadline"] = args.deadline
    if args.next:
        fields["next_action"] = args.next
        fields["next_action_on"] = args.on or (date.today() + timedelta(days=3)).isoformat()
    if args.notes:
        fields["notes"] = args.notes
    app = store.update_application(args.job_id, **fields)
    if not app:
        print(_c("No application with that job id.", BAD))
        return 1
    print(_c(f"{app['company']} -> {args.stage}", OK))
    if args.stage in ("oa", "phone", "onsite"):
        print("Interview mode is on: your daily LeetCode set just got bigger and "
              "reordered toward high-frequency patterns.")
    return 0


def cmd_pipeline(args):
    apps = store.load_applications()
    if not apps:
        print("Nothing in the pipeline yet.")
        return 0
    apps.sort(key=lambda a: (report.STAGE_ORDER.index(a.get("stage", "applied"))
                             if a.get("stage") in report.STAGE_ORDER else 99,
                             a.get("applied_on", "")))
    for app in apps:
        quiet = store.days_since(app.get("last_touch") or app.get("applied_on"))
        flag = ""
        if app.get("stage") in report.LIVE_STAGES and quiet and quiet >= settings.FOLLOWUP_AFTER_DAYS:
            flag = _c(f"  <- silent {quiet}d", WARN)
        print(f"{app['job_id'][:8]}  {app.get('stage', ''):<9} {app.get('company', '')[:20]:<20} "
              f"{app.get('title', '')[:44]:<44} {app.get('applied_on', '')}{flag}")
    summary = report._pipeline_summary(apps)
    print(f"\n{summary['live']} live, {summary['total']} total. "
          + ", ".join(f"{k} {v}" for k, v in summary.items() if k in report.STAGE_ORDER and v))
    return 0


def cmd_people(args):
    card = outreach.research_card(args.company, track=args.track, team_hint=args.team or "")
    if args.json:
        print(json.dumps(card, indent=2))
        return 0

    print(_c(f"\n{card['company']}", BOLD) + f"  ({card['tier_label']}, {args.track} track)")
    print("=" * 70)
    for target in card["targets"]:
        print(f"\n{_c(str(target['priority']) + '. ' + target['who'], BOLD)}")
        print(f"   {_c(target['why'], DIM)}")
        for label, url in target["links"]:
            print(f"   {label:<24} {url}")
    if card["email_patterns"]:
        print(f"\n{_c('Email convention (a guess, verify before sending):', DIM)}")
        for pattern in card["email_patterns"]:
            print(f"   {pattern}")
    print(f"\n{_c('Once you have a name:', DIM)}")
    print(f'   python3 -m recruit contact add --company "{card["company"]}" --name "Jane Doe" '
          f'--title "University Recruiter" --kind recruiter --linkedin <url>')
    print("   python3 -m recruit draft <contact_id>")
    return 0


def cmd_contact(args):
    if args.action == "list":
        rows = store.load_contacts()
        if args.company:
            rows = [r for r in rows if args.company.lower() in r["company"].lower()]
        for row in rows:
            print(f"{row['contact_id']}  {row.get('status', ''):<12} {row.get('company', '')[:18]:<18} "
                  f"{row.get('name', '')[:22]:<22} {row.get('kind', '')[:14]:<14} {row.get('last_contact', '')}")
        print(f"\n{len(rows)} contacts.")
        return 0

    if args.action == "add":
        if not args.company or not args.name:
            print(_c("--company and --name are required.", BAD))
            return 1
        row = store.add_contact(
            company=args.company, name=args.name, title=args.title or "",
            kind=args.kind or "engineer", linkedin=args.linkedin or "",
            email=args.email or "", job_id=args.job_id or "", notes=args.notes or "",
            status="found", source="manual",
        )
        if row is None:
            print(_c("Already tracked.", WARN))
            return 0
        print(_c(f"Added {row['contact_id']}: {row['name']} at {row['company']}", OK))
        if not row["email"]:
            guesses = outreach.guess_emails(row["company"], row["name"])
            if guesses:
                print("Likely email (verify before sending): " + ", ".join(guesses))
        print(f"Draft a message: python3 -m recruit draft {row['contact_id']}")
        return 0

    if args.action == "sent":
        today = date.today().isoformat()
        existing = next((c for c in store.load_contacts() if c["contact_id"] == args.contact_id), None)
        if not existing:
            print(_c("No contact with that id.", BAD))
            return 1
        fields = {"status": "reached_out", "last_contact": today}
        if not existing.get("first_contact"):
            fields["first_contact"] = today
        else:
            fields["followups"] = str(int(existing.get("followups") or 0) + 1)
        store.update_contact(args.contact_id, **fields)
        print(_c("Marked as contacted.", OK))
        return 0

    if args.action == "replied":
        store.update_contact(args.contact_id, status="replied", replied="yes",
                             last_contact=date.today().isoformat())
        print(_c("Nice. Marked as replied.", OK))
        return 0

    print(_c(f"Unknown action {args.action}", BAD))
    return 1


def cmd_draft(args):
    contact = next((c for c in store.load_contacts() if c["contact_id"] == args.contact_id), None)
    if not contact:
        print(_c("No contact with that id.", BAD))
        return 1
    job = store.find_job(contact["job_id"]) if contact.get("job_id") else None
    draft = outreach.draft_message(contact, job)
    print(_c(f"\nLinkedIn note ({len(draft['linkedin'])}/300 chars)", BOLD))
    print("-" * 70)
    print(draft["linkedin"])
    print(_c("\nEmail version", BOLD))
    print("-" * 70)
    print(f"Subject: {draft['email_subject']}\n")
    print(draft["email_body"])
    print(_c(f"\nAfter you send it: python3 -m recruit contact sent {contact['contact_id']}", DIM))
    return 0


def cmd_lc(args):
    if args.action == "plan":
        plan = leetcode.plan_today(new_count=args.new, max_reviews=args.reviews)
        stats = leetcode.stats()
        print(_c(f"\nPattern: {plan['pattern']}", BOLD)
              + f"   {stats['attempted']}/{stats['total']} seen, Blind 75 {stats['blind75_done']}/75, "
                f"{stats['streak']} day streak")
        if plan["interview_mode"]:
            print(_c("Interview mode: something live on the calendar, volume is up.", WARN))
        print()
        for p in plan["reviews"]:
            print(f"  {_c('REVIEW', WARN)}  [{p['difficulty']:<6}] {p['title']:<40} due {p['due_on']}")
            print(f"          {p['url']}")
        for p in plan["new"]:
            tag = "Blind 75" if p["blind75"] else p["pattern"]
            print(f"  {_c('NEW   ', OK)}  [{p['difficulty']:<6}] {p['title']:<40} {tag}")
            print(f"          {p['url']}")
        if not plan["reviews"] and not plan["new"]:
            print("  You have been through the whole bank. Switch to timed mock sets.")
        return 0

    if args.action == "log":
        try:
            row = leetcode.log_attempt(args.slug, args.rating, args.minutes or "", args.notes or "")
        except (KeyError, ValueError) as exc:
            print(_c(str(exc), BAD))
            return 1
        print(_c(f"Logged {row['title']} as {row['rating']}.", OK)
              + f" Next review {row['due_on']} (in {row['interval_days']}d).")
        return 0

    if args.action == "stats":
        stats = leetcode.stats()
        print(f"\nSeen {stats['attempted']}/{stats['total']}   solved clean {stats['solved']}   "
              f"Blind 75 {stats['blind75_done']}/{stats['blind75_total']}   streak {stats['streak']}d   "
              f"{stats['total_attempts']} attempts logged")
        print(f"Currently on: {stats['current_pattern']}\n")
        for pattern in leetcode.bank()["curriculum_order"]:
            bucket = stats["by_pattern"].get(pattern, {"done": 0, "total": 0})
            done, total = bucket["done"], bucket["total"]
            filled = int(round(14 * done / total)) if total else 0
            bar = "#" * filled + "." * (14 - filled)
            print(f"  {pattern:<28} {bar} {done:>2}/{total}")
        return 0

    return 1


def cmd_stats(args):
    jobs = store.load_jobs()
    apps = store.load_applications()
    contacts = store.load_contacts()
    summary = report._pipeline_summary(apps)
    state = store.load_state()

    print(_c("\nBoard", BOLD))
    print(f"  {len([j for j in jobs if j.get('status') in ('new', 'shortlisted')])} open and matching, "
          f"{len(jobs)} seen all time")
    print(f"  last sync: {state.get('last_sync', 'never')}")

    print(_c("\nFunnel", BOLD))
    applied = summary["total"]
    for stage in report.STAGE_ORDER:
        count = summary.get(stage, 0)
        if not count:
            continue
        rate = f"  ({count / applied:.0%} of applications)" if applied else ""
        print(f"  {stage:<10} {count:>3}{rate}")
    if applied:
        responses = sum(summary.get(s, 0) for s in ("oa", "phone", "onsite", "offer"))
        print(f"\n  response rate: {responses}/{applied} = {responses / applied:.0%}")
        referred = sum(1 for a in apps if a.get("referral"))
        if referred:
            print(f"  {referred} of those came with a referral")

    print(_c("\nOutreach", BOLD))
    reached = [c for c in contacts if c.get("status") in ("reached_out", "replied", "call", "referred")]
    replied = [c for c in contacts if c.get("replied") == "yes"]
    print(f"  {len(contacts)} tracked, {len(reached)} contacted, {len(replied)} replied"
          + (f" ({len(replied) / len(reached):.0%})" if reached else ""))

    lc = leetcode.stats()
    print(_c("\nPrep", BOLD))
    print(f"  {lc['attempted']}/{lc['total']} problems seen, Blind 75 {lc['blind75_done']}/75, "
          f"{lc['streak']} day streak, on {lc['current_pattern']}")
    print()
    return 0


def cmd_setup(args):
    example = settings.ROOT / "recruit_config.example.py"
    target = settings.ROOT / "recruit_config.py"
    if target.exists() and not args.force:
        print(f"{target} already exists. Pass --force to overwrite.")
    else:
        target.write_text(example.read_text())
        print(_c(f"Created {target}", OK))
    print("""
Next:
  1. Open recruit_config.py and fill in PROFILE (name, school, pitch).
  2. Set EMAIL if you want the daily brief mailed to you.
     Gmail app password: myaccount.google.com/apppasswords
  3. python3 -m recruit sync
  4. python3 -m recruit report

recruit_config.py is gitignored. Nothing you put in it gets committed.""")
    return 0


# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m recruit",
        description="Recruiting command center: source roles, rank them, track the pipeline, prep, and reach out.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="create recruit_config.py").add_argument("--force", action="store_true")
    sub.add_parser("sync", help="pull every job board and rank the results")

    p = sub.add_parser("report", help="today's brief")
    p.add_argument("--email", action="store_true", help="send it instead of printing")
    p.add_argument("--html", metavar="PATH", help="also write the HTML version here")

    p = sub.add_parser("list", help="browse ranked open roles")
    p.add_argument("--track", choices=["swe", "pm", "dte"])
    p.add_argument("--tier", choices=["tier1", "tier2", "quant", "other"])
    p.add_argument("--company")
    p.add_argument("--limit", type=int, default=30)

    sub.add_parser("show", help="everything known about one role").add_argument("job_id")

    p = sub.add_parser("applied", help="log an application")
    p.add_argument("job_id")
    p.add_argument("--notes")
    p.add_argument("--referral", help="who referred you, if anyone")

    p = sub.add_parser("dismiss", help="hide a role")
    p.add_argument("job_id")
    p.add_argument("--reason")

    sub.add_parser("shortlist", help="mark a role to apply to later").add_argument("job_id")

    p = sub.add_parser("stage", help="move an application forward")
    p.add_argument("job_id")
    p.add_argument("stage", choices=report.STAGE_ORDER)
    p.add_argument("--deadline", help="OA deadline, YYYY-MM-DD")
    p.add_argument("--next", help="next action for you")
    p.add_argument("--on", help="when the next action is due, YYYY-MM-DD")
    p.add_argument("--notes")

    sub.add_parser("pipeline", help="every application and where it stands")

    p = sub.add_parser("people", help="who to reach out to at a company")
    p.add_argument("company")
    p.add_argument("--track", choices=["swe", "pm", "dte"], default="swe")
    p.add_argument("--team", help="team or product area, sharpens the search")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("contact", help="track people you are reaching out to")
    p.add_argument("action", choices=["add", "list", "sent", "replied"])
    p.add_argument("contact_id", nargs="?")
    p.add_argument("--company")
    p.add_argument("--name")
    p.add_argument("--title")
    p.add_argument("--kind", choices=["recruiter", "hiring_manager", "engineer", "pm", "alum", "referral"])
    p.add_argument("--linkedin")
    p.add_argument("--email")
    p.add_argument("--job-id", dest="job_id")
    p.add_argument("--notes")

    sub.add_parser("draft", help="draft an outreach message").add_argument("contact_id")

    p = sub.add_parser("lc", help="LeetCode plan and log")
    p.add_argument("action", choices=["plan", "log", "stats"], nargs="?", default="plan")
    p.add_argument("slug", nargs="?", help="problem slug or part of its title")
    p.add_argument("rating", nargs="?", choices=list(leetcode.RATINGS))
    p.add_argument("--minutes", type=int)
    p.add_argument("--notes")
    p.add_argument("--new", type=int, help="override new problems for today")
    p.add_argument("--reviews", type=int, help="override review count for today")

    sub.add_parser("stats", help="how the whole search is going")
    return parser


COMMANDS = {
    "setup": cmd_setup, "sync": cmd_sync, "report": cmd_report, "list": cmd_list,
    "show": cmd_show, "applied": cmd_applied, "dismiss": cmd_dismiss,
    "shortlist": cmd_shortlist, "stage": cmd_stage, "pipeline": cmd_pipeline,
    "people": cmd_people, "contact": cmd_contact, "draft": cmd_draft,
    "lc": cmd_lc, "stats": cmd_stats,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "lc" and args.action == "log" and (not args.slug or not args.rating):
        print(_c("Usage: python3 -m recruit lc log <slug> solved|hint|struggled|failed", BAD))
        return 1
    try:
        return COMMANDS[args.command](args)
    except BrokenPipeError:
        # piped into head/less and the reader went away
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        return 0
    except KeyboardInterrupt:
        return 130
