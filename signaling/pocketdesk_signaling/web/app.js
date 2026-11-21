// PocketDesk web client — same protocol as the Android app (see ARCHITECTURE.md).
'use strict';
const $ = id => document.getElementById(id);
const enc = new TextEncoder();
const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const hex = b => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
const unhex = h => new Uint8Array(h.match(/../g).map(x => parseInt(x, 16)));

function parseCode(t) {
  t = t.replace(/[\s-]/g, '').toUpperCase();
  if (t.length !== 22 || [...t].some(c => !B32.includes(c))) throw new Error('Invalid pairing code');
  let bits = 0, val = 0; const out = [];
  for (const c of t.slice(6)) { val = (val << 5) | B32.indexOf(c); bits += 5; if (bits >= 8) { out.push((val >> (bits - 8)) & 255); bits -= 8; } }
  return { lookup: t.slice(0, 6), secret: new Uint8Array(out) };
}
async function derivePairKey(secret) {
  const k = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: enc.encode('pocketdesk-pair-v1'), info: enc.encode('pair-key') }, k, 256);
  return new Uint8Array(bits);
}
async function mac(keyBytes, msg) {
  const k = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', k, enc.encode(msg)));
}
function fingerprint(sdp) {
  const m = /^a=fingerprint:\S+\s+([0-9A-Fa-f:]+)\s*$/m.exec(sdp);
  if (!m) throw new Error('no DTLS fingerprint');
  return m[1].toLowerCase();
}
const ctEq = (a, b) => { if (a.length !== b.length) return false; let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i); return r === 0; };

// ---------- storage (this browser only) ----------
const loadPcs = () => { try { return JSON.parse(localStorage.getItem('pd_pcs') || '[]'); } catch { return []; } };
const savePcs = l => localStorage.setItem('pd_pcs', JSON.stringify(l));

// ---------- pairing / home ----------
async function pairFromFragment() {
  const m = /[#&]c=([^&]+)/.exec(location.hash);
  if (!m) return;
  history.replaceState(null, '', location.pathname); // keep the secret out of history
  $('msg').textContent = 'Pairing…';
  try {
    const { lookup, secret } = parseCode(decodeURIComponent(m[1]));
    const key = await derivePairKey(secret);
    const name = (/Android/.test(navigator.userAgent) ? 'Android browser' : /iPhone|iPad/.test(navigator.userAgent) ? 'iPhone browser' : 'Phone browser');
    const r = await fetch('/api/pair/claim', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ code: lookup, device_name: name, proof: await mac(key, `pd1|claim|${lookup}|${name}`) }) });
    if (r.status === 404) throw new Error('Code invalid or expired — generate a new one on the PC.');
    if (r.status === 409) throw new Error('The PC agent is offline.');
    if (!r.ok) throw new Error('Pairing failed (' + r.status + ')');
    const j = await r.json();
    const pcs = loadPcs().filter(p => p.agentId !== j.agent_id);
    pcs.push({ deviceId: j.device_id, token: j.device_token, agentId: j.agent_id, name: j.agent_name, keyHex: hex(key) });
    savePcs(pcs);
    $('msg').textContent = '';
    openPc(pcs[pcs.length - 1]); // connect right away
  } catch (e) { $('msg').textContent = e.message; }
}

function renderHome() {
  const l = $('list'); l.innerHTML = '';
  for (const pc of loadPcs()) {
    const d = document.createElement('div'); d.className = 'pc';
    d.innerHTML = '<span></span>'; d.firstChild.textContent = '🖥 ' + pc.name;
    const b = document.createElement('button'); b.textContent = 'Connect'; b.onclick = () => openPc(pc);
    const x = document.createElement('button'); x.className = 'sec'; x.textContent = 'Remove';
    x.onclick = async () => { if (confirm('Remove this PC?')) { try { await fetch('/api/devices/' + pc.deviceId, { method: 'DELETE', headers: { Authorization: `Bearer ${pc.deviceId}:${pc.token}` } }); } catch {} savePcs(loadPcs().filter(p => p !== pc && p.deviceId !== pc.deviceId)); renderHome(); } };
    d.append(b, x); l.appendChild(d);
  }
}

// ---------- remote session ----------
let S = null; // current session state
const stage = $('stage'), vid = $('vid'), cur = $('cur');

