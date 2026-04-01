/**
 * WorldSense Web UI — app.js  (v2)
 * Vanilla JS, fetch API, polling for task status.
 *
 * New in v2:
 *  - Dot-matrix visualization for running tasks
 *  - Evaluation preset system (6 presets + Custom with LLM-generated dimensions)
 *  - System settings page (3 tabs: General / LLM / Advanced)
 *  - Occupation display fix (language-aware names)
 *  - UI layout: Top Attractions/Concerns now above segment tables
 *  - Concurrency refactor: configurable from settings
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const _scriptBase = (() => {
  const path = window.location.pathname;
  const idx = path.lastIndexOf('/');
  return path.substring(0, idx + 1);
})();
const API_BASE = _scriptBase.replace(/\/$/, '');
const POLL_INTERVAL = 2000;
const DOT_POLL_INTERVAL = 1500;

const IS_DEV = new URLSearchParams(window.location.search).has('dev');

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const TAB_KEY = 'ws_active_tab';

const views = {
  'new-run':  document.getElementById('view-new-run'),
  'tasks':    document.getElementById('view-tasks'),
  'detail':   document.getElementById('view-detail'),
  'settings': document.getElementById('view-settings'),
};

function showView(name) {
  Object.entries(views).forEach(([k, el]) => {
    if (el) el.classList.toggle('hidden', k !== name);
  });
  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.view === name);
  });
  document.querySelectorAll('.mobile-nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.view === name);
  });
  if (name === 'tasks') loadTasks();
  if (name === 'settings') loadSettingsPage();
  if (name === 'new-run') initNewRunDefaults();
  if (name !== 'detail') {
    try { localStorage.setItem(TAB_KEY, name); } catch(_) {}
  }
}

document.querySelectorAll('[data-view]').forEach(el => {
  el.addEventListener('click', e => {
    e.preventDefault();
    showView(el.dataset.view);
  });
});

// (LLM Backend selector removed from New Research form — configured in Settings only)

// ---------------------------------------------------------------------------
// New Run Defaults — inherit from Settings
// ---------------------------------------------------------------------------
async function initNewRunDefaults() {
  try {
    const settings = await apiFetch('/api/settings');
    const g = settings?.general || {};

    // Initialize output language from settings.general.default_language
    const langSel = document.getElementById('input-language');
    if (langSel && g.default_language) {
      for (let i = 0; i < langSel.options.length; i++) {
        if (langSel.options[i].value === g.default_language) {
          langSel.selectedIndex = i;
          break;
        }
      }
    }

    // Initialize persona count from settings.general.default_sample_size
    const defaultCount = g.default_sample_size;
    if (defaultCount) {
      const sliderEl  = document.getElementById('input-personas');
      const numEl     = document.getElementById('input-personas-num');
      const labelEl   = document.getElementById('persona-count-label');
      const v = Math.min(200, Math.max(5, defaultCount));
      if (sliderEl)  { sliderEl.value = v; updateSliderFill(sliderEl); }
      if (numEl)     numEl.value = defaultCount;  // num input allows up to 1000
      if (labelEl)   labelEl.textContent = defaultCount;
    }

    // Populate model selector from profiles
    const profiles = settings?.llm_profiles || [];
    const activeProfile = settings?.active_profile || (profiles[0]?.name || '');
    renderModelSelector(profiles, activeProfile);
  } catch (e) {
    // Non-fatal — keep HTML defaults if settings fetch fails
    console.warn('initNewRunDefaults: failed to load settings', e);
  }
}

// Render the model selector dropdown in the New Research form
function renderModelSelector(profiles, activeProfileName) {
  const container = document.getElementById('model-selector-container');
  if (!container) return;

  if (!profiles || profiles.length === 0) {
    container.innerHTML = `<p class="text-xs text-slate-500 italic">No LLM profiles configured. <a href="#" data-view="settings" onclick="showView('settings')" class="text-brand-400 hover:underline">Configure in Settings →</a></p>`;
    return;
  }

  const options = profiles.map(p => {
    const visionMark = p.supports_vision === true ? ' ✓' : p.supports_vision === false ? '' : '';
    const visionTitle = p.supports_vision === true ? 'Vision capable' : p.supports_vision === false ? 'Text only' : 'Vision capability unknown';
    return `<option value="${escHtml(p.name)}" ${p.name === activeProfileName ? 'selected' : ''} data-vision="${p.supports_vision}" title="${visionTitle}">${escHtml(p.name)}${visionMark}</option>`;
  }).join('');

  container.innerHTML = `
    <div class="flex items-center gap-3">
      <div class="flex-1">
        <label class="block text-sm font-medium text-slate-300 mb-1">
          Model <span class="text-slate-500 font-normal">/ 模型</span>
        </label>
        <select id="input-profile" class="w-full bg-surface-800 border border-surface-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-brand-500">
          ${options}
        </select>
      </div>
      <div id="model-vision-badge" class="mt-5 flex-shrink-0">
        ${renderVisionBadgeForProfile(profiles, activeProfileName)}
      </div>
    </div>`;

  // Wire change event to update badge
  const sel = document.getElementById('input-profile');
  if (sel) {
    sel.addEventListener('change', () => {
      const selectedProfile = profiles.find(p => p.name === sel.value);
      const badgeEl = document.getElementById('model-vision-badge');
      if (badgeEl) badgeEl.innerHTML = renderVisionBadge(selectedProfile?.supports_vision);
    });
  }
}

function renderVisionBadgeForProfile(profiles, profileName) {
  const profile = profiles.find(p => p.name === profileName);
  return renderVisionBadge(profile?.supports_vision);
}

// ---------------------------------------------------------------------------
// Advanced Options State (same as before)
// ---------------------------------------------------------------------------
const ALL_COUNTRIES = [
  {code:'US', label:'United States', flag:'🇺🇸'},
  {code:'CN', label:'China', flag:'🇨🇳'},
  {code:'JP', label:'Japan', flag:'🇯🇵'},
  {code:'KR', label:'South Korea', flag:'🇰🇷'},
  {code:'IN', label:'India', flag:'🇮🇳'},
  {code:'DE', label:'Germany', flag:'🇩🇪'},
  {code:'FR', label:'France', flag:'🇫🇷'},
  {code:'GB', label:'UK', flag:'🇬🇧'},
  {code:'BR', label:'Brazil', flag:'🇧🇷'},
  {code:'MX', label:'Mexico', flag:'🇲🇽'},
  {code:'RU', label:'Russia', flag:'🇷🇺'},
  {code:'TR', label:'Turkey', flag:'🇹🇷'},
  {code:'SA', label:'Saudi Arabia', flag:'🇸🇦'},
  {code:'ZA', label:'South Africa', flag:'🇿🇦'},
  {code:'NG', label:'Nigeria', flag:'🇳🇬'},
  {code:'EG', label:'Egypt', flag:'🇪🇬'},
  {code:'ID', label:'Indonesia', flag:'🇮🇩'},
  {code:'TH', label:'Thailand', flag:'🇹🇭'},
  {code:'VN', label:'Vietnam', flag:'🇻🇳'},
  {code:'PH', label:'Philippines', flag:'🇵🇭'},
  {code:'AU', label:'Australia', flag:'🇦🇺'},
  {code:'SG', label:'Singapore', flag:'🇸🇬'},
  {code:'IT', label:'Italy', flag:'🇮🇹'},
  {code:'ES', label:'Spain', flag:'🇪🇸'},
  {code:'AR', label:'Argentina', flag:'🇦🇷'},
];

const POP_WEIGHTS = {
  CN:0.178, IN:0.178, US:0.043, ID:0.035, BR:0.028, NG:0.028, RU:0.018,
  MX:0.017, JP:0.016, PH:0.015, EG:0.014, VN:0.012, TR:0.011, DE:0.010,
  TH:0.009, GB:0.009, FR:0.008, SA:0.045, ZA:0.008, KR:0.007, AR:0.006,
  AU:0.003, SG:0.001, IT:0.008, ES:0.006
};

const AGE_GROUPS = [
  {id:'18-24', label:'18–24 岁'},
  {id:'25-34', label:'25–34 岁'},
  {id:'35-44', label:'35–44 岁'},
  {id:'45-54', label:'45–54 岁'},
  {id:'55-64', label:'55–64 岁'},
  {id:'65+',   label:'65+ 岁'},
];

const DEFAULT_AGE_WEIGHTS = {
  '18-24': 15, '25-34': 22, '35-44': 20, '45-54': 17, '55-64': 14, '65+': 12
};

const GENDER_GROUPS = [
  {id:'male',       label:'Male'},
  {id:'female',     label:'Female'},
  {id:'non-binary', label:'Non-binary'},
];

const DEFAULT_GENDER_WEIGHTS = {male: 50, female: 49, 'non-binary': 1};

const INCOME_GROUPS = [
  {id:'low',          label:'< $20k / yr'},
  {id:'lower-middle', label:'$20k–$50k'},
  {id:'middle',       label:'$50k–$100k'},
  {id:'upper-middle', label:'$100k–$200k'},
  {id:'high',         label:'$200k+'},
];

const DEFAULT_INCOME_WEIGHTS = {
  low: 35, 'lower-middle': 25, middle: 20, 'upper-middle': 12, high: 8
};

let LOCATION_GROUPS = [
  {id:'urban',    label:'Urban (城市)'},
  {id:'suburban', label:'Suburban (城郊)'},
  {id:'rural',    label:'Rural (农村)'},
];

let DEFAULT_LOCATION_WEIGHTS = {urban: 55, suburban: 30, rural: 15};

async function loadLocationsForMarket(market) {
  try {
    const resp = await fetch(`/worldsense/api/locations?market=${encodeURIComponent(market)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const locs = data.locations || [];
    if (locs.length === 0) return;

    LOCATION_GROUPS = locs.map(t => {
      const shortEn = (t.label_en || '').replace(/\s*\(.*$/, '');
      const label = t.label ? `${t.label} / ${shortEn}` : t.label_en;
      return { id: t.id, label };
    });

    const newWeights = {};
    locs.forEach(t => { newWeights[t.id] = t.weight || 10; });
    DEFAULT_LOCATION_WEIGHTS = {...newWeights};
    advState.locationWeights = {...newWeights};

    renderWeightSliders('location-weights', LOCATION_GROUPS, advState.locationWeights, 'updateLocationWeight');
    updateAdvSummary();
  } catch(e) {
    console.warn('Failed to load locations for market:', market, e);
  }
}

let OCCUPATION_GROUPS = [];
let OCCUPATIONS_FLAT = [];

async function loadOccupations() {
  try {
    const resp = await fetch('/worldsense/api/occupations');
    if (resp.ok) {
      OCCUPATION_GROUPS = await resp.json();
      OCCUPATIONS_FLAT = OCCUPATION_GROUPS.flatMap(g => g.items.map(o => ({
        id: o.id,
        label: o.title,
        label_local: o.title_local ? Object.values(o.title_local)[0] : '',
        category: o.category,
        categoryLabel: g.label,
      })));
    }
  } catch(e) {
    console.warn('Failed to load occupations from API:', e);
  }
}

const PERSONALITY_TYPES = [
  {id:'pragmatic_planner',  label:'Pragmatic Planner'},
  {id:'social_connector',   label:'Social Connector'},
  {id:'value_hunter',       label:'Value Hunter'},
  {id:'impulse_explorer',   label:'Impulse Explorer'},
  {id:'skeptical_analyst',  label:'Skeptical Analyst'},
  {id:'brand_loyalist',     label:'Brand Loyalist'},
  {id:'eco_conscious',      label:'Eco-Conscious'},
  {id:'status_seeker',      label:'Status Seeker'},
];

let advState = {
  selectedCountries: new Set(),
  nationalityWeights: {},
  ageWeights: {...DEFAULT_AGE_WEIGHTS},
  genderWeights: {...DEFAULT_GENDER_WEIGHTS},
  incomeWeights: {...DEFAULT_INCOME_WEIGHTS},
  locationWeights: {...DEFAULT_LOCATION_WEIGHTS},
  selectedOccupations: new Set(),
  selectedPersonalities: new Set(),
};

function isAdvCustomized() {
  return (
    advState.selectedCountries.size > 0 ||
    advState.selectedOccupations.size > 0 ||
    advState.selectedPersonalities.size > 0 ||
    JSON.stringify(advState.ageWeights) !== JSON.stringify(DEFAULT_AGE_WEIGHTS) ||
    JSON.stringify(advState.genderWeights) !== JSON.stringify(DEFAULT_GENDER_WEIGHTS) ||
    JSON.stringify(advState.incomeWeights) !== JSON.stringify(DEFAULT_INCOME_WEIGHTS) ||
    JSON.stringify(advState.locationWeights) !== JSON.stringify(DEFAULT_LOCATION_WEIGHTS)
  );
}

function updateAdvSummary() {
  const el = document.getElementById('adv-summary');
  if (el) el.classList.toggle('hidden', !isAdvCustomized());
}

function buildDimensionConfig() {
  const dim = {};
  if (advState.selectedCountries.size > 0) {
    const weights = {};
    advState.selectedCountries.forEach(c => {
      weights[c] = (advState.nationalityWeights[c] ?? 10) / 100;
    });
    dim.nationality_weights = weights;
  }
  dim.age_weights = normalizeWeights(advState.ageWeights);
  dim.gender_weights = normalizeWeights(advState.genderWeights);
  dim.income_weights = normalizeWeights(advState.incomeWeights);
  dim.location_weights = normalizeWeights(advState.locationWeights);
  if (advState.selectedOccupations.size > 0) dim.occupation_ids = [...advState.selectedOccupations];
  if (advState.selectedPersonalities.size > 0) dim.personality_traits = [...advState.selectedPersonalities];
  return Object.keys(dim).length > 0 ? dim : null;
}

function updateSliderFill(sliderEl) {
  const min = parseFloat(sliderEl.min) || 0;
  const max = parseFloat(sliderEl.max) || 100;
  const val = parseFloat(sliderEl.value) || 0;
  const pct = ((val - min) / (max - min)) * 100;
  sliderEl.style.background = `linear-gradient(to right, #06b6d4 0%, #06b6d4 ${pct}%, #374151 ${pct}%, #374151 100%)`;
}

function normalizeWeights(wmap) {
  const total = Object.values(wmap).reduce((a, b) => a + b, 0);
  if (total === 0) return wmap;
  const result = {};
  Object.entries(wmap).forEach(([k, v]) => { result[k] = v / total; });
  return result;
}

// ---------------------------------------------------------------------------
// Advanced Options UI Rendering (unchanged from v1)
// ---------------------------------------------------------------------------

function renderNationalityTags() {
  const container = document.getElementById('nationality-tags');
  if (!container) return;
  container.innerHTML = ALL_COUNTRIES.map(c => `
    <span class="country-tag${advState.selectedCountries.has(c.code) ? ' selected' : ''}"
          data-code="${c.code}" onclick="toggleCountry('${c.code}')">
      ${c.flag} ${c.code}
    </span>
  `).join('');
  renderNationalityWeights();
}

function toggleCountry(code) {
  if (advState.selectedCountries.has(code)) {
    advState.selectedCountries.delete(code);
    delete advState.nationalityWeights[code];
  } else {
    advState.selectedCountries.add(code);
    advState.nationalityWeights[code] = 100;
  }
  renderNationalityTags();
  updateAdvSummary();
}

function renderNationalityWeights() {
  const container = document.getElementById('nationality-weights');
  if (!container) return;
  if (advState.selectedCountries.size === 0) {
    container.innerHTML = '<p class="text-xs text-slate-600 italic">No countries selected — using market defaults</p>';
    return;
  }

  const raw = {};
  advState.selectedCountries.forEach(c => { raw[c] = advState.nationalityWeights[c] ?? 10; });
  const total = Object.values(raw).reduce((a, b) => a + b, 0);
  const codes = [...advState.selectedCountries];

  const existing = container.querySelectorAll('.weight-row');
  if (existing.length === codes.length) {
    const pcts = codes.map((code) => {
      const val = raw[code];
      return total > 0 ? Math.round((val / total) * 100) : 0;
    });
    const sumExceptLast = pcts.slice(0, -1).reduce((a, b) => a + b, 0);
    if (pcts.length > 0) pcts[pcts.length - 1] = 100 - sumExceptLast;

    existing.forEach((row, i) => {
      const code = codes[i];
      const val = raw[code];
      const labelEl = row.querySelector('.weight-val');
      if (labelEl) labelEl.textContent = `${pcts[i]}%`;
      const sliderEl = row.querySelector('input[type=range]');
      if (sliderEl && document.activeElement !== sliderEl) {
        sliderEl.value = val;
        updateSliderFill(sliderEl);
      }
    });
    return;
  }

  const pcts = codes.map(code => {
    const val = raw[code];
    return total > 0 ? Math.round((val / total) * 100) : 0;
  });
  const sumExceptLast = pcts.slice(0, -1).reduce((a, b) => a + b, 0);
  if (pcts.length > 0) pcts[pcts.length - 1] = 100 - sumExceptLast;

  container.innerHTML = codes.map((code, i) => {
    const info = ALL_COUNTRIES.find(c => c.code === code) || {flag:'🌐', label:code};
    const val = raw[code];
    return `<div class="weight-row" data-code="${code}">
      <div class="weight-header"><label>${info.flag} ${code}</label><span class="weight-val">${pcts[i]}%</span></div>
      <input type="range" min="0" max="100" value="${val}" data-code="${code}">
    </div>`;
  }).join('');

  container.querySelectorAll('input[type=range]').forEach(slider => {
    updateSliderFill(slider);
    slider.addEventListener('input', function() {
      updateSliderFill(this);
      updateNationalityWeight(this.dataset.code, this.value);
    });
  });
}

function updateNationalityWeight(code, val) {
  advState.nationalityWeights[code] = parseInt(val);
  renderNationalityWeights();
}

function presetNationality(type) {
  if (type === 'uniform') {
    advState.selectedCountries = new Set(ALL_COUNTRIES.map(c => c.code));
    const w = {};
    ALL_COUNTRIES.forEach(c => { w[c.code] = 100; });
    advState.nationalityWeights = w;
  } else if (type === 'population') {
    advState.selectedCountries = new Set(ALL_COUNTRIES.map(c => c.code));
    const w = {};
    const maxPop = Math.max(...ALL_COUNTRIES.map(c => POP_WEIGHTS[c.code] || 0.001));
    ALL_COUNTRIES.forEach(c => {
      w[c.code] = Math.max(1, Math.round(((POP_WEIGHTS[c.code] || 0.001) / maxPop) * 100));
    });
    advState.nationalityWeights = w;
  }
  renderNationalityTags();
  updateAdvSummary();
}

function renderWeightSliders(containerId, groups, weights, onChange) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const total = Object.values(weights).reduce((a, b) => a + b, 0);

  const pcts = groups.map(g => {
    const val = weights[g.id] ?? 0;
    return total > 0 ? Math.round((val / total) * 100) : 0;
  });
  const sumExceptLast = pcts.slice(0, -1).reduce((a, b) => a + b, 0);
  if (pcts.length > 0) pcts[pcts.length - 1] = 100 - sumExceptLast;

  const existing = container.querySelectorAll('.weight-row');
  if (existing.length === groups.length) {
    existing.forEach((row, i) => {
      const g = groups[i];
      const val = weights[g.id] ?? 0;
      const labelEl = row.querySelector('.weight-val');
      if (labelEl) labelEl.textContent = `${pcts[i]}%`;
      const sliderEl = row.querySelector('input[type=range]');
      if (sliderEl && document.activeElement !== sliderEl) {
        sliderEl.value = val;
        updateSliderFill(sliderEl);
      }
    });
    return;
  }

  container.innerHTML = groups.map((g, i) => {
    const val = weights[g.id] ?? 0;
    return `<div class="weight-row" data-group-id="${g.id}">
      <div class="weight-header"><label>${g.label}</label><span class="weight-val">${pcts[i]}%</span></div>
      <input type="range" min="0" max="100" value="${val}"
        data-on-change="${onChange}" data-id="${g.id}">
    </div>`;
  }).join('');

  container.querySelectorAll('input[type=range]').forEach(slider => {
    updateSliderFill(slider);
    slider.addEventListener('input', function() {
      updateSliderFill(this);
      const fn = this.dataset.onChange;
      const id = this.dataset.id;
      if (window[fn]) window[fn](id, this.value);
    });
  });
}

function updateAgeWeight(id, val) {
  advState.ageWeights[id] = parseInt(val);
  renderWeightSliders('age-weights', AGE_GROUPS, advState.ageWeights, 'updateAgeWeight');
  updateAdvSummary();
}

function updateGenderWeight(id, val) {
  advState.genderWeights[id] = parseInt(val);
  renderWeightSliders('gender-weights', GENDER_GROUPS, advState.genderWeights, 'updateGenderWeight');
  updateAdvSummary();
}

function updateIncomeWeight(id, val) {
  advState.incomeWeights[id] = parseInt(val);
  renderWeightSliders('income-weights', INCOME_GROUPS, advState.incomeWeights, 'updateIncomeWeight');
  updateAdvSummary();
}

function updateLocationWeight(id, val) {
  advState.locationWeights[id] = parseInt(val);
  renderWeightSliders('location-weights', LOCATION_GROUPS, advState.locationWeights, 'updateLocationWeight');
  updateAdvSummary();
}

function renderTagSelector(containerId, items, selectedSet, toggleFn) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = items.map(item => `
    <span class="tag-pill${selectedSet.has(item.id) ? ' selected' : ''}"
          onclick="${toggleFn}('${item.id}')">
      ${item.label}
    </span>
  `).join('');
}

// ---------------------------------------------------------------------------
// Occupation selector
// ---------------------------------------------------------------------------

function filterOccupations(query) {
  const groupsEl = document.getElementById('occupation-groups');
  if (!groupsEl) return;
  const q = (query || '').toLowerCase().trim();

  if (!q) { groupsEl.classList.add('hidden'); return; }

  const matches = OCCUPATIONS_FLAT.filter(o =>
    o.label.toLowerCase().includes(q) ||
    (o.label_local && o.label_local.toLowerCase().includes(q)) ||
    o.categoryLabel.toLowerCase().includes(q)
  ).slice(0, 40);

  if (!matches.length) { groupsEl.classList.add('hidden'); return; }

  groupsEl.innerHTML = matches.map(o => {
    const sel = advState.selectedOccupations.has(o.id);
    const localTag = o.label_local ? ` <span class="text-slate-500 text-xs">${escHtml(o.label_local)}</span>` : '';
    return `<div class="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-600 cursor-pointer text-sm ${sel ? 'text-brand-400' : 'text-white'}"
                 onclick="selectOccupation('${o.id}')">
              <span class="text-slate-500 text-xs w-28 flex-shrink-0">${escHtml(o.categoryLabel)}</span>
              <span>${escHtml(o.label)}</span>${localTag}
              ${sel ? '<span class="ml-auto text-brand-400 text-xs">✓</span>' : ''}
            </div>`;
  }).join('');
  groupsEl.classList.remove('hidden');
}

function selectOccupation(id) {
  if (advState.selectedOccupations.has(id)) {
    advState.selectedOccupations.delete(id);
  } else {
    advState.selectedOccupations.add(id);
  }
  const searchEl = document.getElementById('occupation-search');
  filterOccupations(searchEl ? searchEl.value : '');
  renderSelectedOccupations();
  updateAdvSummary();
}

function renderSelectedOccupations() {
  const container = document.getElementById('occupation-tags');
  if (!container) return;
  const selected = [...advState.selectedOccupations];
  if (!selected.length) {
    container.innerHTML = '<span class="text-xs text-slate-600">All occupations (none selected)</span>';
    return;
  }
  container.innerHTML = selected.map(id => {
    const occ = OCCUPATIONS_FLAT.find(o => o.id === id);
    const label = occ ? occ.label : id;
    return `<span class="tag-pill selected" onclick="selectOccupation('${id}')">${escHtml(label)} ×</span>`;
  }).join('');
}

function toggleOccupation(id) { selectOccupation(id); }

function togglePersonality(id) {
  if (advState.selectedPersonalities.has(id)) advState.selectedPersonalities.delete(id);
  else advState.selectedPersonalities.add(id);
  renderTagSelector('personality-tags', PERSONALITY_TYPES, advState.selectedPersonalities, 'togglePersonality');
  updateAdvSummary();
}

function resetAdvanced() {
  advState = {
    selectedCountries: new Set(),
    nationalityWeights: {},
    ageWeights: {...DEFAULT_AGE_WEIGHTS},
    genderWeights: {...DEFAULT_GENDER_WEIGHTS},
    incomeWeights: {...DEFAULT_INCOME_WEIGHTS},
    locationWeights: {...DEFAULT_LOCATION_WEIGHTS},
    selectedOccupations: new Set(),
    selectedPersonalities: new Set(),
  };
  renderAllAdvanced();
  updateAdvSummary();
}

function renderAllAdvanced() {
  renderNationalityTags();
  renderWeightSliders('age-weights', AGE_GROUPS, advState.ageWeights, 'updateAgeWeight');
  renderWeightSliders('gender-weights', GENDER_GROUPS, advState.genderWeights, 'updateGenderWeight');
  renderWeightSliders('income-weights', INCOME_GROUPS, advState.incomeWeights, 'updateIncomeWeight');
  renderWeightSliders('location-weights', LOCATION_GROUPS, advState.locationWeights, 'updateLocationWeight');
  renderSelectedOccupations();
  renderTagSelector('personality-tags', PERSONALITY_TYPES, advState.selectedPersonalities, 'togglePersonality');
}

// ---------------------------------------------------------------------------
// Market → Nationality linkage
// ---------------------------------------------------------------------------
const MARKET_NATIONALITY_PRESETS = {
  global: null,
  us: { countries: ['US'], weights: { US: 100 } },
  cn: { countries: ['CN'], weights: { CN: 100 } },
  jp: { countries: ['JP'], weights: { JP: 100 } },
  kr: { countries: ['KR'], weights: { KR: 100 } },
  in: { countries: ['IN'], weights: { IN: 100 } },
  de: { countries: ['DE'], weights: { DE: 100 } },
  fr: { countries: ['FR'], weights: { FR: 100 } },
  gb: { countries: ['GB'], weights: { GB: 100 } },
  br: { countries: ['BR'], weights: { BR: 100 } },
  asia: {
    countries: ['CN','JP','KR','IN','ID','TH','VN','PH','SG'],
    weights:   { CN:30, JP:15, KR:8, IN:20, ID:10, TH:6, VN:5, PH:4, SG:2 }
  },
  europe: {
    countries: ['DE','FR','GB','IT','ES'],
    weights:   { DE:25, FR:20, GB:20, IT:18, ES:17 }
  },
  latam: { countries: ['BR','MX','AR'], weights: { BR:50, MX:35, AR:15 } },
  africa: { countries: ['NG','ZA','EG'], weights: { NG:40, ZA:30, EG:30 } },
  mena: { countries: ['SA','EG','TR'], weights: { SA:40, EG:35, TR:25 } },
  developed: {
    countries: ['US','DE','JP','GB','AU','FR','KR','SG'],
    weights:   { US:30, DE:12, JP:15, GB:12, AU:5, FR:10, KR:10, SG:6 }
  },
  emerging: {
    countries: ['CN','IN','BR','ID','MX','NG','TR','VN','EG','TH'],
    weights:   { CN:25, IN:25, BR:12, ID:10, MX:8, NG:6, TR:5, VN:4, EG:3, TH:2 }
  },
};

function applyMarketNationalityPreset(marketVal) {
  const preset = MARKET_NATIONALITY_PRESETS[marketVal];
  if (preset === undefined) return;
  if (preset === null) {
    presetNationality('population');
  } else {
    advState.selectedCountries = new Set(preset.countries);
    const w = {};
    preset.countries.forEach(c => { w[c] = preset.weights[c] ?? 10; });
    advState.nationalityWeights = w;
    renderNationalityTags();
    updateAdvSummary();
  }
}

const marketEl = document.getElementById('input-market');
if (marketEl) {
  marketEl.addEventListener('change', function() {
    applyMarketNationalityPreset(this.value);
    loadLocationsForMarket(this.value);
  });
}

// ---------------------------------------------------------------------------
// Advanced panel toggle
// ---------------------------------------------------------------------------
const advPanel = document.getElementById('adv-panel');
const advIcon  = document.querySelector('.adv-toggle-icon');

const advToggle = document.getElementById('adv-toggle');
if (advToggle) {
  advToggle.addEventListener('click', () => {
    if (!advPanel) return;
    const isOpen = advPanel.classList.toggle('open');
    if (advIcon) advIcon.classList.toggle('open', isOpen);
  });
}

const btnResetAdv = document.getElementById('btn-reset-adv');
if (btnResetAdv) btnResetAdv.addEventListener('click', resetAdvanced);

// ---------------------------------------------------------------------------
// URL Content Extraction
// ---------------------------------------------------------------------------
const btnExtractUrl = document.getElementById('btn-extract-url');
const inputUrl = document.getElementById('input-url');
if (btnExtractUrl) btnExtractUrl.addEventListener('click', extractUrlContent);

// Auto-detect URL paste into content textarea
const inputContent = document.getElementById('input-content');
if (inputContent) {
  inputContent.addEventListener('paste', (e) => {
    setTimeout(() => {
      const val = inputContent.value.trim();
      if (/^https?:\/\/\S+$/.test(val) && inputUrl) {
        inputUrl.value = val;
        inputContent.value = '';
        extractUrlContent();
      }
    }, 50);
  });
}

async function extractUrlContent() {
  const url = inputUrl?.value?.trim();
  if (!url) return;

  const statusEl = document.getElementById('url-extract-status');
  const contentEl = document.getElementById('input-content');
  const btn = document.getElementById('btn-extract-url');

  // Show loading
  if (statusEl) {
    statusEl.classList.remove('hidden');
    statusEl.className = 'mb-2 px-3 py-2 rounded-lg text-xs bg-brand-700/20 border border-brand-600/30 text-brand-300';
    statusEl.textContent = 'Extracting content…';
  }
  if (btn) { btn.disabled = true; btn.textContent = '…'; }

  try {
    const data = await apiFetch('/api/extract-url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });

    if (contentEl && data.text) {
      // Prepend source info, then extracted text
      const meta = data.metadata || {};
      let header = '';
      if (meta.title) header += `[${meta.title}]\n`;
      if (meta.source === 'youtube' && meta.channel) header += `Channel: ${meta.channel}\n`;
      if (meta.source === 'web' && meta.author) header += `Author: ${meta.author}\n`;
      header += `Source: ${url}\n---\n`;

      contentEl.value = header + data.text;
    }

    if (statusEl) {
      const meta = data.metadata || {};
      const source = meta.source === 'youtube' ? 'YouTube subtitles' : 'article text';
      const chars = data.text?.length || 0;
      statusEl.className = 'mb-2 px-3 py-2 rounded-lg text-xs bg-green-900/30 border border-green-700/30 text-green-400';
      statusEl.innerHTML = `Extracted ${chars.toLocaleString()} chars from ${escHtml(source)}${meta.title ? ' — <strong>' + escHtml(meta.title) + '</strong>' : ''}`;
    }
  } catch (err) {
    if (statusEl) {
      statusEl.className = 'mb-2 px-3 py-2 rounded-lg text-xs bg-red-900/30 border border-red-700/30 text-red-400';
      statusEl.textContent = 'Extraction failed: ' + (err.message || err);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Extract'; }
  }
}

// ---------------------------------------------------------------------------
// Prompt Preview
// ---------------------------------------------------------------------------
const promptPreviewToggle = document.getElementById('prompt-preview-toggle');
const promptPreviewPanel = document.getElementById('prompt-preview-panel');
const promptPreviewIcon = document.querySelector('.prompt-preview-icon');
if (promptPreviewToggle) {
  promptPreviewToggle.addEventListener('click', () => {
    if (!promptPreviewPanel) return;
    const isNowHidden = promptPreviewPanel.classList.toggle('hidden');
    if (promptPreviewIcon) promptPreviewIcon.style.transform = isNowHidden ? '' : 'rotate(180deg)';
    // Auto-load every time the panel opens
    if (!isNowHidden) {
      loadPromptPreview();
    }
  });
}
const btnRefreshPrompt = document.getElementById('btn-refresh-prompt');
if (btnRefreshPrompt) btnRefreshPrompt.addEventListener('click', loadPromptPreview);

async function loadPromptPreview() {
  const sysEl = document.getElementById('prompt-preview-system');
  const userEl = document.getElementById('prompt-preview-user');
  const personaEl = document.getElementById('prompt-preview-persona');
  if (!sysEl || !userEl) return;

  sysEl.textContent = 'Loading…';
  userEl.textContent = '';

  const content = document.getElementById('input-content')?.value || '';
  const scenario = document.getElementById('input-scenario-context')?.value || '';
  const market = document.getElementById('input-market')?.value || 'global';
  const language = document.getElementById('input-language')?.value || 'English';
  // Get research type from global state (set by selectPreset())
  const researchType = (typeof _selectedPreset !== 'undefined' && _selectedPreset && _selectedPreset !== 'custom')
    ? _selectedPreset : 'product_purchase';

  try {
    const data = await apiFetch('/api/prompt-preview', {
      method: 'POST',
      body: JSON.stringify({ content, scenario_context: scenario, market, research_type: researchType, language }),
    });
    sysEl.textContent = data.system_prompt || '';
    userEl.textContent = data.user_prompt || '';
    if (data.sample_persona && personaEl) {
      const sp = data.sample_persona;
      personaEl.textContent = `Sample persona: ${sp.flag || ''} ${sp.name || 'Anonymous'}, ${sp.age}y ${sp.gender}, ${sp.nationality}, ${sp.occupation_title || ''} ${sp.mbti ? '(' + sp.mbti + ')' : ''}`;
    }
  } catch (err) {
    sysEl.textContent = 'Error: ' + err.message;
  }
}

// ---------------------------------------------------------------------------
// Persona Preview
// ---------------------------------------------------------------------------
const btnPreview = document.getElementById('btn-preview');
if (btnPreview) btnPreview.addEventListener('click', previewPersonas);

async function previewPersonas() {
  const btn = document.getElementById('btn-preview');
  const grid = document.getElementById('persona-preview-grid');
  if (!btn || !grid) return;

  btn.disabled = true;
  btn.innerHTML = `<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Loading…`;

  grid.innerHTML = Array(5).fill(0).map(() => `
    <div class="persona-card">
      <div class="flex items-center gap-3 mb-3">
        <div class="skeleton w-8 h-8 rounded-full"></div>
        <div class="flex-1">
          <div class="skeleton h-4 w-24 mb-1"></div>
          <div class="skeleton h-3 w-16"></div>
        </div>
      </div>
      <div class="skeleton h-3 w-full mb-1"></div>
      <div class="skeleton h-3 w-4/5 mb-1"></div>
      <div class="skeleton h-3 w-3/5"></div>
    </div>
  `).join('');

  try {
    const market = document.getElementById('input-market')?.value || 'global';
    const dim = buildDimensionConfig();
    const body = { count: 5, market };
    if (dim) body.dimensions = dim;
    const personas = await apiFetch('/api/personas', { method: 'POST', body: JSON.stringify(body) });
    grid.innerHTML = personas.map(renderPersonaCard).join('');
  } catch (err) {
    grid.innerHTML = `<p class="text-red-400 text-sm col-span-full">Failed to load preview: ${escHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg> Preview Personas`;
  }
}

function renderPersonaCard(p) {
  const genderIcon = p.gender === 'male' ? '♂' : p.gender === 'female' ? '♀' : '⚧';
  const incomeLabel = p.income_display
    ? p.income_display.replace('Income: ', '')
    : ({
        'low':          '< $20k/yr',
        'lower-middle': '$20k–$50k',
        'middle':       '$50k–$100k',
        'upper-middle': '$100k–$200k',
        'high':         '$200k+',
      }[p.income_bracket] || p.income_bracket);

  const occDisplay = p.occupation_label || p.occupation_title || p.occupation_id || 'Unknown';
  const locationLabel = p.city_tier_label || p.urban_rural || '';
  const locationBadge = locationLabel ? `<div class="text-xs text-slate-500 mt-0.5">📍 ${escHtml(locationLabel)}</div>` : '';
  const eduBadge = p.occupation_education ? `<div class="text-xs text-slate-600 mt-0.5">🎓 ${escHtml(p.occupation_education)}</div>` : '';
  const ptLabel = (p.personality_type || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  const bgText = p.personal_background || '';

  return `
  <div class="persona-card">
    <div class="flex items-start gap-2 mb-2">
      <span class="text-xl">${p.flag || '🌐'}</span>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-1.5">
          <span class="font-semibold text-sm text-white">${escHtml(p.name || 'Unknown')}</span>
          <span class="text-slate-500 text-xs">${genderIcon}</span>
        </div>
        <div class="text-xs text-slate-400">${p.country_name}, ${p.age} yrs</div>
      </div>
    </div>
    <div class="text-xs text-slate-400 mb-1">${escHtml(occDisplay)}</div>
    <div class="text-xs text-slate-500 mb-1">${escHtml(incomeLabel)}</div>
    ${locationBadge}${eduBadge}
    <div class="flex flex-wrap gap-1 my-2">
      <span class="inline-block text-xs px-2 py-0.5 bg-surface-700 text-brand-400 rounded-full">${ptLabel}</span>${p.mbti ? `<span class="inline-block text-xs px-2 py-0.5 bg-surface-700 text-violet-400 rounded-full">${escHtml(p.mbti)}</span>` : ''}
    </div>
    <div class="space-y-1.5 mb-2">
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-12 flex-shrink-0">Price</span>
        <div class="cog-bar-track"><div class="cog-bar-fill" style="width:${Math.round((p.price_sensitivity||0)*100)}%"></div></div>
        <span class="text-xs text-slate-400 w-8 text-right">${Math.round((p.price_sensitivity||0)*100)}%</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-12 flex-shrink-0">Risk</span>
        <div class="cog-bar-track"><div class="cog-bar-fill" style="width:${Math.round((p.risk_appetite||0)*100)}%; background: linear-gradient(90deg, #f59e0b, #ef4444)"></div></div>
        <span class="text-xs text-slate-400 w-8 text-right">${Math.round((p.risk_appetite||0)*100)}%</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-12 flex-shrink-0">Novel</span>
        <div class="cog-bar-track"><div class="cog-bar-fill" style="width:${Math.round((p.novelty_seeking||0)*100)}%; background: linear-gradient(90deg, #a78bfa, #ec4899)"></div></div>
        <span class="text-xs text-slate-400 w-8 text-right">${Math.round((p.novelty_seeking||0)*100)}%</span>
      </div>
    </div>
    <div class="flex gap-2 mb-2">
      <div class="flex-1 px-2 py-1 bg-surface-800 rounded text-center">
        <div class="text-xs text-slate-500">Decision</div>
        <div class="text-xs font-medium text-slate-200">${escHtml(p.decision_style || '—')}</div>
      </div>
      <div class="flex-1 px-2 py-1 bg-surface-800 rounded text-center">
        <div class="text-xs text-slate-500">Trust</div>
        <div class="text-xs font-medium text-slate-200">${escHtml(p.trust_chain || '—')}</div>
      </div>
    </div>
    ${bgText ? `<p class="text-xs text-slate-500 mb-1 leading-relaxed">${escHtml(bgText)}</p>` : ''}
    <p class="text-xs text-slate-400 italic">"${escHtml(p.vibe || '')}"</p>
  </div>`;
}

// ---------------------------------------------------------------------------
// Evaluation Preset System (v2: 6 presets + Custom)
// ---------------------------------------------------------------------------

const EVAL_PRESETS = [
  {
    id: 'product_purchase',
    emoji: '🛒',
    label: 'Product Purchase',
    desc_zh: '买不买',
    desc_en: 'Would you buy this? Evaluate purchase intent, price acceptance, and key decision factors.',
    scenario_hint: 'You encounter this product listing while shopping online.',
    dimensions: ['purchase_decision', 'pay_willingness', 'overall_impression'],
  },
  {
    id: 'social_follow',
    emoji: '📱',
    label: 'Social Follow',
    desc_zh: '关不关注',
    desc_en: 'Would you follow or subscribe? Evaluate content value, credibility, and follow intent.',
    scenario_hint: 'You are scrolling through your social feed and discover this account for the first time.',
    dimensions: ['follow_subscribe', 'overall_impression', 'share_willingness'],
  },
  {
    id: 'content_reaction',
    emoji: '👀',
    label: 'Content Reaction',
    desc_zh: '看不看',
    desc_en: 'Would you watch/read this? Evaluate attention capture and engagement intent.',
    scenario_hint: 'You see this content recommended in your feed.',
    dimensions: ['overall_impression', 'share_willingness', 'follow_subscribe'],
  },
  {
    id: 'app_trial',
    emoji: '📲',
    label: 'App / Service Trial',
    desc_zh: '试不试',
    desc_en: 'Would you try this app or service? Evaluate trial intent and perceived value.',
    scenario_hint: 'You encounter this app or service for the first time.',
    dimensions: ['goal_match', 'pay_willingness', 'overall_impression'],
  },
  {
    id: 'concept_test',
    emoji: '💡',
    label: 'Concept Test',
    desc_zh: '怎么看',
    desc_en: 'What do you think of this concept overall? Evaluate general sentiment and resonance.',
    scenario_hint: 'You are asked to give honest feedback on a new concept.',
    dimensions: ['overall_impression', 'goal_match', 'share_willingness'],
  },
  {
    id: 'competitive_switch',
    emoji: '🔄',
    label: 'Competitive Switch',
    desc_zh: '换不换',
    desc_en: 'Would you switch from your current solution to this? Evaluate switching intent and pain points.',
    scenario_hint: 'You are currently using a competing product/service.',
    dimensions: ['purchase_decision', 'goal_match', 'pay_willingness'],
  },
];

// Research type → human-readable label
function getResearchTypeLabel(rt) {
  const map = {
    'product_purchase':   '🛒 Product Purchase',
    'social_follow':      '📱 Social Follow',
    'content_reaction':   '👀 Content Reaction',
    'app_trial':          '📲 App/Service Trial',
    'concept_test':       '💡 Concept Test',
    'competitive_switch': '🔄 Competitive Switch',
  };
  return map[rt] || rt;
}

// Intent label config per research type — maps backend research_type → display labels
const INTENT_LABEL_CONFIG = {
  'product_purchase': {
    breakdownTitle: 'Purchase Intent Breakdown',
    slot1Label: 'Buy',       slot1Desc: 'would buy',
    slot2Label: 'Hesitate',
    rateLabel: 'Buy Rate',   rateLabelCn: '购买率',
  },
  'social_follow': {
    breakdownTitle: 'Follow Intent Breakdown',
    slot1Label: 'Follow',    slot1Desc: 'would follow',
    slot2Label: 'Consider',
    rateLabel: 'Follow Rate', rateLabelCn: '关注率',
  },
  'content_reaction': {
    breakdownTitle: 'Content Reaction Breakdown',
    slot1Label: 'Watch',     slot1Desc: 'would watch/read',
    slot2Label: 'Maybe',
    rateLabel: 'Watch Rate',  rateLabelCn: '观看率',
  },
  'app_trial': {
    breakdownTitle: 'Trial Intent Breakdown',
    slot1Label: 'Trial',     slot1Desc: 'would try',
    slot2Label: 'Consider',
    rateLabel: 'Trial Rate',  rateLabelCn: '试用率',
  },
  'concept_test': {
    breakdownTitle: 'Concept Resonance Breakdown',
    slot1Label: 'Resonates', slot1Desc: 'concept resonates',
    slot2Label: 'Hesitate',
    rateLabel: 'Resonance Rate', rateLabelCn: '共鸣率',
  },
  'competitive_switch': {
    breakdownTitle: 'Switch Intent Breakdown',
    slot1Label: 'Switch',    slot1Desc: 'would switch',
    slot2Label: 'Consider',
    rateLabel: 'Switch Rate', rateLabelCn: '转换率',
  },
};

// Custom preset state
let _customPreset = {
  purpose: '',      // research purpose textarea
  dimensions: [],   // [{id, label, desc}] - user-configured custom dimensions
  llmGenerated: false,
};

let _selectedPreset = 'product_purchase';  // preset ID or 'custom'

const EVAL_DIMENSIONS_MAP = {
  'follow_subscribe':   {emoji:'📱', label:'关注/订阅意愿',  desc:'Would you follow/subscribe?'},
  'pay_willingness':    {emoji:'💰', label:'付费意愿',        desc:'Would you pay for this?'},
  'share_willingness':  {emoji:'🔄', label:'分享意愿',        desc:'Would you share this?'},
  'overall_impression': {emoji:'⭐', label:'整体印象',        desc:'Overall impression (1-10)'},
  'goal_match':         {emoji:'🎯', label:'目标匹配',        desc:'Does this solve your problem?'},
  'purchase_decision':  {emoji:'🏪', label:'购买决策',        desc:'Would you buy this?'},
};

// Get the intent breakdown dimensions for a given research type
function getBreakdownDimensions(researchType) {
  const preset = EVAL_PRESETS.find(p => p.id === researchType);
  if (!preset) return [];
  return (preset.dimensions || []).map(dimId => {
    const dim = EVAL_DIMENSIONS_MAP[dimId];
    return dim ? { ...dim, id: dimId } : { emoji: '•', label: dimId, id: dimId };
  });
}

// Render the breakdown preview panel below the preset selector
function renderBreakdownPreview() {
  const container = document.getElementById('preset-breakdown-preview');
  if (!container) return;

  if (_selectedPreset === 'custom') {
    container.innerHTML = '';
    container.classList.add('hidden');
    return;
  }

  const preset = EVAL_PRESETS.find(p => p.id === _selectedPreset);
  if (!preset) {
    container.innerHTML = '';
    container.classList.add('hidden');
    return;
  }

  const dims = getBreakdownDimensions(_selectedPreset);
  const intentCfg = INTENT_LABEL_CONFIG[_selectedPreset] || {};
  const slot1 = intentCfg.slot1Label || 'Yes';
  const slot2 = intentCfg.slot2Label || 'Maybe';

  container.classList.remove('hidden');
  container.innerHTML = `
    <div class="space-y-3">
      <div class="text-xs text-slate-400 leading-relaxed">${escHtml(preset.desc_en)}</div>

      <div>
        <div class="text-xs text-slate-500 mb-1.5">Decision Output <span class="text-slate-600">/ 决策输出 — LLM 为每个 persona 三选一:</span></div>
        <div class="flex gap-2">
          <span class="inline-flex items-center gap-1 px-2.5 py-1 bg-green-900/30 border border-green-700/40 rounded-lg text-xs text-green-400 font-medium">🟢 ${escHtml(slot1)}</span>
          <span class="inline-flex items-center gap-1 px-2.5 py-1 bg-yellow-900/30 border border-yellow-700/40 rounded-lg text-xs text-yellow-400 font-medium">🟡 ${escHtml(slot2)}</span>
          <span class="inline-flex items-center gap-1 px-2.5 py-1 bg-red-900/30 border border-red-700/40 rounded-lg text-xs text-red-400 font-medium">🔴 Pass</span>
        </div>
      </div>

      <div>
        <div class="text-xs text-slate-500 mb-1.5">Evaluation Focus <span class="text-slate-600">/ 评估角度 — 引导 LLM 从这些角度展开分析:</span></div>
        <div class="flex flex-wrap gap-1.5">
          ${dims.map(d => `<span class="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-800 border border-surface-600 rounded text-xs text-slate-300">${d.emoji} ${escHtml(d.label)}</span>`).join('')}
        </div>
      </div>
    </div>`;
}

function renderEvalPresets() {
  const container = document.getElementById('eval-preset-list');
  if (!container) return;

  const presetHtml = EVAL_PRESETS.map(p => {
    const sel = _selectedPreset === p.id;
    return `<button type="button"
      class="eval-preset-btn ${sel ? 'selected' : ''}"
      onclick="selectPreset('${p.id}')">
        <span class="text-lg">${p.emoji}</span>
        <div class="text-left">
          <div class="text-xs font-medium text-white">${p.label}</div>
          <div class="text-xs text-slate-500">${p.desc_zh}</div>
        </div>
      </button>`;
  }).join('');

  const customSel = _selectedPreset === 'custom';
  const customHtml = `<button type="button"
    class="eval-preset-btn ${customSel ? 'selected' : ''}"
    onclick="selectPreset('custom')">
      <span class="text-lg">✏️</span>
      <div class="text-left">
        <div class="text-xs font-medium text-white">Custom</div>
        <div class="text-xs text-slate-500">自定义</div>
      </div>
    </button>`;

  container.innerHTML = presetHtml + customHtml;

  // Render breakdown preview
  renderBreakdownPreview();

  // Render custom panel
  renderCustomPresetPanel();
}

function selectPreset(id) {
  _selectedPreset = id;
  renderEvalPresets();
}

function renderCustomPresetPanel() {
  const panel = document.getElementById('eval-custom-panel');
  if (!panel) return;
  if (_selectedPreset !== 'custom') {
    panel.classList.add('hidden');
    return;
  }
  panel.classList.remove('hidden');
  renderCustomDimensions();
}

async function generateDimensionsFromPurpose() {
  const purposeEl = document.getElementById('custom-purpose');
  if (!purposeEl) return;
  const purpose = purposeEl.value.trim();
  if (!purpose) { showMsg('Please describe your research purpose first.', 'error'); return; }

  const btn = document.getElementById('btn-gen-dimensions');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }

  try {
    // Call a lightweight local inference to generate dimensions
    // We simulate this by calling the settings-configured backend for a quick generation
    // For now, generate sensible defaults based on purpose keywords
    const dims = _inferDimensionsFromPurpose(purpose);
    _customPreset.purpose = purpose;
    _customPreset.dimensions = dims;
    _customPreset.llmGenerated = true;
    renderCustomDimensions();
  } catch(e) {
    showMsg(`Failed to generate dimensions: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ Auto-generate Dimensions'; }
  }
}

function _inferDimensionsFromPurpose(purpose) {
  // Rule-based inference from purpose keywords
  const p = purpose.toLowerCase();
  const dims = [];

  if (p.includes('buy') || p.includes('purchase') || p.includes('买')) {
    dims.push({id:'purchase_decision', label:'Purchase Decision', desc:'Would you buy this?'});
    dims.push({id:'pay_willingness', label:'Price Willingness', desc:'What price would you accept?'});
  }
  if (p.includes('follow') || p.includes('subscribe') || p.includes('关注')) {
    dims.push({id:'follow_subscribe', label:'Follow Intent', desc:'Would you follow/subscribe?'});
  }
  if (p.includes('share') || p.includes('分享')) {
    dims.push({id:'share_willingness', label:'Share Willingness', desc:'Would you share this?'});
  }
  if (p.includes('brand') || p.includes('品牌') || p.includes('awareness')) {
    dims.push({id:'overall_impression', label:'Brand Impression', desc:'Overall impression (1-10)'});
  }
  if (p.includes('problem') || p.includes('solution') || p.includes('痛点') || p.includes('goal')) {
    dims.push({id:'goal_match', label:'Problem-Solution Fit', desc:'Does this solve your problem?'});
  }

  // Always include overall impression if nothing matched
  if (dims.length === 0) {
    dims.push({id:'overall_impression', label:'Overall Impression', desc:'Rate your overall impression (1-10)'});
    dims.push({id:'goal_match', label:'Relevance', desc:'How relevant is this to you?'});
  }
  // Cap at 4
  return dims.slice(0, 4);
}

function renderCustomDimensions() {
  const container = document.getElementById('custom-dimensions-list');
  if (!container) return;

  if (_customPreset.dimensions.length === 0) {
    container.innerHTML = `<p class="text-xs text-slate-600 italic">No dimensions yet. Add manually or generate from purpose above.</p>`;
    return;
  }

  container.innerHTML = _customPreset.dimensions.map((d, i) => `
    <div class="custom-dim-card">
      <div class="flex items-center justify-between gap-2">
        <div class="flex-1">
          <input type="text" value="${escHtml(d.label)}"
            class="bg-transparent text-sm text-white border-b border-surface-600 focus:border-brand-500 outline-none w-full"
            onchange="updateCustomDim(${i}, 'label', this.value)" />
          <input type="text" value="${escHtml(d.desc)}"
            class="bg-transparent text-xs text-slate-500 border-b border-transparent focus:border-surface-600 outline-none w-full mt-0.5"
            onchange="updateCustomDim(${i}, 'desc', this.value)" />
        </div>
        <button type="button" onclick="removeCustomDim(${i})"
          class="text-slate-600 hover:text-red-400 text-xs transition-colors flex-shrink-0">✕</button>
      </div>
    </div>
  `).join('');
}

function addCustomDim() {
  _customPreset.dimensions.push({id: `custom_${Date.now()}`, label: 'New Dimension', desc: 'Describe what to evaluate'});
  renderCustomDimensions();
}

function updateCustomDim(idx, field, value) {
  if (_customPreset.dimensions[idx]) {
    _customPreset.dimensions[idx][field] = value;
  }
}

function removeCustomDim(idx) {
  _customPreset.dimensions.splice(idx, 1);
  renderCustomDimensions();
}

// Build the evaluation payload for form submission
function buildEvalPayload() {
  if (_selectedPreset === 'custom') {
    const purpose = document.getElementById('custom-purpose')?.value?.trim() || '';
    const dimLabels = _customPreset.dimensions.map(d => `${d.label}: ${d.desc}`).join('\n');
    const customInstr = purpose + (dimLabels ? `\n\nEvaluation dimensions:\n${dimLabels}` : '');
    return {
      evaluation_criteria: [],
      custom_instructions: customInstr,
    };
  }

  const preset = EVAL_PRESETS.find(p => p.id === _selectedPreset);
  if (!preset) return { evaluation_criteria: [], custom_instructions: '' };

  return {
    evaluation_criteria: preset.dimensions,
    custom_instructions: `${preset.desc_en}\n\nScenario: ${preset.scenario_hint}`,
  };
}

// Wire up custom panel events
document.addEventListener('DOMContentLoaded', () => {
  const btnGenDims = document.getElementById('btn-gen-dimensions');
  if (btnGenDims) btnGenDims.addEventListener('click', generateDimensionsFromPurpose);

  const btnAddDim = document.getElementById('btn-add-dim');
  if (btnAddDim) btnAddDim.addEventListener('click', addCustomDim);

  // Old custom instructions toggle (keep for backward compat)
  const btn = document.getElementById('btn-custom-instr');
  const panel = document.getElementById('custom-instr-panel');
  const icon = document.getElementById('custom-instr-icon');
  if (btn && panel) {
    btn.addEventListener('click', () => {
      const isOpen = !panel.classList.contains('hidden');
      panel.classList.toggle('hidden', isOpen);
      if (icon) icon.textContent = isOpen ? '＋' : '－';
    });
  }
});

// ---------------------------------------------------------------------------
// File attachment state
// ---------------------------------------------------------------------------
let _attachedFiles = [];

function renderFileChips() {
  const container = document.getElementById('file-chips');
  if (!container) return;
  if (_attachedFiles.length === 0) { container.innerHTML = ''; return; }
  container.innerHTML = _attachedFiles.map((f, idx) => {
    const ext = f.name.split('.').pop().toLowerCase();
    const isImage = ['jpg','jpeg','png','webp','gif'].includes(ext);
    const isPdf   = ext === 'pdf';
    const isDoc   = ['docx','doc'].includes(ext);
    const isText  = ['txt','md'].includes(ext);
    const typeClass = isImage ? 'chip-image' : isPdf ? 'chip-pdf' : isDoc ? 'chip-word' : isText ? 'chip-text' : '';
    const icon = isImage ? '🖼️' : isPdf ? '📄' : isDoc ? '📝' : isText ? '📃' : '📎';
    const size = f.size < 1024 * 1024 ? `${(f.size / 1024).toFixed(0)} KB` : `${(f.size / 1024 / 1024).toFixed(1)} MB`;
    const thumbHtml = isImage ? `<img src="${URL.createObjectURL(f)}" class="w-6 h-6 rounded object-cover flex-shrink-0" alt="" />` : `<span class="chip-icon">${icon}</span>`;
    return `<div class="file-chip ${typeClass}">
      ${thumbHtml}
      <span class="chip-name" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
      <span class="text-xs text-slate-600 flex-shrink-0">${size}</span>
      <span class="chip-del" onclick="removeFile(${idx})" title="Remove">✕</span>
    </div>`;
  }).join('');
}

function removeFile(idx) {
  _attachedFiles.splice(idx, 1);
  renderFileChips();
}

function addFiles(fileList) {
  const ALLOWED = new Set(['pdf','jpg','jpeg','png','webp','gif','txt','md','docx','doc']);
  const MAX_BYTES = 50 * 1024 * 1024;
  for (const f of fileList) {
    const ext = f.name.split('.').pop().toLowerCase();
    if (!ALLOWED.has(ext)) { showMsg(`Unsupported file type: .${ext}`, 'error'); continue; }
    if (f.size > MAX_BYTES) { showMsg(`File too large (max 50 MB): ${f.name}`, 'error'); continue; }
    if (!_attachedFiles.find(x => x.name === f.name && x.size === f.size)) {
      _attachedFiles.push(f);
    }
  }
  renderFileChips();
}

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

if (fileInput) {
  fileInput.addEventListener('change', () => {
    addFiles(fileInput.files);
    fileInput.value = '';
  });
}
if (dropZone) {
  dropZone.addEventListener('dragenter', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
    document.getElementById('drop-overlay')?.classList.remove('hidden');
  });
  dropZone.addEventListener('dragover', e => { e.preventDefault(); });
  dropZone.addEventListener('dragleave', e => {
    if (!dropZone.contains(e.relatedTarget)) {
      dropZone.classList.remove('drag-over');
      document.getElementById('drop-overlay')?.classList.add('hidden');
    }
  });
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    document.getElementById('drop-overlay')?.classList.add('hidden');
    addFiles(e.dataTransfer.files);
  });
}

// ---------------------------------------------------------------------------
// New Run Form
// ---------------------------------------------------------------------------
const slider     = document.getElementById('input-personas');
const numInput   = document.getElementById('input-personas-num');
const countLabel = document.getElementById('persona-count-label');

if (slider) {
  updateSliderFill(slider);
  slider.addEventListener('input', () => {
    if (numInput) numInput.value = slider.value;
    if (countLabel) countLabel.textContent = slider.value;
    updateSliderFill(slider);
  });
}
if (numInput) {
  numInput.addEventListener('input', () => {
    const v = Math.min(200, Math.max(5, parseInt(numInput.value) || 5));
    if (slider) { slider.value = v; updateSliderFill(slider); }
    if (countLabel) countLabel.textContent = numInput.value;
  });
}

const runForm = document.getElementById('run-form');
if (runForm) {
  runForm.addEventListener('submit', async e => {
    e.preventDefault();
    const content = document.getElementById('input-content')?.value?.trim() || '';
    if (!content && _attachedFiles.length === 0) {
      showMsg('Please enter content or attach a file.', 'error');
      return;
    }

    // Vision capability check: block image uploads with non-vision models
    const hasImages = _attachedFiles.some(f => {
      const ext = f.name.split('.').pop().toLowerCase();
      return ['jpg','jpeg','png','webp','gif'].includes(ext);
    });
    if (hasImages) {
      const profileSel = document.getElementById('input-profile');
      if (profileSel) {
        const selectedOption = profileSel.options[profileSel.selectedIndex];
        const supportsVision = selectedOption?.dataset?.vision;
        if (supportsVision === 'false') {
          showMsg(
            'Selected model does not support image understanding. Please choose a vision-capable model or remove images from the task.',
            'error'
          );
          return;
        }
      }
    }

    const btn = document.getElementById('btn-submit');
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting...'; }
    showMsg('', '');

    try {
      const dim = buildDimensionConfig();
      const scenarioContext = document.getElementById('input-scenario-context')?.value?.trim() || '';
      const evalPayload = buildEvalPayload();

      const fd = new FormData();
      fd.append('content', content);
      fd.append('scenario_context', scenarioContext);
      fd.append('personas_count', String(parseInt(numInput?.value || '20') || 20));
      fd.append('market', document.getElementById('input-market')?.value || 'global');
      fd.append('concurrency', '0');  // 0 = use settings
      if (dim) fd.append('dimensions_json', JSON.stringify(dim));
      fd.append('evaluation_criteria_json', JSON.stringify(evalPayload.evaluation_criteria));
      if (evalPayload.custom_instructions) fd.append('custom_instructions', evalPayload.custom_instructions);
      const language = document.getElementById('input-language')?.value || 'English';
      fd.append('language', language);
      fd.append('research_type', _selectedPreset === 'custom' ? 'product_purchase' : _selectedPreset);
      // Append selected profile name
      const profileSel = document.getElementById('input-profile');
      if (profileSel && profileSel.value) fd.append('profile_name', profileSel.value);
      _attachedFiles.forEach(f => fd.append('files', f, f.name));

      const res = await apiFetchForm('/api/run', fd);

      const qid = document.getElementById('quick-task-id');
      if (qid) qid.textContent = res.task_id;
      document.getElementById('quick-result')?.classList.remove('hidden');
      showMsg('Task started!', 'success');

      _attachedFiles = [];
      renderFileChips();
      startPolling(res.task_id);
      setTimeout(() => showView('tasks'), 1200);
    } catch (err) {
      showMsg(`Error: ${err.message}`, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Run Research'; }
    }
  });
}

function showMsg(text, type) {
  const el = document.getElementById('submit-msg');
  if (!el) return;
  el.textContent = text;
  el.className = `text-sm ${type === 'error' ? 'text-red-400' : type === 'success' ? 'text-green-400' : 'text-slate-400'}`;
}

// ---------------------------------------------------------------------------
// Task List
// ---------------------------------------------------------------------------
let _pollTimers = {};

async function loadTasks() {
  const container = document.getElementById('task-list');
  if (!container) return;
  try {
    const tasks = await apiFetch('/api/tasks');
    if (!tasks || tasks.length === 0) {
      container.innerHTML = '<p class="text-slate-500 text-sm">No tasks yet. Run your first research!</p>';
      return;
    }
    container.innerHTML = tasks.map(renderTaskCard).join('');
    container.querySelectorAll('.task-card').forEach(card => {
      card.addEventListener('click', () => openDetail(card.dataset.id));
    });
    tasks.forEach(t => {
      if (t.status === 'running' || t.status === 'pending') startPolling(t.task_id);
    });
  } catch (err) {
    container.innerHTML = `<p class="text-red-400 text-sm">Failed to load tasks: ${err.message}</p>`;
  }
}

function renderTaskCard(task) {
  const progress = task.total_personas > 0 ? Math.round((task.completed_personas / task.total_personas) * 100) : 0;
  const isRunning = task.status === 'running' || task.status === 'pending';
  const created = new Date(task.created_at).toLocaleString();
  const snippet = (task.content || '').substring(0, 100) + (task.content?.length > 100 ? '…' : '');
  const durationStr = task.started_at && task.completed_at
    ? `${Math.round((new Date(task.completed_at) - new Date(task.started_at)) / 1000)}s` : '';

  return `
  <div class="task-card" data-id="${task.task_id}">
    <div class="flex items-start justify-between gap-4">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-1">
          <span class="badge badge-${task.status}">
            ${isRunning ? '<span class="pulse-dot"></span>' : ''}
            ${task.status}
          </span>
          <span class="text-xs text-slate-500 font-mono">${task.task_id}</span>
          ${durationStr ? `<span class="text-xs text-slate-600">${durationStr}</span>` : ''}
        </div>
        <p class="text-sm text-slate-300 truncate">${escHtml(snippet)}</p>
        <div class="flex flex-wrap items-center gap-3 mt-1">
          <span class="text-xs text-slate-500">🌐 ${task.market}</span>
          <span class="text-xs text-slate-500">👥 ${task.persona_count} personas</span>
          <span class="text-xs text-slate-500">${created}</span>
          ${task.research_type ? `<span class="text-xs text-brand-400">${escHtml(getResearchTypeLabel(task.research_type))}</span>` : ''}
          ${task.metadata?.llm_profile?.model ? `<span class="text-xs text-purple-400">🤖 ${escHtml(task.metadata.llm_profile.model)}</span>` : ''}
        </div>
      </div>
      <div class="text-right text-xs text-slate-400 flex-shrink-0">
        ${task.status === 'completed' ? `<span class="text-green-400">✓ Done</span>` : ''}
        ${task.status === 'failed' ? `<span class="text-red-400">✗ Failed</span>` : ''}
      </div>
    </div>
    ${isRunning && task.total_personas > 0 ? `
    <div class="mt-3">
      <div class="flex justify-between text-xs text-slate-500 mb-1">
        <span>Progress</span>
        <span>${task.completed_personas} / ${task.total_personas} (${progress}%)</span>
      </div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill" style="width:${progress}%"></div>
      </div>
    </div>` : ''}
  </div>`;
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
function startPolling(taskId) {
  if (_pollTimers[taskId]) return;
  _pollTimers[taskId] = setInterval(async () => {
    try {
      const data = await apiFetch(`/api/tasks/${taskId}`);
      const task = data.task || data;
      if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
        clearInterval(_pollTimers[taskId]);
        delete _pollTimers[taskId];
        const currentView = Object.entries(views).find(([, el]) => el && !el.classList.contains('hidden'))?.[0];
        if (currentView === 'tasks') loadTasks();
        if (currentView === 'detail') {
          const detailId = document.getElementById('view-detail')?.dataset.taskId;
          if (detailId === taskId) openDetail(taskId);
        }
      } else {
        const currentView = Object.entries(views).find(([, el]) => el && !el.classList.contains('hidden'))?.[0];
        if (currentView === 'tasks') loadTasks();
        if (currentView === 'detail') {
          const detailId = document.getElementById('view-detail')?.dataset.taskId;
          if (detailId === taskId) updateDetailProgress(taskId, task);
        }
      }
    } catch (_) {}
  }, POLL_INTERVAL);
}

// ---------------------------------------------------------------------------
// Dot Matrix Visualization
// ---------------------------------------------------------------------------

// Status → CSS class + color + tooltip
const DOT_STATUS_CONFIG = {
  pending:  { cls: 'dot-pending',  color: '#475569', label: 'Not started' },
  running:  { cls: 'dot-running',  color: '#38bdf8', label: 'Running' },
  retrying: { cls: 'dot-retrying', color: '#f59e0b', label: 'Retrying (error)' },
  failed:   { cls: 'dot-failed',   color: '#ef4444', label: 'Failed (max retries)' },
  done:     { cls: 'dot-done',     color: '#22c55e', label: 'Completed' },
};

let _dotPollTimers = {};
let _dotData = {};  // taskId -> {states: [...], personas: [...]}

function renderDotMatrix(containerId, states, personas, taskComplete) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (states.length === 0) {
    container.innerHTML = '<p class="text-xs text-slate-600">No persona data yet...</p>';
    return;
  }

  // Build a map of persona data by ID for hover cards.
  // Persona data may come embedded in state.persona (new backend) or from separate personas array (legacy).
  const personaMap = {};
  // First: from separate personas array (legacy path)
  if (personas) personas.forEach(p => { if (p.persona_id) personaMap[p.persona_id] = p; });
  // Then: from state.persona field (new path — overrides if both present)
  states.forEach(s => { if (s.persona) personaMap[s.persona_id] = s.persona; });

  // Count stats
  const counts = {pending:0, running:0, retrying:0, failed:0, done:0};
  states.forEach(s => { counts[s.status] = (counts[s.status] || 0) + 1; });

  const legendHtml = Object.entries(DOT_STATUS_CONFIG).map(([k, v]) => {
    if (!counts[k]) return '';
    return `<span class="flex items-center gap-1 text-xs text-slate-500">
      <span class="w-2.5 h-2.5 rounded-full inline-block" style="background:${v.color}"></span>
      ${v.label} (${counts[k]})
    </span>`;
  }).filter(Boolean).join('');

  // Render dots
  const dotsHtml = states.map(s => {
    const cfg = DOT_STATUS_CONFIG[s.status] || DOT_STATUS_CONFIG.pending;
    const animClass = (s.status === 'running' || s.status === 'retrying') ? ' dot-animate' : '';
    // Fallback title for accessibility (rich tooltip is rendered via JS)
    const persona = personaMap[s.persona_id];
    const titleText = persona ? `#${s.index + 1} ${persona.name || ''}` : `#${s.index + 1}`;

    return `<span class="dot ${cfg.cls}${animClass}"
      data-persona-id="${escHtml(s.persona_id)}"
      data-status="${s.status}"
      title="${escHtml(titleText)}"
      onmouseenter="showDotTooltip(event, '${escHtml(s.persona_id)}', '${s.status}', '${(s.error||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').substring(0,100)}', ${s.attempt || 0})"
      onmouseleave="hideDotTooltip()"></span>`;
  }).join('');

  const positionClass = taskComplete ? 'mt-8 pt-6 border-t border-surface-700' : '';

  container.innerHTML = `
    <div class="${positionClass}">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold text-slate-300">Persona Matrix</h3>
        <div class="flex flex-wrap gap-3">${legendHtml}</div>
      </div>
      <div class="dot-matrix">${dotsHtml}</div>
    </div>
  `;

  // Build tooltip element if not exists
  if (!document.getElementById('dot-tooltip')) {
    const tt = document.createElement('div');
    tt.id = 'dot-tooltip';
    tt.className = 'dot-tooltip hidden';
    document.body.appendChild(tt);
  }

  // Store maps for tooltip lookup
  container._personaMap = personaMap;
  container._statesMap = {};
  states.forEach(s => { container._statesMap[s.persona_id] = s; });
}

function showDotTooltip(event, personaId, status, error, attempt) {
  const tt = document.getElementById('dot-tooltip');
  if (!tt) return;

  // Find persona data from nearest dot-matrix container
  let personaMap = {}, statesMap = {};
  let el = event.target;
  while (el && !el._personaMap) el = el.parentElement;
  if (el) { personaMap = el._personaMap || {}; statesMap = el._statesMap || {}; }

  const persona = personaMap[personaId];
  const state = statesMap[personaId];
  const cfg = DOT_STATUS_CONFIG[status] || DOT_STATUS_CONFIG.pending;

  // ---- Persona card section ----
  let html = `<div class="dot-tooltip-header" style="border-color:${cfg.color}">`;
  html += `<span class="dot-tooltip-status" style="color:${cfg.color}">${cfg.label.toUpperCase()}</span>`;
  if (persona?.name) {
    html += `<span class="dot-tooltip-name">${escHtml(persona.name)}</span>`;
  } else {
    html += `<span class="dot-tooltip-name text-slate-500">#${(attempt||0)+1} ${escHtml(personaId.substring(0,8))}</span>`;
  }
  html += `</div>`;

  if (persona) {
    html += `<div class="dot-tooltip-section">`;
    // Demographics row
    const demoParts = [
      persona.country_name ? `🌍 ${persona.country_name}` : '',
      persona.age ? `${persona.age}y` : '',
      persona.gender || '',
    ].filter(Boolean);
    html += `<div class="dot-tooltip-row">${escHtml(demoParts.join(' · '))}</div>`;
    // Occupation
    if (persona.occupation_label || persona.occupation_title) {
      html += `<div class="dot-tooltip-row">💼 ${escHtml(persona.occupation_label || persona.occupation_title)}</div>`;
    }
    // Income
    if (persona.income_display) {
      html += `<div class="dot-tooltip-row dim">💰 ${escHtml(persona.income_display)}</div>`;
    }
    // Personality
    if (persona.personality_type) {
      html += `<div class="dot-tooltip-row dim">🧠 ${escHtml(persona.personality_type.replace(/_/g,' '))}${persona.mbti ? ' · ' + escHtml(persona.mbti) : ''}</div>`;
    }
    html += `</div>`;
  }

  // ---- Feedback section (only for completed personas with result data) ----
  if (status === 'done' && persona) {
    const intent = persona.purchase_intent;
    const nps = persona.nps_score;
    const sentiment = persona.sentiment_score;
    const verbatim = persona.verbatim;
    if (intent != null || nps != null) {
      html += `<div class="dot-tooltip-section" style="background:rgba(34,197,94,0.06)">`;
      // Intent + NPS + sentiment in one row
      const intentColors = {buy:'#22c55e', follow:'#22c55e', trial:'#22c55e', watch:'#22c55e', switch:'#22c55e',
                            hesitate:'#f59e0b', consider:'#f59e0b', maybe:'#f59e0b',
                            pass:'#ef4444'};
      const iColor = intentColors[intent] || '#94a3b8';
      let feedbackParts = [];
      if (intent) feedbackParts.push(`<span style="color:${iColor};font-weight:600">${escHtml(intent).toUpperCase()}</span>`);
      if (nps != null) feedbackParts.push(`NPS ${nps}/10`);
      if (sentiment != null) feedbackParts.push(`${sentiment >= 0 ? '+' : ''}${Number(sentiment).toFixed(2)}`);
      html += `<div class="dot-tooltip-row">${feedbackParts.join(' · ')}</div>`;
      // Verbatim (truncated)
      if (verbatim) {
        const vShort = verbatim.length > 80 ? verbatim.substring(0, 80) + '…' : verbatim;
        html += `<div class="dot-tooltip-row dim" style="font-style:italic;line-height:1.4">"${escHtml(vShort)}"</div>`;
      }
      html += `</div>`;
    }
  }

  // ---- Timing section (started_at / duration) — show what's available ----
  if (state) {
    const hasStarted = state.started_at != null;
    const hasDone = state.completed_at != null || state.llm_elapsed_ms != null;
    if (hasStarted || hasDone) {
      html += `<div class="dot-tooltip-section">`;
      if (hasStarted) {
        const startDate = new Date(state.started_at * 1000);
        const startStr = startDate.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        html += `<div class="dot-tooltip-row dim">🕐 Started ${escHtml(startStr)}</div>`;
      }
      if (state.llm_elapsed_ms != null) {
        const secs = (state.llm_elapsed_ms / 1000).toFixed(1);
        html += `<div class="dot-tooltip-row dim">⏳ Duration ${secs}s</div>`;
      } else if (hasStarted && status === 'running') {
        // Live duration for in-flight persona
        const elapsed = ((Date.now() / 1000) - state.started_at).toFixed(0);
        html += `<div class="dot-tooltip-row dim">⏳ Running ${elapsed}s…</div>`;
      }
      html += `</div>`;
    }
  }

  // ---- LLM call section (only for done/failed states with metadata) ----
  if (state && (state.llm_model || state.llm_prompt_tokens != null || state.llm_completion_tokens != null)) {
    html += `<div class="dot-tooltip-section dot-tooltip-llm">`;
    html += `<div class="dot-tooltip-label">LLM Call</div>`;
    if (state.llm_model) {
      html += `<div class="dot-tooltip-row">🤖 ${escHtml(state.llm_model)}</div>`;
    }
    if (state.llm_prompt_tokens != null || state.llm_completion_tokens != null) {
      const ptok = state.llm_prompt_tokens ?? '?';
      const ctok = state.llm_completion_tokens ?? '?';
      html += `<div class="dot-tooltip-row">🪙 ${ptok}+${ctok} tokens</div>`;
    }
    if (attempt > 0) {
      html += `<div class="dot-tooltip-row warn">⚠ Attempt #${attempt + 1}</div>`;
    }
    html += `</div>`;
  } else if (attempt > 0) {
    html += `<div class="dot-tooltip-row warn" style="padding:4px 8px">⚠ Attempt #${attempt + 1}</div>`;
  }

  // ---- Error section ----
  if (error) {
    html += `<div class="dot-tooltip-section dot-tooltip-error">`;
    html += `<div class="dot-tooltip-label">Error</div>`;
    html += `<div class="dot-tooltip-error-msg">${escHtml(error.substring(0, 150))}</div>`;
    html += `</div>`;
  }

  tt.innerHTML = html;
  tt.classList.remove('hidden');

  // Use viewport coordinates (position: fixed)
  const rect = event.target.getBoundingClientRect();
  const ttW = 220;
  let left = rect.right + 8;
  if (left + ttW > window.innerWidth) left = rect.left - ttW - 8;
  if (left < 0) left = 4;
  tt.style.left = `${left}px`;

  // Flip upward if tooltip would overflow viewport bottom
  const ttH = tt.offsetHeight || 200;
  let top = rect.top - 4;
  if (top + ttH > window.innerHeight) {
    top = rect.bottom - ttH + 4;
    if (top < 0) top = 4;
  }
  tt.style.top = `${top}px`;
}

function hideDotTooltip() {
  const tt = document.getElementById('dot-tooltip');
  if (tt) tt.classList.add('hidden');
}

async function startDotPolling(taskId) {
  if (_dotPollTimers[taskId]) return;

  const poll = async () => {
    try {
      const [states, taskData] = await Promise.all([
        apiFetch(`/api/tasks/${taskId}/persona-states`),
        apiFetch(`/api/tasks/${taskId}`),
      ]);
      const task = taskData.task || taskData;
      const isComplete = task.status === 'completed' || task.status === 'failed';

      const detailEl = document.getElementById('view-detail');
      if (detailEl && detailEl.dataset.taskId === taskId) {
        let effectiveStates = states || [];

        // Problem 3 fix: if no states yet but task is running/pending,
        // seed all N dots as pending so the matrix shows immediately
        if (effectiveStates.length === 0 && (task.status === 'running' || task.status === 'pending')) {
          const n = task.total_personas || task.persona_count || 0;
          if (n > 0) {
            effectiveStates = Array.from({length: n}, (_, i) => ({
              persona_id: `pending_${i}`,
              index: i,
              status: 'pending',
              attempt: 0,
              error: null,
            }));
          }
        }

        if (effectiveStates.length > 0) {
          _dotData[taskId] = {...(_dotData[taskId] || {}), states: effectiveStates};
          renderDotMatrix(
            `dot-matrix-${taskId}`,
            effectiveStates,
            _dotData[taskId]?.personas || [],
            isComplete,
          );
        }

        if (isComplete) {
          clearInterval(_dotPollTimers[taskId]);
          delete _dotPollTimers[taskId];
        }
      }
    } catch(_) {}
  };

  await poll();  // immediate first poll
  _dotPollTimers[taskId] = setInterval(poll, DOT_POLL_INTERVAL);
}

function stopDotPolling(taskId) {
  if (_dotPollTimers[taskId]) {
    clearInterval(_dotPollTimers[taskId]);
    delete _dotPollTimers[taskId];
  }
}

// ---------------------------------------------------------------------------
// Task Detail
// ---------------------------------------------------------------------------
async function openDetail(taskId) {
  showView('detail');
  const container = document.getElementById('detail-content');
  const detailEl = document.getElementById('view-detail');
  if (!container || !detailEl) return;
  detailEl.dataset.taskId = taskId;
  container.innerHTML = '<p class="text-slate-400 text-sm animate-pulse">Loading...</p>';

  try {
    const data = await apiFetch(`/api/tasks/${taskId}`);
    container.innerHTML = renderDetail(data);
    const task = data.task || data;
    if (task.status === 'running' || task.status === 'pending') {
      startPolling(taskId);
      startDotPolling(taskId);
    } else {
      // Load completed persona states for dot matrix at bottom
      startDotPolling(taskId);
      setTimeout(() => stopDotPolling(taskId), 3000);  // one-shot load
    }
  } catch (err) {
    container.innerHTML = `<p class="text-red-400 text-sm">Failed to load task: ${err.message}</p>`;
  }
}

async function updateDetailProgress(taskId, task) {
  // Light update: just refresh progress bar without full re-render
  const pctEl = document.querySelector(`#view-detail .progress-bar-fill`);
  const cntEl = document.querySelector(`#view-detail .detail-progress-count`);
  if (pctEl && task.total_personas > 0) {
    const pct = Math.round((task.completed_personas / task.total_personas) * 100);
    pctEl.style.width = `${pct}%`;
    if (cntEl) cntEl.textContent = `${task.completed_personas} / ${task.total_personas}`;
  }
}

const btnBack = document.getElementById('btn-back');
if (btnBack) btnBack.addEventListener('click', () => showView('tasks'));

const btnRefresh = document.getElementById('btn-refresh');
if (btnRefresh) btnRefresh.addEventListener('click', loadTasks);

// ---------------------------------------------------------------------------
// Markdown renderer (minimal, no external deps)
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
  if (!text) return '';
  let html = escHtml(text);

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3 class="text-sm font-semibold text-slate-200 mt-3 mb-1">$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2 class="text-base font-semibold text-slate-100 mt-4 mb-1">$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold text-white mt-4 mb-2">$1</h1>');

  // Bold/italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-surface-700 rounded text-xs font-mono text-brand-300">$1</code>');

  // Horizontal rule
  html = html.replace(/^---+$/gm, '<hr class="border-surface-700 my-3" />');

  // Unordered lists
  html = html.replace(/^[*\-] (.+)$/gm, '<li class="ml-4 text-slate-300 text-sm">• $1</li>');
  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="ml-4 text-slate-300 text-sm list-decimal list-inside">$1</li>');
  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li[^>]*>.*<\/li>\n?)+/g, m => `<ul class="space-y-0.5 my-1">${m}</ul>`);

  // Blockquote
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote class="border-l-2 border-brand-500 pl-3 text-slate-400 italic text-sm my-1">$1</blockquote>');

  // Paragraphs: split by double newline
  const blocks = html.split(/\n{2,}/);
  html = blocks.map(block => {
    const trimmed = block.trim();
    if (!trimmed) return '';
    // Already a block-level element
    if (/^<(h[1-6]|ul|ol|li|hr|blockquote|div)/.test(trimmed)) return trimmed;
    // Single newlines inside a paragraph → <br>
    return `<p class="text-sm text-slate-300 leading-relaxed">${trimmed.replace(/\n/g, '<br>')}</p>`;
  }).join('');

  return html;
}

// Collapsible markdown block with fade-out for long content
function renderCollapsibleMarkdown(text, maxLines = 8) {
  const id = 'md_' + Math.random().toString(36).slice(2, 8);
  const lines = text.split('\n').length;
  const isLong = lines > maxLines;
  const rendered = renderMarkdown(text);
  if (!isLong) {
    return `<div class="prose-ws">${rendered}</div>`;
  }
  // Approx line height ~20px; show maxLines worth
  const previewHeight = maxLines * 22;
  return `<div class="relative">
    <div id="${id}_body" class="prose-ws overflow-hidden" style="max-height:${previewHeight}px">
      ${rendered}
    </div>
    <div id="${id}_fade" class="absolute bottom-0 left-0 right-0 h-12 pointer-events-none"
      style="background: linear-gradient(transparent, #1e293b)"></div>
    <button onclick="expandMarkdown('${id}')" id="${id}_btn"
      class="mt-1 text-xs text-brand-400 hover:text-brand-300 transition-colors">
      ▼ Show more
    </button>
  </div>`;
}

function expandMarkdown(id) {
  const body = document.getElementById(id + '_body');
  const fade = document.getElementById(id + '_fade');
  const btn  = document.getElementById(id + '_btn');
  if (!body) return;
  const isExpanded = body.style.maxHeight === 'none';
  if (isExpanded) {
    body.style.maxHeight = '176px';
    if (fade) fade.style.display = '';
    if (btn) btn.textContent = '▼ Show more';
  } else {
    body.style.maxHeight = 'none';
    if (fade) fade.style.display = 'none';
    if (btn) btn.textContent = '▲ Show less';
  }
}

function renderDetail(data) {
  const task = data.task || data;
  const summary = data.summary || null;
  const isRunning = task.status === 'running' || task.status === 'pending';

  const attachments = task.metadata?.attachments || [];
  const researchType = task.research_type || 'product_purchase';
  const intentConfig = INTENT_LABEL_CONFIG[researchType] || INTENT_LABEL_CONFIG['product_purchase'];
  const preset = EVAL_PRESETS.find(p => p.id === researchType);

  // ----- Zone 0: Header -----
  let html = `
  <div class="mb-5">
    <div class="flex items-center gap-3 mb-1">
      <h1 class="text-xl font-bold">Task <span class="font-mono text-brand-400">${task.task_id}</span></h1>
      <span class="badge badge-${task.status}">
        ${isRunning ? '<span class="pulse-dot"></span>' : ''}
        ${task.status}
      </span>
    </div>
    <div class="flex flex-wrap gap-3 mt-1 text-xs text-slate-500">
      <span>🌐 ${task.market}</span>
      <span>👥 ${task.persona_count} personas</span>
      <span>⚙️ ${task.backend}</span>
      <span>🕐 ${new Date(task.created_at).toLocaleString()}</span>
      ${task.research_type ? `<span class="text-brand-400">${escHtml(getResearchTypeLabel(task.research_type))}</span>` : ''}
      ${(task.metadata?.llm_profile?.model) ? `<span class="text-purple-400">🤖 ${escHtml(task.metadata.llm_profile.model)}</span>` : ''}
    </div>
  </div>`;

  // ----- Zone 1: Survey anatomy — "how content was sent to LLM" -----
  html += `<div class="metric-card mb-5 space-y-4">
    <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Survey Input Anatomy
      <span class="ml-2 font-normal normal-case text-slate-600">— what each persona received</span>
    </h2>`;

  // 1a. Scenario context
  if (task.scenario_context) {
    html += `<div>
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">🎭 Scenario Context</div>
      <div class="bg-surface-900/60 border border-surface-700 rounded-lg px-3 py-2 text-sm text-slate-300 italic">
        ${escHtml(task.scenario_context)}
      </div>
    </div>`;
  }

  // 1b. Research type + decision output + evaluation focus
  const slot1 = intentConfig.slot1Label || 'Yes';
  const slot2 = intentConfig.slot2Label || 'Maybe';
  html += `<div>
    <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">🔬 Research Type</div>
    <div class="flex flex-wrap items-center gap-2 mb-3">
      <span class="inline-flex items-center gap-1.5 px-2.5 py-1 bg-brand-700/30 border border-brand-600/40 rounded-lg text-xs text-brand-300 font-medium">
        ${preset ? preset.emoji + ' ' : ''}${escHtml(getResearchTypeLabel(researchType))}
      </span>
    </div>
    <div class="text-xs text-slate-500 mb-1.5">Decision Output <span class="text-slate-600">/ 决策输出:</span></div>
    <div class="flex gap-2 mb-3">
      <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-green-900/30 border border-green-700/40 rounded text-xs text-green-400 font-medium">🟢 ${escHtml(slot1)}</span>
      <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-yellow-900/30 border border-yellow-700/40 rounded text-xs text-yellow-400 font-medium">🟡 ${escHtml(slot2)}</span>
      <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-red-900/30 border border-red-700/40 rounded text-xs text-red-400 font-medium">🔴 Pass</span>
    </div>`;

  const breakdownDims = getBreakdownDimensions(researchType);
  if (breakdownDims.length > 0) {
    html += `<div class="text-xs text-slate-500 mb-1.5">Evaluation Focus <span class="text-slate-600">/ 评估角度:</span></div>
    <div class="flex flex-wrap gap-1.5">
      ${breakdownDims.map(d => `<span class="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-700 border border-surface-600 rounded text-xs text-slate-400">${d.emoji} ${escHtml(d.label)}</span>`).join('')}
    </div>`;
  }

  html += `</div>`;

  // 1c. Attached files (inline images, PDF links, text files)
  if (attachments.length > 0) {
    html += `<div>
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">📎 Attached Files</div>
      <div class="space-y-3">`;

    attachments.forEach(att => {
      const fileUrl = `${API_BASE}/api/uploads/${task.task_id}/${encodeURIComponent(att.saved_name)}`;
      if (att.file_type === 'image') {
        html += `<div>
          <div class="text-xs text-slate-600 mb-1">${escHtml(att.original_name)} (${Math.round(att.size_bytes / 1024)} KB)</div>
          <img src="${fileUrl}" alt="${escHtml(att.original_name)}"
            class="max-w-sm max-h-64 rounded-lg border border-surface-700 object-contain cursor-pointer hover:opacity-90 transition-opacity"
            onclick="window.open('${fileUrl}', '_blank')" />
          ${att.image_description ? `<p class="text-xs text-slate-500 italic mt-1 max-w-sm">AI description: ${escHtml(att.image_description)}</p>` : ''}
        </div>`;
      } else if (att.file_type === 'pdf') {
        html += `<a href="${fileUrl}" target="_blank" rel="noopener"
          class="inline-flex items-center gap-2 px-3 py-2 bg-violet-900/30 border border-violet-700/40 rounded-lg text-xs text-violet-300 hover:bg-violet-900/50 transition-colors">
          📄 ${escHtml(att.original_name)}
          <span class="text-violet-500">(${Math.round(att.size_bytes / 1024)} KB) ↗</span>
        </a>`;
      } else {
        const icon = att.file_type === 'word' ? '📝' : att.file_type === 'text' ? '📃' : '📎';
        html += `<div class="inline-flex items-center gap-2 px-3 py-1.5 bg-surface-700 border border-surface-600 rounded-lg text-xs text-slate-300">
          ${icon} ${escHtml(att.original_name)}
          <span class="text-slate-500">(${Math.round(att.size_bytes / 1024)} KB)</span>
        </div>`;
      }
    });

    html += `</div></div>`;
  }

  // 1d. Main content / what was evaluated
  const rawContent = task.content || '';
  // Strip the appended file content + EVALUATION FOCUS block for display
  // (these are added programmatically — show the user-facing content only)
  let displayContent = rawContent;
  const fileContentIdx = displayContent.indexOf('\n\n[Attached file content:]');
  if (fileContentIdx !== -1) displayContent = displayContent.substring(0, fileContentIdx);
  const evalFocusIdx = displayContent.indexOf('\n\n---\nEVALUATION FOCUS:');
  if (evalFocusIdx !== -1) displayContent = displayContent.substring(0, evalFocusIdx);
  displayContent = displayContent.trim();

  if (displayContent) {
    html += `<div>
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">📋 Content to Evaluate</div>
      <div class="bg-surface-900/60 border border-surface-700 rounded-lg px-3 py-2">
        ${renderCollapsibleMarkdown(displayContent)}
      </div>
    </div>`;
  }

  // 1e. Evaluation criteria / custom instructions (if any)
  const evalCriteria = task.metadata?.evaluation_criteria || [];
  const customInstr = task.metadata?.custom_instructions || '';
  if (evalCriteria.length > 0 || customInstr) {
    html += `<div>
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">🎯 Evaluation Focus</div>
      <div class="bg-surface-900/60 border border-surface-700 rounded-lg px-3 py-2 space-y-1">`;
    if (evalCriteria.length > 0) {
      evalCriteria.forEach(c => {
        const dim = EVAL_DIMENSIONS_MAP[c];
        if (dim) {
          html += `<div class="text-xs text-slate-300">${dim.emoji} <strong>${dim.label}</strong> — ${dim.desc}</div>`;
        } else {
          html += `<div class="text-xs text-slate-300">• ${escHtml(c)}</div>`;
        }
      });
    }
    if (customInstr) {
      html += `<div class="text-xs text-slate-500 mt-1 italic">${renderCollapsibleMarkdown(customInstr, 5)}</div>`;
    }
    html += `</div></div>`;
  }

  html += `</div>`; // end metric-card anatomy

  // ----- Two-column layout: left = results, right = persona matrix -----
  // Right column: persona matrix (always present)
  let rightCol = `<div id="dot-matrix-${task.task_id}" class="metric-card">
    <p class="text-xs text-slate-600">Loading persona matrix...</p>
  </div>`;

  // Left column: progress + results
  let leftCol = '';

  // Running progress
  if (isRunning && task.total_personas > 0) {
    const progressPct = Math.round((task.completed_personas / task.total_personas) * 100);
    leftCol += `
    <div class="metric-card mb-5">
      <div class="flex justify-between text-sm mb-2">
        <span>Running inference…</span>
        <span class="text-brand-400 detail-progress-count">${task.completed_personas} / ${task.total_personas}</span>
      </div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill" style="width:${progressPct}%"></div>
      </div>
    </div>`;
  }

  if (task.status === 'failed') {
    leftCol += `<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-sm text-red-300 mb-5">
      <strong>Error:</strong> ${escHtml(task.error || 'Unknown error')}
    </div>`;
  }

  if (summary) {
    // Overall stats
    leftCol += `
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      ${metricCard(intentConfig.slot1Label + ' Rate', pct(summary.buy_rate), 'Of personas: ' + intentConfig.slot1Desc)}
      ${metricCard('Avg NPS', summary.avg_nps?.toFixed(1), 'Net Promoter Score (0-10)')}
      ${metricCard('Promoters', pct(summary.nps_promoters), 'Scored 9-10')}
      ${metricCard('Sentiment', fmtSentiment(summary.avg_sentiment), 'Avg sentiment (-1 to +1)')}
    </div>

    <div class="metric-card mb-6">
      <h2 class="text-sm font-semibold mb-4 text-slate-300">${intentConfig.breakdownTitle}</h2>
      <div class="space-y-3">
        ${intentBar(intentConfig.slot1Label, summary.buy_rate, '#22c55e')}
        ${intentBar(intentConfig.slot2Label, summary.hesitate_rate, '#f59e0b')}
        ${intentBar('Pass', summary.pass_rate, '#ef4444')}
      </div>
    </div>`;

    // Top Attractions / Concerns
    if (summary.top_attractions?.length || summary.top_concerns?.length) {
      leftCol += `<div class="grid grid-cols-2 gap-4 mb-6">`;
      if (summary.top_attractions?.length) {
        leftCol += `<div class="metric-card">
          <h2 class="text-sm font-semibold mb-3 text-green-400">💚 Top Attractions</h2>
          <ul class="space-y-1.5">
            ${summary.top_attractions.map(t => `<li class="text-xs text-slate-300">• ${escHtml(t)}</li>`).join('')}
          </ul>
        </div>`;
      }
      if (summary.top_concerns?.length) {
        leftCol += `<div class="metric-card">
          <h2 class="text-sm font-semibold mb-3 text-red-400">❗ Top Concerns</h2>
          <ul class="space-y-1.5">
            ${summary.top_concerns.map(t => `<li class="text-xs text-slate-300">• ${escHtml(t)}</li>`).join('')}
          </ul>
        </div>`;
      }
      leftCol += `</div>`;
    }

    // Segment tables
    const currentLanguage = task.language || task.metadata?.language || 'English';
    const isChinese = currentLanguage === '中文' || currentLanguage === 'zh' || currentLanguage === 'Chinese';
    const segRateLabel = isChinese
      ? (intentConfig.rateLabelCn || intentConfig.rateLabel || 'Buy Rate')
      : (intentConfig.rateLabel || 'Buy Rate');
    const segTitles = isChinese
      ? { nat: '按国籍', age: '按年龄段', income: '按收入', occ: '按职业' }
      : { nat: 'By Nationality', age: 'By Age Group', income: 'By Income', occ: 'By Occupation' };

    const segments = [
      [segTitles.nat,    summary.by_nationality, null],
      [segTitles.age,    summary.by_age_group, null],
      [segTitles.income, summary.by_income, null],
      [segTitles.occ,    summary.by_occupation, isChinese ? 'cn' : 'en'],
    ];

    segments.forEach(([title, segData, langHint]) => {
      if (segData && Object.keys(segData).length > 0) {
        leftCol += renderSegTable(title, segData, langHint, segRateLabel);
      }
    });

    // Verbatims
    if (summary.sample_verbatims?.length) {
      leftCol += `<div class="metric-card mb-6">
        <h2 class="text-sm font-semibold mb-3 text-slate-300">💬 Sample Verbatims</h2>
        <div class="space-y-2">
          ${summary.sample_verbatims.map(v => `<div class="verbatim-box">"${escHtml(v)}"</div>`).join('')}
        </div>
      </div>`;
    }
  } else if (task.status === 'completed') {
    leftCol += '<p class="text-slate-400 text-sm">Results not available yet.</p>';
  }

  // Assemble two-column layout
  html += `
  <div class="flex flex-col lg:flex-row gap-6">
    <div class="flex-1 min-w-0">${leftCol}</div>
    <div class="w-full lg:w-80 flex-shrink-0">
      <div class="lg:sticky lg:top-4">${rightCol}</div>
    </div>
  </div>`;

  return html;
}

function metricCard(label, value, sub) {
  return `<div class="metric-card">
    <div class="metric-value">${value ?? '—'}</div>
    <div class="metric-label">${label}</div>
    ${sub ? `<div class="text-xs text-slate-600 mt-1">${sub}</div>` : ''}
  </div>`;
}

function intentBar(label, rate, color) {
  const p = Math.round((rate || 0) * 100);
  return `<div>
    <div class="flex justify-between text-xs mb-1">
      <span class="text-slate-400">${label}</span>
      <span style="color:${color}">${p}%</span>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" style="width:${p}%; background:${color}"></div>
    </div>
  </div>`;
}

function renderSegTable(title, segData, langHint, rateLabel) {
  const rateLabelDisplay = rateLabel || 'Buy Rate';
  const entries = Object.entries(segData).sort((a, b) => (b[1].buy_rate || 0) - (a[1].buy_rate || 0));

  const rows = entries.map(([key, stats]) => {
    const buyPct = Math.round((stats.buy_rate || 0) * 100);
    // For occupation table: key may be occupation_id (old data) or occupation_title (new data)
    // Try to resolve to readable name from OCCUPATIONS_FLAT
    let displayKey = key;
    if (langHint !== null && OCCUPATIONS_FLAT.length > 0) {
      // Try to match by id first (handles old data with id keys), then by label
      const occ = OCCUPATIONS_FLAT.find(o => o.id === key) ||
                  OCCUPATIONS_FLAT.find(o => o.label === key);
      if (occ) {
        // For Chinese: use local name if available
        if (langHint === 'cn' && occ.label_local) {
          displayKey = occ.label_local;
        } else {
          // For all other languages: use English title
          displayKey = occ.label;
        }
      }
    }

    return `<tr>
      <td class="font-mono text-slate-300">${escHtml(displayKey)}</td>
      <td class="text-slate-400">${stats.count ?? '—'}</td>
      <td>
        <div class="mini-bar-wrap">
          <div class="mini-bar-track">
            <div class="mini-bar-fill" style="width:${buyPct}%"></div>
          </div>
          <span class="text-xs text-brand-400 w-8 text-right">${buyPct}%</span>
        </div>
      </td>
      <td class="text-slate-400">${stats.avg_nps?.toFixed(1) ?? '—'}</td>
      <td class="text-slate-400">${fmtSentiment(stats.avg_sentiment)}</td>
    </tr>`;
  }).join('');

  return `<div class="metric-card mb-4">
    <h2 class="text-sm font-semibold mb-3 text-slate-300">${title}</h2>
    <table class="seg-table">
      <thead><tr>
        <th>Segment</th><th>n</th><th>${escHtml(rateLabelDisplay)}</th><th>NPS</th><th>Sentiment</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ---------------------------------------------------------------------------
// System Settings Page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Settings Page — multi-profile LLM support
// ---------------------------------------------------------------------------

let _settingsData = null;
let _profilesData = [];       // full profile list from API
let _activeProfileName = '';  // currently selected profile in the editor
let _editingProfileName = '';  // profile being edited in right panel

async function loadSettingsPage() {
  const container = document.getElementById('settings-content');
  if (!container) return;
  container.innerHTML = '<p class="text-slate-400 text-sm animate-pulse">Loading settings...</p>';

  try {
    [_settingsData] = await Promise.all([apiFetch('/api/settings')]);
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = _settingsData.active_profile || (_profilesData[0]?.name || '');
    _editingProfileName = _activeProfileName;
    renderSettingsPage(_settingsData);
  } catch(e) {
    container.innerHTML = `<p class="text-red-400 text-sm">Failed to load settings: ${e.message}</p>`;
  }
}

let _activeSettingsTab = 'general';

function switchSettingsTab(tab) {
  _activeSettingsTab = tab;
  document.querySelectorAll('.settings-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
  document.querySelectorAll('.settings-tab-panel').forEach(panel => {
    panel.classList.toggle('hidden', panel.dataset.tab !== tab);
  });
}

function renderSettingsPage(settings) {
  const container = document.getElementById('settings-content');
  if (!container) return;

  const g = settings.general || {};
  const l = settings.llm || {};
  const a = settings.advanced || {};

  container.innerHTML = `
  <div class="max-w-4xl">
    <!-- Tab Bar -->
    <div class="flex gap-1 mb-6 border-b border-surface-700 pb-0">
      <button class="settings-tab-btn active px-4 py-2 text-sm rounded-t-lg" data-tab="general" onclick="switchSettingsTab('general')">General</button>
      <button class="settings-tab-btn px-4 py-2 text-sm rounded-t-lg" data-tab="llm" onclick="switchSettingsTab('llm')">LLM</button>
      <button class="settings-tab-btn px-4 py-2 text-sm rounded-t-lg" data-tab="advanced" onclick="switchSettingsTab('advanced')">Advanced</button>
    </div>

    <!-- General Tab -->
    <div class="settings-tab-panel space-y-5" data-tab="general">
      <div>
        <label class="settings-label">Default Language</label>
        <select id="s-default-language" class="settings-input">
          ${['English','中文','日本語','한국어','Español','Français','Deutsch','Português','العربية','हिन्दी']
            .map(lang => `<option value="${lang}" ${g.default_language === lang ? 'selected' : ''}>${lang}</option>`)
            .join('')}
        </select>
      </div>
      <div>
        <label class="settings-label">Default Sample Size</label>
        <input type="number" id="s-default-sample-size" min="1" max="10000" value="${g.default_sample_size || 50}"
          class="settings-input w-40" />
        <p class="text-xs text-slate-500 mt-1">Number of personas generated per task by default.</p>
      </div>
      <div>
        <label class="settings-label">Default Country/Region</label>
        <select id="s-default-country" class="settings-input">
          <option value="">Global (auto)</option>
          ${ALL_COUNTRIES.map(c => `<option value="${c.code}" ${g.default_country === c.code ? 'selected' : ''}>${c.flag} ${c.label}</option>`).join('')}
        </select>
      </div>
      <div class="mt-8 flex items-center gap-4">
        <button onclick="saveGeneralSettings()"
          class="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors">
          Save
        </button>
        <span id="settings-save-msg-general" class="text-sm text-slate-400"></span>
      </div>
    </div>

    <!-- LLM Tab — two-column layout: profile list (left) + editor (right) -->
    <div class="settings-tab-panel hidden" data-tab="llm">
      <div class="flex gap-6">
        <!-- Left: profile list -->
        <div class="w-52 flex-shrink-0">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold text-slate-400 uppercase tracking-wide">Profiles</span>
            <button onclick="showAddProfileDialog()"
              class="text-brand-400 hover:text-brand-300 text-lg leading-none" title="Add profile">＋</button>
          </div>
          <div id="llm-profile-list" class="space-y-1">
            ${renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName)}
          </div>
          <!-- Concurrency / timeout controls below the profile list -->
          <div class="mt-6 space-y-3">
            <p class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-1">Runtime</p>
            <div>
              <label class="settings-label text-xs">Concurrency</label>
              <input type="number" id="s-concurrency" min="1" max="500" value="${l.concurrency_limit || 10}"
                class="settings-input" />
              <p class="text-xs text-slate-500 mt-0.5">GLM: 30-50 safe.</p>
            </div>
            <div>
              <label class="settings-label text-xs">Timeout (s)</label>
              <input type="number" id="s-timeout" min="5" max="600" value="${l.request_timeout || 120}"
                class="settings-input" />
            </div>
            <div>
              <label class="settings-label text-xs">Max Retries</label>
              <input type="number" id="s-max-retries" min="0" max="10" value="${l.max_retries ?? 3}"
                class="settings-input" />
            </div>
            <div>
              <label class="settings-label text-xs">Token Budget</label>
              <input type="number" id="s-token-budget" min="0" value="${l.token_budget_per_task || 0}"
                class="settings-input" />
              <p class="text-xs text-slate-500 mt-0.5">0 = unlimited.</p>
            </div>
            <button onclick="saveLLMRuntimeSettings()"
              class="w-full mt-2 px-3 py-1.5 bg-surface-700 hover:bg-surface-600 text-slate-300 text-xs rounded-lg transition-colors">
              Save Runtime
            </button>
            <span id="settings-save-msg-runtime" class="text-xs text-slate-400 block"></span>
          </div>
        </div>

        <!-- Right: profile editor -->
        <div class="flex-1 min-w-0">
          <div id="llm-profile-editor">
            ${renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName)}
          </div>
        </div>
      </div>
    </div>

    <!-- Advanced Tab -->
    <div class="settings-tab-panel hidden space-y-5" data-tab="advanced">
      <div>
        <label class="settings-label">Temperature</label>
        <div class="flex items-center gap-3">
          <input type="range" id="s-temperature-range" min="0" max="2" step="0.05" value="${a.temperature ?? 0.9}"
            class="flex-1" oninput="document.getElementById('s-temperature-val').textContent = this.value; updateSliderFill(this)" />
          <span id="s-temperature-val" class="text-brand-400 font-mono text-sm w-10">${a.temperature ?? 0.9}</span>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <input type="checkbox" id="s-debug-mode" ${a.debug_mode ? 'checked' : ''}
          class="w-4 h-4 rounded accent-brand-500" />
        <label for="s-debug-mode" class="settings-label mb-0">Debug Mode</label>
      </div>
      <div>
        <label class="settings-label">Default Export Format</label>
        <select id="s-export-format" class="settings-input w-40">
          <option value="json" ${a.default_export_format === 'json' ? 'selected' : ''}>JSON</option>
          <option value="csv" ${a.default_export_format === 'csv' ? 'selected' : ''}>CSV</option>
        </select>
      </div>
      <div>
        <label class="settings-label">Result Retention (days)</label>
        <input type="number" id="s-retention" min="1" max="3650" value="${a.result_retention_days || 90}"
          class="settings-input w-40" />
        <p class="text-xs text-slate-500 mt-1">Results older than this are eligible for cleanup.</p>
      </div>
      <div class="mt-8 flex items-center gap-4">
        <button onclick="saveAdvancedSettings()"
          class="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors">
          Save
        </button>
        <span id="settings-save-msg-advanced" class="text-sm text-slate-400"></span>
      </div>
    </div>
  </div>

  <!-- Add Profile Dialog (hidden) -->
  <div id="add-profile-dialog" class="hidden fixed inset-0 bg-black/60 flex items-center justify-center z-50">
    <div class="bg-surface-800 rounded-xl p-6 w-80 shadow-2xl border border-surface-600">
      <h3 class="text-base font-semibold text-white mb-4">New Profile</h3>
      <label class="settings-label">Profile Name</label>
      <input type="text" id="new-profile-name" placeholder="e.g. GLM-5, GPT-4o, Claude"
        class="settings-input mb-4" />
      <div class="flex gap-3 justify-end">
        <button onclick="document.getElementById('add-profile-dialog').classList.add('hidden')"
          class="px-4 py-2 text-sm text-slate-400 hover:text-white rounded-lg transition-colors">Cancel</button>
        <button onclick="createProfile()"
          class="px-4 py-2 text-sm bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors">Create</button>
      </div>
    </div>
  </div>`;

  // Initialize temp slider fill
  const tempSlider = document.getElementById('s-temperature-range');
  if (tempSlider) updateSliderFill(tempSlider);

  // Ensure correct tab is shown
  switchSettingsTab(_activeSettingsTab);
}

// Render vision capability badge
function renderVisionBadge(supportsVision) {
  if (supportsVision === true) {
    return '<span class="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 bg-green-900/60 text-green-400 rounded-full flex-shrink-0" title="Vision capable">Vision ✓</span>';
  } else if (supportsVision === false) {
    return '<span class="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 bg-slate-700 text-slate-500 rounded-full flex-shrink-0" title="Text only">Text Only</span>';
  }
  return '<span class="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 bg-slate-700/50 text-slate-600 rounded-full flex-shrink-0" title="Vision capability not yet tested">?</span>';
}

// Render profile list items (sidebar)
function renderProfileListItems(profiles, activeProfileName, editingProfileName) {
  if (!profiles || profiles.length === 0) {
    return '<p class="text-xs text-slate-500 italic">No profiles yet</p>';
  }
  return profiles.map(p => {
    const isActive = p.name === activeProfileName;
    const isEditing = p.name === editingProfileName;
    const visionBadge = renderVisionBadge(p.supports_vision);
    return `
    <div class="group flex items-center gap-1.5 rounded-lg px-2 py-1.5 cursor-pointer transition-colors ${isEditing ? 'bg-surface-600' : 'hover:bg-surface-700'}"
      onclick="selectProfileForEditing('${escHtml(p.name)}')">
      <span class="flex-1 text-sm ${isEditing ? 'text-white font-medium' : 'text-slate-300'} truncate">${escHtml(p.name)}</span>
      ${visionBadge}
      ${isActive ? '<span class="text-brand-400 text-xs flex-shrink-0" title="Default Model">●</span>' : '<span class="text-transparent text-xs flex-shrink-0">●</span>'}
    </div>`;
  }).join('');
}

// Render the right-side profile editor
function renderProfileEditor(profiles, editingProfileName, activeProfileName) {
  const profile = profiles.find(p => p.name === editingProfileName) || profiles[0];
  if (!profile) {
    return `<div class="text-slate-500 text-sm pt-4">
      <p>No profiles yet.</p>
      <p class="mt-2">Click <strong class="text-brand-400">＋</strong> to create your first LLM profile.</p>
    </div>`;
  }
  const isActive = profile.name === activeProfileName;
  const visionBadge = renderVisionBadge(profile.supports_vision);
  return `
  <div class="space-y-4">
    <!-- Profile header with name + actions -->
    <div class="flex items-center gap-3">
      <div id="profile-name-display" class="flex items-center gap-2 flex-1 min-w-0">
        <h3 class="text-base font-semibold text-white truncate">${escHtml(profile.name)}</h3>
        ${isActive ? '<span class="text-xs bg-brand-800 text-brand-300 px-2 py-0.5 rounded-full flex-shrink-0">Default Model</span>' : ''}
        ${visionBadge}
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        ${!isActive ? `<button onclick="activateProfile('${escHtml(profile.name)}')"
          class="px-3 py-1.5 text-xs bg-brand-700 hover:bg-brand-600 text-white rounded-lg transition-colors">
          Set as Default
        </button>` : ''}
        <button onclick="promptRenameProfile('${escHtml(profile.name)}')"
          class="px-3 py-1.5 text-xs bg-surface-700 hover:bg-surface-600 text-slate-300 rounded-lg transition-colors">
          Rename
        </button>
        <button onclick="deleteProfile('${escHtml(profile.name)}')"
          class="px-3 py-1.5 text-xs bg-red-900/50 hover:bg-red-800/70 text-red-300 rounded-lg transition-colors">
          Delete
        </button>
      </div>
    </div>

    <!-- Profile fields -->
    <div>
      <label class="settings-label">Provider</label>
      <select id="p-provider" class="settings-input">
        <option value="openai" ${profile.provider === 'openai' ? 'selected' : ''}>OpenAI / OpenAI-Compatible</option>
        <option value="anthropic" ${profile.provider === 'anthropic' ? 'selected' : ''}>Anthropic</option>
        <option value="custom" ${profile.provider === 'custom' ? 'selected' : ''}>Custom</option>
        <option value="mock" ${profile.provider === 'mock' ? 'selected' : ''}>Mock (testing)</option>
      </select>
    </div>
    <div>
      <label class="settings-label">Model Name</label>
      <input type="text" id="p-model" value="${escHtml(profile.model || '')}" placeholder="e.g. glm-4-plus, gpt-4o-mini"
        class="settings-input" />
    </div>
    <div>
      <label class="settings-label">API Key</label>
      <input type="password" id="p-api-key" value="${escHtml(profile.api_key || '')}" placeholder="sk-..."
        class="settings-input" autocomplete="off" />
      <p class="text-xs text-slate-500 mt-1">Leave blank to use WS_API_KEY environment variable.</p>
    </div>
    <div>
      <label class="settings-label">Endpoint URL</label>
      <input type="text" id="p-endpoint" value="${escHtml(profile.endpoint || '')}" placeholder="https://open.bigmodel.cn/api/coding/paas/v4"
        class="settings-input" />
      <p class="text-xs text-slate-500 mt-1">Leave blank to use WS_API_BASE_URL environment variable.</p>
    </div>

    <div class="flex items-center gap-4 pt-2 flex-wrap">
      <button onclick="saveProfile('${escHtml(profile.name)}')"
        class="px-5 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-colors">
        Save Profile
      </button>
      <button onclick="reProbeVision('${escHtml(profile.name)}')"
        class="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-slate-300 text-xs rounded-lg transition-colors">
        🔍 Re-test Vision
      </button>
      <span id="profile-save-msg" class="text-sm text-slate-400"></span>
    </div>
  </div>`;
}

// Select a profile to edit (right panel)
function selectProfileForEditing(name) {
  _editingProfileName = name;
  // Re-render list (highlight) and editor
  const listEl = document.getElementById('llm-profile-list');
  if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, name);
  const editorEl = document.getElementById('llm-profile-editor');
  if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, name, _activeProfileName);
}

// Show add profile dialog
function showAddProfileDialog() {
  const dlg = document.getElementById('add-profile-dialog');
  if (dlg) {
    dlg.classList.remove('hidden');
    const inp = document.getElementById('new-profile-name');
    if (inp) { inp.value = ''; inp.focus(); }
  }
}

// Create a new profile
async function createProfile() {
  const nameEl = document.getElementById('new-profile-name');
  const name = nameEl?.value?.trim();
  if (!name) { alert('Profile name cannot be empty'); return; }

  try {
    await apiFetch('/api/llm-profiles', {
      method: 'POST',
      body: JSON.stringify({ name, activate: _profilesData.length === 0 }),
    });
    document.getElementById('add-profile-dialog')?.classList.add('hidden');
    // Reload settings data
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = _settingsData.active_profile || '';
    _editingProfileName = name;
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    alert(`Failed to create profile: ${e.message}`);
  }
}

// Save profile edits (automatically re-probes vision capability)
async function saveProfile(originalName) {
  const msgEl = document.getElementById('profile-save-msg');
  if (msgEl) { msgEl.textContent = 'Saving... Testing vision capability...'; msgEl.className = 'text-sm text-slate-400'; }

  const payload = {
    provider: document.getElementById('p-provider')?.value || 'openai',
    model: document.getElementById('p-model')?.value?.trim() || '',
    api_key: document.getElementById('p-api-key')?.value || '',
    endpoint: document.getElementById('p-endpoint')?.value?.trim() || '',
  };

  try {
    const result = await apiFetch(`/api/llm-profiles/${encodeURIComponent(originalName)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    // Refresh data
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = _settingsData.active_profile || '';

    // Show vision result in save message
    const visionStatus = result?.supports_vision === true
      ? '✓ Saved — Vision capable'
      : result?.supports_vision === false
        ? '✓ Saved — Text only (no vision)'
        : '✓ Saved';
    if (msgEl) { msgEl.textContent = visionStatus; msgEl.className = 'text-sm text-green-400'; }
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 4000);

    // Re-render list + editor (vision badge may have changed)
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    if (msgEl) { msgEl.textContent = `Error: ${e.message}`; msgEl.className = 'text-sm text-red-400'; }
  }
}

// Manually re-probe vision for a profile
async function reProbeVision(profileName) {
  const msgEl = document.getElementById('profile-save-msg');
  if (msgEl) { msgEl.textContent = 'Testing vision capability...'; msgEl.className = 'text-sm text-slate-400'; }

  try {
    const result = await apiFetch(`/api/llm-profiles/${encodeURIComponent(profileName)}/probe-vision`, { method: 'POST' });
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];

    const visionStatus = result?.supports_vision === true
      ? '✓ Vision capable'
      : '✗ Text only (no vision)';
    if (msgEl) { msgEl.textContent = visionStatus; msgEl.className = result?.supports_vision ? 'text-sm text-green-400' : 'text-sm text-slate-400'; }
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 4000);

    // Re-render with updated badge
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    if (msgEl) { msgEl.textContent = `Probe failed: ${e.message}`; msgEl.className = 'text-sm text-red-400'; }
  }
}

// Activate a profile
async function activateProfile(name) {
  try {
    await apiFetch(`/api/llm-profiles/${encodeURIComponent(name)}/activate`, { method: 'POST' });
    _activeProfileName = name;
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = _settingsData.active_profile || name;
    // Re-render both panels
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    alert(`Failed to activate: ${e.message}`);
  }
}

// Rename profile
async function promptRenameProfile(name) {
  const newName = prompt('Rename profile:', name);
  if (!newName || newName === name) return;
  try {
    await apiFetch(`/api/llm-profiles/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ name: newName }),
    });
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = _settingsData.active_profile || '';
    _editingProfileName = newName;
    // Re-render
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    alert(`Rename failed: ${e.message}`);
  }
}

// Delete profile
async function deleteProfile(name) {
  if (!confirm(`Delete profile "${name}"?`)) return;
  try {
    const res = await apiFetch(`/api/llm-profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
    _settingsData = await apiFetch('/api/settings');
    _profilesData = _settingsData.llm_profiles || [];
    _activeProfileName = res.active_profile || (_profilesData[0]?.name || '');
    _editingProfileName = _activeProfileName;
    const listEl = document.getElementById('llm-profile-list');
    if (listEl) listEl.innerHTML = renderProfileListItems(_profilesData, _activeProfileName, _editingProfileName);
    const editorEl = document.getElementById('llm-profile-editor');
    if (editorEl) editorEl.innerHTML = renderProfileEditor(_profilesData, _editingProfileName, _activeProfileName);
  } catch(e) {
    alert(`Delete failed: ${e.message}`);
  }
}

// Save general settings only
async function saveGeneralSettings() {
  const msgEl = document.getElementById('settings-save-msg-general');
  if (msgEl) { msgEl.textContent = 'Saving...'; msgEl.className = 'text-sm text-slate-400'; }
  const payload = {
    general: {
      default_language: document.getElementById('s-default-language')?.value,
      default_sample_size: parseInt(document.getElementById('s-default-sample-size')?.value || '50'),
      default_country: document.getElementById('s-default-country')?.value || '',
    },
  };
  try {
    await apiFetch('/api/settings', { method: 'PUT', body: JSON.stringify(payload) });
    if (msgEl) { msgEl.textContent = '✓ Saved'; msgEl.className = 'text-sm text-green-400'; }
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 3000);
  } catch(e) {
    if (msgEl) { msgEl.textContent = `Error: ${e.message}`; msgEl.className = 'text-sm text-red-400'; }
  }
}

// Save LLM runtime settings (concurrency/timeout/retries/budget)
async function saveLLMRuntimeSettings() {
  const msgEl = document.getElementById('settings-save-msg-runtime');
  if (msgEl) { msgEl.textContent = 'Saving...'; msgEl.className = 'text-xs text-slate-400'; }
  const payload = {
    llm: {
      concurrency_limit: parseInt(document.getElementById('s-concurrency')?.value || '10'),
      request_timeout: parseInt(document.getElementById('s-timeout')?.value || '120'),
      max_retries: parseInt(document.getElementById('s-max-retries')?.value || '3'),
      token_budget_per_task: parseInt(document.getElementById('s-token-budget')?.value || '0'),
    },
  };
  try {
    await apiFetch('/api/settings', { method: 'PUT', body: JSON.stringify(payload) });
    if (msgEl) { msgEl.textContent = '✓ Saved'; msgEl.className = 'text-xs text-green-400'; }
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 3000);
  } catch(e) {
    if (msgEl) { msgEl.textContent = `Error: ${e.message}`; msgEl.className = 'text-xs text-red-400'; }
  }
}

// Save advanced settings
async function saveAdvancedSettings() {
  const msgEl = document.getElementById('settings-save-msg-advanced');
  if (msgEl) { msgEl.textContent = 'Saving...'; msgEl.className = 'text-sm text-slate-400'; }
  const payload = {
    advanced: {
      temperature: parseFloat(document.getElementById('s-temperature-range')?.value || '0.9'),
      debug_mode: document.getElementById('s-debug-mode')?.checked || false,
      default_export_format: document.getElementById('s-export-format')?.value || 'json',
      result_retention_days: parseInt(document.getElementById('s-retention')?.value || '90'),
    },
  };
  try {
    await apiFetch('/api/settings', { method: 'PUT', body: JSON.stringify(payload) });
    if (msgEl) { msgEl.textContent = '✓ Saved'; msgEl.className = 'text-sm text-green-400'; }
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 3000);
  } catch(e) {
    if (msgEl) { msgEl.textContent = `Error: ${e.message}`; msgEl.className = 'text-sm text-red-400'; }
  }
}

// Legacy saveSettings — kept for backward compatibility (calls saveGeneralSettings)
async function saveSettings() {
  await saveGeneralSettings();
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
async function apiFetch(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.text();
    let msg = body;
    try { msg = JSON.parse(body).detail || body; } catch (_) {}
    throw new Error(`${res.status}: ${msg}`);
  }
  return res.json();
}

async function apiFetchForm(path, formData) {
  const res = await fetch(API_BASE + path, { method: 'POST', body: formData });
  if (!res.ok) {
    const body = await res.text();
    let msg = body;
    try { msg = JSON.parse(body).detail || body; } catch (_) {}
    throw new Error(`${res.status}: ${msg}`);
  }
  return res.json();
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function pct(val) {
  if (val == null) return '—';
  return `${Math.round(val * 100)}%`;
}

function fmtSentiment(val) {
  if (val == null) return '—';
  const n = parseFloat(val).toFixed(2);
  const color = val >= 0.1 ? 'text-green-400' : val <= -0.1 ? 'text-red-400' : 'text-slate-400';
  return `<span class="${color}">${n}</span>`;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
renderAllAdvanced();
renderEvalPresets();

loadOccupations().then(() => {
  renderSelectedOccupations();
});

(function initLocations() {
  const el = document.getElementById('input-market');
  if (el) loadLocationsForMarket(el.value);
})();

document.addEventListener('click', (e) => {
  const groups = document.getElementById('occupation-groups');
  const search = document.getElementById('occupation-search');
  if (groups && !groups.classList.contains('hidden')) {
    if (!groups.contains(e.target) && e.target !== search) {
      groups.classList.add('hidden');
    }
  }
});

(function initTab() {
  let savedTab;
  try { savedTab = localStorage.getItem(TAB_KEY); } catch(_) {}
  showView(savedTab && views[savedTab] ? savedTab : 'new-run');
})();
