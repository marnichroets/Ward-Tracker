import io
import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Same logo the coordinator's own weekly report embeds (main.py's LOGO_PATH)
# — kept as an independent constant rather than importing from main.py to
# avoid a circular import between the two modules.
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")

from smartsheet_reporting import (
    CANVASSING,
    CATEGORY_LABELS,
    classification_for_entry,
    entry_activity_text,
    smartsheet_bucket,
    spreadsheet_safe_text,
)
from week_dates import (
    DAY_LABELS,
    DAY_OFFSET,
    DAY_ORDER,
    MONTHS,
    activity_date_for_day,
    current_week_key,
    format_week_label,
    reporting_week_end,
    reporting_week_start,
    sast_today,
    week_key_and_day_for_date,
)


WARD_NOT_SUPPLIED = "Ward not supplied"
UNASSIGNED_WARD = "Unassigned"
LEADERSHIP_PRESETS = {
    "this_week",
    "last_week",
    "last_4_weeks",
    "last_6_weeks",
    "custom",
    "all",
}


def slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def normalize_name_words(name: str) -> set[str]:
    name = re.sub(r"\([^)]*\)", "", str(name or ""))
    name = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return set(w for w in name.split() if w)


def names_match(a: str, b: str) -> bool:
    words_a = normalize_name_words(a)
    words_b = normalize_name_words(b)
    if not words_a or not words_b:
        return False
    return words_a <= words_b or words_b <= words_a


def dedupe_candidate_names(names: Iterable[str]) -> list[str]:
    # Collapses legacy display-name variants of the same person (a dropped
    # "(CLLR)" suffix, a middle name, case-only differences) using the same
    # names_match() word-subset rule already relied on elsewhere to match a
    # typed name against the roster. Processing the fullest name first (most
    # words, then longest text) means a shorter variant is only dropped when
    # it is genuinely a subset of one already kept — an ambiguous initial
    # like "R. Pickering" never subsumes or gets subsumed by "Richard
    # Pickering", so unrelated people are never merged.
    ordered = sorted(
        (name for name in set(names) if name),
        key=lambda n: (-len(normalize_name_words(n)), -len(n)),
    )
    kept: list[str] = []
    for name in ordered:
        if not any(names_match(name, existing) for existing in kept):
            kept.append(name)
    return sorted(kept, key=lambda n: n.lower())


def participant_names(values: Iterable[object]) -> list[str]:
    out = []
    seen = set()
    for value in values or []:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        key = text.casefold()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def parse_iso_date(value: object, field_name: str = "date") -> date:
    try:
        parsed = date.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO calendar date")
    if parsed.isoformat() != str(value):
        raise ValueError(f"{field_name} must be an ISO calendar date")
    return parsed


def maybe_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def maybe_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def entry_date(doc: dict) -> Optional[date]:
    explicit = maybe_date(doc.get("activity_date"))
    if explicit:
        return explicit
    week_key = doc.get("week_key")
    day = doc.get("day")
    if week_key and day in DAY_OFFSET:
        try:
            return date.fromisoformat(activity_date_for_day(str(week_key), str(day)))
        except (TypeError, ValueError):
            return None
    return None


def entry_week_key(doc: dict) -> str:
    if doc.get("week_key"):
        return str(doc["week_key"])
    d = entry_date(doc)
    if not d:
        return ""
    return week_key_and_day_for_date(d)[0]


def ward_label(value: object) -> str:
    text = str(value or "").strip()
    return text or WARD_NOT_SUPPLIED


def actual_ward_from_text(value: object) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    explicit = re.findall(r"\bward\s*0*(\d{1,3})\b", text, flags=re.IGNORECASE)
    explicit = list(dict.fromkeys(str(int(n)) for n in explicit))
    if len(explicit) == 1:
        return f"Ward {explicit[0]}"
    if len(explicit) > 1:
        return None

    # Accept a lone numeric ward value ("7") or a numeric ward followed by an
    # area ("14, Amahlathi"). Do not parse arbitrary embedded numbers such as
    # village numbers.
    simple = re.fullmatch(r"0*(\d{1,3})(?:\s*,\s*[A-Za-z][A-Za-z\s-]*)?", text)
    if simple:
        return f"Ward {int(simple.group(1))}"

    abbrev = re.fullmatch(r"[A-Za-z]{2,}\s+0*(\d{1,3})", text)
    if abbrev:
        return f"Ward {int(abbrev.group(1))}"
    return None


def normalize_actual_ward_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"(?:ward\s*)?0*(\d{1,3})", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Actual ward must be a ward number, for example Ward 7.")
    return f"Ward {int(match.group(1))}"


def safe_normalize_actual_ward_value(value: object) -> str:
    try:
        return normalize_actual_ward_value(value)
    except ValueError:
        return ""


def municipality_from_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or actual_ward_from_text(text):
        return ""
    return text


def natural_ward_key(value: str) -> tuple[int, int, str]:
    text = str(value or "")
    match = re.search(r"\bward\s*(\d+)\b", text, re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), text.lower())
    match = re.search(r"\b(\d+)\b", text)
    if match:
        return (1, int(match.group(1)), text.lower())
    if text == WARD_NOT_SUPPLIED:
        return (3, 0, text.lower())
    return (2, 0, text.lower())


# Ward numbers are only unique WITHIN a municipality — Amahlathi Ward 4 and
# Raymond Mhlaba Ward 4 are different wards that must never be grouped,
# counted, or displayed together. Every internal ward-keyed lookup (by_ward,
# ward_candidates, ward_evidence, ward filters, per-entry attribution) uses
# this composite key; a bare ward string ("Ward 4") is used only for
# on-screen/Excel display, alongside its own separate municipality field.
WARD_KEY_SEP = "::"


def ward_key(municipality: object, ward: object) -> str:
    municipality = str(municipality or "").strip()
    ward = str(ward or "").strip()
    if not ward:
        return ""
    return f"{municipality}{WARD_KEY_SEP}{ward}" if municipality else ward


def split_ward_key(key: object) -> tuple[str, str]:
    text = str(key or "")
    if WARD_KEY_SEP in text:
        municipality, ward = text.split(WARD_KEY_SEP, 1)
        return municipality, ward
    return "", text


def ward_key_sort(key: str) -> tuple:
    municipality, ward = split_ward_key(key)
    return (municipality.lower(), natural_ward_key(ward))


# The official ward structure for each municipality this constituency
# covers — used so "Wards Active" reports the true denominator (every ward
# that officially exists, whether or not a candidate is confirmed for it
# yet or any activity has been logged there) rather than only the wards
# that happen to already have a candidate or a historical mention.
OFFICIAL_WARD_COUNTS: dict[str, int] = {
    "Amahlathi": 14,
    "Raymond Mhlaba": 21,
}


def official_ward_keys(municipality: str) -> list[str]:
    count = OFFICIAL_WARD_COUNTS.get(municipality)
    if not count:
        return []
    return [ward_key(municipality, f"Ward {n}") for n in range(1, count + 1)]


def display_date(d: Optional[date]) -> str:
    if not d:
        return ""
    return d.strftime("%d %b %Y").lstrip("0")


def period_label(start: date, end: date, preset: str) -> str:
    if preset == "all":
        return f"All available data ({display_date(start)} - {display_date(end)})"
    if start == end:
        return display_date(start)
    week_key = week_key_and_day_for_date(start)[0]
    if start == reporting_week_start(week_key) and end == reporting_week_end(week_key):
        return format_week_label(week_key)
    return f"{display_date(start)} - {display_date(end)}"


def previous_week_key(week_key: str) -> str:
    return (date.fromisoformat(week_key) - timedelta(days=7)).isoformat()


