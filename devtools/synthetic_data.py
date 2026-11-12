"""Deterministic SYNTHETIC Ntsikana data for local development and testing.

Every candidate name, venue, campaign and activity here is invented. The
only real-world facts used are Ntsikana's public geography — the two
municipalities and their official ward counts already encoded in
leadership_reporting.OFFICIAL_WARD_COUNTS — so dashboards and reports render
with the same shape they will have against production data.

Documents are built through main.py's own helpers (roster-ward resolution,
reporting/SmartSheet metadata, campaign validation) so they have exactly the
stored shape the live app writes. Dates are generated relative to "today",
so the current week always contains data.
"""
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone

SEED = 20261112
HISTORY_WEEKS = 12

# Invented names. Deliberately drawn from common first names/surnames and
# combined by a seeded shuffle — they do not describe any real candidate.
FIRST_NAMES = [
    "Lindiwe", "Sipho", "Ayanda", "Thandeka", "Luthando", "Nomvula", "Andile", "Zintle",
    "Mandla", "Busisiwe", "Lwazi", "Sinazo", "Thabo", "Noluthando", "Xolani", "Yonela",
    "Anele", "Pieter", "Marike", "Johan", "Charlene", "Riaan", "Anita", "Deon",
    "Siyabonga", "Nosipho", "Kagiso", "Asanda", "Bongani", "Phumla",
]
SURNAMES = [
    "Mbeki-Dube", "Nqoko", "Sontsele", "Mavuso", "Tshabalala", "Gqirana", "Ndlela", "Mkhize",
    "Booysen", "Vermaak", "Stander", "Koekemoer", "Mqhayi", "Jaxa", "Ntloko", "Zondi",
    "Hlongwane", "Fourie", "Smit", "Bezuidenhout-Viljoen", "Mtirara", "Qwabe", "Dlamini-Sauls",
    "Mokoena", "Petersen", "Mabandla", "Khumalo", "Swart",
]

MUNICIPALITIES = {"Amahlathi": 14, "Raymond Mhlaba": 21}

# Ward-candidate coverage: most wards have a candidate; a few deliberately do
# not, so "no candidate / no activity" states are exercised.
UNCOVERED_WARDS = {("Amahlathi", 11), ("Raymond Mhlaba", 6), ("Raymond Mhlaba", 15), ("Raymond Mhlaba", 19),
                   ("Raymond Mhlaba", 20), ("Raymond Mhlaba", 21), ("Amahlathi", 14), ("Raymond Mhlaba", 13),
                   ("Raymond Mhlaba", 17), ("Raymond Mhlaba", 3)}

# (municipality, wards) for multi-ward (PR) candidates.
MULTI_WARD = [("Amahlathi", [11, 14]), ("Raymond Mhlaba", [13, 15, 17]), ("Raymond Mhlaba", [19, 20, 21])]

# Weighted mix of the real candidate activity options (frontend
# smartsheet-activities.js) — canvassing-heavy, like a real campaign period.
ACTIVITY_WEIGHTS = [
    ("Door to Door", 30), ("Info table : canvassing", 9), ("Telecanvassing", 8), ("House Meeting", 8),
    ("Street Meeting", 7), ("Public Meeting", 4), ("Oversight", 6), ("Stakeholder meeting", 6),
    ("Leaflet Distribution", 5), ("Clean up", 4), ("Canvassing Surgery", 3), ("Info Table", 3),
    ("Soup Kitchen", 2), ("Social Media", 2), ("Neighborhood watch patrol and handover", 2),
    ("Rescue Event: Pothole repair", 1),
]
VENUE_TEMPLATES = [
    "Community hall, {w}", "Taxi rank, {w}", "Sports field, {w}", "Primary school hall, {w}",
    "Clinic forecourt, {w}", "Church hall, {w}", "Main road shops, {w}", "Library steps, {w}",
    "Village pump area, {w}", "RDP section C, {w}", "Old age home, {w}", "Spaza strip, {w}",
]
# Engagement profiles: mean activities per week at full ramp.
ENGAGEMENT = [3.2, 2.6, 2.2, 1.8, 1.4, 1.0, 0.6, 0.0]


def _sast_now():
    from week_dates import sast_today
    return sast_today()


