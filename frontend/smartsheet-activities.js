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

  const ACTIVITY_OPTIONS = [
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

  const api = {CATEGORIES, CATEGORY_LABELS, ACTIVITY_OPTIONS};
  root.SmartSheetActivities = api;
  if(typeof module !== 'undefined' && module.exports){
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