def resolve_period(
    preset: str = "this_week",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    entries: Iterable[dict] = (),
    campaigns: Iterable[dict] = (),
    now: datetime | date | None = None,
) -> dict:
    preset = (preset or "this_week").strip().lower()
    if preset not in LEADERSHIP_PRESETS:
        raise ValueError("Invalid reporting period")

    today = sast_today(now)
    this_week = current_week_key(today)

    if preset == "custom":
        if not date_from or not date_to:
            raise ValueError("Custom date range requires a start and end date")
        start = parse_iso_date(date_from, "date_from")
        end = parse_iso_date(date_to, "date_to")
    elif preset == "last_week":
        week_key = previous_week_key(this_week)
        start = reporting_week_start(week_key)
        end = reporting_week_end(week_key)
    elif preset == "last_4_weeks":
        end = reporting_week_end(this_week)
        start = reporting_week_start(this_week) - timedelta(days=21)
    elif preset == "last_6_weeks":
        end = reporting_week_end(this_week)
        start = reporting_week_start(this_week) - timedelta(days=35)
    elif preset == "all":
        dates: list[date] = []
        for doc in entries:
            d = entry_date(doc)
            if d:
                dates.append(d)
        for campaign in campaigns:
            for key in ("start_date", "end_date"):
                d = maybe_date(campaign.get(key))
                if d:
                    dates.append(d)
        if dates:
            start = min(dates)
            end = max(max(dates), today)
        else:
            start = reporting_week_start(this_week)
            end = reporting_week_end(this_week)
    else:
        start = reporting_week_start(this_week)
        end = reporting_week_end(this_week)

    if end < start:
        raise ValueError("date_to may not be before date_from")

    days = (end - start).days + 1
    return {
        "preset": preset,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "label": period_label(start, end, preset),
        "days": days,
        "week_count": max(1, math.ceil(days / 7)),
    }


def period_dates(period: dict) -> tuple[date, date]:
    return parse_iso_date(period["start_date"], "start_date"), parse_iso_date(period["end_date"], "end_date")


def build_roster_context(roster: Iterable[dict], entries: Iterable[dict]) -> dict:
    entries_list = list(entries)
    roster_list = list(roster)
    people = []
    by_person_id = {}
    by_ward: dict[str, list[dict]] = {}
    ward_candidates: dict[str, set[str]] = {}
    ward_evidence: dict[str, set[str]] = {}
    by_entry_person_id: dict[str, list[dict]] = {}

    for doc in entries_list:
        person_id = str(doc.get("person_id") or slugify(str(doc.get("name") or "")))
        if person_id:
            by_entry_person_id.setdefault(person_id, []).append(doc)

    for doc in roster_list:
        name = str(doc.get("name") or "").strip()
        person_id = str(doc.get("name_slug") or slugify(name))
        related_entries = by_entry_person_id.get(person_id, []) if person_id else []

        # A confirmed multi-ward assignment (actual_wards) is authoritative
        # and skips historical inference entirely — inference exists only to
        # suggest a single ward for a candidate nobody has confirmed yet, and
        # must never override an admin's explicit list.
        explicit_wards = sorted(
            {w for value in (doc.get("actual_wards") or []) if (w := safe_normalize_actual_ward_value(value))},
            key=natural_ward_key,
        )
        explicit_single = safe_normalize_actual_ward_value(doc.get("actual_ward")) if doc.get("actual_ward") else ""
        if not explicit_wards and explicit_single:
            explicit_wards = [explicit_single]

        candidate_wards: set[str] = set(explicit_wards)
        if not explicit_wards:
            candidate_wards.update(w for w in [actual_ward_from_text(doc.get("ward"))] if w)
            candidate_wards.update(
                w for entry in related_entries
                if (w := actual_ward_from_text(entry.get("ward")))
            )

        if explicit_wards:
            wards = explicit_wards
            ward_source = "explicit"
        elif len(candidate_wards) == 1:
            wards = sorted(candidate_wards, key=natural_ward_key)
            ward_source = "roster" if actual_ward_from_text(doc.get("ward")) else "candidate-history"
        else:
            wards = []
            ward_source = ""

        municipality = str(doc.get("municipality") or "").strip() or municipality_from_text(doc.get("ward")) or next(
            (municipality_from_text(entry.get("ward")) for entry in related_entries if municipality_from_text(entry.get("ward"))),
            "",
        )
        ward_keys = [ward_key(municipality, w) for w in wards]
        person = {
            "id": person_id,
            "name": name,
            "wards": wards,
            # Legacy single-ward convenience fields — blank for a candidate
            # with zero OR multiple confirmed wards, so old call sites that
            # still read `ward` never see a misleadingly-partial answer for
            # a multi-ward candidate. Use `wards`/`ward_keys` for anything
            # that must handle multi-ward candidates correctly.
            "ward": wards[0] if len(wards) == 1 else "",
            "ward_display": ", ".join(wards) if wards else "",
            "ward_keys": ward_keys,
            "municipality": municipality,
            "ward_source": ward_source,
            "unassigned_reason": "" if wards else ("Multiple ward numbers found" if len(candidate_wards) > 1 else "No ward number found"),
        }
        if not person["name"] and not person["id"]:
            continue
        people.append(person)
        if person_id:
            by_person_id[person_id] = person
        for w, wk in zip(wards, ward_keys):
            by_ward.setdefault(wk, []).append(person)
            ward_candidates.setdefault(wk, set()).add(name or person_id)
            ward_evidence.setdefault(wk, set()).add(ward_source)

    # Register a ward mentioned in raw activity text as a known ward option
    # even before any roster candidate confirms it — scoped to that entry's
    # own author's municipality when known, so a stray "Ward 4" on an
    # Amahlathi candidate's activity can never silently create or join a
    # Raymond Mhlaba Ward 4 bucket.
    for doc in entries_list:
        explicit_ward = actual_ward_from_text(doc.get("ward"))
        if not explicit_ward:
            continue
        person_id = str(doc.get("person_id") or slugify(str(doc.get("name") or "")))
        owner = by_person_id.get(person_id)
        municipality = (owner or {}).get("municipality") or ""
        by_ward.setdefault(ward_key(municipality, explicit_ward), [])

    # Every officially-numbered ward of a municipality actually represented
    # on the roster is a known ward option even with zero candidates
    # confirmed for it yet — so, e.g., Amahlathi always shows all 14 wards
    # (not just the ones someone happens to be assigned to), and "Wards
    # Active" reports a true denominator instead of undercounting.
    municipalities_present = {p.get("municipality") for p in people if p.get("municipality")}
    for municipality in municipalities_present:
        for wk in official_ward_keys(municipality):
            by_ward.setdefault(wk, [])

    historical_people: dict[str, dict] = {}
    for doc in entries_list:
        name = str(doc.get("name") or "").strip()
        person_id = str(doc.get("person_id") or slugify(name))
        if not person_id and not name:
            continue
        if person_id not in by_person_id and person_id not in historical_people:
            related_entries = by_entry_person_id.get(person_id, [])
            candidate_wards = {
                w for entry in related_entries
                if (w := actual_ward_from_text(entry.get("ward")))
            }
            actual_ward = sorted(candidate_wards, key=natural_ward_key)[0] if len(candidate_wards) == 1 else ""
            municipality = municipality_from_text(doc.get("ward"))
            historical_people[person_id] = {
                "id": person_id,
                "name": name or person_id,
                "wards": [actual_ward] if actual_ward else [],
                "ward": actual_ward,
                "ward_display": actual_ward,
                "ward_keys": [ward_key(municipality, actual_ward)] if actual_ward else [],
                "municipality": municipality,
                "historical": True,
                "ward_source": "historical-entry" if actual_ward else "",
                "unassigned_reason": "" if actual_ward else ("Multiple ward numbers found" if len(candidate_wards) > 1 else "No ward number found"),
            }
        record = historical_people.get(person_id)
        if record and record.get("ward_keys"):
            by_ward.setdefault(record["ward_keys"][0], []).append(record)

    candidate_options = people + sorted(
        historical_people.values(),
        key=lambda p: (p.get("name") or "").lower(),
    )

    assigned_people = [p for p in people if p.get("wards")]
    unassigned_people = [p for p in people if not p.get("wards")]
    return {
        "people": people,
        "assigned_people": assigned_people,
        "unassigned_people": unassigned_people,
        "candidate_options": sorted(candidate_options, key=lambda p: (p.get("name") or "").lower()),
        "by_person_id": by_person_id,
        "by_ward": by_ward,
        "ward_options": sorted(by_ward.keys(), key=ward_key_sort),
        "ward_candidates": {ward: sorted(names) for ward, names in ward_candidates.items()},
        "ward_evidence": {ward: sorted(values) for ward, values in ward_evidence.items()},
    }


def person_matches_filter(doc: dict, person_id: Optional[str]) -> bool:
    if not person_id:
        return True
    doc_person_id = str(doc.get("person_id") or "")
    if doc_person_id == person_id:
        return True
    return slugify(str(doc.get("name") or "")) == person_id


def entry_owner(doc: dict, context: dict) -> Optional[dict]:
    person_id = str(doc.get("person_id") or "")
    return context["by_person_id"].get(person_id) if person_id else None


