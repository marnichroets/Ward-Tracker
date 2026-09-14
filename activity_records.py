"""Shared activity record rules used by writes, reports and duplicate review."""

import re
from typing import Iterable, Optional


NOT_REVIEWED = "not_reviewed"
POSSIBLE_DUPLICATE = "possible_duplicate"
CONFIRMED_DUPLICATE = "confirmed_duplicate"
NOT_DUPLICATE = "not_duplicate"
CAMPAIGN_FLOW = "campaign_flow"
EXPLICIT_SELECTOR = "explicit_selector"
COORDINATOR_CONFIRMED = "coordinator_confirmed"
LEGACY_UNVERIFIED = "legacy_unverified"
TRUSTED_CAMPAIGN_LINK_SOURCES = {CAMPAIGN_FLOW, EXPLICIT_SELECTOR, COORDINATOR_CONFIRMED}
DUPLICATE_REVIEW_STATUSES = (
    NOT_REVIEWED, POSSIBLE_DUPLICATE, CONFIRMED_DUPLICATE, NOT_DUPLICATE,
)


def normalize_match_text(value: object) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def duplicate_review_status(doc: dict) -> str:
    value = doc.get("duplicate_review_status")
    return value if value in DUPLICATE_REVIEW_STATUSES else NOT_REVIEWED


def is_reportable_activity(doc: dict) -> bool:
    """Only a human-confirmed duplicate is excluded from operational data."""
    return duplicate_review_status(doc) != CONFIRMED_DUPLICATE


def campaign_link_source(doc: dict) -> Optional[str]:
    """Classify existing links read-only; never backfills legacy documents."""
    if not doc.get("campaign_id"):
        return None
    source = doc.get("campaign_link_source")
    return source if source in TRUSTED_CAMPAIGN_LINK_SOURCES else LEGACY_UNVERIFIED


def has_trusted_campaign_link(doc: dict) -> bool:
    return bool(doc.get("campaign_id") and campaign_link_source(doc) in TRUSTED_CAMPAIGN_LINK_SOURCES)


def reportable_activities(entries: Iterable[dict]) -> list[dict]:
    return [doc for doc in entries if is_reportable_activity(doc)]


def activity_duplicate_kind(new: dict, existing: dict) -> Optional[str]:
    """Conservative comparison after a candidate/date indexed pre-filter."""
    if str(new.get("person_id") or "") != str(existing.get("person_id") or ""):
        return None
    if str(new.get("activity_date") or "") != str(existing.get("activity_date") or ""):
        return None
    if normalize_match_text(new.get("type_display") or new.get("type")) != normalize_match_text(
        existing.get("type_display") or existing.get("type")
    ):
        return None
    if normalize_match_text(new.get("ward")) != normalize_match_text(existing.get("ward")):
        return None
    if str(new.get("campaign_id") or "") != str(existing.get("campaign_id") or ""):
        return None

    same_venue = normalize_match_text(new.get("venue")) == normalize_match_text(existing.get("venue"))
    same_start = normalize_match_text(new.get("start_time")) == normalize_match_text(existing.get("start_time"))
    same_end = normalize_match_text(new.get("end_time")) == normalize_match_text(existing.get("end_time"))
    return "exact" if same_venue and same_start and same_end else "possible"


def planned_activity_duplicate(first: dict, second: dict) -> bool:
    return (
        str(first.get("date") or "") == str(second.get("date") or "")
        and normalize_match_text(first.get("activity_type")) == normalize_match_text(second.get("activity_type"))
        and normalize_match_text(first.get("area")) == normalize_match_text(second.get("area"))
    )


def similar_text(first: object, second: object) -> bool:
    """Exact-after-normalization or clear containment; no edit-distance fuzz."""
    a, b = normalize_match_text(first), normalize_match_text(second)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 8 and (a in b or b in a))


def campaign_duplicate_likely(new: dict, existing: dict) -> bool:
    if str(new.get("person_id") or "") != str(existing.get("person_id") or ""):
        return False
    if existing.get("submission_status", "submitted") == "draft":
        return False
    if not new.get("start_date") or not new.get("end_date") or not existing.get("start_date") or not existing.get("end_date"):
        return False
    if new["start_date"] > existing["end_date"] or new["end_date"] < existing["start_date"]:
        return False
    if normalize_match_text(new.get("municipality")) != normalize_match_text(existing.get("municipality")):
        return False
    new_wards = {normalize_match_text(v) for v in (new.get("wards") or []) if normalize_match_text(v)}
    old_wards = {normalize_match_text(v) for v in (existing.get("wards") or []) if normalize_match_text(v)}
    if new_wards and old_wards and new_wards.isdisjoint(old_wards):
        return False
    return similar_text(new.get("name"), existing.get("name")) and similar_text(
        new.get("objective"), existing.get("objective")
    )


def activity_time_label(start_time: object, end_time: object = None) -> str:
    """One display rule for canonical stored local activity times."""
    start, end = str(start_time or "").strip(), str(end_time or "").strip()
    if start and end:
        return f"{start} - {end}"
    if start:
        return start
    if end:
        return end
    return "Time not recorded"