function openPc(pc) {
  $('home').style.display = 'none'; stage.style.display = 'block';
  S = { pc, retries: 0, trackpad: false, norm: { x: .5, y: .5 }, remote: { w: 0, h: 0 }, mods: new Set(), closed: false, pend: { abs: null, dx: 0, dy: 0, wx: 0, wy: 0 } };
  S.zoom = 1; S.pan = { x: 0, y: 0 }; $('view').style.transform = ''; $('lockmsg').style.display = 'none';
  overlay('Connecting…', false); holdWake(); connect();
}
function overlay(msg, retry) { $('overlay').style.display = 'flex'; $('ovmsg').textContent = msg; $('ovbtn').style.display = retry ? '' : 'none'; }

async function connect() {
  const s = S; if (!s || s.closed) return;
  teardown(s);
  try {
    const key = unhex(s.pc.keyHex);
    s.ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    const msgs = new Map();
    const waitMsg = (type, ms) => new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('Timed out waiting for ' + type)), ms); msgs.set(type, m => { clearTimeout(t); res(m); }); });
    s.waitMsg = waitMsg;
    const ready = waitMsg('ready', 12000), answer = waitMsg('answer', 30000);
    answer.catch(() => {}); ready.catch(() => {});
    s.ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.type === 'error' || m.type === 'agent_offline') { const f = msgs.get('relay_ok') || msgs.get('answer'); if (f) f({ type: 'fail', error: m.type === 'agent_offline' ? 'The PC is offline.' : (m.error === 'auth' ? 'Access revoked — remove and re-pair.' : 'The PC rejected the request.') }); return; }
      const f = msgs.get(m.type); if (f) f(m);
    };
    s.ws.onclose = () => { if (!s.closed && s.state !== 'connected' && s.ws) retry(s, 'Signaling closed'); };
    await new Promise((res, rej) => { s.ws.onopen = res; s.ws.onerror = () => rej(new Error('Cannot reach server')); });
    s.ws.send(JSON.stringify({ type: 'auth', role: 'device', id: s.pc.deviceId, secret: s.pc.token }));
    const rd = await ready;
    overlay('Connecting to ' + s.pc.name + '…', false);
    let preferRelay = false; try { preferRelay = localStorage.getItem('pd_relay_' + s.pc.deviceId) === '1'; } catch {}
    if (preferRelay) { await startRelay(s); return; }
    s.rtc = new RTCPeerConnection({ iceServers: rd.ice_servers });
    s.dc = s.rtc.createDataChannel('control', { ordered: true });
    s.dc.onopen = () => onOpen(s); s.dc.onmessage = e => onData(s, JSON.parse(e.data));
    s.rtc.addTransceiver('video', { direction: 'recvonly' });
    s.rtc.ontrack = e => { vid.srcObject = e.streams[0]; vid.play().catch(() => {}); };
    s.rtc.onconnectionstatechange = () => {
      const st = s.rtc && s.rtc.connectionState;
      if (st === 'connected') { s.state = 'connected'; s.retries = 0; $('overlay').style.display = 'none'; }
      else if (st === 'failed' || st === 'closed') { if (s.relay) return; if (s.state !== 'connected') startRelay(s); else retry(s, 'Connection lost'); }
      else if (st === 'disconnected') setTimeout(() => { if (s.rtc && s.rtc.connectionState === 'disconnected') retry(s, 'Connection lost'); }, 6000);
    };
    await s.rtc.setLocalDescription(await s.rtc.createOffer());
    await new Promise(res => { if (s.rtc.iceGatheringState === 'complete') return res(); const t = setTimeout(res, 8000); s.rtc.onicegatheringstatechange = () => { if (s.rtc.iceGatheringState === 'complete') { clearTimeout(t); res(); } }; });
    const sdp = s.rtc.localDescription.sdp;
    s.sid = hex(crypto.getRandomValues(new Uint8Array(16))); s.ts = Math.floor(Date.now() / 1000);
    s.ws.send(JSON.stringify({ type: 'offer', agent_id: s.pc.agentId, session_id: s.sid, ts: s.ts, sdp, mac: await mac(key, `pd1|offer|${s.sid}|${s.pc.deviceId}|${s.ts}|${fingerprint(sdp)}`) }));
    const ans = await answer;
    if (ans.type === 'fail') { s.closed = true; teardown(s); overlay(ans.error, true); return; }
    const expect = await mac(key, `pd1|answer|${s.sid}|${s.pc.deviceId}|${ans.ts}|${fingerprint(ans.sdp)}`);
    if (ans.session_id !== s.sid || !ctEq(expect, String(ans.mac))) { s.closed = true; teardown(s); overlay('Security check failed: the PC could not be verified. Remove and re-pair.', false); return; }
    await s.rtc.setRemoteDescription({ type: 'answer', sdp: ans.sdp });
    // No direct/TURN path within 12 s (typical on mobile data / office networks): use the encrypted relay.
    s.fallback = setTimeout(() => { if (S === s && s.state !== 'connected' && !s.closed) startRelay(s); }, 12000);
  } catch (e) { retry(s, e.message); }
}
function retry(s, why) {
  if (s !== S || s.closed || s.retrying) return;
  // never give up: keep retrying (backoff capped at 6 s) until the user presses ✕ or access is revoked
  s.retries++; s.retrying = true; teardown(s); overlay(`Reconnecting… (attempt ${s.retries})\n${why}`, true);
  setTimeout(() => { s.retrying = false; if (s === S && !s.closed) connect(); }, Math.min(6000, 700 * s.retries));
}
function reconnectNow() { const s = S; if (!s || s.closed) return; s.retrying = false; s.retries = 0; connect(); }
// keep-alive layer: watchdog, wake-lock, and instant recovery when the phone wakes / changes network
let wake = null;
async function holdWake() { try { if (navigator.wakeLock && S && document.visibilityState === 'visible') wake = await navigator.wakeLock.request('screen'); } catch {} }
setInterval(() => {
  const s = S; if (!s || s.closed || s.retrying) return;
  if (s.state === 'connected' && s.lastRx && performance.now() - s.lastRx > 12000) { overlay('Connection stalled — reconnecting…', true); retry(s, 'No data from PC'); }
}, 3000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { holdWake(); const s = S; if (s && !s.closed && (s.state !== 'connected' || performance.now() - (s.lastRx || 0) > 8000)) reconnectNow(); } });
window.addEventListener('online', () => { if (S && !S.closed && S.state !== 'connected') reconnectNow(); });
window.addEventListener('offline', () => { if (S) overlay('No internet on this phone — waiting…', true); });
function teardown(s) {
  clearInterval(s.flush); clearInterval(s.ping); clearInterval(s.fpsT); clearTimeout(s.fallback); s.relay = false; s.gotFrame = false;
  $('cv').style.display = 'none'; vid.style.display = '';
  const { rtc, ws, dc } = s; s.rtc = s.ws = s.dc = null; s.state = '';
  try { dc && dc.close(); } catch {} try { rtc && rtc.close(); } catch {} try { ws && ws.close(); } catch {}
}
function exitSession() {
  if (S) { send({ t: 'bye' }); S.closed = true; const s = S; setTimeout(() => teardown(s), 100); S = null; }
  try { wake && wake.release(); } catch {}
  vid.srcObject = null; stage.style.display = 'none'; $('home').style.display = 'block'; renderHome();
}

