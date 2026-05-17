import serial
import time
import tkinter as tk
from tkinter import scrolledtext
from pycaw.pycaw import AudioUtilities
from typing import Optional

# --- CONFIGURATION ---
arduino_port = 'COM3'
baud_rate = 9600

# --- HARDWARE CONNECTION ---
try:
    ser = serial.Serial(arduino_port, baud_rate, timeout=0)
except Exception as e:
    print(f"Failed to connect to {arduino_port}.")
    exit()

# --- AUDIO SETUP ---
device = AudioUtilities.GetSpeakers()
if device is None:
    raise Exception("No active speakers found!")

volume = device.EndpointVolume
last_known_vol = round(volume.GetMasterVolumeLevelScalar() * 100)
last_knob_turn_time = 0
last_device_check = time.time()
serial_buffer = ""

# --- GUI REFERENCES ---
log_box:      Optional[scrolledtext.ScrolledText] = None
led_var:      Optional[tk.BooleanVar]             = None
knob_lock_var: Optional[tk.BooleanVar]            = None
status_label: Optional[tk.Label]                  = None
osd_window:   Optional[tk.Toplevel]               = None
osd_canvas:   Optional[tk.Canvas]                 = None
osd_hide_job: Optional[str]                       = None

GRAPH_POINTS = 100
vol_history = [last_known_vol] * GRAPH_POINTS
graph_canvas: Optional[tk.Canvas] = None

# --- LOGGING ---
def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}\n"
    print(entry, end="")
    if log_box is not None:
        log_box.config(state=tk.NORMAL)
        log_box.insert(tk.END, entry)
        log_box.see(tk.END)
        log_box.config(state=tk.DISABLED)

# --- OSD ---
OSD_W = 260
OSD_H = 70
BAR_W = 200
BAR_H = 3
BAR_X = 30
BAR_Y = 48

def _rounded_rect(canvas: tk.Canvas, x1: int, y1: int,
                  x2: int, y2: int, r: int, **kw) -> None:
    canvas.create_arc(x1,     y1,     x1+2*r, y1+2*r, start=90,  extent=90, style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y1,     x2,     y1+2*r, start=0,   extent=90, style="pieslice", **kw)
    canvas.create_arc(x1,     y2-2*r, x1+2*r, y2,     start=180, extent=90, style="pieslice", **kw)
    canvas.create_arc(x2-2*r, y2-2*r, x2,     y2,     start=270, extent=90, style="pieslice", **kw)
    canvas.create_rectangle(x1+r, y1,   x2-r, y2,   **kw)
    canvas.create_rectangle(x1,   y1+r, x2,   y2-r, **kw)

def build_osd() -> None:
    global osd_window, osd_canvas
    osd_window = tk.Toplevel(root)
    osd_window.overrideredirect(True)
    osd_window.attributes("-topmost", True)
    osd_window.attributes("-alpha", 0.0)
    osd_window.configure(bg="#0d0d0d")
    osd_window.withdraw()

    osd_canvas = tk.Canvas(osd_window, width=OSD_W, height=OSD_H,
                           bg="#0d0d0d", highlightthickness=0)
    osd_canvas.pack()

    _rounded_rect(osd_canvas, 0, 0, OSD_W, OSD_H, 18, fill="#1c1c1c", outline="")
    osd_canvas.create_text(28,        24, text="🔊", font=("Segoe UI Emoji", 13),
                           fill="#ffffff", tags="icon")
    osd_canvas.create_text(OSD_W-28, 24, text="0%",  font=("Segoe UI", 14, "bold"),
                           fill="#ffffff", anchor="e", tags="pct")
    osd_canvas.create_rectangle(BAR_X, BAR_Y, BAR_X+BAR_W, BAR_Y+BAR_H,
                                fill="#333333", outline="", tags="track")
    osd_canvas.create_rectangle(BAR_X, BAR_Y, BAR_X, BAR_Y+BAR_H,
                                fill="#ffffff", outline="", tags="fill")

def show_osd(vol_pct: int) -> None:
    global osd_hide_job
    if osd_window is None or osd_canvas is None: return

    icon = "🔇" if vol_pct == 0 else "🔈" if vol_pct < 33 else "🔉" if vol_pct < 66 else "🔊"
    fill_w = max(1, int(BAR_W * vol_pct / 100))

    osd_canvas.itemconfig("icon", text=icon)
    osd_canvas.itemconfig("pct",  text=f"{vol_pct}%")
    osd_canvas.coords("fill", BAR_X, BAR_Y, BAR_X + fill_w, BAR_Y + BAR_H)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - OSD_W) // 2
    y = screen_h - OSD_H - 72
    osd_window.geometry(f"{OSD_W}x{OSD_H}+{x}+{y}")
    osd_window.deiconify()
    osd_window.attributes("-alpha", 0.93)

    if osd_hide_job is not None:
        root.after_cancel(osd_hide_job)
    osd_hide_job = root.after(1800, fade_osd)

