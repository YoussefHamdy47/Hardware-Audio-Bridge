import os
import sys
import time
import logging
import threading
import serial
import spotipy
import comtypes
from spotipy.oauth2 import SpotifyOAuth
import tkinter as tk
import customtkinter as ctk
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
from typing import Optional
import pystray
from PIL import Image, ImageDraw, ImageOps, ImageTk

# ==========================================
# CONFIGURATION - BUNNYS MIXDESK
# ==========================================
ARDUINO_PORT = 'COM3'
BAUD_RATE = 9600

SPOTIPY_CLIENT_ID = 'YOUR_CLIENT_ID_HERE'
SPOTIPY_CLIENT_SECRET = 'YOUR_CLIENT_SECRET_HERE'
SPOTIPY_REDIRECT_URI = 'http://localhost:8888/callback'

ACCENT_COLOR = "#3ddc84"
BG_MAIN = "#0d0d12"
BG_CARD = "#15151c"
DANGER_COLOR = "#ff4a4a"

# ==========================================
# LOGGING & TELEMETRY SYSTEM
# ==========================================
log_formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
file_handler = logging.FileHandler('bunnys_mixdesk.log')
file_handler.setFormatter(log_formatter)
logger = logging.getLogger('MixDesk')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

tel_packets = 0
tel_start_time = time.time()
tel_last_signal = "N/A"

def ui_log(message: str, is_serial: bool = False) -> None:
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    
    if sys.stdout is not None:
        sys.stdout.write(entry)
        sys.stdout.flush()
    
    if not is_serial:
        logger.info(message)
        if 'sys_log_box' in globals() and sys_log_box is not None:
            sys_log_box.configure(state="normal")
            sys_log_box.insert("end", entry)
            sys_log_box.see("end")
            sys_log_box.configure(state="disabled")
    else:
        if 'serial_log_box' in globals() and serial_log_box is not None:
            serial_log_box.configure(state="normal")
            serial_log_box.insert("end", f"→ {message}\n")
            serial_log_box.see("end")
            serial_log_box.configure(state="disabled")

# ==========================================
# DYNAMIC GRAPHICS & LOGO FILTERING
# ==========================================
def get_asset_path(filename: str) -> str:
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, filename)

def load_and_filter_logo(size=120):
    filename = get_asset_path("logo.png")
    if not os.path.exists(filename):
        filename = get_asset_path("logo.jpg")
    
    try:
        if os.path.exists(filename):
            img = Image.open(filename).convert("RGBA")
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            green_layer = Image.new("RGBA", img.size, ACCENT_COLOR)
            mask = img.convert("L")
            mask = ImageOps.invert(mask)
            return Image.composite(green_layer, Image.new("RGBA", img.size, (0,0,0,0)), mask)
    except Exception as e:
        ui_log(f"Custom logo failed to process: {e}")

    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((10, 10, size-10, size-10), radius=20, fill=BG_CARD, outline=ACCENT_COLOR, width=3)
    draw.line((40, 30, 40, size-30), fill=ACCENT_COLOR, width=6)
    draw.arc((40, 30, 80, 70), start=-90, end=90, fill=ACCENT_COLOR, width=6)
    draw.arc((40, 70, 85, 110), start=-90, end=90, fill=ACCENT_COLOR, width=6)
    return img

def create_tray_icon(vol_pct):
    img = load_and_filter_logo(64)
    draw = ImageDraw.Draw(img)
    fill_h = int(52 * (vol_pct / 100))
    draw.rectangle((4, 60 - fill_h, 8, 60), fill="#ffffff")
    return img

# ==========================================
# OSD ENGINE (RESTORED)
# ==========================================
OSD_W, OSD_H = 260, 70
BAR_W, BAR_H = 200, 3
BAR_X, BAR_Y = 30, 48
osd_window = None
osd_canvas = None
osd_hide_job = None

def _rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kw) -> None:
    canvas.create_arc(x1, y1, x1+2*r, y1+2*r, start=90, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y1, x2, y1+2*r, start=0, extent=90, style="pieslice", **kw)
    canvas.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, style="pieslice", **kw)
    canvas.create_rectangle(x1+r, y1, x2-r, y2, **kw)
    canvas.create_rectangle(x1, y1+r, x2, y2-r, **kw)