// ---------- encrypted WebSocket relay (fallback when no direct/TURN path exists) ----------
async function relayKeys(pairKey, sidHex) {
  const ikm = await crypto.subtle.importKey('raw', pairKey, 'HKDF', false, ['deriveBits']);
  const mk = async info => crypto.subtle.importKey('raw', await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: unhex(sidHex), info: enc.encode(info) }, ikm, 256), 'AES-GCM', false, ['encrypt', 'decrypt']);
  return { a2d: await mk('relay-a2d'), d2a: await mk('relay-d2a') };
}
const nonce = ctr => { const n = new Uint8Array(12); n.set(ctr, 4); return n; };
function relaySend(o) {           // ordered: counters must be strictly increasing
  const s = S; if (!s || !s.relay) return;
  const body = enc.encode(JSON.stringify(o));
  s.chain = s.chain.then(async () => {
    if (!s.ws || s.ws.readyState !== 1) return;
    const ctr = new Uint8Array(8); new DataView(ctr.buffer).setBigUint64(0, BigInt(s.txN++), false);
    const pt = new Uint8Array(1 + body.length); pt[0] = 2; pt.set(body, 1);
    const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce(ctr), additionalData: enc.encode('relay-d2a') }, s.keys.d2a, pt));
    const out = new Uint8Array(8 + ct.length); out.set(ctr); out.set(ct, 8); s.ws.send(out);
  }).catch(() => {});
}
function relayRecv(s, buf) {
  s.rchain = s.rchain.then(async () => {
    const data = new Uint8Array(buf); const ctr = data.slice(0, 8);
    const n = Number(new DataView(ctr.buffer).getBigUint64(0, false));
    if (n <= s.rxN) return; // replay/out-of-order
    const pt = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce(ctr), additionalData: enc.encode('relay-a2d') }, s.keys.a2d, data.slice(8)));
    s.rxN = n; s.lastRx = performance.now();
    if (pt[0] === 1) {
      const bmp = await createImageBitmap(new Blob([pt.slice(1)], { type: 'image/jpeg' }));
      const cv = $('cv'); if (cv.width !== bmp.width || cv.height !== bmp.height) { cv.width = bmp.width; cv.height = bmp.height; }
      cv.getContext('2d').drawImage(bmp, 0, 0); bmp.close(); s.rdim = { w: cv.width, h: cv.height };
      if (!s.gotFrame) { s.gotFrame = true; s.state = 'connected'; $('overlay').style.display = 'none'; try { localStorage.setItem('pd_relay_' + s.pc.deviceId, '1'); } catch {} }
      s.frames = (s.frames || 0) + 1; s.fbytes = (s.fbytes || 0) + data.length;
    } else if (pt[0] === 2) onData(s, JSON.parse(new TextDecoder().decode(pt.slice(1))));
  }).catch(() => {});
}
async function startRelay(s) {
  if (s !== S || s.closed || s.relay) return;
  clearTimeout(s.fallback);
  try { s.rtc && s.rtc.close(); } catch {} s.rtc = null; vid.srcObject = null;
  overlay('Connecting via secure relay…', false);
  try {
    const key = unhex(s.pc.keyHex), sid = hex(crypto.getRandomValues(new Uint8Array(16))), ts = Math.floor(Date.now() / 1000);
    const ok = s.waitMsg('relay_ok', 20000); ok.catch(() => {});
    s.ws.send(JSON.stringify({ type: 'relay_start', session_id: sid, ts, mac: await mac(key, `pd1|relay|${sid}|${s.pc.deviceId}|${ts}`) }));
    const m = await ok;
    if (m.type === 'fail') { s.closed = true; teardown(s); overlay(m.error, true); return; }
    if (m.session_id !== sid || !ctEq(await mac(key, `pd1|relayok|${sid}|${s.pc.deviceId}|${m.ts}`), String(m.mac))) { s.closed = true; teardown(s); overlay('Security check failed: the PC could not be verified.', false); return; }
    s.keys = await relayKeys(key, sid); s.txN = 0; s.rxN = -1; s.chain = Promise.resolve(); s.rchain = Promise.resolve();
    s.relay = true; s.ws.binaryType = 'arraybuffer';
    s.ws.onmessage = ev => { if (typeof ev.data === 'string') { const j = JSON.parse(ev.data); if (j.type === 'error' || j.type === 'agent_offline') { s.closed = true; overlay('The PC refused or is offline.', true); } } else relayRecv(s, ev.data); };
    s.ws.onclose = () => { if (!s.closed) retry(s, 'Connection lost'); };
    $('cv').style.display = 'block'; vid.style.display = 'none';
    onOpen(s);
    s.fpsT = setInterval(() => { s.fps = (s.frames || 0) / 2; s.kbps = (s.fbytes || 0) * 8 / 2000; s.frames = s.fbytes = 0; updStat(); }, 2000);
  } catch (e) { retry(s, e.message); }
}

