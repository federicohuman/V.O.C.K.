#!/usr/bin/env python3
"""
vock.py  -  Complete Fallout 2 voice pipeline in one script.

V.O.C.K - Vocal Output Creation Kit

Reads a .MSG file and a folder of MP3s, and produces TXT, WAV, ACM,
TextGrid, LIP and DAT files automatically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  MSG  ──────────────────────────────────────────► TXT (one per line)
  MP3  ──[FFmpeg 22050Hz mono]──► WAV  ──────────► ACM (via snd2acm)
                                   │
                        [MFA align / approximation]
                                   │
                              TextGrid ──────────► LIP (Fallout format)
                              
  MSG + TXT + ACM + LIP ──► vock.dat

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOLDER STRUCTURE (all created automatically)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ./msg/          ← put your .MSG file here  (or pass --msg directly)
  ./mp3/          ← put your .MP3 files here
  ./txt/          ← generated: one .txt per audio line
  ./wav/          ← generated: 22050 Hz mono WAV (kept permanently)
  ./acm/          ← generated: Fallout 2 ACM audio files
  ./textgrid/     ← generated: MFA alignment TextGrid files (kept permanently)
  ./lip/          ← generated: Fallout 2 LIP files
  ./dat/vock.dat  ← generated: Final output file

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  FFmpeg    - audio conversion (must be on PATH)
  snd2acm   - ACM encoder (snd2acm.exe in script folder or on PATH)
  MFA       - forced aligner (conda env 'aligner', see below)

ONE-TIME MFA SETUP (Linux / WSL):
  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash Miniconda3-latest-Linux-x86_64.sh -b
  ~/miniconda3/bin/conda init bash && exec bash
  conda create -n aligner -c conda-forge montreal-forced-aligner python=3.10 -y
  conda activate aligner
  mfa model download acoustic   english_us_arpa
  mfa model download dictionary english_us_arpa

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # Full pipeline (MFA alignment):
  conda activate aligner
  python3 vock.py --msg msg/ACMORLIS.MSG

  # Skip MFA (text approximation, no conda needed):
  python3 vock.py --msg msg/ACMORLIS.MSG --no-mfa

  # Skip ACM generation (if snd2acm not available):
  python3 vock.py --msg msg/ACMORLIS.MSG --no-acm

  # All options:
  python3 vock.py [--msg FILE] [--mp3dir DIR] [--txtdir DIR]
                            [--wavdir DIR] [--acmdir DIR]
                            [--textgriddir DIR] [--lipdir DIR]
                            [--snd2acm PATH] [--mfa-env NAME]
                            [--no-mfa] [--no-acm]
"""

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys

# ─── LIP constants (from BlackElectric's LIPS.py) ────────────────────────────

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

# ─── Text-only fallback phoneme tables ───────────────────────────────────────

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
    deduped = []
    for c in codes:
        if not deduped or deduped[-1] != c:
            deduped.append(c)
    codes = deduped or [0x0E]
    lead   = min(0.05, duration * 0.04)
    trail  = min(0.08, duration * 0.06)
    speech = duration - lead - trail
    n = len(codes)
    return [(lead + (i / n) * speech, code) for i, code in enumerate(codes)]

# ─── MSG parser ───────────────────────────────────────────────────────────────

MSG_LINE_RE = re.compile(r"^\s*\{[^}]*\}\s*\{([^}]*)\}\s*\{(.*)\}\s*$")

def parse_msg(path: str) -> list:
    """Return [(audio_tag, text), ...] for every line with a non-empty tag."""
    results = []
    with open(path, encoding="latin-1") as fh:
        for line in fh:
            m = MSG_LINE_RE.match(line)
            if not m:
                continue
            tag, text = m.group(1).strip(), m.group(2).strip()
            if tag:
                results.append((tag, text))
    return results

# ─── Audio helpers ────────────────────────────────────────────────────────────

