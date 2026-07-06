// Chi Local Shows — frontend JS

document.addEventListener('DOMContentLoaded', () => {
  buildFilters();
  collapsePastDays();
});

function collapsePastDays() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  document.querySelectorAll('.day-section').forEach(section => {
    const iso = section.dataset.date;
    if (!iso) return;
    const sectionDate = new Date(iso + 'T00:00:00');
    if (sectionDate < today) {
      const details = section.querySelector('details');
      if (details) details.open = false;
    }
  });
}

function buildFilters() {
  const cards = Array.from(document.querySelectorAll('.show-card'));
  if (!cards.length) return;

  // Collect unique dates (preserving order) and venues
  const dateMap = new Map(); // isoDate → short label
  const venueSet = new Set();

  cards.forEach(card => {
    const iso = card.dataset.date;
    const venue = card.dataset.venue;
    if (iso && !dateMap.has(iso)) {
      dateMap.set(iso, fmtDateShort(iso));
    }
    if (venue) venueSet.add(venue);
  });

  const filtersEl = document.getElementById('filters');
  if (!filtersEl) return;

  // Day filter row
  if (dateMap.size > 1) {
    filtersEl.appendChild(buildRow('Day', 'date', dateMap));
  }

  // Venue filter row
  if (venueSet.size > 1) {
    const venueMap = new Map([...venueSet].map(v => [v, v]));
    filtersEl.appendChild(buildRow('Venue', 'venue', venueMap));
  }
}

function buildRow(labelText, filterType, valueMap) {
  const row = document.createElement('div');
  row.className = 'filter-row';

  const lbl = document.createElement('span');
  lbl.className = 'filter-label';
  lbl.textContent = labelText + ':';
  row.appendChild(lbl);

  valueMap.forEach((display, value) => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.textContent = display;
    btn.dataset.filterType = filterType;
    btn.dataset.filterValue = value;
    btn.addEventListener('click', () => {
      btn.classList.toggle('filter-btn--active');
      applyFilters();
    });
    row.appendChild(btn);
  });

  return row;
}

function applyFilters() {
  const activeDates = activeValues('date');
  const activeVenues = activeValues('venue');

  document.querySelectorAll('.show-card').forEach(card => {
    const dateOk = !activeDates.length || activeDates.includes(card.dataset.date);
    const venueOk = !activeVenues.length || activeVenues.includes(card.dataset.venue);
    card.hidden = !(dateOk && venueOk);
  });

  // Hide day sections where all cards are now hidden
  document.querySelectorAll('.day-section').forEach(section => {
    const hasVisible = Array.from(section.querySelectorAll('.show-card'))
      .some(c => !c.hidden);
    section.hidden = !hasVisible;
  });
}

function activeValues(type) {
  return Array.from(
    document.querySelectorAll(`.filter-btn--active[data-filter-type="${type}"]`)
  ).map(btn => btn.dataset.filterValue);
}

function fmtDateShort(iso) {
  // Parse as local date (avoid UTC offset shift by appending T00:00:00)
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' });
}
