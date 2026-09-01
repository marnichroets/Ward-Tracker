(function(root){
  const CATEGORIES = {
    CANVASSING: 'CANVASSING',
    PUBLIC_STREET_MEETING: 'PUBLIC_STREET_MEETING',
    PRESENCE: 'PRESENCE'
  };

  const CATEGORY_LABELS = {
    CANVASSING: 'Canvassing Activities',
    PUBLIC_STREET_MEETING: 'Public / Street Meetings',
    PRESENCE: 'Presence Activities',
    NEEDS_REVIEW: 'Needs Review'
  };

  const CANONICAL_ACTIVITY_OPTIONS = [
    'Info table : canvassing',
    'Canvassing Surgery',
    'Door to Door',
    'Telecanvassing',
    'House Meeting',
    'Info Table',
    'Public Meeting',
    'Street Meeting',
    'Clean up',
    'Oversight',
    'Stakeholder meeting',
    'Neighborhood watch patrol and handover',
    'Rescue Event: Pothole repair',
    'Rescue Event: Street Painting',
    'Rescue Event: Lights',
    'Hoot or Blue wave',
    'Motorcade',
    'Fun day',
    'Sports day',
    'Fundraiser',
    'March',
    'Picket',
    'Rally',
    'Soup Kitchen',
    'Newspaper or Radio Advert',
    'Religious Forum Address',
    'Social Media',
    'Poster removal',
    'Women Safety',
    'Fire extinguishers donated',
    'Donation in kind',
    'Blue Wave',
    'Mayoral Campaign Pledges',
    'Rescue Event',
    'Care Event',
    'Poster fighting',
    'Leaflet Distribution'
  ];

  // Shown last in the candidate dropdown; selecting it reveals a free-text
  // "Other activity" field instead of picking a fixed, pre-mapped label.
  const OTHER_OPTION = 'Other';

  const ACTIVITY_OPTIONS = CANONICAL_ACTIVITY_OPTIONS.concat([OTHER_OPTION]);

  const api = {CATEGORIES, CATEGORY_LABELS, CANONICAL_ACTIVITY_OPTIONS, OTHER_OPTION, ACTIVITY_OPTIONS};
  root.SmartSheetActivities = api;
  if(typeof module !== 'undefined' && module.exports){
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
