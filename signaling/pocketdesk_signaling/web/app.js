// PocketDesk web client — same protocol as the Android app (see ARCHITECTURE.md). Installable (PWA).
'use strict';
const $ = id => document.getElementById(id);
const enc = new TextEncoder();
const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const hex = b => [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
const unhex = h => new Uint8Array(h.match(/../g).map(x => parseInt(x, 16)));
const ctEq = (a, b) => { if (a.length !== b.length) return false; let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i); return r === 0; };
const ls = { get: k => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} }, del: k => { try { localStorage.removeItem(k); } catch {} } };

// ---------- crypto (identical to agent/crypto.py) ----------
function parseCode(t) {
  t = t.replace(/[\s-]/g, '').toUpperCase();
  if (t.length !== 22 || [...t].some(c => !B32.includes(c))) throw new Error('That is not a valid pairing code.');
  let bits = 0, val = 0; const out = [];
  for (const c of t.slice(6)) { val = (val << 5) | B32.indexOf(c); bits += 5; if (bits >= 8) { out.push((val >> (bits - 8)) & 255); bits -= 8; } }
  return { lookup: t.slice(0, 6), secret: new Uint8Array(out) };
}
async function derivePairKey(secret) {
  const k = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: enc.encode('pocketdesk-pair-v1'), info: enc.encode('pair-key') }, k, 256));
}
async function mac(keyBytes, msg) {
  const k = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', k, enc.encode(msg)));
}
function fingerprint(sdp) { const m = /^a=fingerprint:\S+\s+([0-9A-Fa-f:]+)\s*$/m.exec(sdp); if (!m) throw new Error('no DTLS fingerprint'); return m[1].toLowerCase(); }

// ---------- storage ----------
const loadPcs = () => { try { return JSON.parse(ls.get('pd_pcs') || '[]'); } catch { return []; } };
const savePcs = l => ls.set('pd_pcs', JSON.stringify(l));
const base = pc => ((pc && pc.server) || window.PD_SERVER || location.origin).replace(/\/+$/, '');
const wsUrl = pc => base(pc).replace(/^http/, 'ws') + '/ws';
const deviceName = () => /Android/.test(navigator.userAgent) ? 'Android phone' : /iPhone|iPad/.test(navigator.userAgent) ? 'iPhone' : 'Phone browser';
function notice(t) { const m = $('msg'); m.textContent = t || ''; m.style.display = t ? 'block' : 'none'; }

