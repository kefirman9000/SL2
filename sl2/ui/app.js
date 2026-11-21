/* SL2 front end: one file, no frameworks. */
'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const T = window.SL2.token;
const audio = $('#audio');
const S = { genres: [], genre: 'liquid_dnb', song: null, sel: null, lib: [], libSel: null, mix: {}, length: 'normal',
            loop: false, roll: { notes: [], dirty: false, zoom: 14 }, busy: false, choices: {}, caps: {}, feel: {}, ab: null };
// small per-browser memory (favourite genres, recent genres, your composer picks); never required
const mem = {
  get(k, d) { try { const v = localStorage.getItem('sl2.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('sl2.' + k, JSON.stringify(v)); } catch (e) { /* storage off: fine */ } },
};
const FEEL = [
  ['fills', 'FILLS', { none: 'NONE', fewer: 'FEWER', normal: 'NORMAL', more: 'MORE' }, 'Drum fills at the ends of sections and phrases'],
  ['hats', 'HI-HATS', { sparse: 'SPARSE', normal: 'NORMAL', busy: 'BUSY' }, 'Sparse = 8ths, busy = extra 16ths'],
  ['ghosts', 'GHOST NOTES', { off: 'OFF', normal: 'SOME', more: 'MORE' }, 'Soft in-between snare hits'],
  ['builds', 'BUILD-UPS', { on: 'ON', subtle: 'SUBTLE', off: 'OFF' }, 'Subtle = no snare rolls or risers, the groove keeps going; off = no build sections'],
  ['fx', 'TRANSITION FX', { normal: 'ALL', fewer: 'FEWER', off: 'OFF' }, 'Risers, reverse cymbals, impacts, downlifters'],
  ['variation', 'VARIATION', { low: 'LOOPY', normal: 'NORMAL', high: 'RESTLESS' }, 'How much the parts change from phrase to phrase: fills, entries, sweeps, later drops'],
];

// ------------------------------------------------------------------ api
async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({}, opts, { headers: Object.assign({ 'X-SL2-Token': T }, opts.headers || {}) }));
  const j = await r.json().catch(() => ({ error: 'bad response' }));
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
function toast(msg, ms = 3200) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('on'), ms); }
const fmt = s => { s = Math.max(0, s | 0); return `${(s / 60) | 0}:${String(s % 60).padStart(2, '0')}`; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function runJob(jobId, label) {
  S.busy = true;
  const w = $('#progWrap'); w.classList.add('on');
  try {
    for (;;) {
      const j = await api('/api/job/' + jobId);
      $('#progBar').style.width = (j.progress * 100).toFixed(0) + '%';
      $('#progMsg').textContent = `${label}: ${j.message}`;
      setMarquee(`${label.toUpperCase()}... ${Math.round(j.progress * 100)}% *** ${j.message.toUpperCase()} *** `);
      if (j.status === 'done') return j.result;
      if (j.status === 'error') throw new Error(j.error);
      await new Promise(r => setTimeout(r, 400));
    }
  } finally { S.busy = false; setTimeout(() => w.classList.remove('on'), 600); }
}

// ------------------------------------------------------------------ marquee & lcd
let marqX = 0, marqText = '';
function setMarquee(t) { if (t === marqText) return; marqText = t; $('#marq').textContent = t + '   ' + t; }
function tickMarquee() {
  const el = $('#marq'), w = el.scrollWidth / 2;
  marqX = (marqX + 0.6) % Math.max(1, w);
  el.style.transform = `translateX(${-marqX}px)`;
}

// ------------------------------------------------------------------ genres
function renderGenres() {
  const box = $('#genres'), top = box.scrollTop; box.innerHTML = '';
  const q = ($('#gsearch').value || '').trim().toLowerCase();
  const favs = mem.get('favs', []), recent = mem.get('recent', []);
  const hit = g => !q || [g.name, g.desc, g.group, ...(g.keywords || []), g.refs || ''].join(' ').toLowerCase().includes(q);
  const groups = [];
  if (!q) {
    const f = S.genres.filter(g => favs.includes(g.id)); if (f.length) groups.push(['☆ Favourites', f]);
    const r = recent.map(id => S.genres.find(g => g.id === id)).filter(Boolean).slice(0, 4); if (r.length) groups.push(['Recent', r]);
  }
  let grp = null, cur = null;
  for (const g of S.genres.filter(hit)) { if (g.group !== grp) { grp = g.group; cur = [grp || 'More', []]; groups.push(cur); } cur[1].push(g); }
  if (!groups.length) box.insertAdjacentHTML('beforeend', '<div class="grp">no genre matches - try a sound or a mood</div>');
  for (const [name, list] of groups) {
    box.insertAdjacentHTML('beforeend', `<div class="grp">${esc(name)}</div>`);
    for (const g of list) {
      const d = document.createElement('div');
      d.className = 'g' + (g.id === S.genre ? ' on' : '');
      d.title = g.desc + (g.refs ? `\nModelled on: ${g.refs}` : '');
      d.innerHTML = `<span class="fav ${favs.includes(g.id) ? 'on' : ''}" title="Favourite">${favs.includes(g.id) ? '★' : '☆'}</span><span>${esc(g.name)}</span>${g.refs ? '<span class="ref">★</span>' : ''}<span class="r">${g.bpm[0]}-${g.bpm[1]}</span>`;
      d.onclick = () => { S.genre = g.id; renderGenres(); $('#said').textContent = g.desc.toUpperCase(); };
      d.querySelector('.fav').onclick = e => {
        e.stopPropagation();
        const f = mem.get('favs', []), i = f.indexOf(g.id);
        if (i >= 0) f.splice(i, 1); else f.push(g.id);
        mem.set('favs', f); renderGenres();
      };
      box.appendChild(d);
    }
  }
  box.scrollTop = top;
}
function noteRecent(id) { const r = mem.get('recent', []).filter(x => x !== id); r.unshift(id); mem.set('recent', r.slice(0, 6)); }

function renderFeel() {
  const box = $('#feel'); box.innerHTML = '';
  for (const [k, label, opts, tip] of FEEL) {
    const cur = S.feel[k] || Object.keys(opts).find(v => v === 'normal' || v === 'on') || Object.keys(opts)[0];
    const d = document.createElement('div'); d.title = tip;
    d.innerHTML = `<div class="lab">${label}</div><div class="seg">${Object.entries(opts).map(([v, t]) => `<button data-v="${v}" class="${v === cur ? 'on' : ''}">${t}</button>`).join('')}</div>`;
    d.querySelectorAll('button').forEach(b => b.onclick = () => { S.feel[k] = b.dataset.v; saveComposer(); renderFeel(); });
    box.appendChild(d);
  }
}
function saveComposer() { mem.set('composer', { feel: S.feel, length: S.length, energy: +$('#energy').value, genre: S.genre }); }

function settingsFromUI() {
  const s = Object.assign({ genre: S.genre, energy: +$('#energy').value / 100, length: S.length, seed: parseInt($('#seed').value) || 1 }, S.feel);
  const b = parseFloat($('#bpm').value); if (b) s.bpm = b;
  const k = $('#key').value.trim(); if (k) s.key = k;
  return s;
}

async function compose(extra = {}) {
  if (S.busy) return toast('BUSY - ONE THING AT A TIME');
  let s = settingsFromUI();
  const text = $('#prompt').value.trim();
  if (text && !extra.skipPrompt) {
    const r = await post('/api/prompt', { text });
    $('#said').textContent = r.understood.join('  ·  ').toUpperCase();
    s = Object.assign(s, r.settings);
    if (r.settings.genre) { S.genre = r.settings.genre; renderGenres(); }
    if (r.settings.energy) { $('#energy').value = Math.round(r.settings.energy * 100); $('#energyV').textContent = $('#energy').value; }
  }
  Object.assign(s, extra); delete s.skipPrompt;
  noteRecent(s.genre); saveComposer();
  try {
    const { job } = await post('/api/generate', s);
    const meta = await runJob(job, 'composing');
    await loadSong(meta.id, true);
    refreshLibrary();
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}

// ------------------------------------------------------------------ songs
async function loadSong(id, autoplay) {
  const v = await api('/api/song/' + id);
  S.song = v; S.mix = JSON.parse(JSON.stringify(v.meta.mix || {}));
  const m = v.meta, sg = v.song;
  setMarquee(`${m.title.toUpperCase()} - ${sg.genre_name.toUpperCase()} (${fmt(m.duration)}) *** ${sg.key.toUpperCase()} *** ${Math.round(sg.bpm)} BPM *** `);
  $('#bpmBox').textContent = Math.round(sg.bpm); $('#keyBox').textContent = sg.key.toUpperCase(); $('#indGenre').textContent = sg.genre_name;
  const t = audio.currentTime, wasPlaying = !audio.paused;
  audio.src = `/api/song/${id}/mix.wav?t=${encodeURIComponent(T)}&r=${m.rev || 0}`;
  if (!autoplay && wasPlaying) { audio.currentTime = t; }
  if (autoplay || wasPlaying) audio.play().catch(() => {});
  if (!S.sel || !v.tracks.find(x => x.id === S.sel)) S.sel = (v.tracks.find(x => x.role === 'lead') || v.tracks.find(x => x.role === 'bass') || v.tracks[0] || {}).id;
  renderFaders(); renderTimeline(); renderTrackSel(); renderInfo(); renderPlaylist();
  await loadRoll();
}

function renderInfo() {
  const m = S.song.meta;
  const lines = [...(m.insights || [])];
  const ag = m.autogain || {};
  const ag2 = Object.entries(ag).filter(([, v]) => v && v.gain_db != null).map(([k, v]) => `${k} ${v.gain_db > 0 ? '+' : ''}${v.gain_db}`).join(', ');
  if (ag2) lines.push('Auto-gain (dB): ' + ag2);
  lines.push(`Form: ${(m.report.form || []).join(' · ')}`);
  $('#insights').textContent = lines.map(l => '> ' + l).join('\n');
}

// ------------------------------------------------------------------ mixer
function renderFaders() {
  const box = $('#faders'); box.innerHTML = '';
  box.insertAdjacentHTML('beforeend', `<div class="scale"><span>+12 db</span><span>+0 db</span><span>-12 db</span></div>`);
  const pre = document.createElement('div'); pre.className = 'ch master';
  pre.innerHTML = `<span class="db" id="preDb">0.0</span><input type="range" class="vf" min="-12" max="12" step="0.5" value="0" id="preamp"><span class="nm">PREAMP</span>`;
  box.appendChild(pre);
  $('#preamp').oninput = e => { pre.querySelector('.db').textContent = (+e.target.value).toFixed(1); applyOut(); };
  for (const t of S.song.tracks) {
    const mx = S.mix[t.id] || {};
    const ch = document.createElement('div'); ch.className = 'ch' + (t.id === S.sel ? ' sel' : '');
    ch.innerHTML = `<span class="db">${(mx.gain_db || 0).toFixed(1)}</span>
      <input type="range" class="vf" min="-12" max="12" step="0.5" value="${mx.gain_db || 0}">
      <span class="nm" title="${esc(t.label)} - click to edit">${esc(t.id)}</span>
      <div class="ms"><button class="m ${mx.mute ? 'on' : ''}" title="Mute">M</button><button class="s ${mx.solo ? 'on' : ''}" title="Solo">S</button><button class="l ${t.locked ? 'on' : ''}" title="Lock">L</button></div>`;
    const f = ch.querySelector('.vf');
    f.oninput = () => { ch.querySelector('.db').textContent = (+f.value).toFixed(1); setMix(t.id, { gain_db: +f.value }); drawCurve(); };
    f.onchange = () => scheduleRemix();
    ch.querySelector('.nm').onclick = () => { S.sel = t.id; renderFaders(); renderTrackSel(); loadRoll(); };
    ch.querySelector('.m').onclick = e => { e.target.classList.toggle('on'); setMix(t.id, { mute: e.target.classList.contains('on') }); scheduleRemix(0); };
    ch.querySelector('.s').onclick = e => { e.target.classList.toggle('on'); setMix(t.id, { solo: e.target.classList.contains('on') }); scheduleRemix(0); };
    ch.querySelector('.l').onclick = async e => { const on = !t.locked; t.locked = on; e.target.classList.toggle('on', on); await post(`/api/song/${S.song.meta.id}/lock`, { track: t.id, on }); renderTrackSel(); toast(on ? `${t.id.toUpperCase()} LOCKED - KEPT WHEN RE-ROLLING` : `${t.id.toUpperCase()} UNLOCKED`); };
    box.appendChild(ch);
  }
  drawCurve();
}
function setMix(id, v) { S.mix[id] = Object.assign(S.mix[id] || {}, v); }
function drawCurve() {
  const c = $('#curve'), g = c.getContext('2d'); c.width = c.clientWidth || 300;
  g.clearRect(0, 0, c.width, c.height);
  if (!S.song) return;
  const vals = S.song.tracks.map(t => (S.mix[t.id] || {}).gain_db || 0);
  g.strokeStyle = '#e8c24a'; g.lineWidth = 1.5; g.beginPath();
  vals.forEach((v, i) => { const x = 6 + i * (c.width - 12) / Math.max(1, vals.length - 1), y = c.height / 2 - v / 12 * (c.height / 2 - 3); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.stroke();
}
let remixT = null;
function scheduleRemix(delay = 500) {
  if (!$('#mixAuto').classList.contains('on')) return;
  clearTimeout(remixT); remixT = setTimeout(remix, delay);
}
async function remix() {
  if (!S.song) return;
  if (S.busy) { scheduleRemix(800); return; }
  const mix = $('#mixOn').classList.contains('on') ? S.mix : {};
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/mix`, { mix });
    await runJob(job, 'mixing');
    await loadSong(S.song.meta.id, false);
  } catch (e) { toast('ERROR: ' + e.message); }
}

// ------------------------------------------------------------------ audio out + visualiser
let actx = null, an = null, gainN = null, panN = null;
function ensureAudio() {
  if (actx) return;
  actx = new (window.AudioContext || window.webkitAudioContext)();
  const src = actx.createMediaElementSource(audio);
  gainN = actx.createGain(); panN = actx.createStereoPanner(); an = actx.createAnalyser(); an.fftSize = 2048; an.smoothingTimeConstant = 0.6;
  src.connect(gainN).connect(panN).connect(an).connect(actx.destination);
  applyOut();
}
function applyOut() {
  if (!gainN) return;
  const pre = $('#preamp') ? +$('#preamp').value : 0;
  gainN.gain.value = (+$('#vol').value / 100) ** 1.6 * Math.pow(10, pre / 20);
  panN.pan.value = +$('#bal').value / 100;
}
const peaksHold = new Array(19).fill(0);
function drawVis() {
  const c = $('#vis'), g = c.getContext('2d'), W = c.width, H = c.height;
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
  g.fillStyle = '#0b1a0b';
  for (let y = 0; y < H; y += 4) for (let x = 0; x < W; x += 4) g.fillRect(x, y, 1, 1);
  if (!an || audio.paused) return;
  const d = new Uint8Array(an.frequencyBinCount); an.getByteFrequencyData(d);
  const n = 19, bw = Math.floor(W / n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(Math.pow(i / n, 2) * d.length * 0.7) + 1, b = Math.floor(Math.pow((i + 1) / n, 2) * d.length * 0.7) + 2;
    let m = 0; for (let k = a; k < b; k++) m = Math.max(m, d[k]);
    const h = Math.round((m / 255) * H);
    for (let y = 0; y < h; y += 2) {
      const f = y / H; g.fillStyle = f > 0.8 ? '#ff4b2b' : f > 0.6 ? '#e8c24a' : '#39ff14'; g.fillRect(i * bw + 1, H - y - 2, bw - 2, 1);
    }
    peaksHold[i] = Math.max(peaksHold[i] - 0.7, h);
    g.fillStyle = '#d9dbe8'; g.fillRect(i * bw + 1, H - peaksHold[i] - 2, bw - 2, 1);
  }
}

// ------------------------------------------------------------------ timeline & sections
function secAt(beat) { const s = S.song.song.sections; return s.find(x => beat >= x.start_bar * 4 && beat < (x.start_bar + x.bars) * 4); }
function beatNow() { return audio.currentTime * S.song.song.bpm / 60; }
function renderTimeline() {
  const tl = $('#timeline'); tl.innerHTML = '';
  const sg = S.song.song, total = sg.bars;
  const mutes = (sg.settings && sg.settings.section_mutes) || {};
  sg.sections.forEach((s, i) => s._i = i);
  for (const s of sg.sections) {
    const i = s._i;
    const d = document.createElement('div');
    d.className = `sec ${s.kind}${mutes[i] && mutes[i].length ? ' muted' : ''}`; d.style.width = (s.bars / total * 100) + '%';
    d.innerHTML = `<div class="e" style="height:${Math.round(s.energy * 100)}%"></div><span class="n">${esc(s.name)} ${s.bars}</span>`;
    d.title = `${s.name}: bars ${s.start_bar + 1}-${s.start_bar + s.bars}, energy ${Math.round(s.energy * 100)}`;
    d.onclick = () => { audio.currentTime = s.start_bar * 4 * 60 / sg.bpm; if (audio.paused) play(); };
    d.oncontextmenu = e => { e.preventDefault(); sectionMenu(e.clientX, e.clientY, i); };
    tl.appendChild(d);
  }
  tl.insertAdjacentHTML('beforeend', '<div class="ph" id="ph"></div>');
  const marks = $('#secmarks'); marks.innerHTML = '';
  for (const s of sg.sections.slice(1)) marks.insertAdjacentHTML('beforeend', `<i style="left:${s.start_bar / total * 100}%"></i>`);
}

async function sectionOp(index, action, extra = {}) {
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/section`, Object.assign({ index, action }, extra));
    const meta = await runJob(job, action === 'take' ? 'new take of the section' : 'editing the section');
    await loadSong(meta.id, !audio.paused); refreshLibrary(); toast(meta.note.toUpperCase());
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}
function sectionMenu(x, y, i) {
  const sg = S.song.song, s = sg.sections[i], bpm = sg.bpm, t0 = s.start_bar * 4 * 60 / bpm;
  const muted = ((sg.settings && sg.settings.section_mutes) || {})[i] || [];
  const items = [
    ['▶ Play from here', () => { audio.currentTime = t0; play(); }],
    ['↻ Loop this section', () => { S.song.song.sections.forEach(x => x._loop = x === s); S.loop = true; $('#bRepeat').classList.add('on'); audio.currentTime = t0; play(); }],
    ['🎲 New take of this section', () => sectionOp(i, 'take')], '-',
    ['⧉ Duplicate', () => sectionOp(i, 'duplicate')],
    ['+ 4 bars longer', () => sectionOp(i, 'longer', { bars: 4 })],
    ['− 4 bars shorter', () => sectionOp(i, 'shorter', { bars: 4 })],
    ['◀ Move earlier', () => sectionOp(i, 'left')],
    ['▶ Move later', () => sectionOp(i, 'right')],
    ['✕ Remove', () => { if (confirm(`Remove "${s.name}" (${s.bars} bars)?`)) sectionOp(i, 'remove'); }], '-',
  ];
  const take = S.song.tracks.filter(t => !muted.includes(t.id)).map(t => [`∅ Take ${t.id} out of this section`, () => sectionOp(i, 'mute', { track: t.id })]);
  const back = muted.map(id => [`↺ Let ${id} back in (next re-roll)`, () => sectionOp(i, 'unmute', { track: id })]);
  menu(x, y, [...items, ...take.slice(0, 12), ...back], `${s.name.toUpperCase()} · BARS ${s.start_bar + 1}-${s.start_bar + s.bars}`);
}

// ------------------------------------------------------------------ more like this, A/B
const KEEP = [['tempo', 'Tempo & key'], ['form', 'Song form'], ['groove', 'Drum groove'], ['bass', 'Bass line'], ['chords', 'Chords'], ['melody', 'Melody'], ['sounds', 'Sounds & mix']];
function moreLikeThis(x, y) {
  if (!S.song) return toast('NO SONG LOADED');
  const keep = new Set(mem.get('keep', ['tempo', 'groove', 'chords', 'sounds']));
  const draw = () => menu(x, y, [
    ...KEEP.map(([k, l]) => ({ label: 'Keep ' + l, chk: keep.has(k), stay: true, fn: () => { keep.has(k) ? keep.delete(k) : keep.add(k); mem.set('keep', [...keep]); draw(); } })),
    '-', ['✨ Make it', () => variation([...keep])],
  ], 'MORE LIKE THIS');
  draw();
}
async function variation(keep) {
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/variation`, { keep });
    const meta = await runJob(job, keep.length ? 'more like this' : 'something different');
    await loadSong(meta.id, true); refreshLibrary();
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}
function toggleAB() {
  const b = $('#bAB');
  if (!S.song) return;
  if (!S.ab) { S.ab = { a: S.song.meta.id, b: null, on: 'a' }; b.classList.add('on', 'a'); toast('A = THIS SONG. OPEN ANOTHER ONE, THEN PRESS A/B TO FLIP'); return; }
  const cur = S.song.meta.id;
  if (cur === S.ab.a && !S.ab.b) { S.ab = null; b.classList.remove('on', 'a', 'b'); toast('A/B OFF'); return; }
  if (cur !== S.ab.a) S.ab.b = cur;
  const go = cur === S.ab.a ? S.ab.b : S.ab.a, t = audio.currentTime, playing = !audio.paused;
  loadSong(go, false).then(() => {
    const seek = () => { audio.currentTime = Math.min(t, (audio.duration || t + 1) - 0.1); if (playing) play(); };
    if (audio.readyState >= 1) seek(); else audio.addEventListener('loadedmetadata', seek, { once: true });
    b.classList.toggle('a', go === S.ab.a); b.classList.toggle('b', go !== S.ab.a);
    toast(go === S.ab.a ? 'A' : 'B', 900);
  });
}

// ------------------------------------------------------------------ part effects and master
function fxAmount(name, p) {
  const e = S.effects.find(x => x.id === name); if (!e) return '';
  for (const a of ['light', 'medium', 'heavy']) if (Object.entries(e.presets[a]).every(([k, v]) => p[k] === undefined || p[k] === v)) return a;
  return 'custom';
}
function renderFx() {
  const box = $('#fxchips'); box.innerHTML = '';
  const t = S.song && S.song.tracks.find(x => x.id === S.sel); if (!t) return;
  const chain = t.fx || [];
  if (!chain.length) box.insertAdjacentHTML('beforeend', '<span class="none">no effects on this part - add one</span>');
  chain.forEach(([name, p], i) => {
    const e = S.effects.find(x => x.id === name) || { label: name };
    const c = document.createElement('span'); c.className = 'chip';
    c.innerHTML = `${esc(e.label)} <i>${fxAmount(name, p || {}).toUpperCase()}</i>`;
    c.onclick = ev => {
      const r = ev.target.getBoundingClientRect();
      const set = a => { const ch = chain.map(x => [x[0], Object.assign({}, x[1])]); ch[i] = [name, Object.assign({}, e.presets[a])]; setFx(ch); };
      menu(r.left, r.bottom + 2, [['Light', () => set('light')], ['Medium', () => set('medium')], ['Heavy', () => set('heavy')], '-',
        i > 0 ? ['◀ Earlier in the chain', () => { const ch = chain.slice(); [ch[i - 1], ch[i]] = [ch[i], ch[i - 1]]; setFx(ch); }] : { label: '◀ Earlier in the chain' },
        ['✕ Remove', () => setFx(chain.filter((_, j) => j !== i))]], e.label.toUpperCase());
    };
    box.appendChild(c);
  });
}
async function setFx(chain) {
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/fx`, { track: S.sel, fx: chain });
    const meta = await runJob(job, 'effects on ' + S.sel);
    await loadSong(meta.id, !audio.paused); refreshLibrary();
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}
$('#fxAdd').onclick = e => {
  const t = S.song && S.song.tracks.find(x => x.id === S.sel); if (!t) return toast('NO PART SELECTED');
  const r = e.target.getBoundingClientRect();
  menu(r.left - 140, r.bottom + 2, S.effects.map(x => [x.label, () => setFx([...(t.fx || []), [x.id, Object.assign({}, x.presets.medium)]])]), 'ADD TO ' + S.sel.toUpperCase());
};
const MASTER = [['loudness', 'LOUDNESS', { genre: 'As the genre', club: 'Club (-7 LUFS)', stream: 'Streaming (-14 LUFS)' }],
  ['width', 'STEREO WIDTH', { narrow: 'Narrower', genre: 'As the genre', wide: 'Wider' }],
  ['tone', 'TONE', { darker: 'Darker', genre: 'As the genre', brighter: 'Brighter' }],
  ['glue', 'GLUE COMPRESSION', { off: 'Off', genre: 'Gentle', heavy: 'Heavy' }],
  ['buses', 'MIX BUSES (drum punch, mono sub, room for the lead)', { on: 'On', off: 'Off' }],
  ['tape', 'TAPE SATURATION', { off: 'Off', on: 'On' }]];
$('#mixMaster').onclick = e => {
  if (!S.song) return;
  const r = e.target.getBoundingClientRect();
  const m = S.mix._master || {};
  const items = [];
  for (const [k, label, opts] of MASTER) {
    items.push({ label: label });
    for (const [v, t] of Object.entries(opts)) {
      const cur = m[k] || (k === 'tape' ? 'off' : k === 'buses' ? 'on' : 'genre');
      items.push({ label: '  ' + t, chk: cur === v, fn: () => { S.mix._master = Object.assign({}, S.mix._master, { [k]: v }); remix(); } });
    }
  }
  menu(r.left - 60, r.bottom + 2, items, 'MASTER');
};

// ------------------------------------------------------------------ track select, sounds, piano roll
function renderTrackSel() {
  const ts = $('#trackSel'); ts.innerHTML = '';
  for (const t of S.song.tracks) ts.insertAdjacentHTML('beforeend', `<option value="${t.id}" ${t.id === S.sel ? 'selected' : ''}>${esc(t.id)} (${esc(t.role)})${t.locked ? ' 🔒' : ''}</option>`);
  const t = S.song.tracks.find(x => x.id === S.sel);
  const ss = $('#soundSel'); ss.innerHTML = '';
  if (t) {
    const choices = t.choices.length ? t.choices : [{ id: t.instrument, label: t.label }];
    if (!choices.find(c => c.id === t.instrument)) choices.unshift({ id: t.instrument, label: t.label });
    for (const c of choices) ss.insertAdjacentHTML('beforeend', `<option value="${c.id}" ${c.id === t.instrument ? 'selected' : ''}>${esc(c.label)}</option>`);
    ss.disabled = !t.choices.length;
    $('#bLock').textContent = t.locked ? '🔓 UNLOCK' : '🔒 LOCK';
  }
  renderFx();
}
async function loadRoll() {
  if (!S.song || !S.sel) return;
  S.roll.notes = await api(`/api/song/${S.song.meta.id}/notes?track=${encodeURIComponent(S.sel)}`);
  S.roll.dirty = false; $('#bApply').disabled = true;
  drawRoll();
  if (S.roll.notes.length && audio.paused) $('.roll').scrollLeft = Math.max(0, Math.min(...S.roll.notes.map(n => n[0])) * S.roll.zoom - 40);
}
function rollGeom() {
  const ns = S.roll.notes;
  let lo = 127, hi = 0; for (const n of ns) { lo = Math.min(lo, n[2]); hi = Math.max(hi, n[2]); }
  if (lo > hi) { lo = 48; hi = 72; }
  lo -= 2; hi += 2; if (hi - lo < 20) { const c = (hi + lo) / 2; lo = Math.floor(c - 10); hi = Math.ceil(c + 10); }
  const totalBeats = S.song.song.bars * 4, pxb = S.roll.zoom, H = 260, rows = hi - lo + 1, rh = H / rows;
  return { lo, hi, totalBeats, pxb, H, rh, W: Math.ceil(totalBeats * pxb) };
}
function drawRoll() {
  const c = $('#roll'), G = rollGeom(), g = c.getContext('2d');
  c.width = G.W; c.height = G.H; c.style.width = G.W + 'px';
  g.fillStyle = '#000'; g.fillRect(0, 0, G.W, G.H);
  for (let p = G.lo; p <= G.hi; p++) {
    const y = G.H - (p - G.lo + 1) * G.rh;
    if ([1, 3, 6, 8, 10].includes(p % 12)) { g.fillStyle = '#050a05'; g.fillRect(0, y, G.W, G.rh); }
    if (p % 12 === 0) { g.fillStyle = '#0d260d'; g.fillRect(0, y + G.rh - 1, G.W, 1); }
  }
  for (let b = 0; b <= G.totalBeats; b++) { g.fillStyle = b % 4 === 0 ? '#123a12' : '#071407'; g.fillRect(b * G.pxb, 0, 1, G.H); }
  for (const s of S.song.song.sections) { g.fillStyle = '#e8c24a'; g.fillRect(s.start_bar * 4 * G.pxb, 0, 1, G.H); g.font = '13px VT323'; g.fillText(s.name.toUpperCase(), s.start_bar * 4 * G.pxb + 3, 11); }
  for (const n of S.roll.notes) {
    const x = n[0] * G.pxb, w = Math.max(2, n[1] * G.pxb - 1), y = G.H - (n[2] - G.lo + 1) * G.rh;
    g.fillStyle = `rgba(57,255,20,${0.35 + 0.65 * n[3]})`; g.fillRect(x, y + 1, w, Math.max(2, G.rh - 2));
  }
  if (S.song && !audio.paused || audio.currentTime > 0) { g.fillStyle = '#fff'; g.fillRect(beatNow() * G.pxb, 0, 1, G.H); }
}
$('#roll').addEventListener('click', e => {
  if (!S.song || e.shiftKey) return;
  const c = $('#roll'), r = c.getBoundingClientRect(), G = rollGeom();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  const beat = x / G.pxb, pitch = G.lo + Math.floor((G.H - y) / G.rh);
  const hit = S.roll.notes.findIndex(n => n[2] === pitch && beat >= n[0] && beat <= n[0] + n[1]);
  if (hit >= 0) S.roll.notes.splice(hit, 1);
  else {
    const t = S.song.tracks.find(x => x.id === S.sel);
    const drum = ['kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'].includes(t.role);
    S.roll.notes.push([Math.floor(beat * 4) / 4, drum ? 0.2 : 0.5, pitch, 0.85]);
  }
  S.roll.dirty = true; $('#bApply').disabled = false; drawRoll();
});
let dragX = null;
$('.roll').addEventListener('mousedown', e => { if (e.shiftKey) dragX = [e.clientX, $('.roll').scrollLeft]; });
window.addEventListener('mousemove', e => { if (dragX) $('.roll').scrollLeft = dragX[1] - (e.clientX - dragX[0]); });
window.addEventListener('mouseup', () => dragX = null);

// ------------------------------------------------------------------ playlist & library
async function refreshLibrary() { S.lib = await api('/api/library'); renderPlaylist(); }
function renderPlaylist() {
  const box = $('#plist'); box.innerHTML = '';
  const cur = S.song && S.song.meta.id;
  S.lib.forEach((m, i) => {
    const d = document.createElement('div');
    d.className = 'it' + (m.id === cur ? ' cur' : '') + (m.id === S.libSel ? ' sel' : '');
    d.innerHTML = `<span>${i + 1}.</span><span class="t">${m.starred ? '<span class="st">★</span> ' : ''}${esc(m.title)} - ${esc(m.genre_name || m.genre)}${m.note && m.note !== 'new song' ? ' (' + esc(m.note) + ')' : ''}</span><span>${fmt(m.duration || 0)}</span>`;
    d.onclick = () => { S.libSel = m.id; renderPlaylist(); };
    d.ondblclick = () => loadSong(m.id, true);
    box.appendChild(d);
  });
}
function menu(x, y, items, title) {
  const m = $('#menu'); m.innerHTML = '';
  if (title) m.insertAdjacentHTML('beforeend', `<div class="hd">${esc(title)}</div>`);
  for (const it of items) {
    if (it === '-') { m.insertAdjacentHTML('beforeend', '<div class="sep"></div>'); continue; }
    const o = Array.isArray(it) ? { label: it[0], fn: it[1] } : it;
    const d = document.createElement('div'); d.className = 'mi' + ('chk' in o ? ' chk' + (o.chk ? ' on' : '') : '') + (o.fn ? '' : ' dim');
    d.textContent = o.label;
    d.onclick = () => { if (!o.fn) return; if (!o.stay) m.classList.remove('on'); o.fn(); };
    m.appendChild(d);
  }
  m.classList.add('on');
  const h = m.offsetHeight, w = m.offsetWidth;
  m.style.left = Math.max(4, Math.min(x, innerWidth - w - 8)) + 'px'; m.style.top = Math.max(4, Math.min(y, innerHeight - h - 8)) + 'px';
}
document.addEventListener('mousedown', e => { if (!e.target.closest('.menu')) $('#menu').classList.remove('on'); });
async function dl(what) {
  if (!S.song) return;
  const path = `/api/song/${S.song.meta.id}/${what}`;
  const desk = window.pywebview && window.pywebview.api && window.pywebview.api.save;
  if (!desk) { location.href = `${path}?t=${encodeURIComponent(T)}`; return; }
  try {                                         // the desktop program: a real "Save as" dialog
    toast('PREPARING THE FILE ...', 20000);
    const r = await window.pywebview.api.save(path);
    if (r && r.ok) { toast('SAVED ' + r.path.split(/[\\/]/).pop().toUpperCase(), 4000); window.pywebview.api.reveal(r.path); }
    else if (r && r.cancelled) toast('NOT SAVED');
    else toast('COULD NOT SAVE: ' + ((r && r.error) || 'unknown'), 6000);
  } catch (e) { toast('COULD NOT SAVE: ' + e, 6000); }
}

// ------------------------------------------------------------------ reference analysis
async function openSongFile(file) {
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await api('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: await file.text() });
    const meta = await runJob(job, 'opening ' + file.name);
    await loadSong(meta.id, true); refreshLibrary(); toast('OPENED ' + meta.title.toUpperCase());
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}
async function analyzeFile(file) {
  if (/\.json$/i.test(file.name)) return openSongFile(file);
  if (S.busy) return toast('BUSY');
  $('#said').textContent = `MEASURING ${file.name.toUpperCase()}...`;
  try {
    const { job } = await api('/api/analyze', { method: 'POST', headers: { 'X-Filename': file.name }, body: file });
    const r = await runJob(job, 'analysing');
    const a = r.analysis, best = r.matches[0];
    S.genre = best.genre; renderGenres();
    $('#bpm').value = Math.round(best.bpm);
    $('#said').textContent = `${best.bpm} BPM · ${a.key.toUpperCase()} (UNSURE) · ${a.lufs} LUFS · WIDTH ${a.width} · INTRO ${a.intro_bars} BARS → ` +
      r.matches.slice(0, 3).map(m => (S.genres.find(g => g.id === m.genre) || {}).name).join(' / ').toUpperCase() + '. PRESS COMPOSE.';
    toast('CLOSEST GENRE: ' + (S.genres.find(g => g.id === best.genre) || {}).name.toUpperCase());
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}

// ------------------------------------------------------------------ transport
function play() { ensureAudio(); if (actx.state === 'suspended') actx.resume(); if (audio.src) audio.play(); }
$('#bPlay').onclick = play;
$('#bPause').onclick = () => audio.paused ? play() : audio.pause();
$('#bStop').onclick = () => { audio.pause(); audio.currentTime = 0; };
$('#bPrev').onclick = () => { if (S.song && S.song.meta.parent) loadSong(S.song.meta.parent, true); else toast('NO EARLIER VERSION'); };
$('#bNext').onclick = () => reroll('all');
$('#bEject').onclick = () => $('#fileIn').click();
$('#fileIn').onchange = e => { const f = e.target.files[0]; if (f) analyzeFile(f); e.target.value = ''; };
$('#bShuffle').onclick = () => {
  const g = S.genres[Math.floor(Math.random() * S.genres.length)];
  S.genre = g.id; renderGenres(); $('#seed').value = 1 + Math.floor(Math.random() * 9999); $('#prompt').value = '';
  compose({ skipPrompt: true });
};
$('#bRepeat').onclick = () => toggleLoop();
function toggleLoop() { S.loop = !S.loop; $('#bRepeat').classList.toggle('on', S.loop); toast(S.loop ? 'LOOPING THE CURRENT SECTION' : 'LOOP OFF'); }
$('#bAB').onclick = toggleAB;
$('#bMore').onclick = e => { const r = e.target.getBoundingClientRect(); moreLikeThis(r.left, r.bottom + 2); };
$('#bDiff').onclick = () => { if (!S.song) return compose(); variation([]); };
$('#gsearch').oninput = renderGenres;
$('#seek').oninput = e => { if (audio.duration) audio.currentTime = audio.duration * e.target.value / 1000; };
$('#vol').oninput = applyOut; $('#bal').oninput = applyOut;
$('#togMix').onclick = e => { e.target.classList.toggle('on'); $('#wMixer').style.display = e.target.classList.contains('on') ? '' : 'none'; };
$('#togPl').onclick = e => { e.target.classList.toggle('on'); $('#wPlaylist').style.display = e.target.classList.contains('on') ? '' : 'none'; };
$$('.tbb').forEach(b => b.onclick = () => b.closest('.win').classList.toggle('shaded'));
$$('.tb').forEach(b => b.ondblclick = () => b.closest('.win').classList.toggle('shaded'));

async function reroll(what) {
  if (!S.song) return compose();
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/reroll`, { what });
    const meta = await runJob(job, 're-rolling ' + what);
    await loadSong(meta.id, true); refreshLibrary();
  } catch (e) { toast('ERROR: ' + e.message, 6000); }
}

// ------------------------------------------------------------------ composer controls
$('#bCompose').onclick = () => compose();
$('#prompt').addEventListener('keydown', e => { if (e.key === 'Enter') compose(); });
$('#energy').oninput = e => { $('#energyV').textContent = e.target.value; saveComposer(); };
$$('#length button').forEach(b => b.onclick = () => { S.length = b.dataset.v; $$('#length button').forEach(x => x.classList.toggle('on', x === b)); saveComposer(); });
const drop = $('#drop');
drop.onclick = () => $('#fileIn').click();
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) analyzeFile(f); });

// ------------------------------------------------------------------ editor controls
$('#rrHarm').onclick = () => reroll('harmony');
$('#rrForm').onclick = () => reroll('form');
$('#rrAll').onclick = () => reroll('all');
$('#trackSel').onchange = e => { S.sel = e.target.value; renderFaders(); renderTrackSel(); loadRoll(); };
$('#soundSel').onchange = async e => {
  if (S.busy) return toast('BUSY');
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/instrument`, { track: S.sel, instrument: e.target.value });
    const meta = await runJob(job, 'new sound');
    await loadSong(meta.id, true); refreshLibrary();
  } catch (err) { toast('ERROR: ' + err.message); }
};
$('#bLock').onclick = async () => {
  const t = S.song.tracks.find(x => x.id === S.sel); if (!t) return;
  t.locked = !t.locked; await post(`/api/song/${S.song.meta.id}/lock`, { track: t.id, on: t.locked });
  renderTrackSel(); renderFaders();
};
$('#bReroll').onclick = () => reroll(S.sel);
$('#zoomIn').onclick = () => { S.roll.zoom = Math.min(60, S.roll.zoom * 1.4); drawRoll(); };
$('#zoomOut').onclick = () => { S.roll.zoom = Math.max(3, S.roll.zoom / 1.4); drawRoll(); };
$('#bApply').onclick = async () => {
  try {
    const { job } = await post(`/api/song/${S.song.meta.id}/notes`, { track: S.sel, notes: S.roll.notes });
    const meta = await runJob(job, 'rendering your edit');
    await loadSong(meta.id, true); refreshLibrary(); toast(`${S.sel.toUpperCase()} EDITED AND LOCKED`);
  } catch (e) { toast('ERROR: ' + e.message); }
};

// ------------------------------------------------------------------ mixer & playlist buttons
$('#mixOn').onclick = e => { e.target.classList.toggle('on'); remix(); };
$('#mixAuto').onclick = e => { e.target.classList.toggle('on'); toast(e.target.classList.contains('on') ? 'FADER MOVES APPLY AUTOMATICALLY' : 'AUTO OFF - USE PRESETS > APPLY MIX'); };
$('#mixPresets').onclick = e => {
  const r = e.target.getBoundingClientRect();
  const set = f => { for (const t of S.song.tracks) setMix(t.id, { gain_db: f(t) }); renderFaders(); remix(); };
  const drum = t => ['kick', 'snare', 'clap', 'hat', 'ohat', 'ride', 'shaker', 'perc', 'rim', 'cowbell'].includes(t.role);
  menu(r.left, r.bottom + 2, [
    ['Flat (as written)', () => { S.mix = S.mix._master ? { _master: S.mix._master } : {}; renderFaders(); remix(); }],
    ['Drums up', () => set(t => drum(t) ? 2.5 : 0)],
    ['Low end up', () => set(t => ['kick', 'bass', 'riff'].includes(t.role) ? 2.5 : 0)],
    ['Melody up', () => set(t => ['lead', 'arp'].includes(t.role) ? 3 : 0)],
    ['Chill (drums back)', () => set(t => drum(t) ? -4 : 0)],
    '-', ['Apply mix now', () => remix()],
  ]);
};
$('#plAdd').onclick = () => compose();
$('#plRem').onclick = async () => {
  if (!S.libSel) return toast('SELECT A SONG FIRST');
  const m = S.lib.find(x => x.id === S.libSel);
  if (!confirm(`Delete "${m.title}" (${m.note || ''})?`)) return;
  await post(`/api/song/${S.libSel}/delete`); S.libSel = null; refreshLibrary();
};
$('#plSel').onclick = async () => {
  const id = S.libSel || (S.song && S.song.meta.id); if (!id) return;
  const m = S.lib.find(x => x.id === id); await post(`/api/song/${id}/star`, { on: !(m && m.starred) }); refreshLibrary();
};
$('#plMisc').onclick = e => {
  const r = e.target.getBoundingClientRect();
  menu(r.left, r.top - 220, [['Download WAV (master)', () => dl('wav')], ['Download WAV 24-bit (for mastering)', () => dl('wav24')],
    S.caps.mp3 ? ['Download MP3 (256k)', () => dl('mp3')] : { label: 'MP3 needs ffmpeg installed' },
    ['Download stems (ZIP)', () => dl('stems')], ['Download MIDI', () => dl('midi')], ['Download song file (.sl2.json)', () => dl('json')],
    '-', ['Open a song file...', () => $('#fileIn').click()], ['Copy diagnostics (for a bug report)', copyDiag]]);
};
$('#plOpts').onclick = async e => {
  if (!S.song) return;
  const r = e.target.getBoundingClientRect();
  const h = await api(`/api/song/${S.song.meta.id}/history`);
  menu(r.left - 120, r.top - 24 * h.length - 10, h.map((v, i) => [`${i === 0 ? '● ' : ''}${new Date(v.created * 1000).toLocaleTimeString()}  ${v.note || ''}`, () => loadSong(v.id, true)]));
};
async function copyDiag() {
  try {
    const d = await api('/api/diag');
    const text = Object.entries(d).map(([k, v]) => `${k}: ${v}`).join('\n') + (S.song ? `\nsong: ${S.song.meta.id} (${S.song.song.genre})` : '');
    await navigator.clipboard.writeText(text); toast('DIAGNOSTICS COPIED');
  } catch (e) { toast('COULD NOT COPY: ' + e.message); }
}
function jumpSection(dir) {
  if (!S.song) return;
  const secs = S.song.song.sections, now = beatNow(), bpm = S.song.song.bpm;
  const i = secs.findIndex(x => now >= x.start_bar * 4 && now < (x.start_bar + x.bars) * 4);
  const j = Math.max(0, Math.min(secs.length - 1, (i < 0 ? 0 : i) + dir));
  audio.currentTime = secs[j].start_bar * 4 * 60 / bpm;
}
document.addEventListener('keydown', e => {
  if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (e.code === 'Space') { e.preventDefault(); audio.paused ? play() : audio.pause(); }
  else if (e.key === 'ArrowLeft') audio.currentTime = Math.max(0, audio.currentTime - 5);
  else if (e.key === 'ArrowRight') audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5);
  else if (e.key === '[') jumpSection(-1);
  else if (e.key === ']') jumpSection(1);
  else if (k === 'l') toggleLoop();
  else if (k === 'n') reroll('all');
  else if (k === 'b') toggleAB();
  else if (k === 'z') $('#bPrev').click();
  else if (k === 'm') { const r = $('#bMore').getBoundingClientRect(); moreLikeThis(r.left, r.bottom + 2); }
});

// ------------------------------------------------------------------ frame loop
function frame() {
  tickMarquee(); drawVis();
  if (S.song && audio.duration) {
    $('#seek').value = Math.round(audio.currentTime / audio.duration * 1000);
    $('#clock').textContent = fmt(audio.currentTime);
    $('#plTime').textContent = `${fmt(audio.currentTime)}/${fmt(audio.duration)}`;
    const ph = $('#ph'); if (ph) ph.style.left = (beatNow() / (S.song.song.bars * 4) * 100) + '%';
    if (S.loop && !audio.paused) {
      const s = S.song.song.sections.find(x => x._loop) || null;
      const cur = s || secAt(beatNow() - 0.05);
      if (cur) {
        S.song.song.sections.forEach(x => x._loop = x === cur);
        const end = (cur.start_bar + cur.bars) * 4 * 60 / S.song.song.bpm;
        if (audio.currentTime >= end - 0.02) audio.currentTime = cur.start_bar * 4 * 60 / S.song.song.bpm;
      }
    } else if (S.song) S.song.song.sections.forEach(x => x._loop = false);
    if (!audio.paused && frame.n++ % 6 === 0) drawRoll();
  }
  requestAnimationFrame(frame);
}
frame.n = 0;
audio.addEventListener('play', ensureAudio);

// ------------------------------------------------------------------ start
(async () => {
  const g = await api('/api/genres');
  S.genres = g.genres; S.choices = g.choices || {}; S.caps = g.caps || {}; S.effects = g.effects || [];
  const saved = mem.get('composer', {});
  S.genre = (S.genres.find(x => x.id === saved.genre) || S.genres.find(x => x.id === 'liquid_dnb') || S.genres[0]).id;
  S.feel = saved.feel || {};
  if (saved.length) { S.length = saved.length; $$('#length button').forEach(x => x.classList.toggle('on', x.dataset.v === S.length)); }
  if (saved.energy) { $('#energy').value = saved.energy; $('#energyV').textContent = saved.energy; }
  renderGenres(); renderFeel();
  await refreshLibrary();
  if (S.lib.length) await loadSong(S.lib[0].id, false);
  else setMarquee('SL2 - STUDIO LAB 2 *** DESCRIBE A TRACK IN THE COMPOSER, OR PICK A GENRE AND PRESS COMPOSE *** ');
  requestAnimationFrame(frame);
})();
