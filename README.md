# V.O.C.K. — Vocal Output Creation Kit

A Python script that automates the complete voice modding pipeline for Fallout 2.
Give it a `.MSG` dialogue file and a folder of audio files (mp3 or wav) — it produces a ready-to-install `vock.dat` containing ACM audio, LIP sync, and dialogue files.

## What it does

```
  MSG ────────────────────────────────────────────────► TXT (one per line)
  WAV or MP3 ──[Normalize and encode]───► wav-enc/ ───► ACM (via snd2acm)
                                              │
                                   [MFA align / approximation]
                                              │
                                        TextGrid ─────► LIP (Fallout format)

  MSG + TXT + ACM + LIP ──────────────────────────────► DAT (vock.dat)
```


## Output DAT structure

```
text\english\dialog\*.msg
sound\speech\<npc>\*.acm
sound\speech\<npc>\*.lip
sound\speech\<npc>\*.txt
```

Where `<npc>` is the identifier for that particular NPC. For example, Aunt Morlis is identified by MOR:
```
text\english\dialog\acmorlis.msg
sound\speech\mor\mor1.acm
sound\speech\mor\mor1.lip
sound\speech\mor\mor1.txt
...
```

The NPC folder name is derived automatically from the audio tags in the MSG file (e.g. `MOR1` → `MOR`).

## Folder structure

```
vock/
├── vock.py
├── snd2acm.exe          ← download separately (see Requirements)
├── msg/                 ← put your .MSG file(s) here
├── mp3/                 ← put your .MP3 files here
├── wav/                 ← put your .WAV files here (any sample rate / bit depth)
├── txt/                 ← generated: one .txt per audio line
├── wav-enc/             ← generated: 22050 Hz mono 16-bit PCM (ready for ACM)
├── acm/                 ← generated: Fallout 2 ACM audio files
├── textgrid/            ← generated: MFA alignment TextGrid files
├── lip/                 ← generated: Fallout 2 LIP files
└── dat/
    └── vock.dat         ← generated: ready-to-install Fallout 2 DAT archive
```

## Requirements

### 1. Environment Setup (Windows)
WSL (Windows Subsystem for Linux) is recommended to run the Linux-based alignment tools. Open Windows PowerShell as Administrator and run:
```powershell
wsl --install
```
Follow the prompts in the new terminal window to create your Linux username and password.

### 2. System Dependencies (Linux/WSL)
Update package lists:
```bash
sudo apt update && sudo apt upgrade -y
```

### 3. FFmpeg
Required for audio processing:
```bash
sudo apt install ffmpeg -y
```

### 4. snd2acm
The only known ACM encoder for Fallout 2, by ABel/TeamX.

Download: https://fodev.net/files/mirrors/teamx-utils/snd2acm.rar

Extract and place `snd2acm.exe` in the same folder as `vock.py`. Install Wine to run it:
```bash
sudo apt install wine -y
```

### 5. Montreal Forced Aligner (MFA)
Used for accurate per-phoneme lip sync timing.

```bash
# Install Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b
~/miniconda3/bin/conda init bash && exec bash

# Accept the ToS
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Create the MFA 'aligner' environment and activate it
conda create -n aligner -c conda-forge montreal-forced-aligner python=3.10 -y
conda activate aligner

# Download the English US acoustic models and dictionaries
mfa model download acoustic   english_us_arpa
mfa model download dictionary english_us_arpa
```

## Usage

```bash
conda activate aligner
python3 vock.py
```

The script auto-detects your `.MSG` file(s) from `./msg/` and your audio files from `./mp3/` and/or `./wav/`.

### Options

```
--msg PATH        Path to a .MSG file or folder (default: ./msg/)
--mp3dir DIR      MP3 input folder (default: ./mp3)
--wavdir DIR      WAV input folder — user-supplied files (default: ./wav)
--wavencdir DIR   Encoded WAV output folder (default: ./wav-enc)
--acmdir DIR      ACM output folder (default: ./acm)
--txtdir DIR      TXT output folder (default: ./txt)
--textgriddir DIR TextGrid output folder (default: ./textgrid)
--lipdir DIR      LIP output folder (default: ./lip)
--datfile PATH    Output DAT file path (default: dat/vock.dat)
--snd2acm PATH    Path to snd2acm.exe if not in script folder
--mfa-env NAME    Conda environment name (default: aligner)
--lufs FLOAT      Target loudness in LUFS for normalization (default: -16.0)
--no-norm         Skip EBU R128 loudness normalization during the encode step
--steps STEP ...  Run only the specified step(s): msg wav enc acm mfa lip dat
--no-enc          Skip audio collection, WAV encoding, and ACM generation (wav, enc, acm steps)
--no-mfa          Skip MFA; use text-only phoneme approximation
--no-acm          Skip ACM generation only (enc still runs)
--no-dat          Skip DAT file creation
```

### Examples