def assigned_ward_for_entry(doc: dict, context: dict) -> str:
    """Returns the composite municipality::ward key this entry counts
    against — never a bare ward number — so activities from two different
    municipalities' same-numbered wards can never be grouped together.
    Municipality always comes from the entry's own author (a person belongs
    to exactly one municipality); the ward itself comes from the entry's own
    explicit text when present, else the author's single confirmed ward. A
    multi-ward candidate's entry with no explicit ward text is deliberately
    left unassigned here — one activity must never be silently counted
    against every ward a multi-ward candidate holds."""
    owner = entry_owner(doc, context)
    municipality = (owner or {}).get("municipality") or municipality_from_text(doc.get("ward"))
    explicit = actual_ward_from_text(doc.get("ward"))
    if explicit:
        return ward_key(municipality, explicit)
    if owner:
        wards = owner.get("wards") or []
        if len(wards) == 1:
            return ward_key(municipality, wards[0])
    return ""


def assigned_ward_display_for_entry(doc: dict, context: dict) -> str:
    """Bare ward text ("Ward 9") for on-screen display only — never used as
    a grouping/equality key, since it drops the municipality that keeps
    same-numbered wards in different municipalities apart."""
    return split_ward_key(assigned_ward_for_entry(doc, context))[1]


def ward_matches_filter(doc: dict, ward: Optional[str], context: dict) -> bool:
    if not ward:
        return True
    return assigned_ward_for_entry(doc, context) == ward


def municipality_matches_filter(doc: dict, municipality: Optional[str], context: dict) -> bool:
    if not municipality:
        return True
    owner = entry_owner(doc, context)
    doc_municipality = (owner or {}).get("municipality") or municipality_from_text(doc.get("ward"))
    return doc_municipality == municipality


def filter_entries(
    entries: Iterable[dict],
    start: date,
    end: date,
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    context: Optional[dict] = None,
    municipality: Optional[str] = None,
) -> list[dict]:
    context = context or build_roster_context([], entries)
    filtered = []
    for doc in entries:
        d = entry_date(doc)
        if not d or d < start or d > end:
            continue
        if not person_matches_filter(doc, person_id):
            continue
        if not ward_matches_filter(doc, ward, context):
            continue
        if not municipality_matches_filter(doc, municipality, context):
            continue
        filtered.append(doc)
    return filtered


def is_canvassing_entry(doc: dict) -> bool:
    classification = classification_for_entry(doc)
    return smartsheet_bucket(classification) == CANVASSING


def count_canvassing(entries: Iterable[dict]) -> int:
    return sum(1 for doc in entries if is_canvassing_entry(doc))


def campaign_dates(campaign: dict) -> tuple[Optional[date], Optional[date]]:
    return maybe_date(campaign.get("start_date")), maybe_date(campaign.get("end_date"))


def derive_campaign_status(campaign: dict, today: date) -> str:
    if campaign.get("archived_at"):
        return "archived"
    start, end = campaign_dates(campaign)
    if not start or not end:
        return "unknown"
    if today < start:
        return "planned"
    if today > end:
        return "completed"
    return "active"


def campaign_overlaps(campaign: dict, start: date, end: date) -> bool:
    campaign_start, campaign_end = campaign_dates(campaign)
    if not campaign_start or not campaign_end:
        return False
    return campaign_start <= end and campaign_end >= start


def campaign_owner(campaign: dict, roster_by_person_id: dict[str, dict]) -> dict:
    person_id = str(campaign.get("person_id") or "")
    return roster_by_person_id.get(person_id, {
        "id": person_id,
        "name": person_id or "Unknown candidate",
        "ward": "",
        "municipality": "",
    })


def campaign_matches_filters(
    campaign: dict,
    roster_by_person_id: dict[str, dict],
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    municipality: Optional[str] = None,
) -> bool:
    owner = campaign_owner(campaign, roster_by_person_id)
    if person_id and owner.get("id") != person_id:
        return False
    if ward and ward not in (owner.get("ward_keys") or []):
        return False
    if municipality and owner.get("municipality") != municipality:
        return False
    return True


def duration_days(start: Optional[date], end: Optional[date]) -> int:
    if not start or not end or end < start:
        return 0
    return (end - start).days + 1


def week_progress(campaign: dict, today: date) -> Optional[dict]:
    start, end = campaign_dates(campaign)
    days = duration_days(start, end)
    if not start or not end or days == 0:
        return None
    total_weeks = max(1, math.ceil(days / 7))
    if today < start:
        current = 0
    elif today > end:
        current = total_weeks
    else:
        current = min(total_weeks, max(1, math.ceil(((today - start).days + 1) / 7)))
    label = f"Week {current} of {total_weeks}" if current else f"Starts in week 1 of {total_weeks}"
    return {"current": current, "total": total_weeks, "label": label}


def campaign_for_report(
    campaign: dict,
    roster_by_person_id: dict[str, dict],
    linked_entries: Iterable[dict],
    today: date,
) -> dict:
    owner = campaign_owner(campaign, roster_by_person_id)
    start, end = campaign_dates(campaign)
    linked = list(linked_entries)
    progress = week_progress(campaign, today)
    days = duration_days(start, end)
    return {
        "id": str(campaign.get("id") or campaign.get("_id") or ""),
        "name": str(campaign.get("name") or "").strip() or "Untitled campaign",
        "candidate": owner.get("name") or "",
        "person_id": owner.get("id") or "",
        "ward": owner.get("ward_display") or UNASSIGNED_WARD,
        "municipality": owner.get("municipality") or "",
        "purpose": str(campaign.get("purpose") or campaign.get("objective") or "").strip(),
        "start_date": start.isoformat() if start else "",
        "end_date": end.isoformat() if end else "",
        "duration_days": days,
        "duration": f"{days} days" if days else "",
        "status": derive_campaign_status(campaign, today),
        "week_progress": progress,
        "activities": len(linked),
        "canvassing": count_canvassing(linked),
    }


def filtered_campaigns(
    campaigns: Iterable[dict],
    roster_by_person_id: dict[str, dict],
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    municipality: Optional[str] = None,
) -> list[dict]:
    return [
        campaign for campaign in campaigns
        if campaign_matches_filters(campaign, roster_by_person_id, ward, person_id, municipality)
    ]


def period_campaigns(
    campaigns: Iterable[dict],
    roster_by_person_id: dict[str, dict],
    start: date,
    end: date,
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    municipality: Optional[str] = None,
) -> list[dict]:
    return [
        campaign for campaign in filtered_campaigns(campaigns, roster_by_person_id, ward, person_id, municipality)
        if campaign_overlaps(campaign, start, end)
    ]


def candidate_submitted(person: dict, entries: Iterable[dict]) -> bool:
    person_id = person.get("id") or ""
    name = person.get("name") or ""
    for doc in entries:
        if person_id and str(doc.get("person_id") or "") == person_id:
            return True
        if name and names_match(str(doc.get("name") or ""), name):
            return True
    return False


def scoped_roster_people(
    context: dict, ward: Optional[str], person_id: Optional[str], municipality: Optional[str] = None
) -> list[dict]:
    people = context["assigned_people"]
    if ward:
        people = [p for p in people if ward in (p.get("ward_keys") or [])]
    if municipality:
        people = [p for p in people if p.get("municipality") == municipality]
    if person_id:
        people = [p for p in people if p.get("id") == person_id]
    return people


def scoped_ward_options(
    context: dict,
    entries: Iterable[dict],
    ward: Optional[str],
    person_id: Optional[str],
    municipality: Optional[str] = None,
) -> list[str]:
    if ward:
        return [ward]
    wards = set(context["ward_options"])
    if person_id:
        wards = set()
        for p in context["candidate_options"]:
            if p.get("id") == person_id:
                wards.update(p.get("ward_keys") or [])
        for doc in entries:
            if person_matches_filter(doc, person_id):
                wards.add(assigned_ward_for_entry(doc, context))
    if municipality:
        wards = {w for w in wards if split_ward_key(w)[0] == municipality}
    return sorted((w for w in wards if w), key=ward_key_sort)


def participation_counts(roster_people: list[dict], period_entries: list[dict]) -> dict:
    if roster_people:
        submitted = sum(1 for person in roster_people if candidate_submitted(person, period_entries))
        expected = len(roster_people)
    else:
        submitted = len({str(e.get("person_id") or e.get("name") or "") for e in period_entries if e.get("person_id") or e.get("name")})
        expected = submitted
    return {"submitted": submitted, "expected": expected}


