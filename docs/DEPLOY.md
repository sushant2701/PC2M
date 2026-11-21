# Making PocketDesk public (anyone can use their own PC)

PocketDesk has two parts that deploy differently:

| Part | What it is | Where it can run |
|---|---|---|
| **Web app** (`signaling/pocketdesk_signaling/web/`) | static files: the phone UI / PWA | **Vercel**, Netlify, GitHub Pages, or served by the server itself |
| **Signaling server** (`signaling/`) | FastAPI + **WebSockets** (pairing, relay) | Render, Fly.io, Railway, a VPS (Docker). **Not Vercel** — Vercel functions cannot hold WebSocket connections |

Each user installs the **Agent** on their own PC (it registers itself with the server); the server stores only hashes of secrets, names and online status. It never sees screens or the pairing secret (relay traffic is end-to-end AES-GCM encrypted).

## 1. Deploy the signaling server (pick one)
**Render (easiest):** push the repo to GitHub → Render → New → Blueprint → select the repo (`render.yaml`). Set `CORS_ORIGINS=https://<your-vercel-site>`. Free plan sleeps and loses data; use a paid instance + disk for real use.
**Any VPS:** `cd signaling/deploy; copy .env.example .env; docker compose up -d --build` (adds HTTPS + TURN).
Result: `https://<your-server>` (check `/healthz`).

## 2. Deploy the web app to Vercel
1. Edit `signaling/pocketdesk_signaling/web/config.js`: `window.PD_SERVER = "https://<your-server>";`
2. Vercel → Add New Project → import the GitHub repo → **Root Directory = `signaling/pocketdesk_signaling/web`**, Framework "Other", no build command → Deploy.
   (CLI alternative: `cd signaling/pocketdesk_signaling/web; npx vercel --prod`.)
3. Set `CORS_ORIGINS` on the server to the Vercel URL.

## 3. Point agents at it
On each PC: `PocketDeskAgent.exe config --server https://<your-server> --web-url https://<your-vercel-site>` then restart. The QR now opens the Vercel app and tells it which server to pair with.

## Abuse / safety for a public service
- Set `REGISTER_KEY` on the server if you only want known users, or leave open and rely on rate limits (10 registrations/hour/IP).
- Run behind HTTPS only; set `TRUST_PROXY=1` only behind your own proxy.
- You become the operator of a remote-access rendezvous: publish a privacy policy, keep the server patched, and don't log SDP/frames (the code doesn't).
- Add per-user accounts / monitoring before inviting strangers (not included).

## Free tunnel (what we use for personal testing)
`tools\start_remote.ps1` — server + self-restarting serveo tunnel + agent on your own PC. The address changes unless you register the ssh key at console.serveo.net.