def build_osd() -> None:
    global osd_window, osd_canvas
    osd_window = ctk.CTkToplevel(app)
    osd_window.overrideredirect(True)
    osd_window.attributes("-topmost", True)
    osd_window.attributes("-alpha", 0.0)
    osd_window.configure(fg_color="#000000")
    osd_window.withdraw()

    osd_canvas = tk.Canvas(osd_window, width=OSD_W, height=OSD_H, bg="#000000", highlightthickness=0)
    osd_canvas.pack()

    _rounded_rect(osd_canvas, 0, 0, OSD_W, OSD_H, 18, fill="#1c1c1c", outline="")
    osd_canvas.create_text(28, 24, text="🔊", font=("Segoe UI Emoji", 13), fill="#ffffff", tags="icon")
    osd_canvas.create_text(OSD_W-28, 24, text="0%", font=("Segoe UI", 14, "bold"), fill="#ffffff", anchor="e", tags="pct")
    osd_canvas.create_rectangle(BAR_X, BAR_Y, BAR_X+BAR_W, BAR_Y+BAR_H, fill="#333333", outline="", tags="track")
    osd_canvas.create_rectangle(BAR_X, BAR_Y, BAR_X, BAR_Y+BAR_H, fill="#ffffff", outline="", tags="fill")

def show_osd(vol_pct: int) -> None:
    global osd_hide_job
    if osd_enabled_var is not None and not osd_enabled_var.get(): return
    if osd_window is None or osd_canvas is None: return

    icon = "🔇" if vol_pct == 0 else "🔈" if vol_pct < 33 else "🔉" if vol_pct < 66 else "🔊"
    fill_w = max(1, int(BAR_W * vol_pct / 100))

    osd_canvas.itemconfig("icon", text=icon)
    osd_canvas.itemconfig("pct",  text=f"{vol_pct}%")
    osd_canvas.coords("fill", BAR_X, BAR_Y, BAR_X + fill_w, BAR_Y + BAR_H)

    screen_w = app.winfo_screenwidth()
    screen_h = app.winfo_screenheight()
    x = (screen_w - OSD_W) // 2
    y = screen_h - OSD_H - 72
    osd_window.geometry(f"{OSD_W}x{OSD_H}+{x}+{y}")
    osd_window.deiconify()
    osd_window.attributes("-alpha", 0.93)

    if osd_hide_job is not None: app.after_cancel(osd_hide_job)
    osd_hide_job = app.after(1800, fade_osd)

def fade_osd(step: float = 0.93) -> None:
    global osd_hide_job
    if osd_window is None: return
    step = round(step - 0.08, 2)
    if step <= 0:
        osd_window.withdraw()
        osd_window.attributes("-alpha", 0.0)
        return
    osd_window.attributes("-alpha", step)
    osd_hide_job = app.after(30, lambda: fade_osd(step))

# ==========================================
# STATE VARIABLES
# ==========================================
ser = None
arduino_connected = False
serial_buffer = ""
device = None
volume_interface = None
last_known_vol = 50
last_device_check = time.time()
is_muted = False
sp = None
spotify_active = False

# ==========================================
# HARDWARE & AUDIO ENGINES
# ==========================================
def init_audio():
    global device, volume_interface, last_known_vol, is_muted
    try:
        devices = AudioUtilities.GetSpeakers()
        if devices is not None:
            device = devices
            volume_interface = device.EndpointVolume
            if volume_interface is not None:
                last_known_vol = round(volume_interface.GetMasterVolumeLevelScalar() * 100)
                is_muted = volume_interface.GetMute() == 1
            ui_log(f"Audio hooked: {device.FriendlyName}")
        else:
            ui_log("Audio Init Error: No active speakers found.")
    except Exception as e:
        ui_log(f"Audio Init Error: {e}")