def fade_osd(step: float = 0.93) -> None:
    global osd_hide_job
    if osd_window is None: return
    step = round(step - 0.08, 2)
    if step <= 0:
        osd_window.withdraw()
        osd_window.attributes("-alpha", 0.0)
        return
    osd_window.attributes("-alpha", step)
    osd_hide_job = root.after(30, lambda: fade_osd(step))

def set_volume(vol_pct: int) -> None:
    volume.SetMasterVolumeLevelScalar(vol_pct / 100.0, None)

def toggle_leds() -> None:
    if led_var is None: return
    state = 1 if led_var.get() else 0
    ser.write(f"L{state}\n".encode('utf-8'))
    if status_label is not None:
        status_label.config(text="LEDs ON" if state else "LEDs OFF")
    log(f"LED toggle → sent 'L{state}' to Arduino")

def toggle_knob_lock() -> None:
    if knob_lock_var is None: return
    locked = knob_lock_var.get()
    log(f"Knob {'LOCKED — knob input ignored' if locked else 'UNLOCKED — knob active'}")
    if status_label is not None:
        status_label.config(text="🔒 Knob locked" if locked else "🔓 Knob unlocked")

def background_audio_sync() -> None:
    global last_known_vol, last_knob_turn_time, device, volume, last_device_check, serial_buffer

    try:
        if time.time() - last_device_check > 2.0:
            last_device_check = time.time()
            current_device = AudioUtilities.GetSpeakers()
            if current_device is not None and device is not None and current_device.id != device.id:
                old_name = device.FriendlyName
                device = current_device
                volume = device.EndpointVolume
                last_known_vol = round(volume.GetMasterVolumeLevelScalar() * 100)
                short_name = device.FriendlyName[:25] + "..." if len(device.FriendlyName) > 25 else device.FriendlyName
                if status_label is not None:
                    status_label.config(text=f"Switched to: {short_name}")
                log(f"DEVICE SWITCH: '{old_name}' → '{device.FriendlyName}' | New vol={last_known_vol}%")

        if ser.in_waiting > 0:
            serial_buffer += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')

        while '\n' in serial_buffer:
            line, serial_buffer = serial_buffer.split('\n', 1)
            raw = line.strip()

            if raw.startswith('V') and raw[1:].isdigit():
                vol_pct = int(raw[1:])
                knob_locked = knob_lock_var.get() if knob_lock_var is not None else False

                if knob_locked:
                    ser.write(f"V{last_known_vol}\n".encode('utf-8'))
                    log(f"KNOB IGNORED (locked): knob={vol_pct}% | keeping {last_known_vol}%")
                else:
                    set_volume(vol_pct)
                    actual = round(volume.GetMasterVolumeLevelScalar() * 100)
                    last_knob_turn_time = time.time()
                    last_known_vol = actual
                    if status_label is not None:
                        status_label.config(text=f"Knob → {vol_pct}%")
                    log(f"KNOB SET: requested={vol_pct}% | Windows snapped to={actual}%")
                    show_osd(vol_pct)

            elif raw:
                log(f"ARDUINO IGNORED: '{raw}'")

        current_pc_vol = round(volume.GetMasterVolumeLevelScalar() * 100)
        time_since_knob = time.time() - last_knob_turn_time

        if time_since_knob > 0.5:
            delta = abs(current_pc_vol - last_known_vol)
            if delta >= 2:
                log(f"PC CHANGE: {last_known_vol}% → {current_pc_vol}% (Δ{delta}) | sending V{current_pc_vol} to Arduino")
                last_known_vol = current_pc_vol
                ser.write(f"V{current_pc_vol}\n".encode('utf-8'))
                if status_label is not None:
                    status_label.config(text=f"PC → {current_pc_vol}%")
        else:
            if current_pc_vol != last_known_vol:
                log(f"KNOB COOLDOWN ({time_since_knob:.2f}s): PC vol={current_pc_vol}% last_known={last_known_vol}% — suppressed sync")
            last_known_vol = current_pc_vol

    except Exception as e:
        log(f"ERROR: {e}")

    root.after(10, background_audio_sync)

# Graphing rendering loop
def update_graph() -> None:
    if graph_canvas is None: return
    
    # Slide the history window over and append the newest volume reading
    vol_history.pop(0)
    vol_history.append(last_known_vol)
    
    graph_canvas.delete("line")
    width = graph_canvas.winfo_width()
    height = graph_canvas.winfo_height()
    if width < 10: width = 460 # Fallback before window fully draws

    # Map the 0-100 values into (x, y) coordinates for the canvas
    coords = []
    step_x = width / (GRAPH_POINTS - 1)
    for i, val in enumerate(vol_history):
        x = i * step_x
        # Invert Y because canvas 0 is at the top
        y = height - (val / 100.0 * height)
        # Keep it slightly off the exact top/bottom edges
        y = max(2, min(height - 2, y)) 
        coords.append((x, y))

    # Flatten the coordinate list and draw the line
    flat_coords = [c for pt in coords for c in pt]
    if len(flat_coords) >= 4:
        graph_canvas.create_line(flat_coords, fill="#3ddc84", width=2, tags="line", joinstyle=tk.ROUND)

    # Redraw at roughly 15 frames per second
    root.after(66, update_graph)