def active_ward_count(ward_rows: list[dict]) -> dict:
    total = len(ward_rows)
    active = sum(1 for row in ward_rows if row.get("activities", 0) > 0)
    return {"active": active, "total": total}


def ward_status(activities: int, canvassing: int, historical: int, week_count: int) -> tuple[str, str]:
    expected_minimum = max(1, week_count) * 2
    if activities >= expected_minimum and canvassing > 0:
        return "Strong", f"{activities} activities and {canvassing} canvassing activities recorded; meets the two-activities-per-week expectation."
    if activities > 0:
        if canvassing > 0:
            return "Active", f"{activities} activities recorded, including canvassing."
        return "Active", f"{activities} activities recorded; no canvassing recorded in this period."
    if historical > 0:
        return "Needs Attention", "No activity recorded in this period; historical activity exists for this ward."
    return "No Activity", "No activity has been recorded for this ward yet."


def ward_sort_key(row: dict) -> tuple:
    # Municipality first, then ward number (natural/numeric, never
    # lexicographic — Ward 2 before Ward 10) — this is display ordering
    # only and never affects how activities are counted or grouped.
    return ((row.get("municipality") or "").lower(), natural_ward_key(row.get("ward", "")))


def build_ward_rows(
    entries: list[dict],
    period_entries: list[dict],
    campaigns: list[dict],
    context: dict,
    period: dict,
    ward_filter: Optional[str] = None,
    person_id: Optional[str] = None,
    today: Optional[date] = None,
    municipality: Optional[str] = None,
) -> list[dict]:
    start, end = period_dates(period)
    today = today or sast_today()
    last_activity_cutoff = min(today, end) if start <= today <= end else end
    roster_by_person_id = context["by_person_id"]
    # A name known under a canonical current-roster identity is only ever
    # listed under that person's own confirmed ward (via roster_candidates
    # below) — never merely because some historical entry's own ward text
    # happens to mention a different ward. Otherwise a roster candidate
    # whose actual_ward is unresolved (ambiguous historical ward text) would
    # appear "attached" to every ward any of their old activities mention,
    # even on periods where none of their activity counts toward that ward.
    known_person_ids = set(roster_by_person_id.keys())
    ward_keys = scoped_ward_options(context, entries, ward_filter, person_id, municipality)
    rows = []

    for wk in ward_keys:
        municipality, bare_ward = split_ward_key(wk)
        period_for_ward = [doc for doc in period_entries if assigned_ward_for_entry(doc, context) == wk]
        all_for_ward = [
            doc for doc in entries
            if assigned_ward_for_entry(doc, context) == wk and person_matches_filter(doc, person_id)
        ]
        linked_campaigns = [
            c for c in period_campaigns(campaigns, roster_by_person_id, start, end, wk, person_id)
            if derive_campaign_status(c, today) != "archived"
        ]
        last = max((d for doc in all_for_ward if (d := entry_date(doc)) and d <= last_activity_cutoff), default=None)
        roster_candidates = [
            p for p in context["candidate_options"]
            if wk in (p.get("ward_keys") or []) and (not person_id or p.get("id") == person_id)
        ]
        historical_names = {
            str(doc.get("name") or "").strip()
            for doc in all_for_ward
            if str(doc.get("name") or "").strip()
            and str(doc.get("person_id") or slugify(str(doc.get("name") or ""))) not in known_person_ids
        }
        roster_names = {p.get("name") or p.get("id") or "" for p in roster_candidates if p.get("name") or p.get("id")}
        candidate_names = dedupe_candidate_names(roster_names | historical_names)
        canvassing = count_canvassing(period_for_ward)
        status, reason = ward_status(len(period_for_ward), canvassing, len(all_for_ward), period["week_count"])
        rows.append({
            "ward": bare_ward,
            "ward_key": wk,
            "municipality": municipality or next((p.get("municipality") or "" for p in roster_candidates if p.get("municipality")), ""),
            "candidate": ", ".join(candidate_names) if candidate_names else "",
            "candidate_count": len(candidate_names),
            "activities": len(period_for_ward),
            "canvassing": canvassing,
            "campaigns": len(linked_campaigns),
            "last_activity": last.isoformat() if last else "",
            "last_activity_label": display_date(last) if last else "No activity yet",
            "status": status,
            "status_reason": reason,
        })

    return sorted(rows, key=ward_sort_key)


def iter_reporting_weeks(start: date, end: date) -> list[dict]:
    first_week = week_key_and_day_for_date(start)[0]
    week_key = first_week
    weeks = []
    while reporting_week_start(week_key) <= end:
        weeks.append({
            "week_key": week_key,
            "start_date": reporting_week_start(week_key),
            "end_date": reporting_week_end(week_key),
        })
        week_key = (date.fromisoformat(week_key) + timedelta(days=7)).isoformat()
    return weeks


def weekly_canvassing(
    entries: Iterable[dict],
    start: date,
    end: date,
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    context: Optional[dict] = None,
    municipality: Optional[str] = None,
) -> list[dict]:
    context = context or build_roster_context([], entries)
    scoped = filter_entries(entries, start, end, ward, person_id, context, municipality)
    rows = []
    for week in iter_reporting_weeks(start, end):
        week_start = max(start, week["start_date"])
        week_end = min(end, week["end_date"])
        week_entries = [
            doc for doc in scoped
            if (d := entry_date(doc)) and week_start <= d <= week_end
        ]
        rows.append({
            "week_key": week["week_key"],
            "label": format_week_label(week["week_key"]),
            "start_date": week_start.isoformat(),
            "end_date": week_end.isoformat(),
            "total": count_canvassing(week_entries),
        })
    return rows


def daily_canvassing_for_week(
    entries: Iterable[dict],
    week_start: date,
    week_end: date,
    ward: Optional[str],
    person_id: Optional[str],
    context: dict,
    today: date,
    municipality: Optional[str] = None,
) -> list[dict]:
    """Canvassing activities per calendar day for one Monday-Sunday week —
    the dashboard's main chart. Each day's own real count is always
    included (a future day with a genuinely pre-logged activity is not
    hidden), so the seven values always sum to exactly the same canvassing
    total as the KPI card for this period; `is_future` only marks a day
    that has not happened yet for display (never treated as a confirmed
    zero), a distinction the frontend renders visually rather than by
    omitting the value."""
    scoped = filter_entries(entries, week_start, week_end, ward, person_id, context, municipality)
    by_date: dict[date, int] = {}
    for doc in scoped:
        if not is_canvassing_entry(doc):
            continue
        d = entry_date(doc)
        if d:
            by_date[d] = by_date.get(d, 0) + 1
    days = []
    d = week_start
    while d <= week_end:
        days.append({
            "date": d.isoformat(),
            "label": f"{DAY_LABELS[DAY_ORDER[d.weekday()]]} {d.day} {MONTHS[d.month - 1]}",
            "total": by_date.get(d, 0),
            "is_future": d > today,
        })
        d += timedelta(days=1)
    return days


def daily_activities_for_week(
    entries: Iterable[dict],
    week_start: date,
    week_end: date,
    ward: Optional[str],
    person_id: Optional[str],
    context: dict,
    today: date,
    municipality: Optional[str] = None,
) -> list[dict]:
    """All activities (any type) per calendar day for one Monday-Sunday
    week — the main dashboard's "Activities This Week" chart. Uses the same
    scoping as daily_canvassing_for_week but counts every activity, not
    just canvassing, so the seven values always sum to exactly the same
    total_activities KPI for this period."""
    scoped = filter_entries(entries, week_start, week_end, ward, person_id, context, municipality)
    by_date: dict[date, int] = {}
    for doc in scoped:
        d = entry_date(doc)
        if d:
            by_date[d] = by_date.get(d, 0) + 1
    days = []
    d = week_start
    while d <= week_end:
        days.append({
            "date": d.isoformat(),
            "label": f"{DAY_LABELS[DAY_ORDER[d.weekday()]]} {d.day} {MONTHS[d.month - 1]}",
            "total": by_date.get(d, 0),
            "is_future": d > today,
        })
        d += timedelta(days=1)
    return days


