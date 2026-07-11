// Chi Local Shows — frontend JS

const BADGE_META = {
  established:  { emoji: '🌟', label: 'Established Acts', tip: 'The average band on this bill has a substantial Spotify following.' },
  rising:       { emoji: '🌱', label: 'Newer Acts',     tip: 'This bill leans toward newer, still-emerging acts.' },
  free:         { emoji: '🎟️', label: 'Free Show',        tip: 'This show appears to be free to attend.' },
  deep_catalog: { emoji: '📀', label: 'Deep Catalog',     tip: 'This band has released a large catalog of tracks.' },
  new:          { emoji: '🆕', label: 'New Act',          tip: "This band's first release came out in the last year." },
  veteran:      { emoji: '🕰️', label: 'Veteran',          tip: 'This band has been releasing music for 10+ years.' },
  popular:      { emoji: '🔥', label: 'Popular',          tip: 'This band has a large Spotify following.' },
  underground:  { emoji: '🔍', label: 'Underground',      tip: 'This band has a small/emerging Spotify following.' },
};

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

  const dateMap = new Map();
  const venueSet = new Set();
  const badgeKeySet = new Set();

  cards.forEach(card => {
    const iso = card.dataset.date;
    const venue = card.dataset.venue;
    if (iso && !dateMap.has(iso)) dateMap.set(iso, fmtDateShort(iso));
    if (venue) venueSet.add(venue);
    (card.dataset.badges || '').split(' ').filter(Boolean).forEach(k => badgeKeySet.add(k));
  });

  const filtersEl = document.getElementById('filters');
  if (!filtersEl) return;

  if (dateMap.size > 1) {
    filtersEl.appendChild(buildRow('Day', 'date', dateMap));
  }

  if (venueSet.size > 1) {
    const venueMap = new Map([...venueSet].map(v => [v, v]));
    filtersEl.appendChild(buildRow('Venue', 'venue', venueMap));
  }

  // Badge filter row — preserve canonical order from BADGE_META
  if (badgeKeySet.size > 0) {
    const badgeMap = new Map();
    Object.keys(BADGE_META).forEach(key => {
      if (badgeKeySet.has(key)) {
        const m = BADGE_META[key];
        badgeMap.set(key, `${m.emoji} ${m.label}`);
      }
    });
    if (badgeMap.size > 0) {
      filtersEl.appendChild(buildRow('Show/Band', 'badge', badgeMap, key => BADGE_META[key]?.tip));
    }
  }

  // Hamburger toggle button (only visible on mobile via CSS)
  const headerTop = document.querySelector('.header-top');
  if (headerTop) {
    const toggle = document.createElement('button');
    toggle.className = 'filters-toggle';
    toggle.setAttribute('aria-label', 'Toggle filters');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = 'Filters ☰';
    toggle.addEventListener('click', () => {
      const open = filtersEl.classList.toggle('filters-open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'Filters ✕' : 'Filters ☰';
    });
    headerTop.appendChild(toggle);
  }
}

function buildRow(labelText, filterType, valueMap, tipFn = null) {
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
    if (tipFn) { const tip = tipFn(value); if (tip) btn.title = tip; }
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
  const activeBadges = activeValues('badge');

  document.querySelectorAll('.show-card').forEach(card => {
    const dateOk = !activeDates.length || activeDates.includes(card.dataset.date);
    const venueOk = !activeVenues.length || activeVenues.includes(card.dataset.venue);
    const cardBadges = (card.dataset.badges || '').split(' ');
    const badgeOk = !activeBadges.length || activeBadges.some(b => cardBadges.includes(b));
    card.hidden = !(dateOk && venueOk && badgeOk);
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