def attempt_serial_connection():
    global ser, arduino_connected
    try:
        if ser is None or not ser.is_open:
            ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=0)
            arduino_connected = True
            ui_log(f"Hardware Bridge connected on {ARDUINO_PORT}")
            if conn_status_label is not None:
                conn_status_label.configure(text="● HARDWARE CONNECTED", text_color=ACCENT_COLOR)
            if tel_state_val is not None:
                tel_state_val.configure(text="ONLINE", text_color=ACCENT_COLOR)
    except Exception as e:
        arduino_connected = False
        if conn_status_label is not None:
            conn_status_label.configure(text="● HARDWARE OFFLINE", text_color=DANGER_COLOR)
        if tel_state_val is not None:
            tel_state_val.configure(text="OFFLINE / SEARCHING", text_color=DANGER_COLOR)

def init_spotify():
    global sp, spotify_active
    if SPOTIPY_CLIENT_ID == 'YOUR_CLIENT_ID_HERE':
        ui_log("Spotify module standing by. Awaiting API configuration.")
        spotify_active = False
        if spot_status_label is not None: spot_status_label.configure(text="● SPOTIFY UNAVAILABLE", text_color="gray")
        if spot_track_label is not None: spot_track_label.configure(text="Awaiting API Configuration", text_color="gray")
        if btn_play is not None: btn_play.configure(state="disabled", fg_color=BG_MAIN, text_color="gray")
        return

# ==========================================
# BACKGROUND DAEMONS
# ==========================================
def hardware_daemon():
    global last_known_vol, serial_buffer, arduino_connected, tel_packets, tel_last_signal, last_device_check, device, volume_interface
    
    # REQUIRED: Initialize Windows COM threading for background audio control
    comtypes.CoInitialize()
    
    while True:
        try:
            # AUTO-SWITCH LOGIC: Checks for Bluetooth connections/disconnections
            if time.time() - last_device_check > 2.0:
                last_device_check = time.time()
                try:
                    current_device = AudioUtilities.GetSpeakers()
                    if current_device is not None and device is not None and current_device.id != device.id:
                        device = current_device
                        volume_interface = device.EndpointVolume
                        if volume_interface is not None:
                            last_known_vol = round(volume_interface.GetMasterVolumeLevelScalar() * 100)
                        ui_log(f"Audio Switched: {device.FriendlyName}")
                        if dev_combo is not None: dev_combo.set("Bluetooth / Default Audio")
                except Exception:
                    pass

            if not arduino_connected:
                attempt_serial_connection()
                time.sleep(3)
                continue

            if ser is not None and ser.in_waiting > 0:
                serial_buffer += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                while '\n' in serial_buffer:
                    line, serial_buffer = serial_buffer.split('\n', 1)
                    raw = line.strip()
                    
                    tel_packets += 1
                    tel_last_signal = raw
                    ui_log(raw, is_serial=True)

                    if raw.startswith('V') and raw[1:].isdigit():
                        vol_pct = int(raw[1:])
                        if not knob_lock_var.get() and volume_interface is not None:
                            volume_interface.SetMasterVolumeLevelScalar(vol_pct / 100.0, None)
                            last_known_vol = vol_pct
                            update_ui_volume(vol_pct)
                            show_osd(vol_pct) # RESTORED: Trigger OSD on knob turn

            if volume_interface is not None:
                pc_vol = round(volume_interface.GetMasterVolumeLevelScalar() * 100)
                if abs(pc_vol - last_known_vol) > 1:
                    last_known_vol = pc_vol
                    update_ui_volume(pc_vol)
                    if ser is not None:
                        tx_cmd = f"V{pc_vol}"
                        ser.write(f"{tx_cmd}\n".encode('utf-8'))
                        tel_packets += 1
                        tel_last_signal = tx_cmd
                        ui_log(f"Host Synced: {tx_cmd}", is_serial=True)
                
            time.sleep(0.05)

        except serial.SerialException:
            arduino_connected = False
            ui_log("Hardware disconnected unexpectedly.")
            if conn_status_label is not None: conn_status_label.configure(text="● HARDWARE OFFLINE", text_color=DANGER_COLOR)
            time.sleep(2)
        except Exception as e:
            time.sleep(1)

