import tkinter as tk
import threading
import time
import hashlib
import string
import requests
import pystray
from PIL import Image, ImageDraw
import webbrowser
import winreg

DEFAULT_CONFIG = {
    "api_url": "https://rwqk4blqg5wvdku6oaqiyqczzy.srv.us/create_channel",
    "api_key": ""
}


class LeagueDataFetcher:
    def __init__(self, base_url="https://127.0.0.1:2999/liveclientdata/allgamedata"):
        self.base_url = base_url

    def fetch(self):
        try:
            response = requests.get(self.base_url, verify=False, timeout=2)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def extract_match_info(self, data):
        """Normalize everything to avoid localization issues."""
        if not data:
            return None
        try:
            # Normalize game mode to uppercase ASCII
            game_mode = data.get("gameData", {}).get("gameMode", "UNKNOWN")
            if isinstance(game_mode, str):
                game_mode = game_mode.upper().strip()

            active_player_id = data.get("activePlayer", {}).get("riotId")
            if not active_player_id:
                return None

            active_team = None
            team_players = []
            for player in data.get("allPlayers", []):
                riot_id = player.get("riotId")
                if not riot_id:
                    continue

                # Normalize Riot IDs (handle Unicode safely)
                riot_id = str(riot_id).strip()

                team = player.get("team", "").upper().strip()
                if riot_id == active_player_id:
                    active_team = team
                if team == active_team:
                    team_players.append(riot_id)

            if not active_team or not team_players:
                return None

            return {
                "active_player_id": active_player_id,
                "team_name": active_team,
                "game_mode": game_mode,
                "team_players": team_players
            }
        except Exception:
            return None


class ChannelIdGenerator:
    def __init__(self):
        self.alphabet = string.ascii_uppercase + string.digits

    def generate(self, players, game_mode, team_name, detected_time=None):
        """Generate consistent 8-char channel ID from normalized data."""
        if detected_time is None:
            detected_time = int(time.time())

        start_bucket = detected_time // (60 * 10)  # round to 10-minute window
        players = sorted([str(p).strip() for p in players])
        raw = "|".join(players) + "|" + str(game_mode).upper() + "|" + str(team_name).upper() + "|" + str(start_bucket)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()  # ensure UTF-8 encoding
        num = int(digest, 16)
        code = ""
        for _ in range(8):
            code += self.alphabet[num % len(self.alphabet)]
            num //= len(self.alphabet)
        return code


