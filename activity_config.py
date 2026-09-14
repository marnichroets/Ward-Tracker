"""Central campaign/activity configuration.

Candidate campaign planning, coordinator capture validation and the public
configuration endpoint all read this module so official lists cannot drift.
"""

import os


# Confirmed verbatim from the supplied Campaign Manager screenshots. Keep the
# labels unchanged because coordinators transfer these values manually.
CONFIRMED_CAMPAIGN_THEMES = (
    "Corruption", "Cost of living", "Councillor", "Crime", "Culture",
    "Documentation", "Education", "Electricity", "Environment", "Farming",
    "Grants", "Healthcare", "Housing", "Illegal immigration", "Jobs",
    "Municipal management", "Not a Campaign", "Protests", "Roads",
    "Service delivery", "Social ills", "Taxation", "Taxis, public transport",
    "Traffic and traffic policing", "Water",
)


OFFICIAL_ACTIVITY_TYPES = tuple(sorted([
    "Billboard", "Blue Wave / Robot blitz", "Bulletin Boards",
    "Care collection drive", "Care event (Oppit)",
    "Cavalcade / Carcade / Motorcade", "Clean-up Event",
    "Community Crime Patrol", "Community Sporting Event",
    "Delivery failure site visit", "Email send", "Federal Leader Event",
    "Front of House", "House meeting", "In-person Canvassing / Door-to-door",
    "Info Table", "Leaflet distribution", "Loudhailing", "March",
    "Microtargeting - In-Person Survey / Door-to-door", "Newspaper advert",
    "NGO/NPO Assistance", "Oversight Visit", "Podcast interview",
    "Poster fighting", "Press conference", "Press statement",
    "Protest / Picket", "Public meeting", "Queue Assistance",
    "Radio interview", "Rally", "Registration Surgery",
    "Religious Forum Address", "Roadmarkings", "Robocalls",
    "Self canvass(es)", "SMS send", "Social media advert",
    "Social media post", "Social media promoted post", "Sound truck",
    "Stakeholder Meeting", "Tele Canvassing", "Television interview",
    "WhatsApp/Telegram",
]))


PLANNED_ACTIVITY_GROUPS = (
    ("Brand Building", (
        "Care collection drive", "Care event (Oppit)", "Clean-up Event",
        "Community Crime Patrol", "Community Sporting Event",
        "Delivery failure site visit", "March", "NGO/NPO Assistance",
        "Oversight Visit", "Protest / Picket", "Public meeting",
        "Queue Assistance", "Religious Forum Address", "Roadmarkings",
        "Stakeholder Meeting",
    )),
    ("Earned Media", (
        "Federal Leader Event", "Podcast interview", "Press conference",
        "Press statement", "Radio interview", "Television interview",
    )),
    ("Mobilization", (
        "Blue Wave / Robot blitz", "Cavalcade / Carcade / Motorcade",
        "Loudhailing", "Rally", "Sound truck",
    )),
    ("Canvassing and voter contact", (
        "In-person Canvassing / Door-to-door", "Tele Canvassing", "Info Table",
        "House meeting", "Leaflet distribution", "Self canvass(es)",
    )),
)

assert all(value in OFFICIAL_ACTIVITY_TYPES for _, values in PLANNED_ACTIVITY_GROUPS for value in values)


def campaign_themes() -> list[str]:
    """Return confirmed values plus any separately configured additions.

    The environment remains an additive escape hatch for future screenshot-
    confirmed values; it cannot replace or paraphrase the known list.
    """
    configured_additions = (
        item.strip() for item in os.environ.get("CAMPAIGN_THEMES", "").split(",") if item.strip()
    )
    return list(dict.fromkeys((*CONFIRMED_CAMPAIGN_THEMES, *configured_additions)))


def activity_config_response() -> dict:
    grouped = {value for _, values in PLANNED_ACTIVITY_GROUPS for value in values}
    planning_groups = [
        {"name": name, "values": list(values)} for name, values in PLANNED_ACTIVITY_GROUPS
    ]
    other_official = [value for value in OFFICIAL_ACTIVITY_TYPES if value not in grouped]
    if other_official:
        planning_groups.append({"name": "Other official activity types", "values": other_official})
    return {
        "planned_activity_groups": planning_groups,
        "official_activity_types": list(OFFICIAL_ACTIVITY_TYPES),
        "campaign_themes": campaign_themes(),
    }