// ---------- pairing ----------
// Accepts a full pairing link (…/#c=CODE[&s=SERVER]) or a bare code.
function parsePairingText(text) {
  text = String(text).trim(); let code = text, server = '';
  try { const u = new URL(text); const h = new URLSearchParams(u.hash.replace(/^#/, '')); code = h.get('c') || ''; server = h.get('s') || u.origin; } catch {}
  return { code, server };
}
async function pairWith(code, server) {
  notice('Pairing…');
  try {
    const { lookup, secret } = parseCode(decodeURIComponent(code));
    const key = await derivePairKey(secret), name = deviceName(), b = (server || window.PD_SERVER || location.origin).replace(/\/+$/, '');
    const r = await fetch(b + '/api/pair/claim', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ code: lookup, device_name: name, proof: await mac(key, `pd1|claim|${lookup}|${name}`) }) });
    if (r.status === 404) throw new Error('Code is invalid or expired.\nOn the PC click “Pair a new phone” again and scan the new QR.');
    if (r.status === 409) throw new Error('The PC agent is offline. Start PocketDesk Agent on the PC.');
    if (r.status === 429) throw new Error('Too many attempts — wait a minute and try again.');
    if (!r.ok) throw new Error('Pairing failed (' + r.status + ').');
    const j = await r.json();
    const pcs = loadPcs().filter(p => p.agentId !== j.agent_id);
    const pc = { server: b, deviceId: j.device_id, token: j.device_token, agentId: j.agent_id, name: j.agent_name, keyHex: hex(key) };
    pcs.push(pc); savePcs(pcs); notice(''); openPc(pc);
  } catch (e) { notice(e.message || String(e)); }
}
function pairFromFragment() {
  const h = new URLSearchParams(location.hash.replace(/^#/, '')), c = h.get('c');
  if (!c) return false;
  history.replaceState(null, '', location.pathname); // keep the secret out of history
  pairWith(c, h.get('s') || '');
  return true;
}

// ---------- QR scanner (Chrome/Android BarcodeDetector) ----------
let scanStream = null, scanTimer = null;
async function startScan() {
  if (!('BarcodeDetector' in window)) { notice('This browser cannot scan QR codes inside the page. Open your phone’s Camera app, point it at the QR on the PC and tap the link.'); return; }
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    const v = $('scanv'); v.srcObject = scanStream; await v.play(); $('scan').style.display = 'flex';
    const det = new BarcodeDetector({ formats: ['qr_code'] });
    scanTimer = setInterval(async () => {
      try { const r = await det.detect(v); if (r.length) { const { code, server } = parsePairingText(r[0].rawValue); if (code) { stopScan(); pairWith(code, server); } } } catch {}
    }, 250);
  } catch (e) { stopScan(); notice('Camera permission is needed to scan. You can also scan the QR with your phone’s Camera app.'); }
}
function stopScan() { clearInterval(scanTimer); if (scanStream) scanStream.getTracks().forEach(t => t.stop()); scanStream = null; $('scan').style.display = 'none'; }
$('bScan').onclick = startScan; $('scanx').onclick = stopScan;

// ---------- home ----------
async function renderHome() {
  const l = $('list'); l.innerHTML = ''; const pcs = loadPcs();
  $('steps').style.display = pcs.length ? 'none' : 'block';
  for (const pc of pcs) {
    const d = document.createElement('div'); d.className = 'pc';
    d.innerHTML = '<span class="ic">🖥</span><div class="nm"><b></b><span class="st"><i class="dot"></i><span>Checking…</span></span></div>';
    d.querySelector('b').textContent = pc.name;
    const b = document.createElement('button'); b.textContent = 'Connect'; b.onclick = () => openPc(pc);
    const x = document.createElement('button'); x.className = 'x'; x.textContent = '🗑'; x.setAttribute('aria-label', 'Remove');
    x.onclick = async () => { if (confirm('Remove “' + pc.name + '” from this phone? It will be unpaired.')) { try { await fetch(base(pc) + '/api/devices/' + pc.deviceId, { method: 'DELETE', headers: { Authorization: `Bearer ${pc.deviceId}:${pc.token}` } }); } catch {} savePcs(loadPcs().filter(p => p.deviceId !== pc.deviceId)); if (ls.get('pd_auto') === pc.deviceId) ls.del('pd_auto'); renderHome(); } };
    d.append(b, x); l.appendChild(d);
    fetch(base(pc) + '/api/status', { headers: { Authorization: `Bearer ${pc.deviceId}:${pc.token}` } }).then(async r => {
      const dot = d.querySelector('.dot'), t = d.querySelector('.st span:last-child');
      if (r.status === 401) { dot.className = 'dot off'; t.textContent = 'Access revoked — remove and pair again'; }
      else if (r.ok) { const j = await r.json(); dot.className = 'dot ' + (j.online ? 'on' : 'off'); t.textContent = j.online ? 'Online' : 'PC offline'; }
    }).catch(() => { d.querySelector('.st span:last-child').textContent = 'Server unreachable'; });
  }
}

// ---------- session state / geometry ----------
let S = null;
const FORCE_RELAY = /[?&]relay=1/.test(location.search);   // open the page with ?relay=1 to force the encrypted relay
const stage = $('stage'), vid = $('vid'), cur = $('cur'), view = $('view'), rotEl = $('rot');
const dims = () => { const W = stage.clientWidth, H = stage.clientHeight; return (S && S.rot % 180) ? { w: H, h: W } : { w: W, h: H }; };
function layout() {
  if (!S) return; const d = dims();
  Object.assign(rotEl.style, { width: d.w + 'px', height: d.h + 'px', marginLeft: -d.w / 2 + 'px', marginTop: -d.h / 2 + 'px', transform: `rotate(${S.rot}deg)` });
  applyView(S.zoom || 1, S.pan || { x: 0, y: 0 });
}
// screen point -> point inside the (rotated) viewer, and the same for movement deltas
function sv(px, py) { const r = stage.getBoundingClientRect(), d = dims(), a = px - r.left - r.width / 2, b = py - r.top - r.height / 2;
  switch (S.rot) { case 0: return { x: a + d.w / 2, y: b + d.h / 2 }; case 90: return { x: b + d.w / 2, y: -a + d.h / 2 }; case 180: return { x: -a + d.w / 2, y: -b + d.h / 2 }; default: return { x: -b + d.w / 2, y: a + d.h / 2 }; } }
function fit() {
  const d = dims(), vw = vid.videoWidth || (S.rdim && S.rdim.w) || S.remote.w || 16, vh = vid.videoHeight || (S.rdim && S.rdim.h) || S.remote.h || 9;
  const sc = Math.min(d.w / vw, d.h / vh), w = vw * sc, h = vh * sc; return { x: (d.w - w) / 2, y: (d.h - h) / 2, w, h, vw };
}
function toNorm(px, py) { const r = fit(), z = S.zoom || 1, p = S.pan || { x: 0, y: 0 }, cx = (px - p.x) / z, cy = (py - p.y) / z; return { x: Math.min(1, Math.max(0, (cx - r.x) / r.w)), y: Math.min(1, Math.max(0, (cy - r.y) / r.h)) }; }
function drawCursor() { if (!S) return; const r = fit(); cur.style.display = 'block'; cur.style.left = (r.x + S.norm.x * r.w) + 'px'; cur.style.top = (r.y + S.norm.y * r.h) + 'px'; cur.style.transform = `scale(${1 / (S.zoom || 1)})`; cur.style.transformOrigin = '0 0'; }
function applyView(z, p) {
  const d = dims(); z = Math.min(6, Math.max(1, z));
  p = { x: Math.min(0, Math.max(d.w - d.w * z, p.x)), y: Math.min(0, Math.max(d.h - d.h * z, p.y)) };
  S.zoom = z; S.pan = p; view.style.transform = `translate(${p.x}px,${p.y}px) scale(${z})`; drawCursor();
}
function zoomAt(cx, cy, nz) { const z = S.zoom || 1, p = S.pan || { x: 0, y: 0 }; nz = Math.min(6, Math.max(1, nz)); const k = nz / z; applyView(nz, { x: cx - (cx - p.x) * k, y: cy - (cy - p.y) * k }); }
const mid = () => { const d = dims(); return { x: d.w / 2, y: d.h / 2 }; };

// ---------- session lifecycle ----------
function openPc(pc) {
  $('home').style.display = 'none'; stage.style.display = 'block'; ls.set('pd_auto', pc.deviceId);
  S = { pc, retries: 0, trackpad: ls.get('pd_mode') === 'trackpad', norm: { x: .5, y: .5 }, remote: { w: 0, h: 0 }, mods: new Set(), closed: false, rot: +(ls.get('pd_rot') || 0), zoom: 1, pan: { x: 0, y: 0 }, quality: ls.get('pd_q') || 'medium', pend: { abs: null, dx: 0, dy: 0, wx: 0, wy: 0 } };
  $('bMode').innerHTML = S.trackpad ? '🖱<small>Trackpad</small>' : '☝<small>Touch</small>'; markQ();
  $('lockmsg').style.display = 'none'; layout(); overlay('Connecting…', false); holdWake(); connect();
}
function overlay(msg, retry) { $('overlay').style.display = 'flex'; $('ovmsg').textContent = msg; $('ovbtn').style.display = retry ? '' : 'none'; $('spin').style.display = retry === 'err' ? 'none' : ''; }

async function connect() {
  const s = S; if (!s || s.closed) return;
  teardown(s);
  try {
    const key = unhex(s.pc.keyHex);
    s.ws = new WebSocket(wsUrl(s.pc));
    const msgs = new Map();
    const waitMsg = (type, ms) => new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('Timed out waiting for ' + type)), ms); msgs.set(type, m => { clearTimeout(t); res(m); }); });
    s.waitMsg = waitMsg;
    const ready = waitMsg('ready', 12000), answer = waitMsg('answer', 30000); answer.catch(() => {}); ready.catch(() => {});
    s.ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.type === 'error' || m.type === 'agent_offline') { const f = msgs.get('relay_ok') || msgs.get('answer'); if (f) f({ type: 'fail', error: m.type === 'agent_offline' ? 'The PC is offline — is it on, and is PocketDesk Agent running?' : (m.error === 'auth' ? 'Access was revoked. Remove this PC and pair again.' : 'The PC rejected the request.'), fatal: m.error === 'auth' }); return; }
      const f = msgs.get(m.type); if (f) f(m);
    };
    s.ws.onclose = () => { if (!s.closed && s.state !== 'connected' && s.ws) retry(s, 'Signaling closed'); };
    await new Promise((res, rej) => { s.ws.onopen = res; s.ws.onerror = () => rej(new Error('Cannot reach the server')); });
    s.ws.send(JSON.stringify({ type: 'auth', role: 'device', id: s.pc.deviceId, secret: s.pc.token }));
    const rd = await ready;
    overlay('Connecting to ' + s.pc.name + '…', false);
    if (FORCE_RELAY || ls.get('pd_relay_' + s.pc.deviceId) === '1') { await startRelay(s); return; }
    s.rtc = new RTCPeerConnection({ iceServers: rd.ice_servers });
    s.dc = s.rtc.createDataChannel('control', { ordered: true });
    s.dc.onopen = () => onOpen(s); s.dc.onmessage = e => onData(s, JSON.parse(e.data));
    s.rtc.addTransceiver('video', { direction: 'recvonly' });
    s.rtc.ontrack = e => { vid.srcObject = e.streams[0]; vid.play().catch(() => {}); };
    s.rtc.onconnectionstatechange = () => {
      const st = s.rtc && s.rtc.connectionState;
      if (st === 'connected') { s.state = 'connected'; s.retries = 0; s.lastRx = performance.now(); $('overlay').style.display = 'none'; }
      else if (st === 'failed' || st === 'closed') { if (s.relay) return; if (s.state !== 'connected') startRelay(s); else retry(s, 'Connection lost'); }
      else if (st === 'disconnected') setTimeout(() => { if (s.rtc && s.rtc.connectionState === 'disconnected') retry(s, 'Connection lost'); }, 6000);
    };
    await s.rtc.setLocalDescription(await s.rtc.createOffer());
    await new Promise(res => { if (s.rtc.iceGatheringState === 'complete') return res(); const t = setTimeout(res, 8000); s.rtc.onicegatheringstatechange = () => { if (s.rtc.iceGatheringState === 'complete') { clearTimeout(t); res(); } }; });
    const sdp = s.rtc.localDescription.sdp;
    s.sid = hex(crypto.getRandomValues(new Uint8Array(16))); s.ts = Math.floor(Date.now() / 1000);
    s.ws.send(JSON.stringify({ type: 'offer', agent_id: s.pc.agentId, session_id: s.sid, ts: s.ts, sdp, mac: await mac(key, `pd1|offer|${s.sid}|${s.pc.deviceId}|${s.ts}|${fingerprint(sdp)}`) }));
    const ans = await answer;
    if (ans.type === 'fail') return fatal(s, ans);
    const expect = await mac(key, `pd1|answer|${s.sid}|${s.pc.deviceId}|${ans.ts}|${fingerprint(ans.sdp)}`);
    if (ans.session_id !== s.sid || !ctEq(expect, String(ans.mac))) { s.closed = true; teardown(s); overlay('Security check failed: the PC could not be verified. Remove it and pair again.', 'err'); return; }
    await s.rtc.setRemoteDescription({ type: 'answer', sdp: ans.sdp });
    // No direct/TURN path within 12 s (typical on mobile data / office networks): use the encrypted relay.
    s.fallback = setTimeout(() => { if (S === s && s.state !== 'connected' && !s.closed) startRelay(s); }, 12000);
  } catch (e) { retry(s, e.message); }
}
function fatal(s, m) { if (m.fatal) { s.closed = true; teardown(s); overlay(m.error, 'err'); } else retry(s, m.error); }
function retry(s, why) {
  if (s !== S || s.closed || s.retrying) return;
  s.retries++; s.retrying = true; teardown(s); overlay(`Reconnecting… (attempt ${s.retries})\n${why}`, true); // never gives up until you sign out
  setTimeout(() => { s.retrying = false; if (s === S && !s.closed) connect(); }, Math.min(6000, 700 * s.retries));
}
function reconnectNow() { const s = S; if (!s || s.closed) return; s.retrying = false; s.retries = 0; connect(); }
function teardown(s) {
  clearInterval(s.flush); clearInterval(s.ping); clearInterval(s.fpsT); clearTimeout(s.fallback); s.relay = false; s.gotFrame = false; s.state = '';
  $('cv').style.display = 'none'; vid.style.display = '';
  const { rtc, ws, dc } = s; s.rtc = s.ws = s.dc = null;
  try { dc && dc.close(); } catch {} try { rtc && rtc.close(); } catch {} try { ws && ws.close(); } catch {}
}
function signOut() {
  ls.del('pd_auto');
  if (S) { send({ t: 'bye' }); S.closed = true; const s = S; setTimeout(() => teardown(s), 150); S = null; }
  try { wake && wake.release(); } catch {} vid.srcObject = null; stage.style.display = 'none'; $('home').style.display = 'block'; $('sheet').style.display = 'none'; renderHome();
}