def trend_start_for_period(period: dict) -> date:
    start, end = period_dates(period)
    # Any single reporting week (not just the this_week/last_week presets —
    # also a custom range that happens to be exactly one Monday-Sunday week,
    # as used by the dashboard's week-by-week navigation) shows a trailing
    # 6-week trend rather than just the one selected week.
    if period["preset"] in {"this_week", "last_week"} or period["days"] == 7:
        return reporting_week_start(week_key_and_day_for_date(end)[0]) - timedelta(days=35)
    return start


def change_summary(current: int, previous: int, noun: str = "last week") -> dict:
    delta = current - previous
    if previous == 0:
        if current == 0:
            return {"delta": 0, "percent": None, "direction": "flat", "label": f"No change vs {noun}"}
        return {"delta": delta, "percent": None, "direction": "up", "label": f"New activity vs {noun}"}
    percent = round((delta / previous) * 100)
    if delta > 0:
        return {"delta": delta, "percent": percent, "direction": "up", "label": f"Up {abs(percent)}% vs {noun}"}
    if delta < 0:
        return {"delta": delta, "percent": percent, "direction": "down", "label": f"Down {abs(percent)}% vs {noun}"}
    return {"delta": 0, "percent": 0, "direction": "flat", "label": f"No change vs {noun}"}


def comparison_line(current: int, previous: int, noun: str = "previous period") -> dict:
    summary = change_summary(current, previous, noun)
    return {
        "current": current,
        "previous": previous,
        "delta": current - previous,
        "direction": summary["direction"],
        "label": summary["label"],
    }


def build_comparison(
    entries: list[dict],
    campaigns: list[dict],
    context: dict,
    period: dict,
    ward: Optional[str],
    person_id: Optional[str],
    today: date,
    municipality: Optional[str] = None,
    in_progress: bool = False,
) -> dict:
    start, end = period_dates(period)
    days = (end - start).days + 1
    previous_start = start - timedelta(days=days)
    previous_end = start - timedelta(days=1)
    current_entries = filter_entries(entries, start, end, ward, person_id, context, municipality)
    previous_entries = filter_entries(entries, previous_start, previous_end, ward, person_id, context, municipality)

    # A week still in progress must never be compared full-vs-full against
    # a completed previous week (that always looks like a misleading
    # collapse) — instead compare the SAME elapsed number of days on each
    # side ("so far" vs "same point last week"). This only affects the
    # activities/canvassing comparison notes shown on the KPI cards; the
    # rest of this function (ward/campaign/participation comparisons) is
    # unaffected.
    # "last week" reads correctly for the common case (a completed
    # Monday-Sunday period, which is what the dashboard's own week
    # navigation always selects); a genuinely longer/non-weekly period
    # (last_4_weeks, all-time, etc. — only reachable via the advanced
    # Reports export, never the main dashboard) still says "previous
    # period" so the wording never claims a false weekly comparison.
    comparison_noun = "last week" if days == 7 else "previous period"
    activities_current, canvassing_current = len(current_entries), count_canvassing(current_entries)
    activities_previous, canvassing_previous = len(previous_entries), count_canvassing(previous_entries)
    if in_progress:
        comparison_noun = "same point last week"
        elapsed_days = (min(end, today) - start).days + 1
        so_far_end = start + timedelta(days=elapsed_days - 1)
        same_point_previous_end = previous_start + timedelta(days=elapsed_days - 1)
        so_far_entries = filter_entries(entries, start, so_far_end, ward, person_id, context, municipality)
        same_point_previous_entries = filter_entries(entries, previous_start, same_point_previous_end, ward, person_id, context, municipality)
        activities_current, canvassing_current = len(so_far_entries), count_canvassing(so_far_entries)
        activities_previous, canvassing_previous = len(same_point_previous_entries), count_canvassing(same_point_previous_entries)

    roster_people = scoped_roster_people(context, ward, person_id, municipality)
    current_rows = build_ward_rows(entries, current_entries, campaigns, context, period, ward, person_id, today, municipality)
    previous_period = {
        "preset": "custom",
        "start_date": previous_start.isoformat(),
        "end_date": previous_end.isoformat(),
        "label": period_label(previous_start, previous_end, "custom"),
        "days": days,
        "week_count": period["week_count"],
    }
    previous_rows = build_ward_rows(entries, previous_entries, campaigns, context, previous_period, ward, person_id, today, municipality)
    current_participation = participation_counts(roster_people, current_entries)
    previous_participation = participation_counts(roster_people, previous_entries)
    roster_by_person_id = context["by_person_id"]
    current_campaigns = [
        c for c in period_campaigns(campaigns, roster_by_person_id, start, end, ward, person_id, municipality)
        if derive_campaign_status(c, today) != "archived"
    ]
    previous_campaigns = [
        c for c in period_campaigns(campaigns, roster_by_person_id, previous_start, previous_end, ward, person_id, municipality)
        if derive_campaign_status(c, today) != "archived"
    ]
    current_active_wards = active_ward_count(current_rows)
    previous_active_wards = active_ward_count(previous_rows)
    return {
        "period_label": f"{display_date(previous_start)} - {display_date(previous_end)}",
        "in_progress": in_progress,
        "noun": comparison_noun,
        "activities": comparison_line(activities_current, activities_previous, comparison_noun),
        "canvassing": comparison_line(canvassing_current, canvassing_previous, comparison_noun),
        "campaigns": comparison_line(len(current_campaigns), len(previous_campaigns)),
        "active_wards": {
            "current": current_active_wards,
            "previous": previous_active_wards,
            "label": f"Previously {previous_active_wards['active']} / {previous_active_wards['total']}",
        },
        "participation": {
            "current": current_participation,
            "previous": previous_participation,
            "label": f"Previously {previous_participation['submitted']} / {previous_participation['expected']}",
        },
    }


def relative_date_label(d: Optional[date], today: date) -> str:
    if not d:
        return ""
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == -1:
        return "Yesterday"
    if delta == 1:
        return "Tomorrow"
    if delta < 0:
        return f"{abs(delta)} days ago"
    return display_date(d)


def latest_activity(entries: Iterable[dict], today: date, context: Optional[dict] = None, limit: int = 10) -> list[dict]:
    context = context or build_roster_context([], entries)
    rows = []
    for doc in entries:
        d = entry_date(doc)
        submitted = maybe_datetime(doc.get("submitted_at"))
        submitted_sort = submitted.timestamp() if submitted else 0
        assigned_ward = assigned_ward_display_for_entry(doc, context)
        rows.append({
            "person_id": str(doc.get("person_id") or ""),
            "candidate": str(doc.get("name") or ""),
            "ward": assigned_ward or UNASSIGNED_WARD,
            "stored_area": ward_label(doc.get("ward")),
            "activity": entry_activity_text(doc),
            "activity_date": d.isoformat() if d else "",
            "date_label": relative_date_label(d, today),
            "venue": str(doc.get("venue") or ""),
            "participant_count": len(doc.get("participant_ids") or []) + len(participant_names(doc.get("other_participants") or [])),
            "evidence_photo_count": len(doc.get("evidence_photos") or []),
            "evidence_photos": doc.get("evidence_photos") or [],
            "submitted_at": str(doc.get("submitted_at") or ""),
            "_sort": (d or date.min, str(doc.get("start_time") or ""), submitted_sort),
        })
    rows.sort(key=lambda row: row["_sort"], reverse=True)
    return [{k: v for k, v in row.items() if k != "_sort"} for row in rows[:limit]]


WARD_NOT_ASSIGNED = "Ward not assigned"


def candidate_period_pool(
    context: dict, ward: Optional[str], person_id: Optional[str], municipality: Optional[str] = None
) -> list[dict]:
    # by_person_id.values() is used (rather than context["people"]) so a
    # roster identity is represented at most once here even if the roster
    # collection happens to hold a duplicate/legacy row for the same slug.
    people = list(context["by_person_id"].values())
    if ward:
        people = [p for p in people if ward in (p.get("ward_keys") or [])]
    if municipality:
        people = [p for p in people if p.get("municipality") == municipality]
    if person_id:
        people = [p for p in people if p.get("id") == person_id]
    return people


def candidate_activity_rows(people: list[dict], period_entries: list[dict]) -> list[dict]:
    rows = []
    for person in people:
        person_entries = [doc for doc in period_entries if person_matches_filter(doc, person.get("id"))]
        last = max((d for doc in person_entries if (d := entry_date(doc))), default=None)
        rows.append({
            "id": person.get("id") or "",
            "name": person.get("name") or person.get("id") or "",
            "ward": person.get("ward_display") or WARD_NOT_ASSIGNED,
            "municipality": person.get("municipality") or "",
            "activities": len(person_entries),
            "canvassing": count_canvassing(person_entries),
            "last_activity": last.isoformat() if last else "",
            "last_activity_label": display_date(last) if last else "",
        })
    return rows