// ---------- data channel ----------
const send = o => { if (!S) return; if (S.relay) relaySend(o); else if (S.dc && S.dc.readyState === 'open') S.dc.send(JSON.stringify(o)); };
function onOpen(s) {
  send({ t: 'cfg', quality: $('qual').value });
  s.flush = setInterval(flush, 16);
  s.ping = setInterval(() => { s.pn = (s.pn || 0) + 1; s.pt = performance.now(); send({ t: 'ping', n: s.pn }); }, 2000);
}
function onData(s, m) {
  s.lastRx = performance.now();
  if (m.t === 'state') $('lockmsg').style.display = m.locked ? 'block' : 'none';
  else if (m.t === 'info') { s.remote = { w: m.w, h: m.h }; s.monitors = m.monitors; }
  else if (m.t === 'cur') { s.norm = { x: m.x, y: m.y }; drawCursor(); }
  else if (m.t === 'stats') { if (!s.relay) { s.fps = m.fps; s.kbps = m.kbps; updStat(); } }
  else if (m.t === 'pong') { s.rtt = Math.round(performance.now() - s.pt); updStat(); }
  else if (m.t === 'clip') { navigator.clipboard && navigator.clipboard.writeText(m.s).catch(() => {}); }
}
function updStat() { const s = S; if (s) $('stat').textContent = `${s.rtt ?? '–'} ms · ${Math.round(s.fps || 0)} fps · ${((s.kbps || 0) / 1000).toFixed(1)} Mb/s`; }