def telemetry_updater():
    while True:
        if 'tel_pkts_val' in globals() and tel_pkts_val is not None:
            tel_pkts_val.configure(text=f"{tel_packets:,}")
        if 'tel_sig_val' in globals() and tel_sig_val is not None:
            tel_sig_val.configure(text=tel_last_signal)
        if 'tel_uptime_val' in globals() and tel_uptime_val is not None:
            uptime = int(time.time() - tel_start_time)
            mins, secs = divmod(uptime, 60)
            hours, mins = divmod(mins, 60)
            tel_uptime_val.configure(text=f"{hours:02d}:{mins:02d}:{secs:02d}")
        time.sleep(0.5)

# ==========================================
# UI ACTIONS
# ==========================================
def update_ui_volume(vol):
    if vol_bar is not None: vol_bar.set(vol / 100.0)
    if vol_lbl is not None: vol_lbl.configure(text=f"{vol}%")
    if tray_icon_obj is not None: tray_icon_obj.title = f"MixDesk: {vol}%"

def toggle_mute():
    global is_muted
    if volume_interface is not None:
        is_muted = not is_muted
        volume_interface.SetMute(1 if is_muted else 0, None)
        if mute_btn is not None:
            mute_btn.configure(text="UNMUTE" if is_muted else "MUTE AUDIO", fg_color=DANGER_COLOR if is_muted else BG_CARD)
        ui_log("System Audio Muted" if is_muted else "System Audio Unmuted")

# ==========================================
# SYSTEM TRAY
# ==========================================
tray_icon_obj = None

def restore_window(icon, item):
    icon.stop()
    app.after(0, app.deiconify)

def quit_app(icon, item):
    icon.stop()
    if ser is not None and ser.is_open: ser.close()
    os._exit(0)

def hide_to_tray():
    app.withdraw()
    menu = pystray.Menu(pystray.MenuItem('Show MixDesk', restore_window), pystray.MenuItem('Force Quit', quit_app))
    global tray_icon_obj
    tray_icon_obj = pystray.Icon("Bunnys_MixDesk", create_tray_icon(last_known_vol), f"MixDesk: {last_known_vol}%", menu)
    threading.Thread(target=tray_icon_obj.run, daemon=True).start()

def on_closing():
    dialog = ctk.CTkToplevel(app)
    dialog.geometry("380x180")
    dialog.title("MixDesk Daemon")
    dialog.attributes("-topmost", True)
    dialog.configure(fg_color=BG_MAIN)
    dialog.update_idletasks()
    dialog.geometry(f"+{app.winfo_x() + 160}+{app.winfo_y() + 100}")

    ctk.CTkLabel(dialog, text="Keep Hardware Bridge Active?", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 5))
    ctk.CTkLabel(dialog, text="Minimize to system tray to keep syncing.", text_color="gray").pack(pady=(0, 20))

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(fill="x", padx=20)
    ctk.CTkButton(btn_frame, text="Minimize to Tray", command=lambda: [dialog.destroy(), hide_to_tray()], corner_radius=8).pack(side="left", padx=5)
    ctk.CTkButton(btn_frame, text="Quit Completely", command=lambda: [dialog.destroy(), os._exit(0)], fg_color=DANGER_COLOR, hover_color="#9e2f2f", corner_radius=8).pack(side="right", padx=5)

# ==========================================
# BUILD UI
# ==========================================
ctk.set_appearance_mode("dark")
app = ctk.CTk()
app.title("Bunnys MixDesk v1.2")
app.geometry("820x540")
app.configure(fg_color=BG_MAIN)
app.protocol("WM_DELETE_WINDOW", on_closing)

try:
    icon_image = load_and_filter_logo(256)
    tk_icon = ImageTk.PhotoImage(icon_image) 
    app.iconphoto(True, tk_icon) # type: ignore
except Exception as e:
    ui_log(f"Icon loading bypassed: {e}")

# --- SIDEBAR ---
sidebar = ctk.CTkFrame(app, fg_color=BG_CARD, width=180, corner_radius=0)
sidebar.pack(side="left", fill="y")
sidebar.pack_propagate(False)