def split_candidate_activity(rows: list[dict]) -> dict:
    logged = [row for row in rows if row["activities"] > 0]
    not_logged = [row for row in rows if row["activities"] == 0]
    logged.sort(key=lambda row: row["name"].lower())
    logged.sort(key=lambda row: row["last_activity"] or "", reverse=True)
    logged.sort(key=lambda row: row["activities"], reverse=True)
    not_logged.sort(key=lambda row: row["name"].lower())
    not_logged.sort(key=lambda row: natural_ward_key(row["ward"]))
    return {"logged": logged, "not_logged": not_logged}


def needs_attention(ward_rows: list[dict], today: date, current_period: bool) -> list[dict]:
    items = []
    for row in ward_rows:
        ward = row["ward"]
        if row["activities"] == 0:
            items.append({"ward": ward, "message": f"{ward} - No activity logged in the selected period"})
        elif row["canvassing"] == 0:
            items.append({"ward": ward, "message": f"{ward} - No canvassing activity recorded in the selected period"})
        last = maybe_date(row.get("last_activity"))
        if current_period and last:
            days = (today - last).days
            if days >= 8:
                items.append({"ward": ward, "message": f"{ward} - Last activity {days} days ago"})
    return items[:12]


def linked_entries_by_campaign(entries: Iterable[dict]) -> dict[str, list[dict]]:
    linked: dict[str, list[dict]] = {}
    for doc in entries:
        campaign_id = str(doc.get("campaign_id") or "")
        if campaign_id:
            linked.setdefault(campaign_id, []).append(doc)
    return linked


def filter_options(context: dict) -> dict:
    municipalities = sorted(
        {p.get("municipality") or "" for p in context["assigned_people"] if p.get("municipality")},
        key=lambda value: value.lower(),
    )
    return {
        "wards": [
            {
                "value": wk,
                "label": f"{municipality} {bare_ward}" if municipality else bare_ward,
                "municipality": municipality,
            }
            for wk in context["ward_options"]
            for municipality, bare_ward in [split_ward_key(wk)]
        ],
        "candidates": [
            {
                "value": p.get("id") or "",
                "label": p.get("name") or p.get("id") or "",
                "ward": p.get("ward_display") or "",
                "municipality": p.get("municipality") or "",
            }
            for p in context["candidate_options"]
            if p.get("id") or p.get("name")
        ],
        "municipalities": [{"value": name, "label": name} for name in municipalities],
        "municipality_available": bool(municipalities),
    }


def assignment_rows(roster: Iterable[dict], entries: Iterable[dict]) -> list[dict]:
    roster_list = list(roster)
    entries_list = list(entries)
    context = build_roster_context(roster_list, entries_list)
    by_id = {person["id"]: person for person in context["people"]}
    rows = []
    for doc in roster_list:
        name = str(doc.get("name") or "").strip()
        person_id = str(doc.get("name_slug") or slugify(name))
        person = by_id.get(person_id, {})
        inferred = person.get("ward") if person.get("ward_source") in {"roster", "candidate-history"} else ""
        confirmed_wards = person.get("wards") or [] if person.get("ward_source") == "explicit" else []
        confirmed = confirmed_wards[0] if len(confirmed_wards) == 1 else ""
        status = "Confirmed" if confirmed_wards else ("Suggested" if inferred else "Needs Assignment")
        rows.append({
            "id": str(doc.get("id") or doc.get("_id") or ""),
            "name": name,
            "legacy_ward": str(doc.get("ward") or "").strip(),
            "municipality": person.get("municipality") or "",
            "actual_ward": person.get("ward") or "",
            "actual_wards": confirmed_wards,
            "confirmed_actual_ward": confirmed,
            "confirmed_actual_wards": confirmed_wards,
            "suggested_actual_ward": inferred or "",
            "status": status,
            "reason": person.get("unassigned_reason") or "",
        })
    rows.sort(key=lambda row: (0 if not row["confirmed_actual_wards"] else 1, row["name"].lower()))
    return rows


def build_dashboard(
    entries: Iterable[dict],
    roster: Iterable[dict],
    campaigns: Iterable[dict],
    preset: str = "this_week",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    ward: Optional[str] = None,
    person_id: Optional[str] = None,
    now: datetime | date | None = None,
    municipality: Optional[str] = None,
) -> dict:
    entries_list = list(entries)
    campaigns_list = list(campaigns)
    period = resolve_period(preset, date_from, date_to, entries_list, campaigns_list, now)
    start, end = period_dates(period)
    today = sast_today(now)
    context = build_roster_context(roster, entries_list)
    ward = ward or None
    person_id = person_id or None
    municipality = municipality or None

    period_entries = filter_entries(entries_list, start, end, ward, person_id, context, municipality)
    roster_people = scoped_roster_people(context, ward, person_id, municipality)
    ward_rows = build_ward_rows(entries_list, period_entries, campaigns_list, context, period, ward, person_id, today, municipality)
    participation = participation_counts(roster_people, period_entries)
    active_wards = active_ward_count(ward_rows)
    linked = linked_entries_by_campaign(entries_list)
    roster_by_person_id = context["by_person_id"]

    active_campaign_rows = []
    for campaign in filtered_campaigns(campaigns_list, roster_by_person_id, ward, person_id, municipality):
        if derive_campaign_status(campaign, today) == "active":
            campaign_id = str(campaign.get("id") or campaign.get("_id") or "")
            active_campaign_rows.append(campaign_for_report(campaign, roster_by_person_id, linked.get(campaign_id, []), today))
    active_campaign_rows.sort(key=lambda c: (c["end_date"], c["name"].lower()))

    candidate_pool = candidate_period_pool(context, ward, person_id, municipality)
    candidate_activity = split_candidate_activity(candidate_activity_rows(candidate_pool, period_entries))

    # The on-screen chart: daily canvassing counts for the selected week —
    # only meaningful when exactly one Monday-Sunday week is selected
    # (always true for the dashboard's own week-by-week navigation). The
    # older multi-week trend (canvassing_trend below) is kept only because
    # the Excel "Weekly Canvassing Activities" sheet still uses it for a
    # longer-run view; the dashboard itself now renders daily_canvassing.
    daily_canvassing = (
        daily_canvassing_for_week(entries_list, start, end, ward, person_id, context, today, municipality)
        if period["days"] == 7
        else []
    )
    # The main dashboard's own chart — replaces the old canvassing-only
    # chart with all activities, so its 7 values sum to total_activities.
    daily_activities = (
        daily_activities_for_week(entries_list, start, end, ward, person_id, context, today, municipality)
        if period["days"] == 7
        else []
    )

    trend_start = trend_start_for_period(period)
    trend = weekly_canvassing(entries_list, trend_start, end, ward, person_id, context, municipality)
    if len(trend) >= 2:
        trend_change = change_summary(trend[-1]["total"], trend[-2]["total"], "last week")
    else:
        trend_change = {"delta": 0, "percent": None, "direction": "flat", "label": "Not enough historical data yet"}

    current_period = start <= today <= end
    # A week that includes today but has not finished yet (Monday..today, of
    # a week that ends later) must never be compared 1:1 against a fully
    # completed previous week — that always looks like a misleading crash.
    period_in_progress = current_period and today < end
    comparison = build_comparison(
        entries_list, campaigns_list, context, period, ward, person_id, today, municipality,
        in_progress=period_in_progress,
    )
    return {
        "period": period,
        "period_in_progress": period_in_progress,
        "filters": {"ward": ward or "", "person_id": person_id or "", "municipality": municipality or ""},
        "filter_options": filter_options(context),
        "canvassing_metric": "Canvassing activities",
        "ward_model": {
            "source": "Roster candidates mapped to actual ward numbers where the stored roster/activity data is unambiguous.",
            "unassigned_candidates": len(context["unassigned_people"]),
            "unassigned_period_activities": sum(1 for doc in period_entries if not assigned_ward_for_entry(doc, context)),
        },
        "status_help": [
            {"status": "Strong", "description": "Multiple activities including canvassing recorded during this period."},
            {"status": "Active", "description": "Some activity recorded during this period."},
            {"status": "Needs Attention", "description": "No activity recorded in this period, but the ward has reported before."},
            {"status": "No Activity", "description": "No activity has been recorded for this ward yet."},
        ],
        "kpis": {
            "total_activities": len(period_entries),
            "total_canvassing": count_canvassing(period_entries),
            "active_campaigns": len(active_campaign_rows),
            "wards_active": active_wards,
            "candidate_participation": participation,
        },
        "daily_canvassing": daily_canvassing,
        "daily_activities": daily_activities,
        "canvassing_trend": {
            "weeks": trend,
            "change": trend_change,
            "has_history": sum(1 for row in trend if row["total"] > 0) >= 2,
        },
        "ward_performance": ward_rows,
        "active_campaigns": active_campaign_rows,
        "latest_activity": latest_activity(period_entries, today, context),
        "comparison": comparison,
        "needs_attention": needs_attention(ward_rows, today, current_period),
        "candidate_activity": candidate_activity,
    }


