"""
A LeetCode plan you can follow without an interview on the calendar.

The point of doing this before you have OAs is coverage: you want to have seen
every pattern at least once and to keep the early ones from decaying. So the
daily set is two things stapled together:

  1. reviews  - problems you already did, resurfaced on a spaced schedule
  2. new      - the next problems in the NeetCode roadmap order, so you finish
                one pattern before starting the next

Bank is the NeetCode 150 (which contains all of Blind 75), vendored into
recruit/data/leetcode_bank.json so this works with no network and no account.
"""

from datetime import date, datetime, timedelta

from . import settings, store

# Spaced repetition intervals in days, indexed by how many times you have
# successfully repeated the problem. Deliberately simple: the schedule only
# has to be good enough to stop you re-solving Two Sum for the tenth time
# while Dijkstra rots.
INTERVALS = {
    "solved": [3, 7, 16, 35, 90, 180],
    "hint": [2, 5, 10, 21, 45, 90],
    "struggled": [1, 3, 7, 14, 30, 60],
    "failed": [1, 1, 2, 4, 8, 16],
}
RATINGS = tuple(INTERVALS)

# Patterns that show up most in big-tech phone screens and OAs. Used to order
# the queue when you are in interview mode and short on time.
HIGH_YIELD = [
    "Arrays & Hashing", "Two Pointers", "Sliding Window", "Stack",
    "Binary Search", "Linked List", "Trees", "Heap / Priority Queue",
    "Graphs", "1-D Dynamic Programming", "Intervals", "Backtracking",
]


def bank():
    return settings.load_leetcode_bank()


def problems():
    return bank()["problems"]


def by_slug():
    return {p["slug"]: p for p in problems()}


def history():
    """Latest log row per problem slug."""
    latest = {}
    for row in store.load_leetcode():
        slug = row.get("slug")
        if not slug:
            continue
        prev = latest.get(slug)
        if prev is None or row.get("date", "") >= prev.get("date", ""):
            latest[slug] = row
    return latest


def next_due(rating, reps):
    steps = INTERVALS.get(rating, INTERVALS["struggled"])
    if rating == "failed":
        reps = 0
    idx = min(max(reps, 0), len(steps) - 1)
    return steps[idx]


def log_attempt(slug, rating, minutes="", notes=""):
    """Record an attempt and schedule the next review. Returns the row."""
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}")
    problem = by_slug().get(slug)
    if problem is None:
        matches = [p for p in problems() if slug.lower() in p["slug"] or slug.lower() in p["title"].lower()]
        if len(matches) != 1:
            raise KeyError(f"unknown problem '{slug}'" + (f" ({len(matches)} fuzzy matches)" if matches else ""))
        problem = matches[0]

    prev = history().get(problem["slug"])
    reps = int(prev.get("reps") or 0) if prev else 0
    reps = 0 if rating == "failed" else reps + 1
    interval = next_due(rating, reps - 1 if reps else 0)
    today = date.today()
    row = {
        "date": today.isoformat(),
        "slug": problem["slug"],
        "title": problem["title"],
        "pattern": problem["pattern"],
        "difficulty": problem["difficulty"],
        "rating": rating,
        "minutes": str(minutes or ""),
        "interval_days": str(interval),
        "due_on": (today + timedelta(days=interval)).isoformat(),
        "reps": str(reps),
        "notes": notes,
    }
    store.append_leetcode(row)
    return row


def current_pattern(hist=None):
    """The pattern you are working through: first one that is not yet covered."""
    hist = hist if hist is not None else history()
    order = bank()["curriculum_order"]
    for pattern in order:
        in_pattern = [p for p in problems() if p["pattern"] == pattern]
        done = [p for p in in_pattern if p["slug"] in hist]
        if len(done) < max(1, int(len(in_pattern) * 0.7)):
            return pattern
    return order[-1]


def interview_mode():
    """True when something real is on the calendar, which changes the mix."""
    today = date.today()
    for app in store.load_applications():
        if app.get("stage") in ("oa", "phone", "onsite"):
            return True
        deadline = app.get("oa_deadline")
        if deadline:
            try:
                if 0 <= (datetime.fromisoformat(deadline).date() - today).days <= 14:
                    return True
            except ValueError:
                pass
    return False


def plan_today(new_count=None, max_reviews=None):
    """Return {'reviews': [...], 'new': [...], 'pattern': str, 'interview_mode': bool}."""
    hist = history()
    index = by_slug()
    today = date.today().isoformat()
    urgent = interview_mode()

    targets = settings.TARGETS
    new_count = new_count if new_count is not None else targets.get("leetcode_new_per_day", 2)
    max_reviews = max_reviews if max_reviews is not None else targets.get("leetcode_max_reviews_per_day", 3)
    if urgent:
        new_count += 2
        max_reviews += 1

    # 1. Due reviews, most overdue first.
    reviews = []
    for slug, row in hist.items():
        due = row.get("due_on") or ""
        if due and due <= today and slug in index:
            item = dict(index[slug])
            item["due_on"] = due
            item["last_rating"] = row.get("rating", "")
            item["overdue_days"] = store.days_since(due) or 0
            reviews.append(item)
    reviews.sort(key=lambda x: (-x["overdue_days"], x["title"]))
    reviews = reviews[:max_reviews]

    # 2. New problems, in roadmap order, Blind 75 first within a pattern.
    pattern = current_pattern(hist)
    order = bank()["curriculum_order"]
    if urgent:
        order = HIGH_YIELD + [p for p in order if p not in HIGH_YIELD]
    start = order.index(pattern) if pattern in order else 0
    queue = []
    for p in order[start:] + order[:start]:
        chunk = [x for x in problems() if x["pattern"] == p and x["slug"] not in hist]
        chunk.sort(key=lambda x: (not x["blind75"], {"Easy": 0, "Medium": 1, "Hard": 2}[x["difficulty"]]))
        queue.extend(chunk)
        if len(queue) >= new_count:
            break

    return {
        "reviews": reviews,
        "new": queue[:new_count],
        "pattern": pattern,
        "interview_mode": urgent,
    }


def stats():
    hist = history()
    all_problems = problems()
    attempted = len(hist)
    solved = sum(1 for r in hist.values() if r.get("rating") == "solved")
    blind_done = sum(1 for p in all_problems if p["blind75"] and p["slug"] in hist)
    by_pattern = {}
    for p in all_problems:
        bucket = by_pattern.setdefault(p["pattern"], {"total": 0, "done": 0})
        bucket["total"] += 1
        if p["slug"] in hist:
            bucket["done"] += 1

    rows = store.load_leetcode()
    days = sorted({r["date"] for r in rows if r.get("date")}, reverse=True)
    streak = 0
    cursor = date.today()
    day_set = set(days)
    # Today not being logged yet should not break yesterday's streak.
    if cursor.isoformat() not in day_set:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in day_set:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "attempted": attempted,
        "total": len(all_problems),
        "solved": solved,
        "blind75_done": blind_done,
        "blind75_total": sum(1 for p in all_problems if p["blind75"]),
        "by_pattern": by_pattern,
        "streak": streak,
        "total_attempts": len(rows),
        "current_pattern": current_pattern(hist),
    }
