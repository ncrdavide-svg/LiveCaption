"""LiveCaption: sottotitoli dal vivo.

Ascolta un ingresso audio, trascrive in italiano (offline, Vosk), aggiunge la punteggiatura,
riconosce i relatori (un colore per ciascuno) e traduce in inglese. Il testo appare a schermo
intero sul secondo monitor."""
import ctypes
import json
import os
import queue
import sys
import threading
import urllib.request
import zipfile
import tkinter as tk
from tkinter import ttk, colorchooser, font as tkfont

# Nell'exe senza console stdout/stderr non esistono: le barre di avanzamento farebbero crashare.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import numpy as np
import sounddevice as sd
from vosk import Model, KaldiRecognizer, SpkModel, SetLogLevel

APP_NAME = "LiveCaption"
APP_VERSION = "1.1.0"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
ICON_FILE = os.path.join(RES_DIR, "assets", "LiveCaption.ico")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), APP_NAME)


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".probe")
        open(probe, "w").close()
        os.remove(probe)
        return True
    except OSError:
        return False


# Modelli: cartella "models" accanto all'exe se c'è (versione portatile), altrimenti in %LOCALAPPDATA%.
_portable = os.path.join(APP_DIR, "models")
MODELS_DIR = _portable if os.path.isdir(_portable) else os.path.join(DATA_DIR, "models")
# Impostazioni accanto all'exe (come LiveCount), oppure in %LOCALAPPDATA% se non scrivibile.
SETTINGS_FILE = os.path.join(APP_DIR if _writable(APP_DIR) else DATA_DIR, "LiveCaption.settings.json")
VOSK_URL = "https://alphacephei.com/vosk/models/"
MAIN_MODEL = "vosk-model-it-0.22"
SPK_MODEL = "vosk-model-spk-0.4"
PUNCT_DIR = os.path.join(MODELS_DIR, "punteggiatura")
PUNCT_REPO = "oliverguhr/fullstop-punctuation-multilang-large"
TRANS_DIR = os.path.join(MODELS_DIR, "traduzione-it-en")
TRANS_REPO = "Helsinki-NLP/opus-mt-it-en"
WINDOW_LABEL = "Finestra (ridimensionabile)"
CHANNELS = ["Ingresso 1", "Ingresso 2", "Mix 1+2"]
MAX_BLOCKS = 25
MODES = {"both": "Italiano + traduzione inglese", "orig": "Solo italiano", "trans": "Solo traduzione inglese"}
MODE_KEYS = {v: k for k, v in MODES.items()}

DEFAULTS = {
    "bg": "#000000",
    "colors": ["#FFFFFF", "#FFD84D", "#5CD6FF", "#8CFF8C"],
    "font": "Arial",
    "size": 60,
    "device": "",
    "channel": "Ingresso 1",
    "screen": "",
    "punct": True,
    "mode": "both",
    "speakers": True,
    "spk_sens": 50,
}

SetLogLevel(-1)

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


# ---------------------------------------------------------------- utilità
def get_monitors():
    """Ritorna lista di (x, y, w, h) per ogni monitor."""
    mons = []
    if sys.platform == "win32":
        from ctypes import wintypes
        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def cb(_h, _hdc, r, _lp):
            rc = r.contents
            mons.append((rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top))
            return 1

        ctypes.windll.user32.EnumDisplayMonitors(None, None, proc_type(cb), 0)
    return mons


def list_input_devices():
    """Ritorna dict etichetta -> indice dispositivo."""
    apis = sd.query_hostapis()
    out = {}
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            label = f"{d['name']}  [{apis[d['hostapi']]['name']}]"
            out[label] = i
    return out


def find_model_dir():
    """Modello di trascrizione: preferisce quello grande se presente."""
    if not os.path.isdir(MODELS_DIR):
        return None
    dirs = [d for d in sorted(os.listdir(MODELS_DIR))
            if d.startswith("vosk-model-") and "spk" not in d
            and os.path.isdir(os.path.join(MODELS_DIR, d))]
    if not dirs:
        return None
    big = [d for d in dirs if "small" not in d]
    return os.path.join(MODELS_DIR, (big or dirs)[0])