def build_ward_detail(
    entries: Iterable[dict],
    roster: Iterable[dict],
    campaigns: Iterable[dict],
    ward: str,
    preset: str = "this_week",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    person_id: Optional[str] = None,
    now: datetime | date | None = None,
) -> dict:
    entries_list = list(entries)
    campaigns_list = list(campaigns)
    roster_list = list(roster)
    dashboard = build_dashboard(entries_list, roster_list, campaigns_list, preset, date_from, date_to, ward, person_id, now)
    period = dashboard["period"]
    _start, end = period_dates(period)
    today = sast_today(now)
    context = build_roster_context(roster_list, entries_list)
    roster_by_person_id = context["by_person_id"]
    linked = linked_entries_by_campaign(entries_list)
    fallback_municipality, fallback_ward = split_ward_key(ward)
    row = dashboard["ward_performance"][0] if dashboard["ward_performance"] else {
        "ward": fallback_ward,
        "ward_key": ward,
        "municipality": fallback_municipality,
        "candidate": "",
        "activities": 0,
        "canvassing": 0,
        "campaigns": 0,
        "last_activity": "",
        "last_activity_label": "No activity yet",
        "status": "No Activity",
        "status_reason": "No activity has been recorded for this ward yet.",
    }
    all_ward_entries = [
        doc for doc in entries_list
        if assigned_ward_for_entry(doc, context) == ward and person_matches_filter(doc, person_id)
    ]
    recent = latest_activity(all_ward_entries, today, context, limit=10)
    trend_start = reporting_week_start(week_key_and_day_for_date(end)[0]) - timedelta(days=35)
    trend = weekly_canvassing(entries_list, trend_start, end, ward, person_id, context)
    previous_weeks = []
    for week in iter_reporting_weeks(trend_start, end):
        week_entries = filter_entries(entries_list, week["start_date"], week["end_date"], ward, person_id, context)
        previous_weeks.append({
            "week_key": week["week_key"],
            "label": format_week_label(week["week_key"]),
            "activities": len(week_entries),
            "canvassing": count_canvassing(week_entries),
        })
    active_campaign_rows = []
    for campaign in filtered_campaigns(campaigns_list, roster_by_person_id, ward, person_id):
        if derive_campaign_status(campaign, today) in {"active", "planned"}:
            campaign_id = str(campaign.get("id") or campaign.get("_id") or "")
            active_campaign_rows.append(campaign_for_report(campaign, roster_by_person_id, linked.get(campaign_id, []), today))
    return {
        "period": period,
        "ward": row,
        "recent_activities": recent,
        "active_campaigns": active_campaign_rows,
        "previous_weeks": previous_weeks[-6:],
        "canvassing_trend": {
            "weeks": trend,
            "has_history": sum(1 for item in trend if item["total"] > 0) >= 2,
        },
    }


def build_campaign_detail(
    campaign: dict,
    entries: Iterable[dict],
    roster: Iterable[dict],
    now: datetime | date | None = None,
) -> dict:
    entries_list = list(entries)
    today = sast_today(now)
    context = build_roster_context(roster, entries_list)
    campaign_id = str(campaign.get("id") or campaign.get("_id") or "")
    linked = [doc for doc in entries_list if str(doc.get("campaign_id") or "") == campaign_id]
    report = campaign_for_report(campaign, context["by_person_id"], linked, today)
    start, end = campaign_dates(campaign)
    trend = weekly_canvassing(linked, start, end, context=context) if start and end else []
    linked_sorted = latest_activity(linked, today, context, limit=25)
    return {
        "campaign": report,
        "activities": linked_sorted,
        "canvassing_trend": {
            "weeks": trend,
            "has_history": sum(1 for item in trend if item["total"] > 0) >= 2,
        },
    }


def safe_cell_text(value: object) -> str:
    return spreadsheet_safe_text(value)


# Shared workbook palette — kept in step with the frontend's DA brand
# variables (--navy / --blue) so every sheet, including the Weekly Summary
# report page, reads as one consistent, professional document.
DA_NAVY = "153B63"
DA_BLUE = "2568AE"
HEADER_FILL = PatternFill(start_color=DA_BLUE, end_color=DA_BLUE, fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN_SIDE = Side(style="thin", color="DCD6C9")
THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
SHADE_FILL = PatternFill(start_color="F6F8FB", end_color="F6F8FB", fill_type="solid")


def append_rows(ws, headers: list[str], rows: list[list[object]], date_columns: set[int] | None = None) -> None:
    date_columns = date_columns or set()

    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.freeze_panes = "A2"
    if headers:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"

    for row_idx, row in enumerate(rows, start=2):
        ws.append(row)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = THIN_BORDER
            if row_idx % 2 == 0:
                cell.fill = SHADE_FILL
            if col_idx in date_columns and isinstance(cell.value, (date, datetime)):
                cell.number_format = "dd mmm yyyy"

    for col_idx, header in enumerate(headers, start=1):
        width = len(header)
        for row in rows:
            value = row[col_idx - 1]
            if value:
                width = max(width, len(str(value)))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(width + 2, 12), 42)


def workbook_entries(entries: list[dict], campaigns: list[dict], roster: list[dict]) -> list[list[object]]:
    campaign_names = {str(c.get("id") or c.get("_id") or ""): c.get("name") or "" for c in campaigns}
    roster_names = {str(p.get("name_slug") or slugify(p.get("name") or "")): str(p.get("name") or "") for p in roster}
    rows = []
    for doc in sorted(entries, key=lambda e: (entry_date(e) or date.min, str(e.get("start_time") or ""), str(e.get("name") or ""))):
        d = entry_date(doc)
        classification = classification_for_entry(doc)
        category = CATEGORY_LABELS.get(smartsheet_bucket(classification), "Needs Review")
        participant_ids = [str(pid) for pid in (doc.get("participant_ids") or []) if str(pid or "").strip()]
        roster_participants = [roster_names.get(pid, pid) for pid in participant_ids]
        other_participants = participant_names(doc.get("other_participants") or [])
        evidence_photos = doc.get("evidence_photos") or []
        rows.append([
            d,
            format_week_label(entry_week_key(doc)) if entry_week_key(doc) else "",
            safe_cell_text(doc.get("name") or ""),
            safe_cell_text(doc.get("ward") or ""),
            safe_cell_text(entry_activity_text(doc)),
            category,
            safe_cell_text(campaign_names.get(str(doc.get("campaign_id") or ""), "")),
            safe_cell_text(doc.get("venue") or ""),
            doc.get("start_time") or "",
            doc.get("end_time") or "",
            safe_cell_text(doc.get("notes") or ""),
            doc.get("submitted_at") or "",
            safe_cell_text(", ".join(roster_participants)),
            safe_cell_text(", ".join(other_participants)),
            len(roster_participants) + len(other_participants),
            len(evidence_photos),
        ])
    return rows


def workbook_campaigns(campaigns: list[dict], roster_by_person_id: dict[str, dict], entries: list[dict], today: date) -> list[list[object]]:
    linked = linked_entries_by_campaign(entries)
    rows = []
    for campaign in campaigns:
        campaign_id = str(campaign.get("id") or campaign.get("_id") or "")
        report = campaign_for_report(campaign, roster_by_person_id, linked.get(campaign_id, []), today)
        progress = report.get("week_progress") or {}
        rows.append([
            safe_cell_text(report["name"]),
            safe_cell_text(report["ward"]),
            safe_cell_text(report["candidate"]),
            safe_cell_text(report["purpose"] or "No purpose added"),
            maybe_date(report["start_date"]),
            maybe_date(report["end_date"]),
            report["duration_days"],
            report["status"].title(),
            progress.get("label") or "",
            report["activities"],
            report["canvassing"],
        ])
    rows.sort(key=lambda row: (row[4] or date.min, str(row[0]).lower()))
    return rows


