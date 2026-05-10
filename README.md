# V.O.C.K. — Vocal Output Creation Kit

A Python script that automates the complete voice modding pipeline for Fallout 2.
Give it a `.MSG` dialogue file and a folder of audio files (mp3 or wav) — it produces a ready-to-install `vock.dat` containing ACM audio, LIP sync, and dialogue files.

## What it does

```
  MSG  ──────────────────────────────────────────► TXT (one per line)
  MP3  ──[FFmpeg 22050Hz mono]──► WAV  ──────────► ACM (via snd2acm)
                                   │
                        [MFA align / approximation]
                                   │
                              TextGrid ──────────► LIP (Fallout format)
                              
  MSG + TXT + ACM + LIP ──► vock.dat
```

All intermediate files (WAV, TextGrid) are kept permanently so you can re-run individual steps without redoing everything.

## Output DAT structure

```
text\english\dialog\*.MSG
sound\Speech\NPC\*.ACM
sound\Speech\NPC\*.lip
sound\Speech\NPC\*.txt
```

Where NPC is the identifier for that particular NPC. For example, Aunt Morlis is identified by MOR:
```
text\english\dialog\ACMORLIS.MSG
sound\Speech\MOR\MOR1.ACM
sound\Speech\MOR\MOR1.lip
sound\Speech\MOR\MOR1.txt
...
```

The NPC folder name is derived automatically from the audio tags in the MSG file (e.g. `MOR1` → `MOR`).

## Folder structure

```
your_npc_folder/
├── vock.py
├── snd2acm.exe          ← download separately (see Requirements)
├── msg/                 ← put your .MSG file(s) here
├── mp3/                 ← put your .MP3 files here (or use wav/)
├── wav/                 ← generated: 22050 Hz mono WAV files
├── txt/                 ← generated: one .txt per audio line
├── acm/                 ← generated: Fallout 2 ACM audio files
├── textgrid/            ← generated: MFA alignment TextGrid files
├── lip/                 ← generated: Fallout 2 LIP files
└── dat/
    └── vock.dat         ← generated: ready-to-install Fallout 2 DAT archive
```

## Requirements

### 1. FFmpeg
```bash
sudo apt install ffmpeg
```

### 2. snd2acm
The only known ACM encoder for Fallout 2, by ABel/TeamX.

Download: https://fodev.net/files/mirrors/teamx-utils/snd2acm.rar

Extract and place `snd2acm.exe` in the same folder as `vock.py`. Install Wine to run it:
```bash
sudo apt install wine
```

Change capitalization to match the script:
```bash
mv SND2ACM.EXE snd2acm.exe
```

### 3. Montreal Forced Aligner (MFA)
Used for accurate per-phoneme lip sync timing. One-time setup:

```bash
# Install Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b
~/miniconda3/bin/conda init bash && exec bash

# Create the MFA environment
conda create -n aligner -c conda-forge montreal-forced-aligner python=3.10 -y

# Download the English models (once only)
conda activate aligner
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
--wavdir DIR      WAV folder — input and output (default: ./wav)
--acmdir DIR      ACM output folder (default: ./acm)
--txtdir DIR      TXT output folder (default: ./txt)
--textgriddir DIR TextGrid output folder (default: ./textgrid)
--lipdir DIR      LIP output folder (default: ./lip)
--datfile PATH    Output DAT file path (default: dat/vock.dat)
--snd2acm PATH    Path to snd2acm.exe if not in script folder
--mfa-env NAME    Conda environment name (default: aligner)
--no-mfa          Skip MFA; use text-only phoneme approximation
--no-acm          Skip ACM generation
--no-dat          Skip DAT file creation
```

### Examples

```bash
# Full pipeline
python3 vock.py

# Custom DAT filename
python3 vock.py --datfile dat/patch001.dat

# Skip ACM (if snd2acm not available yet)
python3 vock.py --no-acm

# Skip MFA (faster, less accurate lip sync)
python3 vock.py --no-mfa

# Generate everything except the DAT
python3 vock.py --no-dat
```

## Notes

- **WAV takes priority over MP3.** If both exist for the same file stem, the WAV is used and the MP3 is ignored.
- **MFA fallback.** If MFA fails on a specific file (e.g. an unrecognised word), that file falls back to text-based phoneme approximation automatically. The rest of the batch continues normally.
- **ACM files are optional in the DAT.** If ACM files are missing (e.g. you ran with `--no-acm`), the DAT will still contain LIP and TXT files.
- **snd2acm on Linux.** Install Wine (`sudo apt install wine`) and the script will invoke `snd2acm.exe` through Wine automatically.

## LIP file format

The LIP binary format was reverse-engineered from BlackElectric's LIPS.py and validated against LIP Editor. Key constants:

- Version: `0x00000002`
- Unknown constant at `0x04`: `0x00005800`
- Sample offset formula: `round(seconds × 2 × 22050)`
- ACM filename field: 8 bytes, uppercase, null-padded, followed by `VOC\0`

## DAT file format

Uses the Fallout 2 DAT2 format (little-endian). Files are stored uncompressed. Format documented at https://fodev.net/files/fo2/dat.html

## How to obtain the MSG file

You must own a legal copy of Fallout 2 to do this.

1. Install fo2dat: fo2dat is a tool used to unpack Fallout MASTER.DAT files.
```bash
pip install fo2dat
```

2. Extract the MSG files: Find your MASTER.DAT file (usually in the Fallout 2 installation folder). Run the following command to extract the dialogue files:
```bash
mkdir master
fo2dat -xf master.dat -C master
```

3. Copy the specific .MSG file you want to edit into the `vock/msg/` folder.

## How to edit the MSG file

To make your NPC talk, you must link the dialogue lines to audio tags:
1. Open your .MSG file (e.g., ACMORLIS.MSG) in a text editor.
2. Locate the line you want to add voice to.
3. The format is: `{103}{}{What is it? You know I have a lot to do!}`.
4. Add your audio "tag" in the middle bracket: `{103}{MOR1}{What is it? You know I have a lot to do!}`.
5. Save your audio file as `MOR1.mp3`. The script will see the MOR1 tag in the MSG and look for mp3/MOR1.mp3.

## License

MIT — do whatever you want with it.