def _candidates(rng):
    first = FIRST_NAMES[:]
    last = SURNAMES[:]
    rng.shuffle(first)
    rng.shuffle(last)
    names = (f"{f} {s}" for f, s in zip(first * 2, last * 2))
    roster = []
    for municipality, count in MUNICIPALITIES.items():
        for n in range(1, count + 1):
            if (municipality, n) in UNCOVERED_WARDS:
                continue
            roster.append({"name": next(names), "municipality": municipality, "wards": [f"Ward {n}"]})
    for municipality, wards in MULTI_WARD:
        roster.append({"name": next(names) + " (PR)", "municipality": municipality, "wards": [f"Ward {w}" for w in wards]})
    return roster


def _roster_docs(people):
    from main import slugify
    docs = []
    for p in people:
        doc = {"name": p["name"], "name_slug": slugify(p["name"]), "municipality": p["municipality"]}
        if len(p["wards"]) == 1:
            doc["ward"] = p["wards"][0]
            doc["actual_ward"] = p["wards"][0]
        else:
            doc["ward"] = p["municipality"]
            doc["actual_wards"] = p["wards"]
        docs.append(doc)
    return docs


def _weighted(rng, pairs):
    total = sum(w for _, w in pairs)
    pick = rng.uniform(0, total)
    for value, weight in pairs:
        pick -= weight
        if pick <= 0:
            return value
    return pairs[-1][0]


def _poisson(rng, mean):
    if mean <= 0:
        return 0
    # Knuth — fine for these small means.
    import math
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _activity_doc(rng, roster_doc, activity_date, today, *, campaign_id=None):
    import main
    from week_dates import week_key_and_day_for_date, format_week_label

    confirmed = main.roster_confirmed_wards(roster_doc)
    chosen = rng.choice(confirmed) if confirmed else None
    ward = main.resolve_ward_for_roster_person(roster_doc, chosen)
    activity = _weighted(rng, ACTIVITY_WEIGHTS)
    start_hour = _weighted(rng, [(8, 2), (9, 4), (10, 4), (11, 2), (13, 2), (14, 3), (15, 3), (16, 2), (17, 1)])
    start_min = rng.choice([0, 0, 30])
    duration_halves = rng.choice([2, 3, 4, 4, 5, 6])
    start = datetime.combine(activity_date, time(start_hour, start_min))
    end = start + timedelta(minutes=30 * duration_halves)
    week_key, day = week_key_and_day_for_date(activity_date)
    doc = {
        "person_id": roster_doc["name_slug"],
        "name": roster_doc["name"],
        "ward": ward,
        "day": day,
        "type": activity,
        "type_display": activity,
        "notes": None,
        "week_key": week_key,
        "week_label": format_week_label(week_key),
        "activity_date": activity_date.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "end_time": end.strftime("%H:%M"),
        "venue": rng.choice(VENUE_TEMPLATES).format(w=ward if ward.startswith("Ward") else "Ward 1"),
        "participant_ids": [],
        "other_participants": [f"Volunteer {rng.randint(1, 40)}" for _ in range(rng.choice([0, 0, 1, 2, 3]))],
        "evidence_photos": [],
        "duplicate_review_status": "not_reviewed",
    }
    if campaign_id:
        doc["campaign_id"] = campaign_id
        doc["campaign_link_source"] = "campaign_flow"
    doc.update(main.reporting_metadata_for_submission(doc))

    sast = timezone(timedelta(hours=2))
    submitted = datetime.combine(activity_date, time(7, 0), sast) - timedelta(days=rng.choice([0, 1, 2, 3, 5]))
    doc["submitted_at"] = _iso(min(submitted, datetime.combine(today, time(20, 0), sast)))

    # Capture backlog shape: older activities are mostly captured; the most
    # recent ones are mostly still awaiting the coordinator.
    age_days = (today - activity_date).days
    capture_probability = 0.0 if age_days < 0 else (0.93 if age_days > 14 else 0.6 if age_days > 7 else 0.2)
    captured_at = datetime.combine(activity_date, time(16, 0), sast) + timedelta(days=rng.randint(1, 6))
    if rng.random() < capture_probability and captured_at.date() <= today:
        doc["capture_status"] = "captured"
        doc["captured_at"] = _iso(captured_at)
    else:
        doc["capture_status"] = "awaiting_capture"
    return doc