def _write_section_title(ws, row: int, text: str) -> int:
    """Writes a bold section heading at column A of `row`; returns the next
    free row. Deliberately no fill/border of its own — the table beneath it
    (via _write_table_block) carries the same header styling as every other
    sheet, keeping this a fast-scanning printable page rather than another
    bordered grid."""
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True, size=12, color=DA_NAVY)
    return row + 1


def _write_table_block(ws, start_row: int, headers: list[str], rows: list[list[object]]) -> int:
    """Writes one small header+data table starting at `start_row` (not
    necessarily row 1, unlike append_rows) using the same header/zebra/
    border styling as every other sheet. Returns the next free row."""
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for offset, row in enumerate(rows):
        row_idx = start_row + 1 + offset
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = THIN_BORDER
            if offset % 2 == 1:
                cell.fill = SHADE_FILL
    return start_row + 1 + len(rows)


def build_weekly_summary_sheet(ws, dashboard: dict) -> None:
    """The workbook's front page — a self-contained, print/forward-friendly
    weekly report using exactly the same dashboard figures as the live
    Leadership Dashboard (no separate calculation of its own): title block,
    headline summary, Who Logged, Has Not Logged, and a Ward Summary."""
    kpis = dashboard["kpis"]
    candidate_activity = dashboard.get("candidate_activity") or {"logged": [], "not_logged": []}
    period = dashboard["period"]

    ws.sheet_view.showGridLines = False
    for col, width in zip("ABCDEF", (28, 18, 26, 12, 20, 16)):
        ws.column_dimensions[col].width = width

    # Matches the coordinator's own weekly report (admin_export_xlsx in
    # main.py): the same logo, the same merged single-line navy title, and
    # the same "Week:" / "Generated:" style summary lines — this is meant to
    # feel like the report Kevin already gets as Coordinator, not a new
    # design invented for Leadership.
    if os.path.exists(LOGO_PATH):
        logo_img = XLImage(LOGO_PATH)
        logo_img.width = 50
        logo_img.height = 61
        ws.add_image(logo_img, "A1")
        ws.row_dimensions[1].height = 48

    row = 2
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    title_cell = ws.cell(row=row, column=1, value="Ntsikana Constituency - Weekly Leadership Report")
    title_cell.font = Font(bold=True, size=14, color=DA_NAVY)
    row += 1
    ws.cell(row=row, column=1, value=f"Reporting Period: {period['label']}").font = Font(bold=True, size=11, color=DA_NAVY)
    row += 1
    ws.cell(row=row, column=1, value=f"Generated: {sast_today().strftime('%d %b %Y')}")
    row += 2
    row = _write_section_title(ws, row, "SUMMARY")
    summary_rows = [
        ("Total Activities", kpis["total_activities"]),
        ("Canvassing Activities", kpis["total_canvassing"]),
        ("Wards Active", f"{kpis['wards_active']['active']} / {kpis['wards_active']['total']}"),
        ("Active Campaigns", kpis["active_campaigns"]),
        ("Candidates Who Logged", len(candidate_activity["logged"])),
        ("Candidates Who Did Not Log", len(candidate_activity["not_logged"])),
    ]
    for offset, (label, value) in enumerate(summary_rows):
        ws.cell(row=row + offset, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row + offset, column=2, value=value)
    row += len(summary_rows) + 2

    row = _write_section_title(ws, row, "WHO LOGGED")
    who_logged_rows = [
        [safe_cell_text(r["name"]), safe_cell_text(r["municipality"]), safe_cell_text(r["ward"]), r["activities"], r["canvassing"]]
        for r in candidate_activity["logged"]
    ]
    row = _write_table_block(ws, row, ["Candidate", "Municipality", "Ward(s)", "Activities", "Canvassing Activities"], who_logged_rows)
    row += 2

    row = _write_section_title(ws, row, "HAS NOT LOGGED")
    not_logged_rows = [
        [safe_cell_text(r["name"]), safe_cell_text(r["municipality"]), safe_cell_text(r["ward"])]
        for r in candidate_activity["not_logged"]
    ]
    row = _write_table_block(ws, row, ["Candidate", "Municipality", "Ward(s)"], not_logged_rows)
    row += 2

    row = _write_section_title(ws, row, "WARD SUMMARY")
    ward_rows = [
        [
            safe_cell_text(wr["municipality"]),
            safe_cell_text(wr["ward"]),
            safe_cell_text(wr["candidate"]) or "Candidate not supplied",
            wr["activities"],
            wr["canvassing"],
            wr["status"],
        ]
        for wr in dashboard["ward_performance"]
    ]
    row = _write_table_block(ws, row, ["Municipality", "Ward", "Candidate", "Activities", "Canvassing Activities", "Status"], ward_rows)

    ws.print_area = f"A1:F{max(row - 1, 1)}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def leadership_workbook_bytes(
    entries: Iterable[dict],
    roster: Iterable[dict],
    campaigns: Iterable[dict],
    dashboard: dict,
) -> bytes:
    entries_list = list(entries)
    campaigns_list = list(campaigns)
    roster_list = list(roster)
    context = build_roster_context(roster_list, entries_list)
    start, end = period_dates(dashboard["period"])
    ward = dashboard["filters"].get("ward") or None
    person_id = dashboard["filters"].get("person_id") or None
    municipality = dashboard["filters"].get("municipality") or None
    filtered_entries_list = filter_entries(entries_list, start, end, ward, person_id, context, municipality)
    filtered_campaign_list = period_campaigns(campaigns_list, context["by_person_id"], start, end, ward, person_id, municipality)
    today = sast_today()

    wb = Workbook()
    ws = wb.active
    ws.title = "Weekly Summary"
    build_weekly_summary_sheet(ws, dashboard)

    ws = wb.create_sheet("Ward Performance")
    ward_rows = [[
        safe_cell_text(row["municipality"]),
        safe_cell_text(row["ward"]),
        safe_cell_text(row["candidate"]),
        row["activities"],
        row["canvassing"],
        row["campaigns"],
        maybe_date(row["last_activity"]),
        row["status"],
        row["status_reason"],
    ] for row in dashboard["ward_performance"]]
    append_rows(ws, ["Municipality", "Ward", "Candidate", "Activities", "Canvassing Activities", "Active Campaigns", "Last Activity", "Status", "Reason"], ward_rows, date_columns={7})

    ws = wb.create_sheet("Activities")
    append_rows(
        ws,
        ["Date", "Week", "Candidate", "Ward", "Activity", "Reporting Category", "Campaign", "Venue", "Start Time", "End Time", "Notes", "Submitted At", "Roster Participants", "Other Participants", "Participant Count", "Evidence Photo Count"],
        workbook_entries(filtered_entries_list, campaigns_list, roster_list),
        date_columns={1},
    )

    ws = wb.create_sheet("Campaigns")
    append_rows(
        ws,
        ["Campaign", "Ward", "Candidate", "Purpose", "Start Date", "End Date", "Duration Days", "Status", "Campaign Week", "Activities", "Canvassing Activities"],
        workbook_campaigns(filtered_campaign_list, context["by_person_id"], entries_list, today),
        date_columns={5, 6},
    )

    ws = wb.create_sheet("Weekly Canvassing Activities")
    trend_rows = [[
        maybe_date(row["start_date"]),
        maybe_date(row["end_date"]),
        row["label"],
        row["total"],
    ] for row in dashboard["canvassing_trend"]["weeks"]]
    append_rows(ws, ["Week Start", "Week End", "Week", "Canvassing Activities"], trend_rows, date_columns={1, 2})
    if trend_rows:
        chart = LineChart()
        chart.title = "Weekly Canvassing Activities"
        chart.y_axis.title = "Activities"
        chart.x_axis.title = "Week"
        chart.width = 18
        chart.height = 9
        data_ref = Reference(ws, min_col=4, min_row=1, max_row=1 + len(trend_rows))
        cats_ref = Reference(ws, min_col=3, min_row=2, max_row=1 + len(trend_rows))
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        ws.add_chart(chart, "F2")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
