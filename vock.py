#!/usr/bin/env python3
"""
vock.py  ─  V.O.C.K.  Vocal Output Creation Kit
           Complete Fallout 2 voice modding pipeline.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  msg ────────[parse CP1252]────────────────► txt (one per dialog line)
                                              ↕ optional: edit manually here
  audio ──────[ffmpeg normalize + encode]───► wav  (22050 Hz mono 16-bit)
  wav ────────[snd2acm / wine]──────────────► acm
  wav + txt ──[MFA]─────────────────────────► textgrid
  textgrid (or txt fallback) ───────────────► lip
  msg + acm + lip + txt ────────────────────► dat/vock.dat

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLDER STRUCTURE (all created automatically)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ./msg/          ← put your .MSG file(s) here
  ./audio/        ← put your audio files here (MP3, WAV, FLAC, M4A, …)
  ./txt/          ← generated/editable: one .txt per audio line
  ./wav/          ← generated: 22050 Hz mono 16-bit PCM (ready for ACM/MFA)
  ./acm/          ← generated: Fallout 2 ACM files
  ./textgrid/     ← generated: MFA TextGrid files
  ./lip/          ← generated: Fallout 2 LIP files
  ./dat/vock.dat  ← generated: ready-to-install Fallout 2 DAT archive

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEPS  (run with --steps or skip with --skip)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  msg   Parse .MSG → individual .txt files in txt/
  wav   Convert audio/ → standardised 22050 Hz mono 16-bit in wav/
  acm   wav/ → ACM via snd2acm.exe
  mfa   MFA forced alignment → textgrid/
  lip   textgrid/ (or txt/ fallback) → lip/
  dat   Pack msg/ + acm/ + lip/ + txt/ → dat/vock.dat

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Full pipeline:
  conda activate aligner
  python3 vock.py

  # Text-correction workflow (human-in-the-loop):
  python3 vock.py --steps msg          # extract TXT files
  #  … edit txt/MOR1.txt, txt/MOR2.txt, etc. …
  python3 vock.py --steps wav mfa lip dat   # resume from audio

  # Rebuild just the DAT:
  python3 vock.py --steps dat

  # Skip MFA (no conda needed, text approximation only):
  python3 vock.py --skip mfa

  # Skip ACM generation (no snd2acm needed):
  python3 vock.py --skip acm

  # Full options:
  python3 vock.py [--msgdir DIR] [--audiodir DIR] [--txtdir DIR]
                  [--wavdir DIR] [--acmdir DIR] [--textgriddir DIR]
                  [--lipdir DIR] [--datfile PATH]
                  [--snd2acm PATH] [--mfa-env NAME]
                  [--lufs FLOAT] [--no-norm]
                  [--steps STEP [STEP ...]]
                  [--skip  STEP [STEP ...]]
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys

# ─── Pipeline step order ──────────────────────────────────────────────────────

ALL_STEPS = ["msg", "wav", "acm", "mfa", "lip", "dat"]

# ─── LIP constants ────────────────────────────────────────────────────────────

LIP_VERSION     = 0x00000002
LIP_UNKNOWN     = 0x00005800
LIP_SAMPLE_RATE = 22050
LIP_MULTIPLIER  = 2   # offset = seconds × 2 × 22050

# ─── ARPAbet → Fallout LIP phoneme code ──────────────────────────────────────

ARPA_TO_LIP = {
    "AA": 0x0A, "AE": 0x02, "AH": 0x0E, "AO": 0x03,
    "AW": 0x0C, "AY": 0x01, "EH": 0x06, "ER": 0x07,
    "EY": 0x0B, "IH": 0x08, "IY": 0x09, "OW": 0x04,
    "OY": 0x0D, "UH": 0x0E, "UW": 0x05,
    "B":  0x10, "CH": 0x13, "D":  0x11, "DH": 0x13,
    "F":  0x13, "G":  0x11, "HH": 0x0F, "JH": 0x13,
    "K":  0x11, "L":  0x12, "M":  0x10, "N":  0x11,
    "NG": 0x11, "P":  0x10, "R":  0x12, "S":  0x13,
    "SH": 0x13, "T":  0x11, "TH": 0x13, "V":  0x13,
    "W":  0x12, "Y":  0x12, "Z":  0x13, "ZH": 0x13,
    "SIL": 0x00, "SP": 0x00, "": 0x00,
}

def arpa_to_lip_code(phoneme: str) -> int:
    p = re.sub(r"\d", "", phoneme.strip().upper())
    return ARPA_TO_LIP.get(p, 0x0E)

# ─── Text-fallback phoneme tables ────────────────────────────────────────────

LETTER_TO_LIP = {
    'a': 0x0A, 'e': 0x06, 'i': 0x08, 'o': 0x04, 'u': 0x05,
    'b': 0x10, 'p': 0x10, 'm': 0x10,
    'd': 0x11, 't': 0x11, 'n': 0x11, 'g': 0x11, 'k': 0x11, 'c': 0x11,
    'l': 0x12, 'r': 0x12, 'w': 0x12, 'y': 0x12,
    's': 0x13, 'z': 0x13, 'f': 0x13, 'v': 0x13,
    'j': 0x13, 'q': 0x11, 'x': 0x13, 'h': 0x0F,
}
DIGRAPH_TO_LIP = {
    'sh': 0x13, 'ch': 0x13, 'th': 0x13, 'dh': 0x13,
    'zh': 0x13, 'ph': 0x13, 'ng': 0x11, 'wh': 0x12,
}

def text_fallback_events(text: str, duration: float) -> list:
    """Generate (timestamp, lip_code) events from plain text."""
    codes = []
    clean = re.sub(r"[^a-zA-Z\s]", "", text).lower()
    i = 0
    while i < len(clean):
        ch = clean[i]
        if ch == ' ':
            i += 1
            continue
        di = clean[i:i+2]
        if di in DIGRAPH_TO_LIP:
            codes.append(DIGRAPH_TO_LIP[di])
            i += 2
        else:
            codes.append(LETTER_TO_LIP.get(ch, 0x0E))
            i += 1
    # Deduplicate consecutive identical codes
    deduped = []
    for c in codes:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    codes = deduped or [0x0E]
    lead  = min(0.05, duration * 0.04)
    trail = min(0.08, duration * 0.06)
    speech = duration - lead - trail
    n = len(codes)
    return [(lead + (i / n) * speech, code) for i, code in enumerate(codes)]

# ─── MSG parser ───────────────────────────────────────────────────────────────

MSG_LINE_RE = re.compile(r"^\s*\{[^}]*\}\s*\{([^}]*)\}\s*\{(.*)\}\s*$")

def parse_msg(path: str) -> list:
    """Return [(audio_tag, text), …] for lines with a non-empty audio tag."""
    results = []
    with open(path, encoding="cp1252") as fh:
        for line in fh:
            m = MSG_LINE_RE.match(line)
            if not m:
                continue
            tag, text = m.group(1).strip(), m.group(2).strip()
            if tag:
                results.append((tag, text))
    return results

# ─── Audio helpers ────────────────────────────────────────────────────────────

# Supported audio input extensions
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}

def ffprobe_duration(path: str) -> float:
    """Use ffprobe to get duration in seconds. Works for any container."""
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on '{path}': {r.stderr.strip()}")
    data = json.loads(r.stdout)
    dur = data.get("format", {}).get("duration")
    if dur is None:
        raise RuntimeError(f"ffprobe returned no duration for '{path}'")
    return float(dur)

def wav_is_standard(path: str) -> bool:
    """Return True if WAV is already 22050 Hz, mono, 16-bit PCM."""
    import wave
    try:
        with wave.open(path, "rb") as w:
            return (w.getframerate() == 22050 and
                    w.getnchannels() == 1 and
                    w.getsampwidth() == 2)
    except Exception:
        return False

# ─── TextGrid parser ──────────────────────────────────────────────────────────

def parse_textgrid_phones(tg_path: str) -> list:
    with open(tg_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    phones_match = re.search(
        r'name\s*=\s*"phones?"(.*?)(?=(?:item\s*\[|\Z))',
        content, re.DOTALL | re.IGNORECASE)
    if not phones_match:
        raise ValueError(f"No 'phones' tier in {tg_path}")
    tier_text = phones_match.group(1)
    intervals = re.findall(
        r'xmin\s*=\s*([\d.]+).*?xmax\s*=\s*([\d.]+).*?text\s*=\s*"([^"]*)"',
        tier_text, re.DOTALL)
    return [(float(xmin), float(xmax), label) for xmin, xmax, label in intervals]

def build_events_from_textgrid(tg_path: str) -> list:
    intervals = parse_textgrid_phones(tg_path)
    events = []
    for xmin, _xmax, label in intervals:
        code = arpa_to_lip_code(label)
        events.append((xmin, code))
    deduped = []
    for xmin, code in events:
        if not deduped or deduped[-1][1] != code:
            deduped.append((xmin, code))
    return deduped if deduped else [(0.0, 0x00)]

# ─── MFA ─────────────────────────────────────────────────────────────────────

def run_mfa(corpus_dir: str, output_dir: str, mfa_env: str) -> bool:
    """Run MFA alignment via 'conda run'. Returns True on success."""
    cmd = [
        "conda", "run", "-n", mfa_env, "--no-capture-output",
        "mfa", "align", "--clean",
        "--output_format", "long_textgrid",
        corpus_dir,
        "english_us_arpa",
        "english_us_arpa",
        output_dir,
    ]
    n = len([f for f in os.listdir(corpus_dir) if f.endswith(".wav")])
    print(f"\n  Running MFA on {n} file(s)…  (this may take a minute)\n")
    r = subprocess.run(cmd, text=True)
    return r.returncode == 0

# ─── snd2acm ─────────────────────────────────────────────────────────────────

def find_snd2acm(hint: str = None) -> str | None:
    candidates = []
    if hint:
        candidates.append(hint)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates += [
        "snd2acm",
        "snd2acm.exe",
        "SND2ACM.EXE",
        os.path.join(script_dir, "snd2acm.exe"),
        os.path.join(script_dir, "SND2ACM.EXE"),
        os.path.join(os.getcwd(), "snd2acm.exe"),
        os.path.join(os.getcwd(), "SND2ACM.EXE"),
    ]
    for c in candidates:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def wav_to_acm(snd2acm_bin: str, wav_path: str, acm_path: str) -> None:
    cmd = [snd2acm_bin, "-16", wav_path, acm_path, "-q0"]
    if os.name != "nt" and snd2acm_bin.lower().endswith(".exe"):
        cmd.insert(0, "wine")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"snd2acm failed:\n{r.stderr.strip()}")
    if not os.path.isfile(acm_path) or os.path.getsize(acm_path) == 0:
        raise RuntimeError(f"snd2acm produced no output for '{wav_path}'")

# ─── LIP writer ──────────────────────────────────────────────────────────────

def write_lip(out_path: str, stem: str, duration: float, events: list) -> None:
    """Write a Fallout 2 .LIP binary file."""
    num_phonemes = len(events)
    num_markers  = num_phonemes + 1
    file_length  = round(LIP_MULTIPLIER * LIP_SAMPLE_RATE * duration)
    acm_field    = stem.upper().encode("ascii")[:8].ljust(8, b"\x00")

    with open(out_path, "wb") as f:
        f.write(struct.pack(">I", LIP_VERSION))
        f.write(struct.pack(">I", LIP_UNKNOWN))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", file_length))
        f.write(struct.pack(">I", num_phonemes))
        f.write(struct.pack(">I", 0))
        f.write(struct.pack(">I", num_markers))
        f.write(acm_field)
        f.write(b"VOC\x00")
        # Phoneme code bytes
        for _ts, code in events:
            f.write(struct.pack("B", code))
        # Marker table: (type DWORD, offset DWORD) per event + end marker
        for idx, (ts, _code) in enumerate(events):
            if idx == 0:
                f.write(struct.pack(">I", 1))
                f.write(struct.pack(">I", 0))
            else:
                offset = round(LIP_MULTIPLIER * LIP_SAMPLE_RATE * ts)
                f.write(struct.pack(">I", 0))
                f.write(struct.pack(">I", offset))
        f.write(struct.pack(">I", 1))
        f.write(struct.pack(">I", file_length))

# ─── DAT2 packer ─────────────────────────────────────────────────────────────
#
# Fallout 2 DAT2 layout (little-endian):
#   [Data Block]   raw file bytes concatenated from offset 0
#   [Directory Tree]
#     DWORD  num_files
#     per file:
#       DWORD  filename_len
#       BYTES  filename (ASCII, backslash separators, lowercase)
#       BYTE   is_compressed  (0 = uncompressed)
#       DWORD  real_size
#       DWORD  packed_size
#       DWORD  offset_in_data_block
#   [Footer]
#     DWORD  tree_size   (bytes of Directory Tree)
#     DWORD  file_size   (total DAT bytes)
#
# Reference: https://fodev.net/files/fo2/dat.html

def _npc_folder(stem: str) -> str:
    """Derive the 3-letter NPC folder from a stem like MOR1 → MOR."""
    return re.sub(r"\d+$", "", stem).upper()

def collect_dat_entries(msg_paths, acm_dir, lip_dir, txt_dir, include_acm=True):
    """Build [(dat_path, local_path), …] pairs with backslash separators."""
    entries = []
    # MSG files → text\english\dialog\
    for msg_path in msg_paths:
        if os.path.isfile(msg_path):
            msg_name = os.path.basename(msg_path).upper()
            entries.append((f"text\\english\\dialog\\{msg_name}", msg_path))
    # Iterate over LIP files to discover stems and NPC folders
    lip_files = {}
    if os.path.isdir(lip_dir):
        for f in os.listdir(lip_dir):
            if f.upper().endswith(".LIP"):
                stem = os.path.splitext(f)[0].upper()
                lip_files[stem] = os.path.join(lip_dir, f)
    for stem, lip_path in sorted(lip_files.items()):
        folder = _npc_folder(stem)
        base   = f"sound\\Speech\\{folder}"
        entries.append((f"{base}\\{stem}.lip", lip_path))
        if include_acm:
            acm_path = os.path.join(acm_dir, stem + ".acm")
            if os.path.isfile(acm_path):
                entries.append((f"{base}\\{stem}.acm", acm_path))
        txt_path = os.path.join(txt_dir, stem + ".txt")
        if os.path.isfile(txt_path):
            entries.append((f"{base}\\{stem}.txt", txt_path))
    return entries

def write_dat2(out_path: str, entries: list) -> None:
    """Write a Fallout 2 DAT2 archive (pure Python, uncompressed)."""
    # Normalise paths to lowercase ASCII with backslashes, sort alphabetically
    entries = [(d.lower(), l) for d, l in entries]
    entries.sort(key=lambda x: x[0])

    # Read all file data upfront and track offsets
    file_data, offsets = [], []
    cursor = 0
    for _dat_path, local_path in entries:
        raw = open(local_path, "rb").read()
        file_data.append(raw)
        offsets.append(cursor)
        cursor += len(raw)

    # Build the directory tree
    tree = bytearray()
    tree += struct.pack("<I", len(entries))
    for i, (dat_path, _local) in enumerate(entries):
        raw      = file_data[i]
        fn_bytes = dat_path.encode("ascii")
        tree += struct.pack("<I", len(fn_bytes))
        tree += fn_bytes
        tree += struct.pack("<B", 0)            # is_compressed = 0
        tree += struct.pack("<I", len(raw))     # real_size
        tree += struct.pack("<I", len(raw))     # packed_size  (= real since uncompressed)
        tree += struct.pack("<I", offsets[i])   # offset in data block

    tree_size = len(tree)
    file_size = cursor + tree_size + 8  # +8 for the two footer DWORDs

    with open(out_path, "wb") as f:
        for raw in file_data:
            f.write(raw)
        f.write(tree)
        f.write(struct.pack("<I", tree_size))
        f.write(struct.pack("<I", file_size))

# ─── Dependency fast-fail check ──────────────────────────────────────────────

def check_dependencies(run: set, snd2acm_hint: str, mfa_env: str) -> None:
    """Exit with a clear error message if required tools are missing."""
    errors = []

    # ffmpeg and ffprobe are required by the wav step (and lip for duration)
    needs_ffmpeg = bool(run & {"wav", "lip"})
    if needs_ffmpeg:
        if not shutil.which("ffmpeg"):
            errors.append(
                "  ffmpeg  not found on PATH.\n"
                "  Install:  sudo apt install ffmpeg -y")
        if not shutil.which("ffprobe"):
            errors.append(
                "  ffprobe not found on PATH.\n"
                "  Install:  sudo apt install ffmpeg -y  (ffprobe is bundled with ffmpeg)")

    # snd2acm for the acm step
    if "acm" in run:
        if not find_snd2acm(snd2acm_hint):
            errors.append(
                "  snd2acm.exe  not found.\n"
                "  Download from https://fodev.net/files/mirrors/teamx-utils/snd2acm.rar\n"
                "  and place snd2acm.exe next to vock.py.  On Linux also install Wine:\n"
                "    sudo apt install wine -y")

    # conda for the mfa step
    if "mfa" in run:
        if not shutil.which("conda"):
            errors.append(
                "  conda  not found on PATH.\n"
                "  Install Miniconda:\n"
                "    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh\n"
                "    bash Miniconda3-latest-Linux-x86_64.sh -b\n"
                "    ~/miniconda3/bin/conda init bash && exec bash")

    if errors:
        print("\n[DEPENDENCY ERROR] The following required tools are missing:\n")
        for e in errors:
            print(e)
        print()
        sys.exit(1)

# ─── Utilities ────────────────────────────────────────────────────────────────

def print_section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def _scan_msg_dir(path: str) -> list:
    """Return sorted list of .MSG file paths found in *path* (a directory)."""
    if not os.path.isdir(path):
        sys.exit(f"MSG directory not found: '{path}'\n"
                 "Create a 'msg/' folder and put your .MSG file(s) in it, "
                 "or pass --msg DIR to point elsewhere.")
    found = sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.upper().endswith(".MSG"))
    if not found:
        sys.exit(f"No .MSG files found in '{path}/'")
    return found


def main():
    parser = argparse.ArgumentParser(
        description="V.O.C.K. — Vocal Output Creation Kit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Paths
    parser.add_argument("--msgdir",          default="msg",
        help="Folder containing .MSG file(s) (default: msg)")
    parser.add_argument("--audiodir",     default="audio",
        help="Input audio folder — any format (default: audio)")
    parser.add_argument("--txtdir",       default="txt",
        help="TXT output/edit folder (default: txt)")
    parser.add_argument("--wavdir",       default="wav",
        help="Standardised WAV output folder (default: wav)")
    parser.add_argument("--acmdir",       default="acm",
        help="ACM output folder (default: acm)")
    parser.add_argument("--textgriddir",  default="textgrid",
        help="TextGrid output folder (default: textgrid)")
    parser.add_argument("--lipdir",       default="lip",
        help="LIP output folder (default: lip)")
    parser.add_argument("--datfile",      default="dat/vock.dat",
        help="Output DAT path (default: dat/vock.dat)")
    parser.add_argument("--snd2acm",      default=None,
        help="Explicit path to snd2acm.exe")
    parser.add_argument("--mfa-env",      default="aligner",
        help="Conda env with MFA installed (default: aligner)")
    # Audio options
    parser.add_argument("--lufs",         type=float, default=-16.0,
        help="Target loudness in LUFS (default: -16.0)")
    parser.add_argument("--no-norm",      action="store_true",
        help="Skip EBU R128 loudness normalisation")
    # Step control
    parser.add_argument("--steps",        nargs="+", metavar="STEP",
        choices=ALL_STEPS,
        help=("Run ONLY these step(s). "
              f"Available: {', '.join(ALL_STEPS)}"))
    parser.add_argument("--skip",         nargs="+", metavar="STEP",
        choices=ALL_STEPS,
        help="Skip these step(s) from the full pipeline.")
    args = parser.parse_args()

    # Resolve which steps to run
    if args.steps:
        run = set(args.steps)
    else:
        run = set(ALL_STEPS)
        if args.skip:
            for s in args.skip:
                run.discard(s)

    # Fast-fail dependency check
    check_dependencies(run, args.snd2acm, args.mfa_env)

    # ── Pipeline state ────────────────────────────────────────────────────────
    msg_paths  = []
    txt_map    = {}      # stem → text (from msg step or loaded from txt/)
    wav_pairs  = []      # (stem, std_wav_path, txt_path) — 22050 Hz mono 16-bit

    acm_ok     = 0
    lip_ok     = 0
    lip_approx = 0
    lip_fail   = 0

    # ── STEP 1: MSG → TXT ────────────────────────────────────────────────────
    if "msg" in run:
        print_section("STEP 1 — Parse MSG → TXT")

        msg_paths = _scan_msg_dir(args.msgdir)

        all_entries = []
        for msg_path in msg_paths:
            print(f"  Reading {msg_path}")
            found = parse_msg(msg_path)
            if not found:
                print(f"  [warn] No tagged audio lines in '{msg_path}' — skipping.")
                continue
            all_entries.extend(found)
            print(f"  {len(found)} line(s) found.")

        if not all_entries:
            sys.exit("No audio-tagged lines found in any MSG file.")

        os.makedirs(args.txtdir, exist_ok=True)
        written = 0
        for tag, text in all_entries:
            out = os.path.join(args.txtdir, f"{tag}.txt")
            # Only overwrite if content differs (preserve manual edits)
            if os.path.isfile(out):
                existing = open(out, encoding="cp1252").read().strip()
                if existing == text:
                    txt_map[tag] = text
                    continue
                # File was manually edited — keep the edit; don't overwrite
                txt_map[tag] = existing
                print(f"  [kept manual edit] {out}")
                continue
            with open(out, "w", encoding="cp1252") as fh:
                fh.write(text)
            txt_map[tag] = text
            written += 1

        print(f"  {written} new TXT file(s) written to '{args.txtdir}/'")
        print(f"  (Total {len(all_entries)} lines; existing files preserved if manually edited)")

    else:
        print_section("STEP 1 — Parse MSG → TXT  [skipped]")
        # Resolve msg_paths for the DAT step (best-effort; missing dir is not fatal here)
        if os.path.isdir(args.msgdir):
            msg_paths = _scan_msg_dir(args.msgdir)
        # Load txt_map from existing TXT files (respecting manual edits)
        if os.path.isdir(args.txtdir):
            for f in sorted(os.listdir(args.txtdir)):
                if f.endswith(".txt"):
                    stem = os.path.splitext(f)[0]
                    txt_map[stem] = open(
                        os.path.join(args.txtdir, f), encoding="cp1252").read().strip()

    # ── STEP 2: audio/ → wav/ (Universal Audio step) ─────────────────────────
    if "wav" in run:
        print_section("STEP 2 — Convert audio/ → wav/  (22050 Hz mono 16-bit)")
        os.makedirs(args.wavdir, exist_ok=True)

        # Scan audio/ for all supported formats
        audio_map: dict[str, str] = {}
        if os.path.isdir(args.audiodir):
            for f in sorted(os.listdir(args.audiodir)):
                ext = os.path.splitext(f)[1].lower()
                if ext in AUDIO_EXTS:
                    stem = os.path.splitext(f)[0]
                    # Higher-priority format wins (wav > mp3 > others)
                    existing_ext = os.path.splitext(audio_map.get(stem, ""))[1].lower()
                    if stem not in audio_map:
                        audio_map[stem] = os.path.join(args.audiodir, f)
                    elif ext == ".wav" and existing_ext != ".wav":
                        audio_map[stem] = os.path.join(args.audiodir, f)
        else:
            print(f"  [warn] Audio folder '{args.audiodir}/' not found.")

        if not audio_map:
            sys.exit(f"No audio files found in '{args.audiodir}/'")

        enc_ok = 0
        skipped = 0
        for stem in sorted(audio_map):
            src_path = audio_map[stem]
            # Validate: must have a matching TXT
            txt_path = os.path.join(args.txtdir, stem + ".txt")
            if not os.path.isfile(txt_path):
                print(f"  [skip] {stem}: no matching .txt in '{args.txtdir}/' "
                      f"(run the 'msg' step first, or the tag is not in the MSG file)")
                skipped += 1
                continue

            out_wav = os.path.join(args.wavdir, stem + ".wav")
            try:
                ext = os.path.splitext(src_path)[1].lower()
                # Fast path: WAV already in correct format and norm disabled
                if args.no_norm and ext == ".wav" and wav_is_standard(src_path):
                    shutil.copy2(src_path, out_wav)
                    print(f"  copied   {out_wav}  (already 22050 Hz mono 16-bit)")
                else:
                    cmd = ["ffmpeg", "-y", "-i", src_path]
                    if not args.no_norm:
                        cmd.extend(["-af", f"loudnorm=I={args.lufs}:LRA=11:TP=-1.5"])
                    cmd.extend(["-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", out_wav])
                    r = subprocess.run(cmd, capture_output=True, text=True)
                    if r.returncode != 0:
                        raise RuntimeError(r.stderr.strip())
                    action = "enc+norm" if not args.no_norm else "encoded"
                    print(f"  {action.ljust(8)} {out_wav}")

                wav_pairs.append((stem, out_wav, txt_path))
                enc_ok += 1
            except RuntimeError as e:
                print(f"  [error] {stem}: ffmpeg failed: {e}")

        print(f"\n  {enc_ok} file(s) ready in '{args.wavdir}/'  "
              f"({skipped} skipped — no matching TXT)")

    else:
        print_section("STEP 2 — Convert audio/ → wav/  [skipped]")
        # Populate wav_pairs from existing standardised WAVs
        if os.path.isdir(args.wavdir):
            for f in sorted(os.listdir(args.wavdir)):
                if f.upper().endswith(".WAV"):
                    stem     = os.path.splitext(f)[0]
                    txt_path = os.path.join(args.txtdir, stem + ".txt")
                    if os.path.isfile(txt_path):
                        wav_pairs.append((stem, os.path.join(args.wavdir, f), txt_path))

    # ── STEP 3: wav/ → ACM ───────────────────────────────────────────────────
    if "acm" in run:
        print_section("STEP 3 — Convert wav/ → acm/")
        if not wav_pairs:
            print("  No standardised WAV files found — run the 'wav' step first.")
        else:
            snd2acm_bin = find_snd2acm(args.snd2acm)
            if not snd2acm_bin:
                print("  snd2acm.exe not found — skipping ACM generation.")
                print("  Place snd2acm.exe next to vock.py and re-run.")
            else:
                os.makedirs(args.acmdir, exist_ok=True)
                for stem, wav_path, _txt in wav_pairs:
                    acm_path = os.path.join(args.acmdir, stem + ".acm")
                    try:
                        wav_to_acm(snd2acm_bin, wav_path, acm_path)
                        size_kb = os.path.getsize(acm_path) / 1024
                        print(f"  wrote  {acm_path}  ({size_kb:.1f} KB)")
                        acm_ok += 1
                    except RuntimeError as e:
                        print(f"  [error] {stem}: {e}")
                print(f"\n  {acm_ok}/{len(wav_pairs)} ACM file(s) written.")
    else:
        print_section("STEP 3 — Convert wav/ → acm/  [skipped]")

    # ── STEP 4: MFA alignment ─────────────────────────────────────────────────
    if "mfa" in run:
        print_section("STEP 4 — MFA forced alignment → TextGrid")
        if not wav_pairs:
            print("  No WAV files available — run the 'wav' step first.")
        else:
            os.makedirs(args.textgriddir, exist_ok=True)
            import tempfile
            with tempfile.TemporaryDirectory(prefix="vock_corpus_") as corpus_dir:
                for stem, wav_path, txt_path in wav_pairs:
                    shutil.copy2(wav_path, os.path.join(corpus_dir, stem + ".wav"))
                    text = open(txt_path, encoding="cp1252").read()
                    open(os.path.join(corpus_dir, stem + ".txt"), "w", encoding="utf-8").write(text)

                mfa_tmp_out = os.path.join(corpus_dir, "aligned")
                os.makedirs(mfa_tmp_out)

                mfa_ok = run_mfa(corpus_dir, mfa_tmp_out, args.mfa_env)

                if mfa_ok:
                    tg_count = 0
                    for f in os.listdir(mfa_tmp_out):
                        if f.endswith(".TextGrid"):
                            shutil.copyfile(
                                os.path.join(mfa_tmp_out, f),
                                os.path.join(args.textgriddir, f))
                            tg_count += 1
                    print(f"\n  {tg_count} TextGrid(s) saved to '{args.textgriddir}/'")
                else:
                    print("\n  MFA failed — text approximation will be used for LIP files.")
    else:
        print_section("STEP 4 — MFA forced alignment  [skipped]")

    # ── STEP 5: LIP generation ────────────────────────────────────────────────
    if "lip" in run:
        print_section("STEP 5 — Generate LIP files")
        if not wav_pairs:
            print("  No WAV files available for duration — run the 'wav' step first.")
        else:
            os.makedirs(args.lipdir, exist_ok=True)
            for stem, wav_path, txt_path in wav_pairs:
                lip_path = os.path.join(args.lipdir, stem + ".lip")
                tg_path  = os.path.join(args.textgriddir, stem + ".TextGrid")

                try:
                    duration = ffprobe_duration(wav_path)
                except Exception as e:
                    print(f"  [error] {stem}: could not read duration: {e}")
                    lip_fail += 1
                    continue

                # Try MFA TextGrid first
                if os.path.isfile(tg_path):
                    try:
                        events = build_events_from_textgrid(tg_path)
                        write_lip(lip_path, stem, duration, events)
                        print(f"  wrote  {lip_path}  "
                              f"({duration:.3f}s, {len(events)} events, MFA)")
                        lip_ok += 1
                        continue
                    except Exception as e:
                        print(f"  [warn] {stem}: TextGrid error ({e}), "
                              "falling back to text approximation")

                # Text-fallback: read from txt_map (honours manual edits) or file
                text = txt_map.get(stem, "")
                if not text and os.path.isfile(txt_path):
                    text = open(txt_path, encoding="cp1252").read().strip()
                events = text_fallback_events(text, duration)
                write_lip(lip_path, stem, duration, events)
                print(f"  wrote  {lip_path}  "
                      f"({duration:.3f}s, {len(events)} events, text-approx)")
                lip_approx += 1

            print(f"\n  {lip_ok} MFA  +  {lip_approx} text-approx  +  {lip_fail} failed")
    else:
        print_section("STEP 5 — Generate LIP files  [skipped]")

    # ── STEP 6: Build DAT ────────────────────────────────────────────────────
    if "dat" in run:
        print_section("STEP 6 — Build vock.dat")
        os.makedirs(os.path.dirname(args.datfile) or ".", exist_ok=True)
        try:
            dat_entries = collect_dat_entries(
                msg_paths   = msg_paths,
                acm_dir     = args.acmdir,
                lip_dir     = args.lipdir,
                txt_dir     = args.txtdir,
                include_acm = ("acm" not in (args.skip or [])),
            )
            if not dat_entries:
                print("  No files to pack — skipping.")
            else:
                write_dat2(args.datfile, dat_entries)
                total_kb = os.path.getsize(args.datfile) / 1024
                print(f"  wrote  {args.datfile}  "
                      f"({len(dat_entries)} file(s), {total_kb:.1f} KB)")
        except Exception as e:
            print(f"  [error] DAT creation failed: {e}")
    else:
        print_section("STEP 6 — Build vock.dat  [skipped]")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("  DONE")
    print(f"{'═'*60}")
    steps_run = [s for s in ALL_STEPS if s in run]
    print(f"  Steps run  : {', '.join(steps_run) or '(none)'}")
    print(f"  TXT files  : {len(txt_map)} known")
    print(f"  WAV files  : {len(wav_pairs)}")
    print(f"  ACM files  : {acm_ok if 'acm' in run else 'skipped'}")
    if "lip" in run:
        print(f"  LIP files  : {lip_ok} MFA  +  {lip_approx} text-approx  "
              f"({lip_fail} failed)")
    else:
        print("  LIP files  : skipped")
    print(f"  DAT file   : {args.datfile if 'dat' in run else 'skipped'}")
    print()


if __name__ == "__main__":
    main()