// keep-alive layer: watchdog, wake-lock, instant recovery on wake / network change
let wake = null;
async function holdWake() { try { if (navigator.wakeLock && S && document.visibilityState === 'visible') wake = await navigator.wakeLock.request('screen'); } catch {} }
setInterval(() => { const s = S; if (s && !s.closed && !s.retrying && s.state === 'connected' && s.lastRx && performance.now() - s.lastRx > 12000) { retry(s, 'No data from the PC'); } }, 3000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { holdWake(); const s = S; if (s && !s.closed && (s.state !== 'connected' || performance.now() - (s.lastRx || 0) > 8000)) reconnectNow(); } });
window.addEventListener('online', () => { if (S && !S.closed && S.state !== 'connected') reconnectNow(); });
window.addEventListener('offline', () => { if (S) overlay('No internet on this phone — waiting…', true); });
window.addEventListener('resize', () => { if (S) layout(); });
window.addEventListener('orientationchange', () => setTimeout(() => S && layout(), 200));

// ---------- encrypted WebSocket relay ----------
async function relayKeys(pairKey, sidHex) {
  const ikm = await crypto.subtle.importKey('raw', pairKey, 'HKDF', false, ['deriveBits']);
  const mk = async info => crypto.subtle.importKey('raw', await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt: unhex(sidHex), info: enc.encode(info) }, ikm, 256), 'AES-GCM', false, ['encrypt', 'decrypt']);
  return { a2d: await mk('relay-a2d'), d2a: await mk('relay-d2a') };
}
const nonce = ctr => { const n = new Uint8Array(12); n.set(ctr, 4); return n; };
function relaySend(o) {
  const s = S; if (!s || !s.relay) return; const body = enc.encode(JSON.stringify(o));
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
    const data = new Uint8Array(buf), ctr = data.slice(0, 8), n = Number(new DataView(ctr.buffer).getBigUint64(0, false));
    if (n <= s.rxN) return;
    const pt = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce(ctr), additionalData: enc.encode('relay-a2d') }, s.keys.a2d, data.slice(8)));
    s.rxN = n; s.lastRx = performance.now();
    if (pt[0] === 1) {
      const bmp = await createImageBitmap(new Blob([pt.slice(1)], { type: 'image/jpeg' })), cv = $('cv');
      if (cv.width !== bmp.width || cv.height !== bmp.height) { cv.width = bmp.width; cv.height = bmp.height; }
      cv.getContext('2d').drawImage(bmp, 0, 0); bmp.close(); s.rdim = { w: cv.width, h: cv.height };
      if (!s.gotFrame) { s.gotFrame = true; s.state = 'connected'; s.retries = 0; $('overlay').style.display = 'none'; ls.set('pd_relay_' + s.pc.deviceId, '1'); drawCursor(); }
      s.frames = (s.frames || 0) + 1; s.fbytes = (s.fbytes || 0) + data.length;
    } else if (pt[0] === 2) onData(s, JSON.parse(new TextDecoder().decode(pt.slice(1))));
  }).catch(() => {});
}
async function startRelay(s) {
  if (s !== S || s.closed || s.relay) return; clearTimeout(s.fallback);
  try { s.rtc && s.rtc.close(); } catch {} s.rtc = null; vid.srcObject = null; overlay('Connecting via secure relay…', false);
  try {
    const key = unhex(s.pc.keyHex), sid = hex(crypto.getRandomValues(new Uint8Array(16))), ts = Math.floor(Date.now() / 1000);
    const ok = s.waitMsg('relay_ok', 20000); ok.catch(() => {});
    s.ws.send(JSON.stringify({ type: 'relay_start', session_id: sid, ts, mac: await mac(key, `pd1|relay|${sid}|${s.pc.deviceId}|${ts}`) }));
    const m = await ok; if (m.type === 'fail') return fatal(s, m);
    if (m.session_id !== sid || !ctEq(await mac(key, `pd1|relayok|${sid}|${s.pc.deviceId}|${m.ts}`), String(m.mac))) { s.closed = true; teardown(s); overlay('Security check failed: the PC could not be verified.', 'err'); return; }
    s.keys = await relayKeys(key, sid); s.txN = 0; s.rxN = -1; s.chain = Promise.resolve(); s.rchain = Promise.resolve(); s.relay = true; s.ws.binaryType = 'arraybuffer';
    s.ws.onmessage = ev => { if (typeof ev.data !== 'string') relayRecv(s, ev.data); };
    s.ws.onclose = () => { if (!s.closed) retry(s, 'Connection lost'); };
    $('cv').style.display = 'block'; vid.style.display = 'none'; onOpen(s);
    s.fpsT = setInterval(() => { s.fps = (s.frames || 0) / 2; s.kbps = (s.fbytes || 0) * 8 / 2000; s.frames = s.fbytes = 0; updStat(); }, 2000);
  } catch (e) { retry(s, e.message); }
}