async def _campaign_doc(rng, roster_doc, start, end, name, today):
    import main
    from activity_config import OFFICIAL_ACTIVITY_TYPES, campaign_themes
    from week_dates import recommended_campaign_activities

    minimum = recommended_campaign_activities(start.isoformat(), end.isoformat())
    planned = []
    for i in range(minimum):
        d = start + timedelta(days=round(i * ((end - start).days / max(1, minimum))))
        planned.append({"id": f"plan-{i}", "date": d.isoformat(), "time": rng.choice(["09:00", "10:00", "14:00"]),
                        "activity_type": rng.choice(OFFICIAL_ACTIVITY_TYPES[:6]), "area": ""})
    body = main.CampaignIn(
        person_id=roster_doc["name_slug"], name=name,
        start_date=start.isoformat(), end_date=end.isoformat(),
        objective="Raise voter registration and turnout in the target area.",
        problem_description="Residents report poor service delivery and low awareness of registration dates.",
        solution="Door-to-door visits and info tables with follow-up house meetings.",
        wards=main.roster_confirmed_wards(roster_doc)[:1],
        campaign_theme=sorted(campaign_themes())[rng.randrange(len(campaign_themes()))],
        purpose="tackling_problem", includes_criticism=False,
        support_people=["Volunteer 3", "Volunteer 7"],
        campaign_message="Synthetic campaign message for local development.",
        planned_activities=planned,
    )
    doc = await main.campaign_doc_from_body(body, roster_doc, draft=False)
    doc.update({
        "person_id": roster_doc["name_slug"],
        "created_at": _iso(datetime.combine(start - timedelta(days=3), time(9, 0), timezone.utc)),
        "archived_at": None,
        "campaign_manager_capture_status": "awaiting_capture",
        "calendar_capture_status": "awaiting_capture",
    })
    return doc


def generate(today=None, seed=SEED):
    """Returns {"roster": [...], "campaigns": [...], "entries": [...]} (no
    _id fields; the store assigns them). Entries reference campaigns by the
    placeholder key "campaign_ref" until the loader assigns real ids."""
    from bson import ObjectId

    rng = random.Random(seed)
    id_rng = random.Random(seed + 1)  # separate stream: ids never shift the data
    today = today or _sast_now()
    roster = _roster_docs(_candidates(rng))

    monday_this_week = today - timedelta(days=today.weekday())
    first_monday = monday_this_week - timedelta(weeks=HISTORY_WEEKS - 1)
    profiles = {doc["name_slug"]: rng.choice(ENGAGEMENT) for doc in roster}

    campaigns, entries = [], []
    campaign_specs = [
        (0, -20, 13, "Ward 4 Registration Drive"),
        (3, -9, 18, "Safer Streets Lighting Campaign"),
        (6, -40, -12, "Clinic Queues Oversight"),
        (9, 4, 31, "Back-to-School Outreach"),
    ]
    loop = asyncio.new_event_loop()
    try:
        for idx, start_off, end_off, name in campaign_specs:
            owner = roster[idx]
            start, end = today + timedelta(days=start_off), today + timedelta(days=end_off)
            doc = loop.run_until_complete(_campaign_doc(rng, owner, start, end, name, today))
            doc["_id"] = ObjectId(bytes(id_rng.getrandbits(8) for _ in range(12)))
            campaigns.append(doc)
    finally:
        loop.close()
    campaign_by_owner = {c["person_id"]: c for c in campaigns}

    weekday_weights = [(0, 2), (1, 3), (2, 3), (3, 3), (4, 3), (5, 6), (6, 1)]
    for week in range(HISTORY_WEEKS + 1):
        monday = first_monday + timedelta(weeks=week)
        ramp = 0.55 + 0.45 * min(1.0, week / (HISTORY_WEEKS - 2))
        for doc in roster:
            mean = profiles[doc["name_slug"]] * ramp
            for _ in range(_poisson(rng, mean)):
                activity_date = monday + timedelta(days=_weighted(rng, weekday_weights))
                # Next week (the final loop iteration) holds only a light
                # sprinkling of already-planned activities.
                if monday > monday_this_week and rng.random() < 0.6:
                    continue
                campaign = campaign_by_owner.get(doc["name_slug"])
                link = None
                if campaign and campaign["start_date"] <= activity_date.isoformat() <= campaign["end_date"] and rng.random() < 0.7:
                    link = str(campaign["_id"])
                entries.append(_activity_doc(rng, doc, activity_date, today, campaign_id=link))
    return {"roster": roster, "campaigns": campaigns, "entries": entries}