// ---------- geometry ----------
function fit() {
  const W = stage.clientWidth, H = stage.clientHeight, vw = vid.videoWidth || (S.rdim && S.rdim.w) || S.remote.w || 16, vh = vid.videoHeight || (S.rdim && S.rdim.h) || S.remote.h || 9;
  const sc = Math.min(W / vw, H / vh), w = vw * sc, h = vh * sc;
  return { x: (W - w) / 2, y: (H - h) / 2, w, h, vw };
}
// zoom/pan: the #view layer is scaled by S.zoom and translated by S.pan (screen px)
function toNorm(px, py) { const r = fit(), z = S.zoom || 1, p = S.pan || { x: 0, y: 0 }; const cx = (px - p.x) / z, cy = (py - p.y) / z; return { x: Math.min(1, Math.max(0, (cx - r.x) / r.w)), y: Math.min(1, Math.max(0, (cy - r.y) / r.h)) }; }
function drawCursor() { if (!S) return; const r = fit(); cur.style.display = 'block'; cur.style.left = (r.x + S.norm.x * r.w) + 'px'; cur.style.top = (r.y + S.norm.y * r.h) + 'px'; cur.style.transform = `scale(${1 / (S.zoom || 1)})`; cur.style.transformOrigin = '0 0'; }
function applyView(z, p) {
  const W = stage.clientWidth, H = stage.clientHeight; z = Math.min(6, Math.max(1, z));
  p = { x: Math.min(0, Math.max(W - W * z, p.x)), y: Math.min(0, Math.max(H - H * z, p.y)) }; // no empty gaps
  S.zoom = z; S.pan = p; $('view').style.transform = `translate(${p.x}px,${p.y}px) scale(${z})`; drawCursor();
}
function zoomAt(cx, cy, nz) { const z = S.zoom || 1, p = S.pan || { x: 0, y: 0 }; nz = Math.min(6, Math.max(1, nz)); const k = nz / z; applyView(nz, { x: cx - (cx - p.x) * k, y: cy - (cy - p.y) * k }); }

// ---------- input (coalesced ~60 Hz) ----------
function flush() {
  const p = S && S.pend; if (!p) return;
  if (p.abs) { send({ t: 'mm', x: +p.abs.x.toFixed(5), y: +p.abs.y.toFixed(5) }); p.abs = null; }
  if (Math.abs(p.dx) >= 1 || Math.abs(p.dy) >= 1) { const dx = Math.trunc(p.dx), dy = Math.trunc(p.dy); p.dx -= dx; p.dy -= dy; send({ t: 'mr', dx, dy }); }
  if (Math.abs(p.wx) >= .1 || Math.abs(p.wy) >= .1) { send({ t: 'ws', dx: p.wx, dy: p.wy }); p.wx = p.wy = 0; }
}
const btn = (b, d) => { flush(); send({ t: 'mb', b, d }); };
const click = b => { btn(b, true); btn(b, false); };
const keyTap = c => { for (const m of S.mods) send({ t: 'k', c: m, d: true }); send({ t: 'k', c, d: true }); send({ t: 'k', c, d: false }); for (const m of [...S.mods].reverse()) send({ t: 'k', c: m, d: false }); if (S.mods.size) { S.mods.clear(); refreshKeys(); } };