def download_vosk(name, status):
    os.makedirs(MODELS_DIR, exist_ok=True)
    zpath = os.path.join(MODELS_DIR, name + ".zip")

    def hook(blocks, bsize, total):
        if total > 0:
            status(f"Scarico {name}... {min(100, blocks * bsize * 100 // total)}%")

    urllib.request.urlretrieve(VOSK_URL + name + ".zip", zpath, hook)
    status(f"Estraggo {name}...")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(MODELS_DIR)
    os.remove(zpath)


def download_hf(repo, path, patterns, status):
    if os.path.isfile(os.path.join(path, "config.json")):
        return
    status(f"Scarico {repo.split('/')[1]} (solo la prima volta)...")
    from huggingface_hub import snapshot_download
    snapshot_download(repo, local_dir=path, allow_patterns=patterns)


# ---------------------------------------------------------------- audio + riconoscimento
class Transcriber:
    def __init__(self, model, spk_model, device, channel, out_q):
        self.model = model
        self.spk_model = spk_model
        self.device = device
        self.channel = channel
        self.out_q = out_q
        self.audio_q = queue.Queue()
        self.level = 0.0
        self.running = False

    def start(self):
        info = sd.query_devices(self.device)
        sr = int(info["default_samplerate"])
        self.nch = max(1, min(2, info["max_input_channels"]))
        self.rec = KaldiRecognizer(self.model, sr)
        if self.spk_model:
            self.rec.SetSpkModel(self.spk_model)
        self.stream = sd.InputStream(device=self.device, channels=self.nch, samplerate=sr,
                                     dtype="int16", blocksize=int(sr * 0.1),
                                     callback=self._callback)
        self.running = True
        self.stream.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass

    def _callback(self, indata, frames, t, status):
        if self.channel == "Mix 1+2" and self.nch > 1:
            mono = indata.astype(np.int32).mean(axis=1).astype(np.int16)
        else:
            idx = 1 if self.channel == "Ingresso 2" else 0
            mono = indata[:, min(idx, self.nch - 1)].copy()
        self.level = float(np.abs(mono).max()) / 32768.0
        self.audio_q.put(mono.tobytes())

    def _loop(self):
        last_partial = ""
        while self.running:
            try:
                data = self.audio_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if self.rec.AcceptWaveform(data):
                res = json.loads(self.rec.Result())
                text = res.get("text", "")
                if text:
                    self.out_q.put(("final", text, res.get("spk"), res.get("spk_frames", 0)))
                last_partial = ""
            else:
                p = json.loads(self.rec.PartialResult()).get("partial", "")
                if p != last_partial:
                    last_partial = p
                    self.out_q.put(("partial", p))


# ---------------------------------------------------------------- relatori
class Speakers:
    """Raggruppa le impronte vocali (x-vector) in relatori, al volo."""
    MIN_FRAMES = 120  # sotto ~1,2 s di voce l'impronta è poco affidabile

    def __init__(self):
        self.reset()

    def reset(self):
        self.centroids = []
        self.last = 0

    def assign(self, vec, frames, threshold):
        if vec is None:
            return self.last
        v = np.asarray(vec, dtype=np.float32)
        v /= (np.linalg.norm(v) + 1e-9)
        if not self.centroids:
            self.centroids.append(v)
            self.last = 0
            return 0
        sims = [float(c @ v) for c in self.centroids]
        best = int(np.argmax(sims))
        if frames < self.MIN_FRAMES:
            # frase corta: resta sul relatore precedente salvo somiglianza netta con un altro
            idx = best if sims[best] >= threshold + 0.1 else self.last
        elif sims[best] >= threshold or len(self.centroids) >= 8:
            idx = best
        else:
            self.centroids.append(v)
            idx = len(self.centroids) - 1
        if frames >= self.MIN_FRAMES:
            c = self.centroids[idx] * 0.8 + v * 0.2
            self.centroids[idx] = c / (np.linalg.norm(c) + 1e-9)
        self.last = idx
        return idx


