/* The Follow-Through: front end. Reads data.json (built by update.py) and renders
   the front page (#/), section pages (#/section/<id>) and decision pages (#/decision/<celex>). */
'use strict';

let D, BY_ID, SEC, TGT;
const TODAY = new Date().toISOString().slice(0, 10);
const $app = document.getElementById('app');
const usedPhotos = new Map();

// ---------------------------------------------------------------- helpers
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n, d = 0) => Number(n).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
const dLong = s => new Date(s + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
const dShort = s => new Date(s + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const eurlex = id => `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${encodeURIComponent(id)}`;
const daysAgo = s => Math.round((Date.parse(TODAY) - Date.parse(s)) / 864e5);
const hash = s => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

function photo(key, seed = '') {
  // prefer the section's own photos, avoid repeating one on the same page, fall back to EU institution photos
  const own = (D.photos[key] || []).filter(p => !/\(ZJ914\).*1655/.test(p.title));
  const extra = ['council', 'commission', 'masthead'].flatMap(k => D.photos[k] || []);
  const start = hash(seed + key) % Math.max(1, own.length);
  const ordered = [...own.slice(start), ...own.slice(0, start), ...extra];
  const p = ordered.find(x => !usedPhotos.has(x.url)) || ordered[0];
  if (p) usedPhotos.set(p.url, p);
  return p || null;
}
// photo matching what a decision is about (its topic, set by update.py), else one from its section
function photoFor(d) {
  const pool = (D.photos.topics || {})[d.topic] || [];
  if (!pool.length) return photo(d.section, d.id);
  const start = hash(d.id) % pool.length;
  const ordered = [...pool.slice(start), ...pool.slice(0, start)];
  const p = ordered.find(x => !usedPhotos.has(x.url)) || ordered[0];
  usedPhotos.set(p.url, p);
  return p;
}
const img = (p, alt = '', cls = '') => p ? `<img class="${cls}" src="${esc(p.url.replace("/1920px-", "/1280px-"))}" alt="${esc(alt || p.title)}" loading="lazy">` : '';
const credit = p => p ? `<div class="caption">Photo: ${esc(p.author)} / <a href="${esc(p.source)}" target="_blank" rel="noopener">${esc(p.licence)}</a></div>` : '';

// ---------------------------------------------------------------- scoring
function milestones(d) {
  const set = new Map();
  set.set(d.date, 'Adopted');
  d.in_force.forEach((x, i) => { if (!set.has(x)) set.set(x, i === 0 ? 'Enters into force' : 'Next stage starts to apply'); });
  d.deadlines.forEach(x => { if (!set.has(x)) set.set(x, 'Deadline (transposition, review or report)'); });
  return [...set].map(([date, what]) => ({ date, what })).filter(m => m.date < '9999').sort((a, b) => a.date.localeCompare(b.date));
}

function paceVerdict(t) {
  if (t.progress >= 100) return { cls: 'good', text: 'Goal reached', ratio: 1 };
  const ratio = t.need_rate ? t.real_rate / t.need_rate : 1;
  if (ratio >= 1) return { cls: 'good', text: 'On track', ratio };
  if (ratio >= 0.7) return { cls: 'warn', text: 'Slightly behind', ratio };
  return { cls: 'bad', text: 'Off track', ratio };
}

function score(d) {
  if (d.targets && d.targets.length) {
    const t = TGT[d.targets[0]], v = paceVerdict(t);
    return { pct: t.progress, kind: 'goal', label: 'Goal progress', cls: v.cls, verdict: v.text, target: t,
      why: `Europe is ${t.progress}% of the way to the goal this decision serves: “${t.short}”.` };
  }
  const ms = milestones(d), passed = ms.filter(m => m.date <= TODAY).length;
  const pct = Math.round(passed / ms.length * 100);
  const next = ms.find(m => m.date > TODAY);
  const verdict = pct >= 100 ? 'Fully in effect' : pct >= 50 ? 'Rolling out' : 'Just starting';
  return { pct, kind: 'rollout', label: 'Rollout', cls: pct >= 100 ? 'good' : '', verdict,
    why: next ? `${passed} of ${ms.length} legal milestones reached. Next: ${next.what.toLowerCase()} on ${dLong(next.date)}.`
              : `All ${ms.length} legal milestones have been reached.` };
}

const pill = d => { const s = score(d); return `<span class="pill ${s.cls}"><i></i>${s.label}: ${s.pct}%</span>`; };
const isNew = d => daysAgo(d.date) <= 14;
const kindTag = d => `<span class="tag ${d.kind === 'EU law' ? 'law' : ''}">${esc(d.kind)}</span>`;
const WHO = { 'EU law': 'Passed by the European Parliament and the Council', 'Council act': 'Adopted by the Council of the EU', 'Foreign policy decision': 'Foreign-policy decision by EU governments', 'Foreign policy update': 'EU governments changed an earlier foreign-policy decision' };
function dek(d) {
  if (d.summary) return d.summary;
  const ms = milestones(d), next = ms.find(m => m.date > TODAY), left = ms.filter(m => m.date > TODAY).length;
  let s = `${WHO[d.kind]} on ${dLong(d.date)}.`;
  if (d.kind === 'Foreign policy update') {
    const base = d.links.changes[0];
    return s + (base ? ` It changes ${base.ref}.` : '') + ' Updates like this usually add or remove names, extend a deadline or change a budget: the official text says which.';
  }
  if (next) s += ` Next step: ${next.what.split(' (')[0].toLowerCase()} on ${dLong(next.date)}${left > 1 ? `, with ${left - 1} more milestone${left > 2 ? 's' : ''} after that` : ''}.`;
  else if (d.in_force[0]) s += ` In force since ${dLong(d.in_force[0])}.`;
  if (d.links.based_on.length) s += ` ${d.links.based_on.length} follow-up action${d.links.based_on.length > 1 ? 's' : ''} so far.`;
  return s;
}
function officialDek(d) {
  const m = d.title.match(/\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\s+(.*)$/);
  let s = (m ? m[1] : d.title).replace(/\s*\(Text with EEA relevance\)\s*/, '').trim();
  s = s.charAt(0).toUpperCase() + s.slice(1);
  return s.length > 190 ? s.slice(0, 190).replace(/\s+\S*$/, '') + '…' : s;
}

// How "newsworthy" a decision is, for the front page
function weight(d) {
  let w = 0;
  if (d.kind === 'EU law') w += 4;
  if (d.kind === 'Foreign policy update') w -= 4;   // routine changes never lead the front page
  if (!/^Rules rewritten|^Customs duties|^Fishing quotas|^EU updates its sanctions/.test(d.headline)) w += 2;
  if (/^EU fund steps in|^Disaster aid|^Military aid/.test(d.headline)) w -= 2;
  w += (d.targets || []).length * 2;
  w += Math.min(3, d.in_force.length + d.deadlines.length) * 0.5;
  w -= daysAgo(d.date) / 45;
  return w;
}

// ---------------------------------------------------------------- router
function route() {
  usedPhotos.clear();
  const h = location.hash.replace(/^#\/?/, '').split('/');
  document.querySelectorAll('nav.sections a').forEach(a => a.classList.toggle('on', (h[0] === 'section' && a.dataset.id === h[1]) || (h[0] === 'goals' && a.dataset.id === 'goals')));
  if (h[0] === 'section' && SEC[h[1]]) renderSection(SEC[h[1]]);
  else if (h[0] === 'decision' && BY_ID[decodeURIComponent(h[1])]) renderDecision(BY_ID[decodeURIComponent(h[1])]);
  else if (h[0] === 'goals') renderGoals();
  else renderFront();
  renderCredits();
  window.scrollTo(0, 0);
}

function renderCredits() {
  document.getElementById('credits').innerHTML = [...usedPhotos.values()].map(p =>
    `<li>${esc(p.title)}: ${esc(p.author)}, <a href="${esc(p.source)}" target="_blank" rel="noopener">${esc(p.licence)}</a>, via Wikimedia Commons</li>`).join('');
}

// ---------------------------------------------------------------- front page
// a target's value as readers should see it: "76.1%", "19,933 deaths", "10.5 million people", or "−37.5%" vs the start
function tval(t, v) {
  if (t.display === 'change') { const c = (v / t.start - 1) * 100; return `${c > 0 ? '+' : c < 0 ? '−' : ''}${fmt(Math.abs(c), 1)}%`; }
  if (t.unit === '%') return `${fmt(v, t.decimals ?? 1)}%`;
  return `${fmt(v, t.decimals ?? 1)} ${t.unit}`;
}
const verdictTxt = v => `${v.text}${v.ratio > 0 && v.ratio < 1 ? `: needs to move ${fmt(1 / v.ratio, 1)}× faster` : v.ratio <= 0 ? ': going the wrong way' : ''}`;

function scoreCard(t, compact) {
  const v = paceVerdict(t);
  const startTxt = t.display === 'change' ? `vs ${t.start_year}` : `from ${tval(t, t.start)} in ${t.start_year}`;
  return `<div class="score-card">
    <span class="kicker">Goal · ${esc(SEC[t.section].name)}</span>
    <div class="t">${esc(t.title)}</div>
    <div class="bar"><span style="width:${t.progress}%;background:var(--${v.cls === 'good' ? 'good' : v.cls === 'warn' ? 'warn' : 'bad'})"></span></div>
    <div class="bar-row"><span>${tval(t, t.series[t.last_year])} in ${t.last_year}${compact ? '' : ` (${startTxt})`}</span><span><b>${t.progress}%</b> of the way</span></div>
    <div class="verdict ${v.cls}">${verdictTxt(v)}</div>
    ${compact ? '' : `<p class="muted" style="font-size:14px;margin:6px 0 0">Set by: ${esc(t.basis)}${t.law ? ` (<a href="${eurlex(t.law)}" target="_blank" rel="noopener">text</a>)` : ''}. Data: ${esc(t.source)}.</p>`}
  </div>`;
}

function renderFront() {
  document.title = `${D.site.name}: ${D.site.tagline}`;
  const ranked = [...D.decisions].sort((a, b) => weight(b) - weight(a));
  const lead = ranked[0], top = ranked.slice(1, 4), more = ranked.slice(4, 12);
  const used = new Set([lead, ...top, ...more].map(d => d.id));
  // newest first, but at most 2 routine updates so new decisions stay visible
  let nUpd = 0;
  const latest = D.decisions.filter(d => d.kind !== 'Foreign policy update' || ++nUpd <= 3).slice(0, 16);
  // A different hemicycle photo each day (changes at midnight UTC, same for every visitor)
  const heads = D.photos.masthead;
  const leadPhoto = heads[Math.floor(Date.now() / 86400000) % heads.length]; usedPhotos.set(leadPhoto.url, leadPhoto);

  let html = `
  <section class="lead">
    <article class="lead-story">
      <a href="#/decision/${encodeURIComponent(lead.id)}">${img(leadPhoto, "European Parliament plenary").replace(" loading=\"lazy\"", "")}</a>
      ${credit(leadPhoto)}
      <div style="margin-top:14px"><span class="kicker">${esc(SEC[lead.section].name)}<span class="k2">${esc(lead.kind)}</span></span></div>
      <a href="#/decision/${encodeURIComponent(lead.id)}"><h1 class="hl">${esc(lead.headline)}</h1></a>
      <p class="dek">${esc(dek(lead))}</p>
      <div class="meta">${pill(lead)}<span>Adopted ${dLong(lead.date)}</span><span>${esc(lead.ref)}</span></div>
      <div class="lead-goals">
        <h3>The Scorecard</h3>
        <div class="lead-goals-grid">${D.targets.slice(0, 4).map(t => scoreCard(t, true)).join('')}</div>
        ${D.targets.length > 4 ? `<a class="more-goals" href="#/goals">All ${D.targets.length} goals we track →</a>` : ''}
      </div>
    </article>
    <aside class="rail">
      <h3>Just in</h3>
      <ul class="plain justin">${latest.map(d => `<li>
        <span class="kicker">${esc(SEC[d.section].kicker)}${isNew(d) ? '<span class="tag new">New</span>' : ''}</span>
        <a href="#/decision/${encodeURIComponent(d.id)}"><div class="hl">${esc(d.headline)}</div></a>
        <div class="meta">${dShort(d.date)}</div></li>`).join('')}</ul>
    </aside>
  </section>

  <div class="section-title"><h2>Top stories</h2></div>
  <section class="top3">${top.map(d => { const p = photoFor(d); return `<article class="card">
      <a href="#/decision/${encodeURIComponent(d.id)}">${img(p, d.headline)}</a>
      <div style="margin-top:12px"><span class="kicker">${esc(SEC[d.section].name)}</span></div>
      <a href="#/decision/${encodeURIComponent(d.id)}"><h2 class="hl">${esc(d.headline)}</h2></a>
      <p class="dek">${esc(dek(d))}</p>
      <div class="meta">${pill(d)}<span>${dShort(d.date)}</span></div></article>`; }).join('')}
  </section>

  <div class="section-title"><h2>More headlines</h2></div>
  <ul class="plain more">${more.map(d => `<li>
      <span class="kicker">${esc(SEC[d.section].kicker)}</span>
      <a href="#/decision/${encodeURIComponent(d.id)}"><div class="hl">${esc(d.headline)}</div></a>
      <div class="meta">${pill(d)}</div></li>`).join('')}</ul>`;

  const council = photo('commission', 'band');
  html += `<section class="band">${img(council, 'Berlaymont, European Commission headquarters')}
    <div><span class="kicker" style="color:var(--gold)">Why this exists</span>
      <h2>Brussels makes the promises. We keep the receipts.</h2>
      <p>Every day, the EU adopts laws, targets and sanctions. Most coverage stops at the vote. We follow each decision after the headlines fade: when it kicks in, what came next, and whether the numbers are moving.</p>
      <p style="font:500 13px var(--sans);color:#9fb0d6">${D.decisions.length} decisions tracked since ${dLong(D.since)} · updated ${dLong(D.updated)}</p>
    </div></section>`;

  html += `<div class="section-title"><h2>The sections</h2></div><section class="sec-grid">`;
  D.sections.forEach(s => {
    const list = D.decisions.filter(d => d.section === s.id && !used.has(d.id)).sort((a, b) => weight(b) - weight(a)).slice(0, 3);
    const all = D.decisions.filter(d => d.section === s.id).length;
    if (!all) return;
    const p = list[0] ? photoFor(list[0]) : photo(s.id, 'sec');   // matches the first headline beside it
    html += `<div class="sec-block"><header><a href="#/section/${s.id}"><h3 class="hl" style="margin:0">${esc(s.name)}</h3></a><span class="count">${all} decisions</span></header>
      <div class="sec-inner"><a href="#/section/${s.id}">${img(p, s.name)}</a>
      <ul class="plain">${list.map(d => `<li><a href="#/decision/${encodeURIComponent(d.id)}"><div class="hl">${esc(d.headline)}</div></a><div class="meta">${dShort(d.date)}</div></li>`).join('')}
      <li><a href="#/section/${s.id}" class="kicker">All ${esc(s.name)} decisions →</a></li></ul></div></div>`;
  });
  html += `</section>`;
  $app.innerHTML = html;
  fitJustIn();
}

// "Just in" shows as many headlines as fit beside the lead story (7 on narrow screens, where the columns stack)
function fitJustIn() {
  const lead = document.querySelector('.lead-story'), items = [...document.querySelectorAll('.justin li')];
  if (!lead || !items.length) return;
  items.forEach(li => li.hidden = false);
  if (innerWidth <= 960) { items.forEach((li, i) => li.hidden = i >= 7); return; }
  const limit = Math.max(...[...lead.children].map(c => c.getBoundingClientRect().bottom));
  for (let i = items.length - 1; i >= 5 && items[i].getBoundingClientRect().bottom > limit; i--) items[i].hidden = true;
}
window.addEventListener('resize', () => { clearTimeout(fitJustIn.t); fitJustIn.t = setTimeout(fitJustIn, 150); });

// ---------------------------------------------------------------- goals page (#/goals)
function renderGoals() {
  document.title = `The Scorecard · ${D.site.name}`;
  const n = D.targets.length, on = D.targets.filter(t => paceVerdict(t).cls === 'good').length;
  const bySec = D.sections.map(s => [s, D.targets.filter(t => t.section === s.id)]).filter(([, ts]) => ts.length);
  $app.innerHTML = `
    <div class="crumbs"><a href="#/">Front page</a> › The Scorecard</div>
    <div class="section-title"><h2>The Scorecard</h2></div>
    <p class="dek" style="max-width:760px">The EU has set itself numbers to hit by 2030. We check each one against the latest official statistics from Eurostat, every day. <b>${on} of ${n}</b> ${on === 1 ? 'is' : 'are'} on track.</p>
    ${bySec.map(([s, ts]) => `<div class="month"><a href="#/section/${s.id}">${esc(s.name)}</a></div>
      <div class="goals">${ts.map(t => scoreCard(t)).join('')}</div>`).join('')}
    <p class="muted" style="font-size:14px;margin-top:24px">“% of the way” compares the latest figure with the starting year shown on each card. “Needs to move × faster” compares the pace of the last ten years with the pace needed to reach the goal by 2030.</p>`;
}

// ---------------------------------------------------------------- section page
function renderSection(s) {
  document.title = `${s.name} · ${D.site.name}`;
  const list = D.decisions.filter(d => d.section === s.id);
  const p = photo(s.id, 'hero');
  const inEffect = list.filter(d => score(d).pct >= 100).length;
  const follow = list.reduce((n, d) => n + d.links.based_on.length + d.links.amended_by.length, 0);
  const goals = D.targets.filter(t => t.section === s.id);
  $app.innerHTML = `
    <div class="crumbs"><a href="#/">Front page</a> › ${esc(s.name)}</div>
    <section class="sec-hero">${img(p, s.name)}
      <div class="over"><span class="kicker">${esc(s.kicker)}</span><h1>${esc(s.name)}</h1>
      <p>Every ${esc(s.name.toLowerCase())} decision the EU has taken since ${dLong(D.since)}, newest first. New ones appear here automatically.</p></div>
    </section>
    ${credit(p)}
    <div class="sec-stats" style="margin-top:14px">
      <div><strong>${list.length}</strong>decisions in two years</div>
      <div><strong>${inEffect}</strong>fully in effect</div>
      <div><strong>${list.length - inEffect}</strong>still rolling out</div>
      <div><strong>${follow}</strong>follow-up acts and reports</div>
    </div>
    ${goals.length ? `<div class="section-title" style="margin-top:22px"><h2>The goals</h2></div><div class="goals">${goals.map(t => scoreCard(t)).join('')}</div>` : ''}
    <div class="filters" id="filters">
      ${['All', 'EU law', 'Council act', 'Foreign policy decision', 'Foreign policy update'].filter(k => k === 'All' || list.some(d => d.kind === k))
        .map((k, i) => `<button data-k="${k}" class="${i ? '' : 'on'}">${k === 'All' ? 'All decisions' : k === 'EU law' ? 'Laws (Parliament + Council)' : k === 'Foreign policy update' ? 'Updates (sanctions, missions, aid)' : k + 's'}</button>`).join('')}
    </div>
    <div id="list"></div>`;
  const draw = k => {
    let html = '', month = '';
    list.filter(d => k === 'All' || d.kind === k).forEach(d => {
      const m = new Date(d.date + 'T12:00').toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
      if (m !== month) { html += `<div class="month">${m}</div>`; month = m; }
      const sc = score(d), dt = new Date(d.date + 'T12:00');
      html += `<article class="row">
        <div class="day">${dt.getDate()}<small>${dt.toLocaleDateString('en-GB', { month: 'short' })}</small></div>
        <div><span class="kicker">${kindTag(d)}${isNew(d) ? '<span class="tag new">New</span>' : ''}<span class="k2">${esc(d.ref)}</span></span>
          <a href="#/decision/${encodeURIComponent(d.id)}"><h2 class="hl">${esc(d.headline)}</h2></a>
          <p class="dek">${esc(dek(d))}</p></div>
        <div class="side">${sc.label}<b>${sc.verdict} · ${sc.pct}%</b><div class="mini ${sc.cls}"><span style="width:${sc.pct}%"></span></div></div>
      </article>`;
    });
    document.getElementById('list').innerHTML = html || '<p class="muted">Nothing here yet.</p>';
  };
  draw('All');
  document.getElementById('filters').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    document.querySelectorAll('#filters button').forEach(x => x.classList.toggle('on', x === b));
    draw(b.dataset.k);
  };
}

// ---------------------------------------------------------------- decision page
function ring(pct, cls) {
  const r = 84, c = 2 * Math.PI * r, col = { good: 'var(--good)', warn: 'var(--warn)', bad: 'var(--bad)' }[cls] || 'var(--eu)';
  return `<svg viewBox="0 0 190 190"><circle cx="95" cy="95" r="${r}" fill="none" stroke="#ece7dc" stroke-width="14"/>
    <circle cx="95" cy="95" r="${r}" fill="none" stroke="${col}" stroke-width="14" stroke-linecap="round"
      stroke-dasharray="${c * pct / 100} ${c}"/></svg>`;
}

function renderDecision(d) {
  document.title = `${d.headline} · ${D.site.name}`;
  const s = SEC[d.section], sc = score(d), ms = milestones(d), p = photoFor(d);
  const next = ms.find(m => m.date > TODAY);
  const nFollow = d.links.based_on.length;
  const related = D.decisions.filter(x => x.section === d.section && x.id !== d.id).sort((a, b) => weight(b) - weight(a)).slice(0, 4);

  $app.innerHTML = `
  <div class="crumbs"><a href="#/">Front page</a> › <a href="#/section/${s.id}">${esc(s.name)}</a></div>
  <div class="article">
    <article>
      <span class="kicker">${esc(s.name)}<span class="k2">${esc(d.kind)} · ${esc(d.ref)}</span>${isNew(d) ? '<span class="tag new">New</span>' : ''}</span>
      <h1 class="hl">${esc(d.headline)}</h1>
      <p class="dek">${esc(dek(d))}</p>
      <div class="meta"><span>Adopted ${dLong(d.date)}</span><span>·</span><span>Tracked by ${esc(D.site.name)}</span></div>
      <figure>${img(p, s.name)}${credit(p)}</figure>
      <div class="official"><b>Official title</b>${esc(d.title)}</div>
    </article>
    <aside><div class="scorebox">
      <div class="lbl">${sc.label}</div>
      <div class="ring">${ring(sc.pct, sc.cls)}<div class="num">${sc.pct}%<small>${sc.kind === 'goal' ? 'of the way to the goal' : 'of milestones reached'}</small></div></div>
      <div class="verdict ${sc.cls}">${sc.verdict}</div>
      <p class="why">${esc(sc.why)}</p>
      <dl class="facts">
        <div><dt>Adopted</dt><dd>${dShort(d.date)}</dd></div>
        <div><dt>In force</dt><dd>${d.in_force[0] ? dShort(d.in_force[0]) : 'n/a'}</dd></div>
        <div><dt>Next milestone</dt><dd>${next ? dShort(next.date) : 'None left'}</dd></div>
        <div><dt>Follow-up actions</dt><dd>${nFollow}</dd></div>
        <div><dt>Later amended</dt><dd>${d.links.amended_by.length ? d.links.amended_by.length + '×' : 'No'}</dd></div>
      </dl>
    </div></aside>
  </div>

  <section class="dig">
    <div class="section-title"><h2>Dig deeper</h2></div>
    <div class="dig-buttons">
      <button data-p="chart">Progress chart<span>${sc.kind === 'goal' ? 'Promises vs. reality, in numbers' : 'How far the rollout has come'}</span></button>
      <button data-p="map">Decision map<span>Everything connected to this decision</span></button>
      <button data-p="timeline">Timeline<span>Every step, past and future</span></button>
      <a href="${eurlex(d.id)}" target="_blank" rel="noopener">Official text ↗<span>Read it on EUR-Lex</span></a>
    </div>
    <div class="panel" id="p-chart"></div>
    <div class="panel" id="p-map"></div>
    <div class="panel" id="p-timeline"></div>
  </section>

  ${related.length ? `<div class="section-title"><h2>More in ${esc(s.name)}</h2><a href="#/section/${s.id}">See all →</a></div>
  <section class="related">${related.map(x => { const ph = photoFor(x); return `<article>
    <a href="#/decision/${encodeURIComponent(x.id)}">${img(ph, x.headline)}<div class="hl">${esc(x.headline)}</div></a>
    <div class="meta">${pill(x)}</div></article>`; }).join('')}</section>` : ''}`;

  const panels = { chart: () => drawChart(d, sc), map: () => drawMap(d, sc), timeline: () => drawTimeline(d) };
  document.querySelector('.dig-buttons').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    const el = document.getElementById('p-' + b.dataset.p), open = !el.classList.contains('on');
    document.querySelectorAll('.dig-buttons button').forEach(x => x.classList.toggle('on', open && x === b));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('on'));
    if (open) { el.innerHTML = panels[b.dataset.p](); el.classList.add('on'); el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  };
}

// ---------- chart
function drawChart(d, sc) {
  if (sc.kind !== 'goal') return rolloutChart(d);
  const t = sc.target, series = Object.entries(t.series).map(([y, v]) => [+y, v]).sort((a, b) => a[0] - b[0]);
  const W = 860, H = 340, m = { l: 58, r: 24, t: 24, b: 34 };
  const x0 = series[0][0], x1 = Math.max(t.goal_year, ...t.later.map(l => l.year)) ;
  const [ly, lv] = series[series.length - 1];
  const projEnd = x1, projRaw = lv + t.real_rate * (projEnd - ly);
  const vals = series.map(s => s[1]).concat([t.goal, ...t.later.map(l => l.value)]);
  // axis: start at zero when the data is close to it, otherwise zoom in so small changes stay visible
  let lo = Math.min(...vals), hi = Math.max(...vals) * 1.08;
  lo = lo < hi * 0.4 ? 0 : lo - (hi - lo) * 0.25;
  const raw = (hi - lo) / 5, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(s => s >= raw);
  const yMin = Math.floor(lo / step) * step, yMax = Math.ceil(hi / step) * step;
  const X = y => m.l + (y - x0) / (x1 - x0) * (W - m.l - m.r), Y = v => m.t + (1 - (v - yMin) / (yMax - yMin)) * (H - m.t - m.b);
  const projV = Math.min(yMax, Math.max(yMin, projRaw));
  const promised = [[ly, lv], [t.goal_year, t.goal], ...t.later.map(l => [l.year, l.value])];
  const axis = v => t.unit === '%' ? `${fmt(v, step < 1 ? 1 : 0)}%` : fmt(v, step < 1 ? 1 : 0);
  let g = '';
  for (let v = yMin; v <= yMax + step / 2; v += step) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ece7dc"/><text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="12" fill="#6f6a60">${axis(v)}</text>`;
  const ystep = x1 - x0 > 12 ? 5 : x1 - x0 > 6 ? 2 : 1;
  for (let y = Math.ceil(x0 / ystep) * ystep; y <= x1; y += ystep) g += `<text x="${X(y)}" y="${H - 10}" text-anchor="middle" font-size="12" fill="#6f6a60">${y}</text>`;
  const path = pts => 'M' + pts.map(([a, v]) => `${X(a).toFixed(1)},${Y(v).toFixed(1)}`).join('L');
  const goals = [[t.goal_year, t.goal, `Goal ${t.goal_year}: ${tval(t, t.goal)}`], ...t.later.map(l => [l.year, l.value, l.label])];
  const up = t.goal > t.start;   // does the line need to go up or down?
  const v = paceVerdict(t);
  const per = t.unit === '%' ? 'percentage points' : t.unit;
  const dp = Math.abs(t.need_rate) < 10 ? 1 : 0;
  return `<h3>${esc(t.title)}</h3>
    <p class="sub">${esc(t.label)}${t.unit === '%' ? '' : ` (${esc(t.unit)})`}. Goal set by: ${esc(t.basis)}. Data: ${esc(t.source)}. This decision is one of the tools meant to get there.</p>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${g}
      <path d="${path(promised)}" fill="none" stroke="var(--good)" stroke-width="2.5" stroke-dasharray="7 5"/>
      <path d="M${X(ly)},${Y(lv)}L${X(projEnd)},${Y(projV)}" fill="none" stroke="var(--bad)" stroke-width="2" stroke-dasharray="2 4"/>
      <path d="${path(series)}" fill="none" stroke="var(--eu)" stroke-width="3"/>
      <circle cx="${X(ly)}" cy="${Y(lv)}" r="5" fill="var(--eu)"/>
      <text x="${X(ly) - 10}" y="${Y(lv) + (up ? -14 : 24)}" text-anchor="end" font-size="13" font-weight="700" fill="var(--eu)">${ly}: ${tval(t, lv)}</text>
      ${goals.map(([a, val, l], i) => `<circle cx="${X(a)}" cy="${Y(val)}" r="6" fill="#fff" stroke="var(--good)" stroke-width="3"/>
        <text x="${X(a) + (a === x1 ? -10 : 10)}" y="${Y(val) + (i === 0 ? 26 : -12)}" text-anchor="${a === x1 ? 'end' : 'start'}" font-size="13" font-weight="700" fill="var(--good)">${esc(l)}</text>`).join('')}
    </svg>
    <div class="legend"><span><i style="border-color:var(--eu)"></i>What actually happened</span><span><i style="border-color:var(--good);border-top-style:dashed"></i>What was promised</span><span><i style="border-color:var(--bad);border-top-style:dotted"></i>If the current pace continues</span></div>
    <p style="margin:16px 0 0"><b class="verdict ${v.cls}" style="display:inline">${verdictTxt(v)}.</b> Over the last decade the figure moved by ${fmt(Math.abs(t.real_rate), dp)} ${esc(per)} a year${(t.real_rate > 0) !== up && t.real_rate ? ' in the wrong direction' : ''}; reaching the goal needs ${fmt(Math.abs(t.need_rate), dp)} ${esc(per)} a year${up ? ' up' : ' down'}.</p>
    ${t.sectors ? sectorBars(t) : ''}`;
}

function sectorBars(t) {
  const rows = Object.entries(t.sectors).map(([name, s]) => {
    const ys = Object.keys(s).map(Number).sort((a, b) => a - b), ly = ys[ys.length - 1];
    return { name, ch: (s[ly] / s[2005] - 1) * 100, ly };
  }).sort((a, b) => a.ch - b.ch);
  const max = Math.max(...rows.map(r => Math.abs(r.ch)));
  return `<h3 style="margin-top:26px">Who is cutting, who is not</h3><p class="sub">Change in emissions since 2005, by sector (Eurostat).</p>
    ${rows.map(r => `<div style="display:grid;grid-template-columns:120px 1fr 64px;gap:10px;align-items:center;font:500 13.5px var(--sans);margin:7px 0">
      <span>${esc(r.name)}</span><div style="background:#f1ede4;height:14px;border-radius:3px;position:relative">
      <span style="position:absolute;right:${r.ch < 0 ? 0 : 'auto'};left:${r.ch < 0 ? 'auto' : 0};width:${Math.abs(r.ch) / max * 100}%;height:100%;border-radius:3px;background:${r.ch <= -30 ? 'var(--good)' : r.ch <= -10 ? 'var(--warn)' : 'var(--bad)'}"></span></div>
      <b style="text-align:right">${r.ch > 0 ? '+' : ''}${fmt(r.ch, 0)}%</b></div>`).join('')}`;
}

function rolloutChart(d) {
  const ms = milestones(d);
  const first = Date.parse(ms[0].date), last = Date.parse(ms[ms.length - 1].date), now = Date.parse(TODAY);
  const end = Math.max(last, now) + 864e5 * 30, start = first - 864e5 * 15;
  const W = 860, H = 150, X = t => 30 + (t - start) / (end - start) * (W - 60);
  const items = ms.map((m, i) => { const t = Date.parse(m.date), past = m.date <= TODAY;
    return `<circle cx="${X(t)}" cy="70" r="9" fill="${past ? 'var(--eu)' : '#fff'}" stroke="var(--eu)" stroke-width="3"/>
      <text x="${X(t)}" y="${i % 2 ? 108 : 42}" text-anchor="middle" font-size="12" font-weight="700" fill="#141414">${dShort(m.date)}</text>
      <text x="${X(t)}" y="${i % 2 ? 124 : 26}" text-anchor="middle" font-size="11.5" fill="#6f6a60">${esc(m.what.split(' (')[0])}</text>`; }).join('');
  return `<h3>Rollout: ${score(d).pct}% of milestones reached</h3>
    <p class="sub">This decision has no single number to track yet, so we follow its legal milestones. Filled = done, hollow = still to come.</p>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
      <line x1="30" x2="${W - 30}" y1="70" y2="70" stroke="#d9d3c7" stroke-width="4"/>
      <line x1="${X(start)}" x2="${X(Math.min(now, end))}" y1="70" y2="70" stroke="var(--eu)" stroke-width="4"/>
      ${items}
      <line x1="${X(now)}" x2="${X(now)}" y1="52" y2="88" stroke="var(--bad)" stroke-width="2"/>
      <text x="${X(now)}" y="146" text-anchor="middle" font-size="11" font-weight="700" fill="var(--bad)">TODAY</text>
    </svg>
    <p style="margin:12px 0 0">${d.links.based_on.length ? `Since adoption, <b>${d.links.based_on.length} follow-up act${d.links.based_on.length > 1 ? 's and reports' : ' or report'}</b> have built on this decision. Open the decision map to see them.` : 'No follow-up acts have been published yet.'}</p>`;
}

// ---------- mind map
function wrap(txt, max) {
  const out = []; let cur = '';
  txt.split(' ').forEach(w => { if ((cur + ' ' + w).trim().length > max && cur) { out.push(cur); cur = w; } else cur = (cur + ' ' + w).trim(); });
  out.push(cur); return out.slice(0, 4);
}
function svgText(lines, x, y, anchor, size, weight, fill = '#141414') {
  const lh = size * 1.18, y0 = y - (lines.length - 1) * lh / 2 + size * 0.35;
  return `<text x="${x}" y="${y0}" text-anchor="${anchor}" font-size="${size}" font-weight="${weight}" fill="${fill}">${lines.map((l, i) => `<tspan x="${x}" dy="${i ? lh : 0}">${esc(l)}</tspan>`).join('')}</text>`;
}

function drawMap(d, sc) {
  const link = id => BY_ID[id] ? `#/decision/${encodeURIComponent(id)}` : eurlex(id);
  const leaf = x => ({ label: x.label || x.ref, sub: dShort(x.date), href: link(x.id), ext: !BY_ID[x.id] });
  const acts = d.links.based_on.filter(x => x.type === 'act'), docs = d.links.based_on.filter(x => x.type !== 'act');
  const branches = [];
  if (sc.target) branches.push({ name: 'The goal', color: '#1e7d4f', items: [{ label: sc.target.short, sub: `${sc.target.progress}% there`, href: null }] });
  branches.push({ name: 'Milestones', color: '#1f3a93', items: milestones(d).map(m => ({ label: m.what.split(' (')[0], sub: dShort(m.date) + (m.date > TODAY ? ' (upcoming)' : ''), href: null })) });
  if (acts.length) branches.push({ name: 'Follow-up rules', color: '#c27c0e', items: acts.map(leaf) });
  if (docs.length) branches.push({ name: 'Reports & votes', color: '#8a5cc2', items: docs.map(x => ({ ...leaf(x), label: (x.id.includes('IP') ? 'Parliament vote' : x.id.includes('DC') ? 'Commission report' : x.id.includes('PC') ? 'Proposal' : 'Document') + ': ' + (x.label || x.ref) })) });
  if (d.links.changes.length) branches.push({ name: 'Laws it changes', color: '#5f6b7a', items: d.links.changes.map(leaf) });
  if (d.links.amended_by.length) branches.push({ name: 'Later amended by', color: '#b3261e', items: d.links.amended_by.map(leaf) });

  // two columns of branches around the centre; leaves stacked beside each branch
  const W = 1000, cx = W / 2, LEAF_H = 48, GAP = 34;
  const sides = [[], []];
  branches.forEach((b, i) => {
    const shown = b.items.slice(0, 5), extra = b.items.length - shown.length;
    b.leaves = extra > 0 ? [...shown, { label: `+${extra} more (see timeline)`, sub: '', href: null }] : shown;
    b.h = Math.max(110, b.leaves.length * LEAF_H);
    sides[i % 2].push(b);
  });
  const colH = sides.map(c => c.reduce((n, b) => n + b.h, 0) + GAP * (c.length - 1));
  const H = Math.max(420, ...colH) + 60, cy = H / 2;
  let lines = '', nodes = '';
  sides.forEach((col, si) => {
    const dir = si === 0 ? 1 : -1;
    let y = (H - colH[si]) / 2;
    col.forEach(b => {
      const by = y + b.h / 2, bx = cx + dir * 215, lx = cx + dir * 318;
      lines += `<path d="M${cx},${cy} C${cx + dir * 110},${cy} ${bx - dir * 90},${by} ${bx},${by}" stroke="${b.color}" stroke-width="3" fill="none" opacity=".55"/>`;
      b.leaves.forEach((l, j) => {
        const ly = by + (j - (b.leaves.length - 1) / 2) * LEAF_H;
        const anchor = dir > 0 ? 'start' : 'end', tx = lx + dir * 11;
        const ls = wrap(l.label, 34).slice(0, 2);
        lines += `<path d="M${bx},${by} C${bx + dir * 50},${by} ${lx - dir * 50},${ly} ${lx},${ly}" stroke="${b.color}" stroke-width="1.4" fill="none" opacity=".4"/>`;
        const label = svgText(ls, tx, ly - (l.sub ? 6 : 0), anchor, 12, 600);
        const sub = l.sub ? `<text x="${tx}" y="${ly + (ls.length > 1 ? 18 : 11)}" text-anchor="${anchor}" font-size="10.5" fill="#6f6a60">${esc(l.sub)}</text>` : '';
        const dot = `<circle cx="${lx}" cy="${ly}" r="5" fill="${b.color}"/>`;
        nodes += l.href ? `<a href="${esc(l.href)}"${l.ext ? ' target="_blank" rel="noopener"' : ''}>${dot}${label}${sub}</a>` : `<g>${dot}${label}${sub}</g>`;
      });
      nodes += `<g><circle cx="${bx}" cy="${by}" r="46" fill="#fff" stroke="${b.color}" stroke-width="3.5"/>
        ${svgText(wrap(b.name, 11), bx, by - 7, 'middle', 12.5, 700)}
        <text x="${bx}" y="${by + 27}" text-anchor="middle" font-size="11.5" font-weight="800" fill="${b.color}">${b.items.length}</text></g>`;
      y += b.h + GAP;
    });
  });
  const short = d.headline.length > 80 ? d.headline.slice(0, 80).replace(/\s+\S*$/, '') + '…' : d.headline;
  const center = `<circle cx="${cx}" cy="${cy}" r="96" fill="#141414"/>${svgText(wrap(short, 20).slice(0, 5), cx, cy - 10, 'middle', 13, 700, '#faf8f3')}
    <text x="${cx}" y="${cy + 62}" text-anchor="middle" font-size="11" fill="#f2c230" font-weight="700">${esc(d.ref)}</text>`;
  return `<h3>Decision map</h3><p class="sub">The decision at the centre; around it, its milestones, the rules and reports that followed, and the laws it touches. Click a node to open it.</p>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${lines}${nodes}${center}</svg>`;
}

// ---------- timeline
function drawTimeline(d) {
  const ev = milestones(d).map(m => ({ date: m.date, what: m.what, cls: m.date > TODAY ? 'future' : '' }));
  d.links.based_on.forEach(x => ev.push({ date: x.date, cls: 'follow', what: `${x.type === 'act' ? 'Follow-up rule' : 'Report or resolution'}: <a href="${BY_ID[x.id] ? '#/decision/' + encodeURIComponent(x.id) : eurlex(x.id)}" ${BY_ID[x.id] ? '' : 'target="_blank" rel="noopener"'}>${esc(x.label || x.id)}</a>`, html: true }));
  d.links.amended_by.forEach(x => ev.push({ date: x.date, cls: 'follow', what: `Amended by <a href="${eurlex(x.id)}" target="_blank" rel="noopener">${esc(x.ref)}</a>`, html: true }));
  ev.sort((a, b) => a.date.localeCompare(b.date));
  return `<h3>Timeline</h3><p class="sub">Blue: legal milestones. Gold: what happened next. Hollow: still to come.</p>
    <ul class="tl">${ev.map(e => `<li class="${e.cls}"><div class="d">${dLong(e.date)}${e.date > TODAY ? ' · upcoming' : ''}</div><div class="w">${e.html ? e.what : esc(e.what)}</div></li>`).join('')}</ul>`;
}

// ---------------------------------------------------------------- boot
fetch('data.json').then(r => r.json()).then(data => {
  D = data;
  BY_ID = Object.fromEntries(D.decisions.map(d => [d.id, d]));
  SEC = Object.fromEntries(D.sections.map(s => [s.id, s]));
  TGT = Object.fromEntries(D.targets.map(t => [t.id, t]));
  document.getElementById('tagline').textContent = D.site.tagline;
  document.getElementById('today').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  document.getElementById('tracking').textContent = `Tracking ${D.decisions.length} EU decisions since ${dShort(D.since)}`;
  document.getElementById('updated').textContent = `Updated ${dShort(D.updated)} from EUR-Lex & Eurostat`;
  document.getElementById('nav').innerHTML = `<div class="wrap"><a href="#/">Front page</a><a href="#/goals" data-id="goals">Scorecard</a>${D.sections.map(s => `<a href="#/section/${s.id}" data-id="${s.id}">${esc(s.name)}</a>`).join('')}</div>`;
  window.addEventListener('hashchange', route);
  route();
}).catch(e => { $app.innerHTML = `<p class="loading">Could not load data.json (${esc(e.message)}). Serve this folder with a local web server.</p>`; });