const ptrs = new Map(); let g = {};
stage.addEventListener('pointerdown', e => {
  if (e.target.closest('#bar,#keys,#overlay,#handle') || !S || S.state !== 'connected') return;
  stage.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (ptrs.size === 1) {
    g = { down: { x: e.clientX, y: e.clientY }, t: Date.now(), moved: false, drag: false, long: false };
    g.timer = setTimeout(() => { if (ptrs.size !== 1 || g.moved) return; g.long = true; navigator.vibrate && navigator.vibrate(30);
      if (S.trackpad) { btn('left', true); g.drag = true; } else { S.pend.abs = toNorm(g.down.x, g.down.y); click('right'); } }, 450);
  } else if (ptrs.size === 2) {
    clearTimeout(g.timer); if (g.drag) { btn('left', false); g.drag = false; }
    const [a, b] = [...ptrs.values()]; g.two = { t: Date.now(), moved: false, c: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, last: null, d0: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), z0: S.zoom || 1, pinch: false };
    g.two.last = g.two.c;
  }
}, { passive: false });
stage.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId)) return;
  const prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (ptrs.size === 1) {
    const dx = e.clientX - prev.x, dy = e.clientY - prev.y;
    if (S.panMode) { if (Math.hypot(e.clientX - g.down.x, e.clientY - g.down.y) > 6) { g.moved = true; clearTimeout(g.timer); const p = S.pan || { x: 0, y: 0 }; applyView(S.zoom || 1, { x: p.x + dx, y: p.y + dy }); } return; }
    if (!g.moved && Math.hypot(e.clientX - g.down.x, e.clientY - g.down.y) > 10) {
      g.moved = true; clearTimeout(g.timer);
      if (!S.trackpad) { S.pend.abs = toNorm(g.down.x, g.down.y); btn('left', true); g.drag = true; }
    }
    if (!g.moved) return;
    if (S.trackpad) { const k = (S.remote.w || fit().vw) / (fit().w * (S.zoom || 1)) * 1.4; S.pend.dx += dx * k; S.pend.dy += dy * k; }
    else S.pend.abs = toNorm(e.clientX, e.clientY);
  } else if (ptrs.size === 2 && g.two) {
    const [a, b] = [...ptrs.values()]; const c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const ratio = Math.hypot(a.x - b.x, a.y - b.y) / g.two.d0;
    if (Math.hypot(c.x - g.two.c.x, c.y - g.two.c.y) > 8 || Math.abs(ratio - 1) > 0.05) g.two.moved = true;
    if (!g.two.pinch && Math.abs(ratio - 1) > 0.12) g.two.pinch = true;
    if (g.two.pinch) { zoomAt(c.x, c.y, g.two.z0 * ratio); const p = S.pan; applyView(S.zoom, { x: p.x + (c.x - g.two.last.x), y: p.y + (c.y - g.two.last.y) }); }
    else { S.pend.wy += (c.y - g.two.last.y) / 40; S.pend.wx -= (c.x - g.two.last.x) / 40; }
    g.two.last = c;
  }
  e.preventDefault();
}, { passive: false });
function pend(e) {
  const had = ptrs.size; ptrs.delete(e.pointerId);
  if (!S) return;
  clearTimeout(g.timer);
  if (had === 2) { if (g.two && !g.two.moved && Date.now() - g.two.t < 350) { S.pend.abs = S.trackpad ? S.norm : toNorm(g.two.c.x, g.two.c.y); click('right'); } g.two = null; return; }
  if (ptrs.size) return;
  if (g.drag) { btn('left', false); g.drag = false; }
  else if (!g.moved && !g.long && !S.panMode && Date.now() - g.t < 350) { if (!S.trackpad) S.pend.abs = toNorm(e.clientX, e.clientY); click('left'); }
}
stage.addEventListener('pointerup', pend); stage.addEventListener('pointercancel', pend);
stage.addEventListener('contextmenu', e => e.preventDefault());