# --- BUILD GUI ---
root = tk.Tk()
root.title("Arduino Volume Controller")
root.geometry("500x560") # Increased height to fit the graph
root.configure(bg="#1a1a1a")
root.resizable(False, False)

# Title
tk.Label(root, text="Hardware Audio Bridge",
         font=("Segoe UI", 15, "bold"), bg="#1a1a1a", fg="#ffffff").pack(pady=(22, 2))

# Device name / status
status_label = tk.Label(root, text=f"  {device.FriendlyName[:35]}",
                        font=("Segoe UI", 9), bg="#1a1a1a", fg="#666666")
status_label.pack(pady=(0, 14))

tk.Frame(root, bg="#2a2a2a", height=1).pack(fill=tk.X, padx=24)

# Controls row
controls = tk.Frame(root, bg="#1a1a1a")
controls.pack(pady=14, padx=28, fill=tk.X)

led_frame = tk.Frame(controls, bg="#1a1a1a")
led_frame.pack(side=tk.LEFT)
tk.Label(led_frame, text="LEDs & Display", font=("Segoe UI", 10), bg="#1a1a1a", fg="#aaaaaa").pack(anchor="w")
led_var = tk.BooleanVar(value=True)
led_chk = tk.Checkbutton(led_frame, text="Enabled", variable=led_var, command=toggle_leds,
                         bg="#1a1a1a", activebackground="#1a1a1a", selectcolor="#2a2a2a",
                         fg="#666666", activeforeground="#aaaaaa", font=("Segoe UI", 9),
                         relief=tk.FLAT, cursor="hand2")
led_chk.pack(anchor="w")

tk.Frame(controls, bg="#2a2a2a", width=1).pack(side=tk.LEFT, fill=tk.Y, padx=24)

lock_frame = tk.Frame(controls, bg="#1a1a1a")
lock_frame.pack(side=tk.LEFT)
tk.Label(lock_frame, text="Knob Input", font=("Segoe UI", 10), bg="#1a1a1a", fg="#aaaaaa").pack(anchor="w")
knob_lock_var = tk.BooleanVar(value=False)
lock_chk = tk.Checkbutton(lock_frame, text="Lock (ignore knob)", variable=knob_lock_var,
                           command=toggle_knob_lock, bg="#1a1a1a", activebackground="#1a1a1a", selectcolor="#2a2a2a",
                           fg="#666666", activeforeground="#aaaaaa", font=("Segoe UI", 9),
                           relief=tk.FLAT, cursor="hand2")
lock_chk.pack(anchor="w")

tk.Frame(root, bg="#2a2a2a", height=1).pack(fill=tk.X, padx=24)

# NEW: The Scrolling Graph UI elements
tk.Label(root, text="LIVE VOLUME OUTPUT", font=("Segoe UI", 7, "bold"),
         bg="#1a1a1a", fg="#333333").pack(anchor="w", padx=28, pady=(10, 2))

graph_frame = tk.Frame(root, bg="#0d0d0d", bd=1, relief=tk.SUNKEN)
graph_frame.pack(fill=tk.X, padx=16, pady=(0, 10))

graph_canvas = tk.Canvas(graph_frame, height=60, bg="#0d0d0d", highlightthickness=0)
graph_canvas.pack(fill=tk.BOTH, expand=True)

# Log elements
tk.Label(root, text="EVENT LOG", font=("Segoe UI", 7, "bold"),
         bg="#1a1a1a", fg="#333333").pack(anchor="w", padx=28, pady=(0, 2))

log_frame = tk.Frame(root, bg="#111111")
log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 0))

log_box = scrolledtext.ScrolledText(log_frame, state=tk.DISABLED,
                                    bg="#111111", fg="#3ddc84",
                                    font=("Cascadia Code", 8),
                                    wrap=tk.WORD, bd=0,
                                    insertbackground="#3ddc84")
log_box.pack(fill=tk.BOTH, expand=True)

def clear_log() -> None:
    if log_box is not None:
        log_box.config(state=tk.NORMAL)
        log_box.delete("1.0", tk.END)
        log_box.config(state=tk.DISABLED)

tk.Button(root, text="clear log", command=clear_log,
          bg="#1a1a1a", fg="#333333", font=("Segoe UI", 8),
          relief=tk.FLAT, cursor="hand2",
          activebackground="#1a1a1a", activeforeground="#888888", bd=0).pack(pady=(4, 10))

build_osd()
log(f"Started. Device='{device.FriendlyName}' | Initial vol={last_known_vol}%")

# Start background tasks
root.after(10, background_audio_sync)
root.after(100, update_graph) # Start the graphing loop
root.mainloop()