// ---------- data channel ----------
const send = o => { if (!S) return; if (S.relay) relaySend(o); else if (S.dc && S.dc.readyState === 'open') S.dc.send(JSON.stringify(o)); };
function onOpen(s) {
  send({ t: 'cfg', quality: s.quality }); s.lastRx = performance.now();
  s.flush = setInterval(flush, 16);
  s.ping = setInterval(() => { s.pn = (s.pn || 0) + 1; s.pt = performance.now(); send({ t: 'ping', n: s.pn }); }, 2000);
}
function onData(s, m) {
  s.lastRx = performance.now();
  if (m.t === 'state') $('lockmsg').style.display = m.locked ? 'block' : 'none';
  else if (m.t === 'info') { s.remote = { w: m.w, h: m.h }; s.monitors = m.monitors; drawCursor(); }
  else if (m.t === 'cur') { s.norm = { x: m.x, y: m.y }; drawCursor(); }
  else if (m.t === 'stats') { if (!s.relay) { s.fps = m.fps; s.kbps = m.kbps; updStat(); } }
  else if (m.t === 'pong') { s.rtt = Math.round(performance.now() - s.pt); updStat(); }
  else if (m.t === 'clip') { navigator.clipboard && navigator.clipboard.writeText(m.s).then(() => toast('PC clipboard copied to phone')).catch(() => toast('Allow clipboard access to copy')); }
}
function updStat() { const s = S; if (s) $('pill').textContent = `${s.relay ? '🔒 relay' : '⚡ direct'} · ${s.rtt ?? '–'} ms · ${Math.round(s.fps || 0)} fps`; }
function toast(t) { const p = $('pill'), old = p.textContent; p.textContent = t; setTimeout(updStat, 2000); }

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
  if (e.target.closest('#dock,#keys,#overlay,#handle,#sheet') || !S || S.state !== 'connected') return;
  stage.setPointerCapture(e.pointerId); const v = sv(e.clientX, e.clientY); ptrs.set(e.pointerId, v);
  if (ptrs.size === 1) {
    g = { down: v, t: Date.now(), moved: false, drag: false, long: false };
    g.timer = setTimeout(() => { if (ptrs.size !== 1 || g.moved || S.panMode) return; g.long = true; navigator.vibrate && navigator.vibrate(30);
      if (S.trackpad) { btn('left', true); g.drag = true; } else { S.pend.abs = toNorm(g.down.x, g.down.y); click('right'); } }, 450);
  } else if (ptrs.size === 2) {
    clearTimeout(g.timer); if (g.drag) { btn('left', false); g.drag = false; }
    const [a, b] = [...ptrs.values()]; g.two = { t: Date.now(), moved: false, c: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, d0: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), z0: S.zoom || 1, pinch: false }; g.two.last = g.two.c;
  }
}, { passive: false });
stage.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId) || !S) return;
  const prev = ptrs.get(e.pointerId), v = sv(e.clientX, e.clientY); ptrs.set(e.pointerId, v);
  if (ptrs.size === 1) {
    const dx = v.x - prev.x, dy = v.y - prev.y;
    if (S.panMode) { if (Math.hypot(v.x - g.down.x, v.y - g.down.y) > 6) { g.moved = true; clearTimeout(g.timer); const p = S.pan; applyView(S.zoom, { x: p.x + dx, y: p.y + dy }); } return; }
    if (!g.moved && Math.hypot(v.x - g.down.x, v.y - g.down.y) > 10) { g.moved = true; clearTimeout(g.timer); if (!S.trackpad) { S.pend.abs = toNorm(g.down.x, g.down.y); btn('left', true); g.drag = true; } }
    if (!g.moved) return;
    if (S.trackpad) { const k = (S.remote.w || fit().vw) / (fit().w * S.zoom) * 1.4; S.pend.dx += dx * k; S.pend.dy += dy * k; } else S.pend.abs = toNorm(v.x, v.y);
  } else if (ptrs.size === 2 && g.two) {
    const [a, b] = [...ptrs.values()], c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, ratio = Math.hypot(a.x - b.x, a.y - b.y) / g.two.d0;
    if (Math.hypot(c.x - g.two.c.x, c.y - g.two.c.y) > 8 || Math.abs(ratio - 1) > 0.05) g.two.moved = true;
    if (!g.two.pinch && Math.abs(ratio - 1) > 0.12) g.two.pinch = true;
    if (g.two.pinch) { zoomAt(c.x, c.y, g.two.z0 * ratio); const p = S.pan; applyView(S.zoom, { x: p.x + (c.x - g.two.last.x), y: p.y + (c.y - g.two.last.y) }); }
    else { S.pend.wy += (c.y - g.two.last.y) / 40; S.pend.wx -= (c.x - g.two.last.x) / 40; }
    g.two.last = c;
  }
  e.preventDefault();
}, { passive: false });
function pend(e) {
  const had = ptrs.size; ptrs.delete(e.pointerId); if (!S) return; clearTimeout(g.timer);
  if (had === 2) { if (g.two && !g.two.moved && Date.now() - g.two.t < 350) { S.pend.abs = S.trackpad ? S.norm : toNorm(g.two.c.x, g.two.c.y); click('right'); } g.two = null; return; }
  if (ptrs.size) return;
  if (g.drag) { btn('left', false); g.drag = false; }
  else if (!g.moved && !g.long && !S.panMode && Date.now() - g.t < 350) { const v = sv(e.clientX, e.clientY); if (!S.trackpad) S.pend.abs = toNorm(v.x, v.y); click('left'); }
}
stage.addEventListener('pointerup', pend); stage.addEventListener('pointercancel', pend); stage.addEventListener('contextmenu', e => e.preventDefault());