// ---------- toolbar / keyboard ----------
$('bClose').onclick = exitSession; $('ovback').onclick = exitSession; $('ovbtn').onclick = () => { S.closed = false; S.retries = 0; S.retrying = false; overlay('Connecting…', false); connect(); };
$('bMode').onclick = () => { S.trackpad = !S.trackpad; $('bMode').textContent = S.trackpad ? 'Trackpad' : 'Touch'; };
$('bPan').onclick = () => { S.panMode = !S.panMode; $('bPan').classList.toggle('on', S.panMode); };
$('bZi').onclick = () => zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, (S.zoom || 1) * 1.4);
$('bZo').onclick = () => zoomAt(stage.clientWidth / 2, stage.clientHeight / 2, (S.zoom || 1) / 1.4);
$('bZ1').onclick = () => applyView(1, { x: 0, y: 0 });
$('qual').onchange = () => send({ t: 'cfg', quality: $('qual').value });
$('bFull').onclick = () => { (stage.requestFullscreen || stage.webkitRequestFullscreen || (() => {})).call(stage); };
$('bLock').onclick = () => { if (confirm('Lock the PC? Windows will NOT let this remote app control the lock screen, so you cannot unlock it from here — only do this if you are at the PC.')) send({ t: 'lock' }); };
$('handle').onclick = () => { const b = $('bar'); b.style.display = b.style.display === 'none' ? 'flex' : 'none'; };
$('bKb').onclick = () => { const k = $('kb'); if (document.activeElement === k) k.blur(); else { k.value = '​'; k.focus(); } };
const kb = $('kb');
kb.addEventListener('input', () => {
  const v = kb.value;
  if (!v.length) send2Key('Backspace');
  else if (v.length > 1) for (const ch of [...v.slice(1)]) {
    if (ch === '\n') keyTap('Enter');
    else if (S.mods.size && /^[a-z0-9]$/i.test(ch)) keyTap(/\d/.test(ch) ? 'Digit' + ch : 'Key' + ch.toUpperCase());
    else send({ t: 'tx', s: ch });
  }
  kb.value = '​';
});
kb.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); keyTap('Enter'); } });
const send2Key = c => keyTap(c);
const KEYROW = [['Ctrl', 'ControlLeft', 1], ['Alt', 'AltLeft', 1], ['Shift', 'ShiftLeft', 1], ['Win', 'MetaLeft', 1], ['Esc', 'Escape'], ['Tab', 'Tab'], ['←', 'ArrowLeft'], ['↑', 'ArrowUp'], ['↓', 'ArrowDown'], ['→', 'ArrowRight'], ['Home', 'Home'], ['End', 'End'], ['PgUp', 'PageUp'], ['PgDn', 'PageDown'], ['Del', 'Delete'],
  ['Copy', 'KeyC', 0, ['ControlLeft']], ['Paste', 'KeyV', 0, ['ControlLeft']], ['Cut', 'KeyX', 0, ['ControlLeft']], ['Undo', 'KeyZ', 0, ['ControlLeft']], ['All', 'KeyA', 0, ['ControlLeft']], ['Alt+Tab', 'Tab', 0, ['AltLeft']], ['Win+D', 'KeyD', 0, ['MetaLeft']], ['TaskMgr', 'Escape', 0, ['ControlLeft', 'ShiftLeft']],
  ...Array.from({ length: 12 }, (_, i) => ['F' + (i + 1), 'F' + (i + 1)])];
function refreshKeys() { for (const b of $('keys').children) if (b.dataset.mod) b.classList.toggle('on', S.mods.has(b.dataset.mod)); }
for (const [label, code, isMod, combo] of KEYROW) {
  const b = document.createElement('button'); b.textContent = label; if (isMod) b.dataset.mod = code;
  b.onclick = () => { if (isMod) { S.mods.has(code) ? S.mods.delete(code) : S.mods.add(code); refreshKeys(); } else if (combo) { for (const m of combo) send({ t: 'k', c: m, d: true }); send({ t: 'k', c: code, d: true }); send({ t: 'k', c: code, d: false }); for (const m of combo.reverse()) send({ t: 'k', c: m, d: false }); } else keyTap(code); };
  $('keys').appendChild(b);
}
$('bKeys').onclick = () => { const k = $('keys'); k.style.display = k.style.display === 'flex' ? 'none' : 'flex'; };
window.addEventListener('resize', () => S && drawCursor());
vid.addEventListener('loadedmetadata', () => S && drawCursor());

renderHome();
pairFromFragment();