# ---------------------------------------------------------------- punteggiatura e traduzione
class TextProcessor:
    def __init__(self):
        self.punct = None
        self.tok = None
        self.trans = None

    def load_punct(self, status):
        download_hf(PUNCT_REPO, PUNCT_DIR,
                    ["config.json", "model.safetensors", "sentencepiece.bpe.model",
                     "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"], status)
        status("Carico modello punteggiatura...")
        from transformers import pipeline
        self.punct = pipeline("token-classification", model=PUNCT_DIR,
                              aggregation_strategy="none", device=-1)

    def load_trans(self, status):
        download_hf(TRANS_REPO, TRANS_DIR, ["*.json", "*.spm", "pytorch_model.bin"], status)
        status("Carico modello traduzione...")
        from transformers import MarianMTModel, MarianTokenizer
        self.tok = MarianTokenizer.from_pretrained(TRANS_DIR)
        self.trans = MarianMTModel.from_pretrained(TRANS_DIR).eval()

    def punctuate(self, text):
        words = text.split()
        if not words:
            return text
        if self.punct:
            res = self.punct(" ".join(words))
            out, char_i, res_i = [], 0, 0
            for w in words:
                char_i += len(w) + 1
                label = "0"
                while res_i < len(res) and char_i > res[res_i]["end"]:
                    label = res[res_i]["entity"]
                    res_i += 1
                out.append(w + (label if label in ".,?:" else ""))
            words = out
        # maiuscole a inizio frase
        cap = True
        for i, w in enumerate(words):
            if cap:
                words[i] = w[0].upper() + w[1:]
            cap = w[-1] in ".?!"
        s = " ".join(words)
        if s[-1] not in ".?!":
            s = s.rstrip(",:") + "."
        return s

    def translate(self, text):
        if not self.trans:
            return None
        import re
        import torch
        # una frase alla volta: il modello tende a saltare la seconda frase se gliene passi due
        sents = [x for x in re.split(r"(?<=[.?!])\s+", text) if x.strip()]
        with torch.no_grad():
            batch = self.tok(sents, return_tensors="pt", padding=True, truncation=True)
            out = self.trans.generate(**batch, num_beams=2, max_length=256)
        return " ".join(self.tok.batch_decode(out, skip_special_tokens=True))