// ---------- toolbar / keyboard ----------
const on = (id, f) => { $(id).onclick = f; };
on('bClose', signOut); on('ovback', signOut); on('ovbtn', () => { if (S) { S.closed = false; reconnectNow(); } });
on('bMode', () => { S.trackpad = !S.trackpad; ls.set('pd_mode', S.trackpad ? 'trackpad' : 'touch'); $('bMode').innerHTML = S.trackpad ? '🖱<small>Trackpad</small>' : '☝<small>Touch</small>'; toast(S.trackpad ? 'Trackpad: drag moves the cursor' : 'Touch: tap where you want to click'); });
on('bPan', () => { S.panMode = !S.panMode; $('bPan').classList.toggle('on', S.panMode); toast(S.panMode ? 'Pan: drag to move the zoomed view' : 'Pan off'); });
on('bZi', () => { const m = mid(); zoomAt(m.x, m.y, (S.zoom || 1) * 1.5); });
on('bZo', () => { const m = mid(); zoomAt(m.x, m.y, (S.zoom || 1) / 1.5); });
on('bZ1', () => applyView(1, { x: 0, y: 0 }));
on('bRot', () => { S.rot = (S.rot + 90) % 360; ls.set('pd_rot', S.rot); applyView(1, { x: 0, y: 0 }); layout(); toast('View rotated ' + S.rot + '°'); });
on('bMore', () => { $('sheet').style.display = 'flex'; });
on('bSheetClose', () => { $('sheet').style.display = 'none'; });
$('sheet').addEventListener('click', e => { if (e.target === $('sheet')) $('sheet').style.display = 'none'; });
function markQ() { for (const b of $('qrow').children) b.classList.toggle('on', S && b.dataset.q === S.quality); }
for (const b of $('qrow').children) b.onclick = () => { S.quality = b.dataset.q; ls.set('pd_q', S.quality); markQ(); send({ t: 'cfg', quality: S.quality }); };
on('bFull', () => { $('sheet').style.display = 'none'; (stage.requestFullscreen || stage.webkitRequestFullscreen || (() => {})).call(stage); });
on('bLock', () => { $('sheet').style.display = 'none'; if (confirm('Lock the PC?\n\nWindows will NOT let this remote app control the lock screen, so you cannot unlock it from here. Only do this if you are at the PC.')) send({ t: 'lock' }); });
on('bClipPush', async () => { $('sheet').style.display = 'none'; try { const t = await navigator.clipboard.readText(); if (t) { send({ t: 'clip', s: t.slice(0, 50000) }); toast('Clipboard sent to PC'); } } catch { toast('Allow clipboard access first'); } });
on('bClipPull', () => { $('sheet').style.display = 'none'; send({ t: 'clipget' }); });
on('handle', () => { const d = $('dock'); const hid = d.style.display === 'none'; d.style.display = hid ? 'flex' : 'none'; $('handle').textContent = hid ? '▲' : '▼'; });
$('handle').style.display = 'block'; $('handle').textContent = '▲';
on('bKb', () => { const k = $('kb'); if (document.activeElement === k) k.blur(); else { k.value = '​'; k.focus(); } });
const kb = $('kb');
kb.addEventListener('input', () => {
  const v = kb.value;
  if (!v.length) keyTap('Backspace');
  else if (v.length > 1) for (const ch of [...v.slice(1)]) { if (ch === '\n') keyTap('Enter'); else if (S.mods.size && /^[a-z0-9]$/i.test(ch)) keyTap(/\d/.test(ch) ? 'Digit' + ch : 'Key' + ch.toUpperCase()); else send({ t: 'tx', s: ch }); }
  kb.value = '​';
});
kb.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); keyTap('Enter'); } });
const KEYROW = [['Esc', 'Escape'], ['Tab', 'Tab'], ['Ctrl', 'ControlLeft', 1], ['Alt', 'AltLeft', 1], ['Shift', 'ShiftLeft', 1], ['Win', 'MetaLeft', 1], ['←', 'ArrowLeft'], ['↑', 'ArrowUp'], ['↓', 'ArrowDown'], ['→', 'ArrowRight'], ['Enter', 'Enter'], ['⌫', 'Backspace'], ['Del', 'Delete'], ['Home', 'Home'], ['End', 'End'], ['PgUp', 'PageUp'], ['PgDn', 'PageDown'],
  ['Copy', 'KeyC', 0, ['ControlLeft']], ['Paste', 'KeyV', 0, ['ControlLeft']], ['Cut', 'KeyX', 0, ['ControlLeft']], ['Undo', 'KeyZ', 0, ['ControlLeft']], ['All', 'KeyA', 0, ['ControlLeft']], ['Save', 'KeyS', 0, ['ControlLeft']], ['Alt+Tab', 'Tab', 0, ['AltLeft']], ['Win+D', 'KeyD', 0, ['MetaLeft']], ['Win+L', 'KeyL', 0, ['MetaLeft']], ['TaskMgr', 'Escape', 0, ['ControlLeft', 'ShiftLeft']],
  ...Array.from({ length: 12 }, (_, i) => ['F' + (i + 1), 'F' + (i + 1)])];
function refreshKeys() { for (const b of $('keys').children) if (b.dataset.mod) b.classList.toggle('on', S.mods.has(b.dataset.mod)); }
for (const [label, code, isMod, combo] of KEYROW) {
  const b = document.createElement('button'); b.textContent = label; if (isMod) b.dataset.mod = code;
  b.onclick = () => { if (isMod) { S.mods.has(code) ? S.mods.delete(code) : S.mods.add(code); refreshKeys(); } else if (combo) { for (const m of combo) send({ t: 'k', c: m, d: true }); send({ t: 'k', c: code, d: true }); send({ t: 'k', c: code, d: false }); for (const m of [...combo].reverse()) send({ t: 'k', c: m, d: false }); } else keyTap(code); };
  $('keys').appendChild(b);
}
on('bKeys', () => { const k = $('keys'), open = k.style.display === 'flex'; k.style.display = open ? 'none' : 'flex'; $('bKeys').classList.toggle('on', !open); });

// ---------- boot ----------
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('/sw.js').catch(() => {});
renderHome();
if (!pairFromFragment()) {            // resume where you left off until you tap "Sign out"
  const auto = ls.get('pd_auto'), pc = loadPcs().find(p => p.deviceId === auto);
  if (pc) openPc(pc);
}
