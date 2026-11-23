// Drives the real web client in headless Chrome. Usage: node e2e_web.js <serverUrl> <pairingCode> <direct|relay>
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
(async () => {
  const [url, code, mode] = process.argv.slice(2);
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] });
  const p = await b.newPage();
  await p.setViewport({ width: 900, height: 500, hasTouch: false });
  p.on('pageerror', e => console.log('[pageerror]', e.message));
  if (process.env.MANUAL) {   // no-camera path: paste the pairing link into the box
    await p.goto(`${url}/${mode === 'relay' ? '?relay=1' : ''}`);
    await p.evaluate(() => { document.querySelector('details.manual').open = true; });
    await p.type('#manual', `${url}/#c=${code}`);
    await p.click('#bManual');
  } else await p.goto(`${url}/${mode === 'relay' ? '?relay=1' : ''}#c=${code}`);
  await p.waitForFunction(() => document.getElementById('stage').style.display === 'block' && document.getElementById('overlay').style.display === 'none', { timeout: 60000 });
  await new Promise(r => setTimeout(r, 2500));
  console.log('PILL', await p.$eval('#pill', e => e.textContent));
  console.log('STAGE_CONNECTED');
  // 1) click at the centre
  for (let i = 0; i < 3; i++) { await p.mouse.click(450, 250); await new Promise(r => setTimeout(r, 400)); }
  console.log('CLICKED_CENTER');
  await new Promise(r => setTimeout(r, 1500));
  // 2) rotate view 90deg then click 100px right of centre => expected remote (0.5, ~0.146)
  await p.click('#bRot'); await new Promise(r => setTimeout(r, 600));
  const st = await p.evaluate(() => { const r = document.getElementById('rot'); return r.style.transform; });
  console.log('ROT', st);
  for (let i = 0; i < 3; i++) { await p.mouse.click(550, 250); await new Promise(r => setTimeout(r, 400)); }
  console.log('CLICKED_ROTATED');
  await new Promise(r => setTimeout(r, 1500));
  // 3) zoom in x2.25 and click centre: stays at centre of the (rotated) view
  await p.click('#bRot'); await p.click('#bRot'); await p.click('#bRot'); // back to 0
  await p.click('#bZi'); await p.click('#bZi'); await p.click('#bZi'); await new Promise(r => setTimeout(r, 2500));
  const z = await p.evaluate(() => document.getElementById('view').style.transform);
  console.log('ZOOM', z);
  // the PC must now be streaming only the visible region (sharp), placed inside the full-monitor layout
  const roi = await p.evaluate(() => JSON.stringify({ roi: S.shownRoi, req: S.roiReq && true, zoom: S.zoom, frame: S.relay ? S.rdim : { w: vid.videoWidth, h: vid.videoHeight } }));
  console.log('ROI', roi);
  for (let i = 0; i < 3; i++) { await p.mouse.click(550, 250); await new Promise(r => setTimeout(r, 400)); }   // 100 px right of centre while zoomed
  console.log('CLICKED_ZOOMED');
  await new Promise(r => setTimeout(r, 800));
  await p.click('#bZ1'); await new Promise(r => setTimeout(r, 2500));
  console.log('ROI_AFTER_RESET', await p.evaluate(() => JSON.stringify({ roi: S.shownRoi })));
  await p.click('#bClose');
  await new Promise(r => setTimeout(r, 800));
  console.log('SIGNED_OUT', await p.evaluate(() => document.getElementById('home').style.display));
  await b.close();
})().catch(e => { console.log('FAIL', e.message); process.exit(1); });