# ---------------------------------------------------------------- interfaccia
class App:
    def __init__(self, root):
        self.root = root
        self.s = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            if "fg" in saved and "colors" not in saved:  # vecchie impostazioni
                saved["colors"] = [saved["fg"]] + DEFAULTS["colors"][1:]
            saved.pop("fg", None)
            if "translate" in saved and "mode" not in saved:  # impostazioni della 1.0
                saved["mode"] = "both" if saved["translate"] else "orig"
            saved.pop("translate", None)
            self.s.update(saved)
        except Exception:
            pass

        self.model = None
        self.spk_model = None
        self.tr = None
        self.q = queue.Queue()          # dal riconoscimento e dai thread verso la UI
        self.work_q = queue.Queue()     # frasi da elaborare (relatore, punteggiatura, traduzione)
        self.proc = TextProcessor()
        self.speakers = Speakers()
        self.blocks = []                # {"id", "spk", "text", "trans"}
        self.next_id = 0
        self.partial = ""
        self.models_done = False

        root.title(f"{APP_NAME} {APP_VERSION}")
        self._set_icon(root)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._build_controls()
        self._build_display()

        threading.Thread(target=self._load_models, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(50, self._poll)
        if os.environ.get("LIVECAPTION_SELFTEST"):
            self._selftest(os.environ["LIVECAPTION_SELFTEST"])

    def _selftest(self, out_path):
        """Usato dalla build: inietta una frase, poi scrive lo stato su file ed esce."""
        def inject():
            if not (self.proc.punct and self.proc.trans):
                return self.root.after(1000, inject)
            self.q.put(("final", "buongiorno a tutti secondo voi è fattibile", None, 0))
            self.root.after(5000, finish)

        def finish():
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"status": self.status.get(), "blocks": self.blocks,
                           "spk_model": self.spk_model is not None}, f, ensure_ascii=False)
            self.quit()
        self.root.after(1000, inject)

    # ---- pannello di controllo
    def _build_controls(self):
        f = ttk.Frame(self.root, padding=12)
        f.grid(sticky="nsew")
        r = 0

        ttk.Label(f, text="Ingresso audio").grid(row=r, column=0, sticky="w", pady=3)
        self.devices = list_input_devices()
        self.dev_var = tk.StringVar(value=self._default_device())
        cb = ttk.Combobox(f, textvariable=self.dev_var, values=list(self.devices),
                          state="readonly", width=55)
        cb.grid(row=r, column=1, columnspan=3, sticky="we")
        cb.bind("<<ComboboxSelected>>", lambda e: self._restart())
        r += 1

        ttk.Label(f, text="Canale").grid(row=r, column=0, sticky="w", pady=3)
        self.ch_var = tk.StringVar(value=self.s["channel"])
        cb = ttk.Combobox(f, textvariable=self.ch_var, values=CHANNELS, state="readonly", width=14)
        cb.grid(row=r, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._restart())
        self.meter = ttk.Progressbar(f, length=220, maximum=1.0)
        self.meter.grid(row=r, column=2, columnspan=2, sticky="we", padx=(8, 0))
        r += 1

        ttk.Label(f, text="Schermo").grid(row=r, column=0, sticky="w", pady=3)
        self.monitors = get_monitors()
        self.screen_opts = [f"Schermo {i + 1}  ({w}x{h})" for i, (x, y, w, h) in enumerate(self.monitors)]
        self.screen_opts.append(WINDOW_LABEL)
        self.scr_var = tk.StringVar(value=self._default_screen())
        cb = ttk.Combobox(f, textvariable=self.scr_var, values=self.screen_opts,
                          state="readonly", width=30)
        cb.grid(row=r, column=1, columnspan=3, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._place_display())
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="we", pady=8)
        r += 1

        ttk.Label(f, text="Font").grid(row=r, column=0, sticky="w", pady=3)
        fams = sorted({x for x in tkfont.families() if not x.startswith("@")}, key=str.lower)
        self.font_var = tk.StringVar(value=self.s["font"])
        cb = ttk.Combobox(f, textvariable=self.font_var, values=fams, state="readonly", width=30)
        cb.grid(row=r, column=1, columnspan=2, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_style())
        r += 1

        ttk.Label(f, text="Grandezza").grid(row=r, column=0, sticky="w", pady=3)
        self.size_var = tk.IntVar(value=int(self.s["size"]))
        sc = ttk.Scale(f, from_=16, to=200, variable=self.size_var,
                       command=lambda v: self._on_size(v))
        sc.grid(row=r, column=1, columnspan=2, sticky="we")
        self.size_lbl = ttk.Label(f, text=str(self.size_var.get()), width=4)
        self.size_lbl.grid(row=r, column=3, sticky="w", padx=6)
        r += 1

        ttk.Label(f, text="Colori").grid(row=r, column=0, sticky="w", pady=3)
        cf = ttk.Frame(f)
        cf.grid(row=r, column=1, columnspan=3, sticky="w")
        self.bg_btn = tk.Button(cf, text="Sfondo", width=9, command=lambda: self._pick("bg"))
        self.bg_btn.pack(side="left", padx=(0, 8))
        self.spk_btns = []
        for i in range(4):
            b = tk.Button(cf, text=f"Relatore {i + 1}", width=9,
                          command=lambda i=i: self._pick(i))
            b.pack(side="left", padx=2)
            self.spk_btns.append(b)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="we", pady=8)
        r += 1

        ttk.Label(f, text="Testo a schermo").grid(row=r, column=0, sticky="w", pady=3)
        self.mode_var = tk.StringVar(value=MODES.get(self.s["mode"], MODES["both"]))
        cb = ttk.Combobox(f, textvariable=self.mode_var, values=list(MODES.values()),
                          state="readonly", width=30)
        cb.grid(row=r, column=1, columnspan=3, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self._render_and_save())
        r += 1

        self.punct_var = tk.BooleanVar(value=self.s["punct"])
        self.spk_var = tk.BooleanVar(value=self.s["speakers"])
        of = ttk.Frame(f)
        of.grid(row=r, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(of, text="Punteggiatura", variable=self.punct_var,
                        command=self._save).pack(side="left")
        ttk.Checkbutton(of, text="Colore per relatore", variable=self.spk_var,
                        command=self._render_and_save).pack(side="left", padx=12)
        r += 1

        ttk.Label(f, text="Sensibilità\ncambio relatore").grid(row=r, column=0, sticky="w", pady=3)
        self.sens_var = tk.IntVar(value=int(self.s["spk_sens"]))
        ttk.Scale(f, from_=0, to=100, variable=self.sens_var,
                  command=lambda v: self._save()).grid(row=r, column=1, columnspan=2, sticky="we")
        ttk.Label(f, text="(più alta = separa di più)", foreground="#777").grid(
            row=r, column=3, sticky="w", padx=6)
        r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=4, sticky="we", pady=8)
        r += 1

        bf = ttk.Frame(f)
        bf.grid(row=r, column=0, columnspan=4, sticky="we")
        self.run_btn = ttk.Button(bf, text="Avvia", command=self._toggle, state="disabled")
        self.run_btn.pack(side="left")
        ttk.Button(bf, text="Pulisci testo", command=self._clear).pack(side="left", padx=8)
        r += 1

        self.status = tk.StringVar(value="Carico modelli...")
        ttk.Label(f, textvariable=self.status, foreground="#555").grid(
            row=r, column=0, columnspan=4, sticky="w", pady=(10, 0))

    @staticmethod
    def _set_icon(win):
        try:
            win.iconbitmap(ICON_FILE)
        except Exception:
            pass

    def _default_device(self):
        if self.s["device"] in self.devices:
            return self.s["device"]
        names = list(self.devices)
        foc = [n for n in names if "focusrite" in n.lower()]
        mme = [n for n in foc if "MME" in n]
        if mme or foc:
            return (mme or foc)[0]
        try:
            default_in = sd.default.device[0]
            for n, i in self.devices.items():
                if i == default_in:
                    return n
        except Exception:
            pass
        return names[0] if names else ""

    def _default_screen(self):
        if self.s["screen"] in self.screen_opts:
            return self.s["screen"]
        for i, (x, y, w, h) in enumerate(self.monitors):
            if (x, y) != (0, 0):  # primo monitor che non è il principale
                return self.screen_opts[i]
        return WINDOW_LABEL

    # ---- finestra testo
    def _build_display(self):
        self.disp = tk.Toplevel(self.root)
        self.disp.title(f"{APP_NAME} - display")
        self._set_icon(self.disp)
        self.disp.protocol("WM_DELETE_WINDOW", lambda: None)
        self.txt = tk.Text(self.disp, wrap="word", borderwidth=0, highlightthickness=0,
                           padx=40, pady=30, cursor="arrow", takefocus=0)
        self.txt.pack(fill="both", expand=True)
        self._place_display()
        self._apply_style()

    def _place_display(self):
        choice = self.scr_var.get()
        if choice == WINDOW_LABEL or choice not in self.screen_opts:
            self.disp.overrideredirect(False)
            self.disp.geometry("1100x450+80+80")
        else:
            x, y, w, h = self.monitors[self.screen_opts.index(choice)]
            self.disp.overrideredirect(True)
            self.disp.geometry(f"{w}x{h}{x:+d}{y:+d}")
        self._save()

    def _apply_style(self):
        bg = self.s["bg"]
        fam, size = self.font_var.get(), int(self.size_var.get())
        self.disp.configure(bg=bg)
        self.txt.configure(bg=bg, fg=self.s["colors"][0], font=(fam, size),
                           insertbackground=bg, selectbackground=bg)
        for i, col in enumerate(self.s["colors"]):
            self.txt.tag_configure(f"o{i}", foreground=col, font=(fam, size),
                                   spacing1=int(size * 0.35))
            self.txt.tag_configure(f"t{i}", foreground=col,
                                   font=(fam, max(10, int(size * 0.75)), "italic"))
        self.bg_btn.configure(bg=bg, fg=self._contrast(bg), activebackground=bg)
        for b, col in zip(self.spk_btns, self.s["colors"]):
            b.configure(bg=col, fg=self._contrast(col), activebackground=col)
        self._render()
        self._save()

    @staticmethod
    def _contrast(hexcol):
        r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
        return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 128 else "#FFFFFF"

    def _on_size(self, v):
        self.size_lbl.configure(text=str(int(float(v))))
        self._apply_style()

    def _pick(self, key):
        cur = self.s["bg"] if key == "bg" else self.s["colors"][key]
        c = colorchooser.askcolor(color=cur, parent=self.root)[1]
        if c:
            if key == "bg":
                self.s["bg"] = c.upper()
            else:
                self.s["colors"][key] = c.upper()
            self._apply_style()

    def _mode(self):
        """'both', 'orig' o 'trans'. Senza modello di traduzione si ripiega sull'originale."""
        mode = MODE_KEYS.get(self.mode_var.get(), "both") if hasattr(self, "mode_var") else "both"
        if mode == "trans" and self.models_done and not self.proc.trans:
            return "orig"
        return mode

    def _render(self):
        if not hasattr(self, "txt"):
            return
        n = len(self.s["colors"])
        mode = self._mode()
        color_spk = self.spk_var.get()
        t = self.txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        first = True
        waiting = False  # in "solo inglese": frasi dette ma non ancora tradotte
        for b in self.blocks[-MAX_BLOCKS:]:
            c = (b["spk"] % n) if (color_spk and b["spk"] is not None) else 0
            if mode == "trans":
                if not b["trans"]:
                    waiting = True
                    continue
                parts = [(b["trans"], f"o{c}")]  # la traduzione prende il posto dell'originale
            else:
                parts = [(b["text"], f"o{c}")]
                if mode == "both" and b["trans"]:
                    parts.append((b["trans"], f"t{c}"))
            for text, tag in parts:
                t.insert("end", ("" if first else "\n") + text, tag)
                first = False
        c = (self.speakers.last % n) if color_spk else 0
        if mode == "trans":
            # l'italiano non si mostra: "…" fa capire che sta arrivando la traduzione
            if self.partial or waiting:
                t.insert("end", ("" if first else "\n") + "…", f"o{c}")
        elif self.partial:
            t.insert("end", ("" if first else "\n") + self.partial, f"o{c}")
        t.see("end")
        t.configure(state="disabled")

    def _render_and_save(self):
        self._render()
        self._save()

    # ---- modelli
    def _load_models(self):
        st = lambda t: self.q.put(("status", t))
        try:
            if not find_model_dir():
                download_vosk(MAIN_MODEL, st)
            st("Carico modello di trascrizione...")
            self.model = Model(find_model_dir())
            try:
                if not os.path.isdir(os.path.join(MODELS_DIR, SPK_MODEL)):
                    download_vosk(SPK_MODEL, st)
                self.spk_model = SpkModel(os.path.join(MODELS_DIR, SPK_MODEL))
            except Exception as e:
                st(f"Riconoscimento relatori non disponibile: {e}")
            self.q.put(("ready", None))
        except Exception as e:
            st(f"Errore modello: {e}")
            return
        msgs = []
        for name, loader in (("punteggiatura", self.proc.load_punct),
                             ("traduzione", self.proc.load_trans)):
            try:
                loader(st)
            except Exception as e:
                msgs.append(f"{name} non disponibile ({e})")
        self.models_done = True
        self.q.put(("rerender", None))
        st("; ".join(msgs) if msgs else ("In ascolto..." if self.tr else "Pronto"))

    def _worker(self):
        """Elabora le frasi finite: relatore, poi punteggiatura, poi traduzione."""
        while True:
            bid, text, vec, frames = self.work_q.get()
            # soglia di somiglianza voce: stessa persona ~0.8+, persone diverse ~0.6 o meno
            thr = 0.55 + 0.35 * self.sens_var.get() / 100.0
            spk = self.speakers.assign(vec, frames, thr) if self.spk_model else 0
            self.q.put(("update", bid, {"spk": spk}))
            try:
                if self.punct_var.get():
                    text = self.proc.punctuate(text)
                else:
                    text = text[0].upper() + text[1:] + "."
                self.q.put(("update", bid, {"text": text}))
                if self._mode() != "orig":
                    tr = self.proc.translate(text)
                    if tr:
                        self.q.put(("update", bid, {"trans": tr}))
            except Exception as e:
                self.q.put(("status", f"Errore elaborazione: {e}"))

    # ---- avvio/arresto ascolto
    def _toggle(self):
        if self.tr:
            self._stop()
        else:
            self._start()

    def _start(self):
        if not self.model:
            return
        dev = self.devices.get(self.dev_var.get())
        if dev is None:
            self.status.set("Seleziona un ingresso audio")
            return
        try:
            self.tr = Transcriber(self.model, self.spk_model, dev, self.ch_var.get(), self.q)
            self.tr.start()
            self.run_btn.configure(text="Ferma")
            if not self.status.get().startswith("Carico") and not self.status.get().startswith("Scarico"):
                self.status.set("In ascolto...")
        except Exception as e:
            self.tr = None
            self.status.set(f"Errore audio: {e}")
        self._save()

    def _stop(self):
        if self.tr:
            self.tr.stop()
            self.tr = None
        self.run_btn.configure(text="Avvia")
        self.meter["value"] = 0
        self.status.set("Fermo")

    def _restart(self):
        self._save()
        if self.tr:
            self._stop()
            self._start()

    def _clear(self):
        self.blocks.clear()
        self.partial = ""
        self.speakers.reset()
        self._render()

    def _poll(self):
        changed = False
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "final":
                    _, text, vec, frames = msg
                    bid = self.next_id
                    self.next_id += 1
                    self.blocks.append({"id": bid, "spk": None, "text": text, "trans": None})
                    self.blocks = self.blocks[-MAX_BLOCKS:]
                    self.partial = ""
                    self.work_q.put((bid, text, vec, frames))
                    changed = True
                elif kind == "partial":
                    self.partial = msg[1]
                    changed = True
                elif kind == "update":
                    _, bid, data = msg
                    for b in self.blocks:
                        if b["id"] == bid:
                            b.update(data)
                            changed = True
                elif kind == "status":
                    self.status.set(msg[1])
                elif kind == "rerender":
                    changed = True
                elif kind == "ready":
                    self.run_btn.configure(state="normal")
                    self._start()
        except queue.Empty:
            pass
        if changed:
            self._render()
        if self.tr:
            self.meter["value"] = self.tr.level
        self.root.after(50, self._poll)

    # ---- impostazioni
    def _save(self):
        if not hasattr(self, "sens_var"):
            return
        self.s.update(font=self.font_var.get(), size=int(self.size_var.get()),
                      device=self.dev_var.get(), channel=self.ch_var.get(),
                      screen=self.scr_var.get(), punct=self.punct_var.get(),
                      mode=MODE_KEYS.get(self.mode_var.get(), "both"), speakers=self.spk_var.get(),
                      spk_sens=int(self.sens_var.get()))
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.s, f, indent=2)
        except Exception:
            pass

    def quit(self):
        self._stop()
        self._save()
        self.root.destroy()


if __name__ == "__main__":
    if sys.platform == "win32":
        # icona propria nella barra delle applicazioni (non quella di Python)
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ncrdavide.LiveCaption")
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