```bash
# Full pipeline
python3 vock.py

# Custom DAT filename
python3 vock.py --datfile dat/patch001.dat

# Disable loudness normalization completely
python3 vock.py --no-norm

# Adjust the target loudness (e.g. make it slightly quieter)
python3 vock.py --lufs -18.0

# Skip encoding and ACM (WAV-only workflow without snd2acm)
python3 vock.py --no-enc

# Skip ACM only (encode still runs; useful to inspect wav-enc/ first)
python3 vock.py --no-acm

# Skip MFA (faster, less accurate lip sync)
python3 vock.py --no-mfa

# Generate everything except the DAT
python3 vock.py --no-dat
```

### Running individual steps

Use `--steps` to run only specific parts of the pipeline. This is useful when
files from a previous run already exist and you only need to redo one step.

Available steps: `msg` `wav` `enc` `acm` `mfa` `lip` `dat`

```bash
# Rebuild just the DAT from existing files
python3 vock.py --steps dat

# Re-run MFA alignment and regenerate LIP files
python3 vock.py --steps mfa lip

# Re-run MFA, LIP, and DAT together
python3 vock.py --steps mfa lip dat

# Re-encode and convert to ACM only (e.g. after replacing audio files)
python3 vock.py --steps enc acm

# Re-run everything from encoding onwards (skip MSG parsing and audio collection)
python3 vock.py --steps enc acm mfa lip dat

# Re-run encoding only (e.g. to inspect wav-enc/ before committing to ACM)
python3 vock.py --steps enc
```

When using `--steps`, skipped steps print `[skipped]` in the console so you can confirm what ran. Files from previous runs in the output folders are used as-is by later steps — it is your responsibility to ensure they are up to date.

## Notes

- **WAV takes priority over MP3.** If both exist for the same file stem, the WAV is used and the MP3 is ignored.
- **Loudness Normalization.** Audio is automatically normalized to -16 LUFS via EBU R128 during the `enc` step to match original game files. Use `--no-norm` to disable this or `--lufs` to change the target.
- **`wav/` is for source files; `wav-enc/` is for output.** Files in `wav/` can be any sample rate or bit depth — the `enc` step normalises everything to 22050 Hz mono 16-bit PCM. `wav-enc/` is what `snd2acm` and MFA actually read.
- **`--no-enc` skips audio collection, encoding, and ACM.** Because `enc` depends on `wav`, and `acm` depends on `wav-enc/` output, passing `--no-enc` automatically drops all three (`wav`, `enc`, `acm`) from the run, preventing snd2acm from being fed incorrectly formatted files.
- **`--no-acm` skips ACM only.** The `enc` step still runs and `wav-enc/` is populated. Useful if you want to inspect the encoded audio before committing to ACM generation.
- **MFA fallback.** If MFA fails on a specific file (e.g. an unrecognised word), that file falls back to text-based phoneme approximation automatically. The rest of the batch continues normally.
- **ACM files are optional in the DAT.** If ACM files are missing (e.g. you ran with `--no-enc` or `--no-acm`), the DAT will still contain LIP and TXT files.
- **snd2acm on Linux.** Install Wine (`sudo apt install wine`) and the script will invoke `snd2acm.exe` through Wine automatically.

## LIP file format

The LIP binary format was reverse-engineered from Black_Electric's LIPS.py and validated against LIP Editor. Key constants:

- Version: `0x00000002`
- Unknown constant at `0x04`: `0x00005800`
- Sample offset formula: `round(seconds × 2 × 22050)`
- ACM filename field: 8 bytes, uppercase, null-padded, followed by `VOC\0`

## DAT file format

Uses the Fallout 2 DAT2 format (little-endian). Files are stored uncompressed. Format documented at https://fodev.net/files/fo2/dat.html

## How to obtain the MSG file

You must own a legal copy of Fallout 2 to do this.

**fo2dat** is a tool used to unpack Fallout 2 DAT files. You need to build it from source.
```bash
sudo apt install rustc cargo -y
git clone https://github.com/adamkewley/fo2dat
cd fo2dat
cargo build --release
sudo cp target/release/fo2dat /usr/local/bin/
```

Once built, extract the dialogue files from your master.dat:
```bash
mkdir master
fo2dat -xf master.dat -C master
```

Copy the specific .MSG file you want to edit into the `vock/msg/` folder.

## How to edit the MSG file

To make your NPC talk, you must link the dialogue lines to audio tags:
1. Open your .MSG file (e.g., ACMORLIS.MSG) in a text editor.
2. Locate the line you want to add voice to.
3. The format is: `{103}{}{What is it? You know I have a lot to do!}`.
4. Add your audio "tag" in the middle bracket: `{103}{MOR1}{What is it? You know I have a lot to do!}`.
5. Save your audio file as `MOR1.mp3`. The script will see the MOR1 tag in the MSG and look for mp3/MOR1.mp3.

## Other useful tools

LIP Editor: https://fodev.net/files/mirrors/teamx-utils/LIPEditor0.96b.rar
