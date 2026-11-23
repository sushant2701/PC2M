"""Tk control window + always-visible remote-session indicator."""
import asyncio
import queue
import time
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, simpledialog, ttk

from .agent import Agent, check_server_url

BG, CARD, ACCENT, OK, BAD, MUT = "#f5f1ea", "#ffffff", "#3d7a5a", "#3d9a5f", "#c4533a", "#6b7468"
TEXT, SAND = "#2b2f2a", "#ece6db"


class AgentUI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title("PocketDesk Agent")
        self.root.geometry("560x820")
        self.root.configure(bg=BG)
        self.agent = Agent(cfg, lambda k, d=None: self.q.put((k, d)))
        self.loop = asyncio.new_event_loop()
        self.banner = None
        self._link = ""
        self._code, self._code_t = None, 0.0
        self._build()

    # ---------- layout ----------
    def _card(self, parent, title):
        f = tk.Frame(parent, bg=CARD, padx=14, pady=12)
        f.pack(fill="x", padx=14, pady=7)
        tk.Label(f, text=title, bg=CARD, fg=MUT, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        return f

    def _btn(self, parent, text, cmd, accent=True, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=ACCENT if accent else SAND, fg="white" if accent else TEXT,
                         relief="flat", font=("Segoe UI", 11, "bold"), padx=16, pady=9, cursor="hand2",
                         activebackground="#2f6247" if accent else "#e0d8c9", activeforeground="white" if accent else TEXT, **kw)

    def _build(self):
        r = self.root
        head = tk.Frame(r, bg=BG)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="🖥  PocketDesk", bg=BG, fg=TEXT, font=("Segoe UI", 18, "bold")).pack(side="left")
        self.status = tk.Label(head, text="● Starting…", bg=BG, fg=MUT, font=("Segoe UI", 11, "bold"))
        self.status.pack(side="right")

        c = self._card(r, "REMOTE SESSION")
        self.sess = tk.Label(c, text="No phone connected", bg=CARD, fg=TEXT, font=("Segoe UI", 13))
        self.sess.pack(anchor="w", pady=(4, 6))
        self.disc_btn = self._btn(c, "Disconnect now", self.disconnect, accent=False)
        self.disc_btn.pack(anchor="w")

        c = self._card(r, "CONNECT YOUR PHONE")
        self._btn(c, "📱  Pair a new phone", self.pair).pack(anchor="w", pady=(6, 8))
        self.qr_lbl = tk.Label(c, bg=CARD, fg=MUT, text="Click “Pair a new phone” — a QR code appears here.\nScan it with your phone camera. Valid for 5 minutes.", justify="left")
        self.qr_lbl.pack(pady=4)
        self.code_lbl = tk.Label(c, text="", bg=CARD, fg=TEXT, font=("Consolas", 13, "bold"))
        self.code_lbl.pack()
        row = tk.Frame(c, bg=CARD)
        row.pack(pady=6)
        self._btn(row, "Copy link", self.copy_link, accent=False).pack(side="left", padx=4)
        self._btn(row, "Open on this PC", self.open_link, accent=False).pack(side="left", padx=4)

        c = self._card(r, "PAIRED PHONES")
        self.lst = tk.Listbox(c, height=4, bg="#faf8f3", fg=TEXT, relief="flat", highlightthickness=1, highlightbackground="#e3dccd",
                              font=("Segoe UI", 10), selectbackground="#e3efe8", selectforeground=TEXT)
        self.lst.pack(fill="x", pady=6)
        self._btn(c, "Revoke selected phone", self.revoke, accent=False).pack(anchor="w")

        c = self._card(r, "ADDRESS")
        self.pub_lbl = tk.Label(c, text="Phone address: …", bg=CARD, fg=TEXT, wraplength=500, justify="left")
        self.pub_lbl.pack(anchor="w")
        self.server_lbl = tk.Label(c, text="Server: " + (self.cfg["server_url"] or "(not set)"), bg=CARD, fg=MUT, wraplength=500, justify="left")
        self.server_lbl.pack(anchor="w", pady=(2, 6))
        self._btn(c, "Change server…", self.set_server, accent=False).pack(anchor="w")
        tk.Label(r, text="While a phone is connected a red banner stays on top of your screen.", bg=BG, fg=MUT).pack(pady=8)
        self._refresh_devices()
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        r.after(150, self._poll)

    # ---------- actions ----------
    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def set_server(self):
        url = simpledialog.askstring("Server", "Signaling server URL (https://…):", initialvalue=self.cfg["server_url"], parent=self.root)
        if url:
            try:
                check_server_url(url.strip())
            except ValueError as e:
                messagebox.showerror("Invalid", str(e))
                return
            self.cfg["server_url"] = url.strip().rstrip("/")
            self.cfg["agent_id"] = self.cfg["agent_secret"] = ""
            self.cfg.save()
            self.server_lbl.config(text="Server: " + self.cfg["server_url"])
            messagebox.showinfo("Saved", "Restart the agent to connect to the new server.")

    def pair(self):
        if not self.cfg["server_url"]:
            return self.set_server()

        def done(fut):
            if fut.exception():
                self.q.put(("error", str(fut.exception())))
        self._submit(self.agent.start_pairing()).add_done_callback(done)

    def copy_link(self):
        if self._link:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._link)

    def open_link(self):
        if self._link:
            webbrowser.open(self._link)

    def revoke(self):
        sel = self.lst.curselection()
        if not sel:
            return
        if messagebox.askyesno("Revoke", "Revoke this phone? It will no longer be able to connect."):
            self._submit(self.agent.revoke_device(self._ids[sel[0]]))

    def disconnect(self):
        self._submit(self.agent.end_session("disconnected on PC"))

    def on_close(self):
        if messagebox.askyesno("Quit", "Quit PocketDesk Agent? Remote access will stop."):
            fut = self._submit(self.agent.stop())
            try:
                fut.result(5)
            except Exception:
                pass
            self.root.destroy()

    # ---------- event pump ----------
    def _refresh_devices(self):
        self.lst.delete(0, "end")
        self._ids = []
        for did, d in self.cfg["devices"].items():
            self.lst.insert("end", f"  {d['name']}   ({did})")
            self._ids.append(did)

    def _show_qr(self, code, keep_clock=False):
        try:
            import qrcode
            from PIL import ImageTk
            from .main import pairing_link
            self._code = code
            if not keep_clock:
                self._code_t = time.time()
            self._link = pairing_link(self.cfg, code)
            img = qrcode.make(self._link).resize((250, 250))
            self._qr_img = ImageTk.PhotoImage(img)
            self.qr_lbl.config(image=self._qr_img, text="")
            self.code_lbl.config(text=code)
        except Exception as e:  # noqa
            self.qr_lbl.config(text=f"QR unavailable: {e}")

    def _poll(self):
        try:
            from .main import current_public_url, pairing_link
            pu = current_public_url(self.cfg)
            self.pub_lbl.config(text="Phone address: " + ("starting… (a few seconds)" if pu.endswith(".invalid") else pu))
            if self._code:  # keep the QR in step with the tunnel address; retire it when the code expires
                if time.time() - self._code_t > 295:
                    self._code = None
                    self._link = ""
                    self.qr_lbl.config(image="", text="That code expired.\nClick “Pair a new phone” for a fresh QR.")
                    self.code_lbl.config(text="")
                elif pairing_link(self.cfg, self._code) != self._link:
                    self._show_qr(self._code, keep_clock=True)
        except Exception:
            pass
        try:
            while True:
                k, d = self.q.get_nowait()
                if k == "status":
                    self.status.config(text="● Online" if d == "online" else "○ Offline — reconnecting…", fg=OK if d == "online" else BAD)
                elif k == "pairing_code":
                    self._show_qr(d)
                elif k in ("devices", "paired"):
                    self._refresh_devices()
                    if k == "paired":
                        self._code = None
                        self.qr_lbl.config(image="", text=f"✅ Paired with “{d['name']}”.")
                        self.code_lbl.config(text="")
                        messagebox.showinfo("Paired", f"Phone '{d['name']}' paired.")
                elif k == "session":
                    self._banner(d)
                elif k == "error":
                    messagebox.showerror("Error", d)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _banner(self, d):
        if d["active"]:
            self.sess.config(text=f"● {d['device']} is connected", fg=OK)
            if self.banner is None:
                b = tk.Toplevel(self.root)
                b.overrideredirect(True)
                b.attributes("-topmost", True)
                b.configure(bg="#c62828")
                self.banner_lbl = tk.Label(b, fg="white", bg="#c62828", font=("Segoe UI", 10, "bold"), padx=10, pady=4)
                self.banner_lbl.pack(side="left")
                tk.Button(b, text="Disconnect", command=self.disconnect, bg="white").pack(side="left", padx=6, pady=3)
                sw = self.root.winfo_screenwidth()
                b.geometry(f"+{sw // 2 - 190}+0")
                self.banner = b
            self.banner_lbl.config(text=f"● REMOTE SESSION ACTIVE — {d['device']}")
            self.banner.lift()
        else:
            self.sess.config(text="No phone connected", fg=TEXT)
            if self.banner is not None:
                self.banner.destroy()
                self.banner = None

    def run(self):
        threading.Thread(target=self._loop_thread, daemon=True).start()
        self.root.mainloop()

    def _loop_thread(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.agent.run())