class ConfigApp:
    def __init__(self, root):
        self.root = root
        self.root.title("League Voice Chat Client")
        self.root.configure(bg="#1a1a1e")

        self.config = self.load_config()

        self.label_font = ("Segoe UI", 12, "bold")
        self.entry_font = ("Segoe UI", 11, "bold")
        self.banner_font = ("Segoe UI", 11)

        # Banner
        banner_frame = tk.Frame(root, bg="#2a2a30", bd=2, relief="groove")
        banner_frame.pack(fill="x", padx=20, pady=(10, 10))

        instructions_text = "⚡ To use this app:\n1. Join the Discord server: "
        tk.Label(
            banner_frame,
            text=instructions_text,
            bg="#2a2a30",
            fg="white",
            font=self.banner_font,
            justify="left",
            anchor="w",
            padx=10,
            pady=5
        ).pack(anchor="w")

        discord_link = "https://discord.gg/N2fqBBM6DV"
        link_label = tk.Label(
            banner_frame,
            text=discord_link,
            bg="#2a2a30",
            fg="#00aaff",
            font=("Segoe UI", 11, "underline"),
            cursor="hand2",
            justify="left",
            anchor="w",
            padx=10
        )
        link_label.pack(anchor="w")
        link_label.bind("<Button-1>", lambda e: webbrowser.open(discord_link))

        rest_instructions = (
            "2. Go to the #tokens channel and type /token\n"
            "3. You will receive your API key in DMs.\n"
            "4. Paste it below and keep the app open.\n"
            "Let the magic happen! ✨"
        )
        tk.Label(
            banner_frame,
            text=rest_instructions,
            bg="#2a2a30",
            fg="white",
            font=self.banner_font,
            justify="left",
            anchor="w",
            padx=10,
            pady=5
        ).pack(fill="x")

        # Inputs
        frame = tk.Frame(root, bg="#1a1a1e")
        frame.pack(padx=20, pady=10, fill="both", expand=True)

        # API Key
        tk.Label(frame, text="API Key:", fg="white", bg="#1a1a1e", font=self.label_font).grid(
            row=0, column=0, sticky="e", padx=10, pady=10
        )
        self.api_key_var = tk.StringVar(value=self.config["api_key"])
        self.api_key_entry = tk.Entry(
            frame, textvariable=self.api_key_var, width=40,
            font=self.entry_font, fg="white", bg="#2a2a30", insertbackground="white"
        )
        self.api_key_entry.grid(row=0, column=1, pady=10, sticky="w")

        # API URL
        tk.Label(frame, text="API URL:", fg="white", bg="#1a1a1e", font=self.label_font).grid(
            row=1, column=0, sticky="e", padx=10, pady=10
        )
        self.api_url_var = tk.StringVar(value=self.config["api_url"])
        self.api_url_entry = tk.Entry(
            frame, textvariable=self.api_url_var, width=40,
            font=self.entry_font, fg="white", bg="#2a2a30", insertbackground="white"
        )
        self.api_url_entry.grid(row=1, column=1, pady=10, sticky="w")

        # Status label
        self.status_var = tk.StringVar(value="")
        tk.Label(frame, textvariable=self.status_var, fg="white", bg="#1a1a1e",
                 font=("Segoe UI", 10)).grid(row=2, column=0, columnspan=2, pady=5)

        # Minimize to tray button
        tk.Button(
            frame, text="🗗 Minimize to Tray", command=self.minimize_to_tray,
            font=self.label_font, fg="white", bg="#3a3a45",
            activebackground="#4a4a55", bd=0
        ).grid(row=3, column=1, pady=20, sticky="e", ipadx=10, ipady=5)

        # Handle closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Center the window
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.resizable(False, False)

        self.icon = None
        self.fetcher = LeagueDataFetcher()
        self.generator = ChannelIdGenerator()
        self.last_match_code = None
        self.polling_active = False

        threading.Thread(target=self.check_api_key_loop, daemon=True).start()

    # ---------- Registry Config ----------
    def load_config(self):
        config = DEFAULT_CONFIG.copy()
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\LeagueVoiceChat", 0, winreg.KEY_READ)
            config["api_url"], _ = winreg.QueryValueEx(key, "api_url")
            config["api_key"], _ = winreg.QueryValueEx(key, "api_key")
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            print("Failed to read config from registry:", e)
        return config

    def save_config(self):
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\LeagueVoiceChat")
            winreg.SetValueEx(key, "api_url", 0, winreg.REG_SZ, self.api_url_var.get())
            winreg.SetValueEx(key, "api_key", 0, winreg.REG_SZ, self.api_key_var.get())
            winreg.CloseKey(key)
        except Exception as e:
            print("Failed to save config to registry:", e)

    # ---------- API Key Checking ----------
    def check_api_key_loop(self):
        while True:
            key = self.api_key_var.get().strip()
            if not key:
                self.api_key_entry.config(bg="#2a2a30")
                self.status_var.set("")
                self.polling_active = False
            elif len(key) != 22:
                self.api_key_entry.config(bg="#aa3333")
                self.status_var.set("❌ Incorrect API Key")
                self.polling_active = False
            else:
                self.api_key_entry.config(bg="#2a2a30")
                self.status_var.set("✅ API Key valid. Waiting for match...")
                if not self.polling_active:
                    threading.Thread(target=self.league_polling_loop, daemon=True).start()
            time.sleep(3)

    # ---------- Match Polling ----------
    def league_polling_loop(self):
        self.polling_active = True
        api_url = self.api_url_var.get()
        api_key = self.api_key_var.get().strip()
        while self.polling_active:
            data = self.fetcher.fetch()
            match_info = self.fetcher.extract_match_info(data)
            if match_info:
                code = self.generator.generate(
                    match_info["team_players"],
                    match_info["game_mode"],
                    match_info["team_name"]
                )
                if code != self.last_match_code:
                    self.last_match_code = code
                    payload = {"channel_id": code}
                    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
                    try:
                        response = requests.post(api_url, json=payload, headers=headers, timeout=5)
                        if response.status_code == 200:
                            self.status_var.set(f"✅ Channel ID sent: {code}")
                            self.poll_for_match_end()
                        elif response.status_code == 403:
                            self.status_var.set("❌ Invalid API Key")
                        else:
                            self.status_var.set(f"❌ Server error {response.status_code}")
                    except Exception:
                        self.status_var.set("❌ Failed to reach server")
            time.sleep(10)

    def poll_for_match_end(self):
        while True:
            data = self.fetcher.fetch()
            match_info = self.fetcher.extract_match_info(data)
            if not match_info:
                self.status_var.set("⚡ Match ended. Waiting for next match...")
                self.last_match_code = None
                return
            time.sleep(20)

    # ---------- Tray ----------
    def minimize_to_tray(self):
        self.save_config()
        self.root.withdraw()
        image = Image.new("RGB", (64, 64), "#1a1a1e")
        d = ImageDraw.Draw(image)
        d.text((10, 20), "LC", fill="white")

        def on_quit(icon, item):
            icon.stop()
            self.root.destroy()

        def on_show(icon, item):
            icon.stop()
            self.root.deiconify()

        self.icon = pystray.Icon("league_voice_chat", image, "League Voice Chat",
                                 menu=pystray.Menu(
                                     pystray.MenuItem("Show", on_show),
                                     pystray.MenuItem("Exit", on_quit)
                                 ))
        threading.Thread(target=self.icon.run, daemon=True).start()

    # ---------- Closing ----------
    def on_close(self):
        self.save_config()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ConfigApp(root)
    root.mainloop()