_BR_V1 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]
_BR_V2 = [0, 8,16,24,32,40,48,56, 64, 80, 96,112,128,144,160,0]
_SR    = {0:{0:44100,1:48000,2:32000}, 2:{0:22050,1:24000,2:16000},
          3:{0:11025,1:12000,2:8000}}

def get_audio_duration(path: str) -> float:
    if path.lower().endswith(".wav"):
        import wave
        with wave.open(path, 'rb') as w:
            return w.getnframes() / w.getframerate()
    try:
        return _mp3_duration_pure(path)
    except RuntimeError:
        return _ffprobe_duration(path)

def _mp3_duration_pure(path: str) -> float:
    with open(path, "rb") as f:
        data = f.read()
    offset = 0
    if data[:3] == b"ID3":
        sz = (((data[6]&0x7F)<<21)|((data[7]&0x7F)<<14)
              |((data[8]&0x7F)<<7)|(data[9]&0x7F))
        offset = 10 + sz
    total, sr = 0, 0
    i = offset
    while i <= len(data) - 4:
        h = struct.unpack_from(">I", data, i)[0]
        if (h & 0xFFE00000) != 0xFFE00000:
            i += 1; continue
        vb=(h>>19)&3; lb=(h>>17)&3; bi=(h>>12)&0xF; sb=(h>>10)&3; pad=(h>>9)&1
        if lb!=1 or sb==3 or bi in(0,15): i+=1; continue
        if   vb==3: vk,bt,spf=0,_BR_V1,1152
        elif vb==2: vk,bt,spf=2,_BR_V2,576
        elif vb==0: vk,bt,spf=3,_BR_V2,576
        else: i+=1; continue
        s=_SR.get(vk,{}).get(sb); b=bt[bi]*1000
        if not s or not b: i+=1; continue
        fs=(144*b//s)+pad
        if fs<21: i+=1; continue
        sr=s; total+=spf; i+=fs
    if not sr: raise RuntimeError("MP3 parse failed")
    return total/sr

def _ffprobe_duration(path: str) -> float:
    r = subprocess.run(["ffprobe","-v","error","-show_entries",
                        "format=duration","-of","json",path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()}")
    return float(json.loads(r.stdout)["format"]["duration"])

def mp3_to_wav(mp3_path: str, wav_path: str) -> None:
    """Convert MP3 to 22050 Hz mono 16-bit WAV (for ACM) and MFA."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", mp3_path,
         "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg failed on '{mp3_path}':\n{r.stderr.strip()}")

# ─── TextGrid parser ──────────────────────────────────────────────────────────

def parse_textgrid_phones(tg_path: str) -> list:
    with open(tg_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    phones_match = re.search(
        r'name\s*=\s*"phones?"(.*?)(?=(?:item\s*\[|\Z))',
        content, re.DOTALL | re.IGNORECASE)
    if not phones_match:
        raise ValueError(f"No 'phones' tier found in {tg_path}")
    tier_text = phones_match.group(1)
    intervals = re.findall(
        r'xmin\s*=\s*([\d.]+).*?xmax\s*=\s*([\d.]+).*?text\s*=\s*"([^"]*)"',
        tier_text, re.DOTALL)
    return [(float(xmin), float(xmax), label)
            for xmin, xmax, label in intervals]

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
    """Run MFA alignment. Uses 'conda run' so no manual activation needed."""
    cmd = [
        "conda", "run", "-n", mfa_env, "--no-capture-output",
        "mfa", "align", "--clean",
        "--output_format", "long_textgrid",
        corpus_dir,
        "english_us_arpa",
        "english_us_arpa",
        output_dir,
    ]
    print(f"\n  Running MFA on {len(os.listdir(corpus_dir))//2} file(s)..."
          f"  (this may take a minute)\n")
    r = subprocess.run(cmd, text=True)
    return r.returncode == 0

# ─── snd2acm ─────────────────────────────────────────────────────────────────

def find_snd2acm(hint: str = None) -> str | None:
    """Return path to snd2acm if found, None otherwise."""
    candidates = []
    if hint:
        candidates.append(hint)
    candidates += [
        "snd2acm",
        "snd2acm.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "snd2acm.exe"),
        os.path.join(os.getcwd(), "snd2acm.exe"),
    ]
    for c in candidates:
        if shutil.which(c) or os.path.isfile(c):
            return c
    return None

def wav_to_acm(snd2acm: str, wav_path: str, acm_path: str) -> None:
    # Build the command array
    cmd = [snd2acm, "-16", wav_path, acm_path, "-q0"]
    
    # If we are on Linux/Mac and it's a Windows executable, prepend 'wine'
    if os.name != 'nt' and snd2acm.lower().endswith('.exe'):
        cmd.insert(0, "wine")

    r = subprocess.run(cmd, capture_output=True, text=True)
    
    if r.returncode != 0:
        raise RuntimeError(f"snd2acm failed:\n{r.stderr.strip()}")
    if not os.path.isfile(acm_path) or os.path.getsize(acm_path) == 0:
        raise RuntimeError(f"snd2acm produced no output for '{wav_path}'")

# ─── LIP writer ──────────────────────────────────────────────────────────────

def write_lip(out_path: str, stem: str, duration: float, events: list) -> None:
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
        for _xmin, code in events:
            f.write(struct.pack("B", code))
        for idx, (xmin, _code) in enumerate(events):
            if idx == 0:
                f.write(struct.pack(">I", 1))
                f.write(struct.pack(">I", 0))
            else:
                ts = round(LIP_MULTIPLIER * LIP_SAMPLE_RATE * xmin)
                f.write(struct.pack(">I", 0))
                f.write(struct.pack(">I", ts))
        f.write(struct.pack(">I", 1))
        f.write(struct.pack(">I", file_length))


# ─── DAT2 packer ─────────────────────────────────────────────────────────────
#
# DAT2 binary layout (little-endian):
#   [Data Block]   raw bytes of every file, concatenated from offset 0
#   [Directory Tree]
#     DWORD  num_files
#     per file: DWORD filename_len, BYTES filename, BYTE is_compressed,
#               DWORD real_size, DWORD packed_size, DWORD offset
#   [Footer]
#     DWORD  tree_size   (bytes)
#     DWORD  file_size   (total DAT bytes)

def _npc_folder(stem):
    import re
    return re.sub(r"\d+$", "", stem).upper()

def collect_dat_entries(msg_paths, acm_dir, lip_dir, txt_dir, skip_acm=False):
    entries = []
    for msg_path in msg_paths:
        if os.path.isfile(msg_path):
            msg_name = os.path.basename(msg_path).upper()
            entries.append((f"text\\english\\dialog\\{msg_name}", msg_path))
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
        if not skip_acm:
            acm_path = os.path.join(acm_dir, stem + ".acm")
            if os.path.isfile(acm_path):
                entries.append((f"{base}\\{stem}.ACM", acm_path))
        txt_path = os.path.join(txt_dir, stem + ".txt")
        if os.path.isfile(txt_path):
            entries.append((f"{base}\\{stem}.txt", txt_path))
    return entries

def write_dat2(out_path, entries):
    # Normalize paths and sort entries alphabetically
    entries = [(d.lower(), l) for d, l in entries]
    entries.sort(key=lambda x: x[0])
    file_data, offsets, cursor = [], [], 0
    for _dat_path, local_path in entries:
        raw = open(local_path, "rb").read()
        file_data.append(raw)
        offsets.append(cursor)
        cursor += len(raw)
    tree = bytearray()
    tree += struct.pack("<I", len(entries))
    for i, (dat_path, _local) in enumerate(entries):
        raw     = file_data[i]
        fn_bytes = dat_path.encode("ascii")
        tree += struct.pack("<I", len(fn_bytes))
        tree += fn_bytes
        tree += struct.pack("<B", 0)
        tree += struct.pack("<I", len(raw))
        tree += struct.pack("<I", len(raw))
        tree += struct.pack("<I", offsets[i])
    tree_size = len(tree)
    file_size = cursor + tree_size + 8
    with open(out_path, "wb") as f:
        for raw in file_data:
            f.write(raw)
        f.write(tree)
        f.write(struct.pack("<I", tree_size))
        f.write(struct.pack("<I", file_size))

# ─── Pipeline ─────────────────────────────────────────────────────────────────

def print_section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def main():
    parser = argparse.ArgumentParser(
        description="V.O.C.K. — Vocal Output Creation Kit\nFallout 2 voice pipeline: MSG+MP3 → TXT+WAV+ACM+LIP+DAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--msg",          default=None,
        help="Path to .MSG file. If omitted, auto-detects from ./msg/")
    parser.add_argument("--mp3dir",       default="mp3")
    parser.add_argument("--txtdir",       default="txt")
    parser.add_argument("--wavdir",       default="wav")
    parser.add_argument("--acmdir",       default="acm")
    parser.add_argument("--textgriddir",  default="textgrid")
    parser.add_argument("--lipdir",       default="lip")
    parser.add_argument("--snd2acm",      default=None,
        help="Path to snd2acm.exe if not on PATH or script folder")
    parser.add_argument("--mfa-env",      default="aligner",
        help="Conda env name where MFA is installed (default: aligner)")
    parser.add_argument("--no-mfa",       action="store_true",
        help="Skip MFA; use text-only phoneme approximation")
    parser.add_argument("--no-acm",       action="store_true",
        help="Skip ACM generation (if snd2acm is not available)")
    parser.add_argument("--no-dat",       action="store_true",
        help="Skip DAT file creation")
    parser.add_argument("--datfile",      default="dat/vock.dat",
        help="Output DAT filename (default: dat/vock.dat)")
    args = parser.parse_args()

    # ── Find and parse MSG file(s) ───────────────────────────────────────────
    print_section("STEP 1 — Parse MSG file(s) → TXT")

    # Collect all MSG paths to process
    msg_paths = []
    if args.msg:
        if os.path.isfile(args.msg):
            msg_paths = [args.msg]
        elif os.path.isdir(args.msg):
            msg_paths = sorted(
                os.path.join(args.msg, f)
                for f in os.listdir(args.msg)
                if f.upper().endswith(".MSG"))
        else:
            sys.exit(f"MSG path not found: '{args.msg}'")
    else:
        msg_dir = "msg"
        if os.path.isdir(msg_dir):
            msg_paths = sorted(
                os.path.join(msg_dir, f)
                for f in os.listdir(msg_dir)
                if f.upper().endswith(".MSG"))
        if not msg_paths:
            sys.exit("No .MSG files found in ./msg/ — pass --msg to specify a file or folder.")

    all_entries = []
    for msg_path in msg_paths:
        print(f"  Reading {msg_path}")
        found = parse_msg(msg_path)
        if not found:
            print(f"  [warn] No audio lines found in '{msg_path}' — skipping.")
            continue
        all_entries.extend(found)
        print(f"  {len(found)} line(s) found.")

    if not all_entries:
        sys.exit("No audio lines found in any MSG file.")

    os.makedirs(args.txtdir, exist_ok=True)
    for tag, text in all_entries:
        out = os.path.join(args.txtdir, f"{tag}.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"  {len(all_entries)} TXT file(s) written to '{args.txtdir}/'")

    entries = all_entries
    txt_map = {tag: text for tag, text in entries}

    # ── Collect audio files (WAV takes priority over MP3) ────────────────────
    # Scan both ./wav/ and ./mp3/ folders. If a WAV already exists for a stem
    # it is used as-is (no conversion needed). MP3s are converted to WAV.
    audio_map = {}   # stem -> (path, needs_conversion)

    wav_src_dir = args.wavdir   # look for pre-existing WAVs here too
    if os.path.isdir(wav_src_dir):
        for f in os.listdir(wav_src_dir):
            if f.upper().endswith(".WAV"):
                stem = os.path.splitext(f)[0]
                audio_map[stem] = (os.path.join(wav_src_dir, f), False)

    if os.path.isdir(args.mp3dir):
        for f in sorted(os.listdir(args.mp3dir)):
            if f.upper().endswith(".MP3"):
                stem = os.path.splitext(f)[0]
                if stem not in audio_map:   # WAV already found? skip MP3
                    audio_map[stem] = (os.path.join(args.mp3dir, f), True)

    if not audio_map:
        sys.exit("No audio files found in wav/ or mp3/ directories.")

    # Match to TXT files
    pairs = []   # [(stem, audio_path, needs_conversion, txt_path)]
    for stem in sorted(audio_map):
        audio_path, needs_conv = audio_map[stem]
        txt_path = os.path.join(args.txtdir, stem + ".txt")
        if not os.path.isfile(txt_path):
            print(f"  [skip] {stem}: no matching TXT (not in MSG file?)")
            continue
        pairs.append((stem, audio_path, needs_conv, txt_path))

    if not pairs:
        sys.exit("No matching audio+TXT pairs found.")

    # ── Audio → WAV ───────────────────────────────────────────────────────────
    print_section("STEP 2 — Prepare WAV files (22050 Hz mono)")
    os.makedirs(args.wavdir, exist_ok=True)

    wav_pairs = []   # [(stem, wav_path, txt_path)]
    for stem, audio_path, needs_conv, txt_path in pairs:
        wav_path = os.path.join(args.wavdir, stem + ".wav")
        if not needs_conv:
            # Already a WAV — normalise to 22050 Hz mono if needed,
            # or just use it directly if it is already in the wav folder.
            if os.path.abspath(audio_path) != os.path.abspath(wav_path):
                try:
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-i", audio_path,
                         "-ar", "22050", "-ac", "1",
                         "-c:a", "pcm_s16le", wav_path],
                        capture_output=True, text=True)
                    if r.returncode != 0:
                        raise RuntimeError(r.stderr.strip())
                    print(f"  normalised {wav_path}")
                except Exception as e:
                    print(f"  [warn] {stem}: ffmpeg normalise failed ({e}), copying as-is")
                    shutil.copy2(audio_path, wav_path)
            else:
                print(f"  using  {wav_path}  (already in wav folder)")
            wav_pairs.append((stem, wav_path, txt_path))
        else:
            try:
                mp3_to_wav(audio_path, wav_path)
                print(f"  wrote  {wav_path}")
                wav_pairs.append((stem, wav_path, txt_path))
            except RuntimeError as e:
                print(f"  [error] {stem}: {e}")

    # ── WAV → ACM ─────────────────────────────────────────────────────────────
    print_section("STEP 3 — Convert WAV → ACM")

    if args.no_acm:
        print("  Skipped (--no-acm)")
    else:
        snd2acm_path = find_snd2acm(args.snd2acm)
        if not snd2acm_path:
            print("  snd2acm not found — skipping ACM generation.")
            print("  Put snd2acm.exe in the same folder as this script to enable it.")
        else:
            os.makedirs(args.acmdir, exist_ok=True)
            acm_ok = 0
            for stem, wav_path, _txt in wav_pairs:
                acm_path = os.path.join(args.acmdir, stem + ".acm")
                try:
                    wav_to_acm(snd2acm_path, wav_path, acm_path)
                    size_kb = os.path.getsize(acm_path) / 1024
                    print(f"  wrote  {acm_path}  ({size_kb:.1f} KB)")
                    acm_ok += 1
                except RuntimeError as e:
                    print(f"  [error] {stem}: {e}")
            print(f"  {acm_ok}/{len(wav_pairs)} ACM file(s) written.")

    # ── MFA alignment ─────────────────────────────────────────────────────────
    print_section("STEP 4 — MFA forced alignment → TextGrid")
    os.makedirs(args.textgriddir, exist_ok=True)

    mfa_ok = False
    if args.no_mfa:
        print("  Skipped (--no-mfa)")
    else:
        # Build a corpus folder: WAV + TXT side by side
        import tempfile
        with tempfile.TemporaryDirectory(prefix="fv_corpus_") as corpus_dir:
            for stem, wav_path, txt_path in wav_pairs:
                shutil.copy2(wav_path, os.path.join(corpus_dir, stem + ".wav"))
                shutil.copy2(txt_path, os.path.join(corpus_dir, stem + ".txt"))

            mfa_tmp_out = os.path.join(corpus_dir, "aligned")
            os.makedirs(mfa_tmp_out)

            mfa_ok = run_mfa(corpus_dir, mfa_tmp_out, args.mfa_env)

            if mfa_ok:
                # Copy TextGrids to permanent textgrid folder
                tg_count = 0
                for f in os.listdir(mfa_tmp_out):
                    if f.endswith(".TextGrid"):
                        shutil.copyfile(
                            os.path.join(mfa_tmp_out, f),
                            os.path.join(args.textgriddir, f))
                        tg_count += 1
                print(f"\n  {tg_count} TextGrid(s) saved to '{args.textgriddir}/'")
            else:
                print("\n  MFA failed — will use text approximation for LIP files.")

    # ── Generate LIP files ────────────────────────────────────────────────────
    print_section("STEP 5 — Generate LIP files")
    os.makedirs(args.lipdir, exist_ok=True)

    lip_ok = 0
    lip_approx = 0
    lip_fail = 0

    for stem, wav_path, txt_path in wav_pairs:
        lip_path = os.path.join(args.lipdir, stem + ".lip")
        tg_path  = os.path.join(args.textgriddir, stem + ".TextGrid")

        try:
            duration = get_audio_duration(wav_path)
        except Exception as e:
            print(f"  [error] {stem}: could not read duration: {e}")
            lip_fail += 1
            continue

        # Try MFA TextGrid first
        if not args.no_mfa and os.path.isfile(tg_path):
            try:
                events = build_events_from_textgrid(tg_path)
                write_lip(lip_path, stem, duration, events)
                print(f"  wrote  {lip_path}  ({duration:.3f}s, {len(events)} events, MFA)")
                lip_ok += 1
                continue
            except Exception as e:
                print(f"  [warn] {stem}: TextGrid error ({e}), falling back to approx")

        # Fallback: text approximation
        text = txt_map.get(stem, "")
        if not text:
            with open(txt_path, encoding="utf-8") as fh:
                text = fh.read().strip()
        events = text_fallback_events(text, duration)
        write_lip(lip_path, stem, duration, events)
        print(f"  wrote  {lip_path}  ({duration:.3f}s, {len(events)} events, approx)")
        lip_approx += 1

    # ── Build DAT file ────────────────────────────────────────────
    print_section("STEP 6 — Build vock.dat")
    if args.no_dat:
        print("  Skipped (--no-dat)")
    else:
        os.makedirs(os.path.dirname(args.datfile) or ".", exist_ok=True)
        try:
            dat_entries = collect_dat_entries(
                msg_paths = msg_paths,
                acm_dir   = args.acmdir,
                lip_dir   = args.lipdir,
                txt_dir   = args.txtdir,
                skip_acm  = args.no_acm,
            )
            if not dat_entries:
                print("  No files to pack — skipping.")
            else:
                write_dat2(args.datfile, dat_entries)
                total_kb = os.path.getsize(args.datfile) / 1024
                print(f"  wrote  {args.datfile}  "
                      f"({len(dat_entries)} files, {total_kb:.1f} KB)")
        except Exception as e:
            print(f"  [error] DAT creation failed: {e}")

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\n{chr(0x2550)*60}")
    print(f"  DONE")
    print(f"{chr(0x2550)*60}")
    print(f"  TXT files : {len(entries)}")
    print(f"  WAV files : {len(wav_pairs)}")
    print(f"  LIP files : {lip_ok} with MFA  +  {lip_approx} approximated"
          f"  ({lip_fail} failed)")
    print(f"  DAT file  : {args.datfile}")
    print(f"  Folders   : {args.txtdir}/  {args.wavdir}/  {args.acmdir}/  "
          f"{args.textgriddir}/  {args.lipdir}/")
    print()


if __name__ == "__main__":
    main()