processed_logo = load_and_filter_logo(110)
logo_img = ctk.CTkImage(light_image=processed_logo, dark_image=processed_logo, size=(110, 110))
ctk.CTkLabel(sidebar, image=logo_img, text="").pack(pady=(25, 5))
ctk.CTkLabel(sidebar, text="MIXDESK", font=ctk.CTkFont(size=20, weight="bold", slant="italic"), text_color=ACCENT_COLOR).pack(pady=(0, 20))

def show_tab(tab_name):
    for f in [home_tab, spot_tab, serial_tab, log_tab]: f.pack_forget()
    if tab_name == "home": home_tab.pack(fill="both", expand=True)
    elif tab_name == "spot": spot_tab.pack(fill="both", expand=True)
    elif tab_name == "serial": serial_tab.pack(fill="both", expand=True)
    elif tab_name == "log": log_tab.pack(fill="both", expand=True)

nav_kwargs = {"fg_color":"transparent", "text_color":"#fff", "hover_color":"#2a2a35", "anchor":"w", "corner_radius":8, "font":ctk.CTkFont(size=13, weight="bold")}
ctk.CTkButton(sidebar, text="  🎧  Master Control", command=lambda: show_tab("home"), **nav_kwargs).pack(fill="x", padx=10, pady=5)
ctk.CTkButton(sidebar, text="  🎵  Spotify Hub", command=lambda: show_tab("spot"), **nav_kwargs).pack(fill="x", padx=10, pady=5)
ctk.CTkButton(sidebar, text="  🔌  Hardware Data", command=lambda: show_tab("serial"), **nav_kwargs).pack(fill="x", padx=10, pady=5)
ctk.CTkButton(sidebar, text="  📜  System Logs", command=lambda: show_tab("log"), **nav_kwargs).pack(fill="x", padx=10, pady=5)

content = ctk.CTkFrame(app, fg_color="transparent")
content.pack(side="left", fill="both", expand=True)

# --- TAB: HOME ---
home_tab = ctk.CTkFrame(content, fg_color="transparent")
top_bar = ctk.CTkFrame(home_tab, fg_color="transparent")
top_bar.pack(fill="x", padx=30, pady=(30, 10))
conn_status_label = ctk.CTkLabel(top_bar, text="● INIT...", font=ctk.CTkFont(size=12, weight="bold"), text_color="gray")
conn_status_label.pack(side="left")
spot_status_label = ctk.CTkLabel(top_bar, text="● SPOTIFY OFFLINE", font=ctk.CTkFont(size=12, weight="bold"), text_color="gray")
spot_status_label.pack(side="right")

ctk.CTkLabel(home_tab, text="Master Volume", font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_COLOR).pack(anchor="w", padx=30)
vol_container = ctk.CTkFrame(home_tab, fg_color=BG_CARD, corner_radius=15)
vol_container.pack(fill="x", padx=30, pady=(5, 20), ipady=15)
vol_lbl = ctk.CTkLabel(vol_container, text="--%", font=ctk.CTkFont(size=48, weight="bold"))
vol_lbl.pack(side="left", padx=25)
vol_bar = ctk.CTkProgressBar(vol_container, width=340, height=12, progress_color=ACCENT_COLOR)
vol_bar.pack(side="left", padx=20)
vol_bar.set(0)

actions_frame = ctk.CTkFrame(home_tab, fg_color="transparent")
actions_frame.pack(fill="x", padx=30, pady=10)
ctk.CTkLabel(actions_frame, text="Output Device Target:", font=ctk.CTkFont(weight="bold")).pack(side="left")
dev_combo = ctk.CTkComboBox(actions_frame, values=["Windows Default Audio"], width=200)
dev_combo.pack(side="left", padx=10)
mute_btn = ctk.CTkButton(actions_frame, text="MUTE AUDIO", command=toggle_mute, fg_color=BG_CARD, hover_color=DANGER_COLOR)
mute_btn.pack(side="right")

