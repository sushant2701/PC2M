"""Tk control window + always-visible remote-session indicator."""
import asyncio
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .agent import Agent, check_server_url


class AgentUI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title("PocketDesk Agent")
        self.root.geometry("520x760")
        self.agent = Agent(cfg, lambda k, d=None: self.q.put((k, d)))
        self.loop = asyncio.new_event_loop()
        self.banner = None
        self._build()

    def _build(self):
        r = self.root
        f = ttk.Frame(r, padding=12)
        f.pack(fill="both", expand=True)
        self.status = ttk.Label(f, text="Starting…", font=("Segoe UI", 11, "bold"))
        self.status.pack(anchor="w")
        self.server_lbl = ttk.Label(f, text="Server: " + (self.cfg["server_url"] or "(not set)"))
        self.server_lbl.pack(anchor="w", pady=(0, 8))
        self.pub_lbl = ttk.Label(f, text="Phone address: …")
        self.pub_lbl.pack(anchor="w")
        ttk.Button(f, text="Set server URL…", command=self.set_server).pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=8)
        ttk.Button(f, text="Pair a new phone (generate code)", command=self.pair).pack(anchor="w")
        self.code = tk.Entry(f, font=("Consolas", 13), state="readonly", readonlybackground="white", width=34)
        self.code.pack(anchor="w", pady=4)
        ttk.Label(f, text="Scan the QR with your phone camera (valid 5 minutes), or enter the code in the app.").pack(anchor="w")
        self.qr_lbl = ttk.Label(f)
        self.qr_lbl.pack(pady=4)
        self.link_txt = tk.Entry(f, state="readonly", readonlybackground="white", width=60)
        self.link_txt.pack(anchor="w")
        ttk.Separator(f).pack(fill="x", pady=8)
        ttk.Label(f, text="Paired phones").pack(anchor="w")
        self.lst = tk.Listbox(f, height=5)
        self.lst.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Revoke selected", command=self.revoke).pack(side="left")
        ttk.Button(row, text="Disconnect session", command=self.disconnect).pack(side="left", padx=6)
        self._refresh_devices()
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        r.after(150, self._poll)

    # --- actions ---
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

    def revoke(self):
        sel = self.lst.curselection()
        if not sel:
            return
        did = self._ids[sel[0]]
        if messagebox.askyesno("Revoke", "Revoke this phone? It will no longer be able to connect."):
            self._submit(self.agent.revoke_device(did))

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

    # --- event pump ---
    def _refresh_devices(self):
        self.lst.delete(0, "end")
        self._ids = []
        for did, d in self.cfg["devices"].items():
            self.lst.insert("end", f"{d['name']}  ({did})")
            self._ids.append(did)

    def _poll(self):
        try:
            from .main import current_public_url
            self.pub_lbl.config(text="Phone address: " + current_public_url(self.cfg))
        except Exception:
            pass
        try:
            while True:
                k, d = self.q.get_nowait()
                if k == "status":
                    self.status.config(text="● Online — waiting for phone" if d == "online" else "○ Offline — reconnecting…")
                elif k == "pairing_code":
                    self.code.config(state="normal")
                    self.code.delete(0, "end")
                    self.code.insert(0, d)
                    self.code.config(state="readonly")
                    self._show_qr(d)
                elif k in ("devices", "paired"):
                    self._refresh_devices()
                    if k == "paired":
                        messagebox.showinfo("Paired", f"Phone '{d['name']}' paired.")
                elif k == "session":
                    self._banner(d)
                elif k == "error":
                    messagebox.showerror("Error", d)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _show_qr(self, code):
        """QR of the phone link (web client + pairing code in the URL fragment)."""
        try:
            import qrcode
            from PIL import ImageTk
            from .main import pairing_link
            link = pairing_link(self.cfg, code)
            img = qrcode.make(link).resize((260, 260))
            self._qr_img = ImageTk.PhotoImage(img)
            self.qr_lbl.config(image=self._qr_img, text="")
            self.link_txt.config(state="normal")
            self.link_txt.delete(0, "end")
            self.link_txt.insert(0, link)
            self.link_txt.config(state="readonly")
        except Exception as e:  # noqa
            self.qr_lbl.config(text=f"QR unavailable: {e}")

    def _banner(self, d):
        if d["active"]:
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
        elif self.banner is not None:
            self.banner.destroy()
            self.banner = None

    def run(self):
        threading.Thread(target=self._loop_thread, daemon=True).start()
        self.root.mainloop()

    def _loop_thread(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.agent.run())