# RESTORED: Visual OSD switch added back into the hardware card
hw_card = ctk.CTkFrame(home_tab, fg_color=BG_CARD, corner_radius=15)
hw_card.pack(fill="x", padx=30, pady=20, ipady=15)

knob_lock_var = ctk.BooleanVar(value=False)
ctk.CTkSwitch(hw_card, text="Lock Physical Knob", variable=knob_lock_var, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=25)

osd_enabled_var = ctk.BooleanVar(value=True)
ctk.CTkSwitch(hw_card, text="Visual OSD", variable=osd_enabled_var, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=20)

led_var = ctk.BooleanVar(value=True)
ctk.CTkSwitch(hw_card, text="Arduino LEDs", variable=led_var, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=20)

# --- TAB: SPOTIFY ---
spot_tab = ctk.CTkFrame(content, fg_color="transparent")
ctk.CTkLabel(spot_tab, text="Spotify Integration", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=30, pady=30)
spot_card = ctk.CTkFrame(spot_tab, fg_color=BG_CARD, corner_radius=15)
spot_card.pack(fill="both", expand=True, padx=30, pady=(0, 30))
ctk.CTkLabel(spot_card, text="NOW PLAYING", font=ctk.CTkFont(size=12, weight="bold"), text_color=ACCENT_COLOR).pack(pady=(40, 5))
spot_track_label = ctk.CTkLabel(spot_card, text="Checking session...", font=ctk.CTkFont(size=20, weight="bold"))
spot_track_label.pack(pady=(0, 40))
sp_ctrls = ctk.CTkFrame(spot_card, fg_color="transparent")
sp_ctrls.pack()
btn_play = ctk.CTkButton(sp_ctrls, text="⏯ Play/Pause", width=120)
btn_play.pack(side="left", padx=10)

# --- TAB: SERIAL MONITOR & DASHBOARD ---
serial_tab = ctk.CTkFrame(content, fg_color="transparent")
ctk.CTkLabel(serial_tab, text="Hardware Telemetry", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=30, pady=(30, 10))
dash_frame = ctk.CTkFrame(serial_tab, fg_color="transparent")
dash_frame.pack(fill="x", padx=30, pady=(0, 15))

def make_stat_box(parent, title, default_val, text_col="#ffffff"):
    box = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
    box.pack(side="left", fill="x", expand=True, padx=5)
    ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color="gray").pack(pady=(10, 0))
    val_lbl = ctk.CTkLabel(box, text=default_val, font=ctk.CTkFont(size=18, weight="bold"), text_color=text_col)
    val_lbl.pack(pady=(0, 10))
    return val_lbl

tel_state_val = make_stat_box(dash_frame, "BRIDGE STATE", "CONNECTING...", ACCENT_COLOR)
tel_sig_val = make_stat_box(dash_frame, "LAST SIGNAL", "N/A")
tel_pkts_val = make_stat_box(dash_frame, "PACKETS (I/O)", "0")
tel_uptime_val = make_stat_box(dash_frame, "UPTIME", "00:00:00")
serial_log_box = ctk.CTkTextbox(serial_tab, state="disabled", fg_color=BG_CARD, text_color="#aaaaaa", font=ctk.CTkFont(family="Consolas", size=12))
serial_log_box.pack(fill="both", expand=True, padx=35, pady=(0, 30))

# --- TAB: SYSTEM LOGS ---
log_tab = ctk.CTkFrame(content, fg_color="transparent")
ctk.CTkLabel(log_tab, text="Application Events", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=30, pady=(30, 10))
sys_log_box = ctk.CTkTextbox(log_tab, state="disabled", fg_color=BG_CARD, text_color=ACCENT_COLOR, font=ctk.CTkFont(family="Consolas", size=12))
sys_log_box.pack(fill="both", expand=True, padx=30, pady=(0, 30))

# ==========================================
# BOOT SEQUENCE
# ==========================================
build_osd()
init_audio()
init_spotify()
show_tab("home")
ui_log("Bunnys MixDesk Initialized.")

threading.Thread(target=hardware_daemon, daemon=True).start()
threading.Thread(target=telemetry_updater, daemon=True).start()

app.mainloop()