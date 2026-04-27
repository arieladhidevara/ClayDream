# ClayDream

A voice-driven generative sculpture installation. Speak a wake word, describe an object, and ClayDream sends the prompt to TouchDesigner to generate a green-marble statue of whatever you said. Captures stream into a wall-style gallery designed for a vertical monitor.

## How it works

```
mic → faster-whisper (local STT) → OSC → TouchDesigner → image capture
                                                              │
                                                              ▼
                                              captures/ ── HTTP gallery
```

1. **`scripts/voice_to_td.py`** listens on the default microphone, runs local speech-to-text with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and watches for the wake word **"clay"** and stop word **"dream"**.
2. Whatever was said between the two words becomes the prompt body, prefixed with `statue, green marble sculpture, carved stone, museum artifact of `, and sent to TouchDesigner over OSC at `127.0.0.1:7000`.
3. **`ClayDream.toe`** generates the image and writes it to `captures/`.
4. **`server.py`** + **`index.html`** serve a fullscreen scrolling gallery of every capture, laid out as a 5×3 grid optimized for a vertical (portrait) monitor.

## Requirements

- Python 3.10+
- [TouchDesigner](https://derivative.ca/) (any recent build)
- A working microphone

Python dependencies:

```bash
python -m venv venv
source venv/bin/activate          # on Windows: venv\Scripts\activate
pip install numpy sounddevice faster-whisper python-osc
```

The first run downloads the Whisper `base.en` model (~140 MB).

## Running

**1. Start the gallery server**

```bash
python server.py
```

Open `http://localhost:8000` and put it on your vertical display. Press `F11` for fullscreen, or launch Chrome in kiosk mode:

```bash
chrome --kiosk http://localhost:8000
```

**2. Open the TouchDesigner project**

Open `ClayDream.toe`. Make sure the OSC In DAT is listening on port `7000` and the capture node writes PNGs into `captures/`.

**3. Start the voice listener**

```bash
python scripts/voice_to_td.py
```

Pin a specific input device if auto-pick guesses wrong:

```bash
python scripts/voice_to_td.py --list-devices
python scripts/voice_to_td.py --device 27
# or
CLAYDREAM_MIC="Microphone Array" python scripts/voice_to_td.py
```

## Speaking to it

> "**Clay**, an angry octopus holding a teacup, **dream**."

→ TouchDesigner receives:

```
statue, green marble sculpture, carved stone, museum artifact of an angry octopus holding a teacup
```

Wake word matching is fuzzy (`clay`, `play`, `claim` all trigger), so transcription slip-ups don't ruin the flow. If you go silent for ~4 seconds without saying `dream`, it resets to idle.

## Configuration

Most knobs live at the top of [`scripts/voice_to_td.py`](scripts/voice_to_td.py):

| Setting | Purpose |
| --- | --- |
| `START_WORD` / `STOP_WORD` | Wake / commit phrases |
| `PROMPT_PREFIX` | What gets prepended to every prompt |
| `MAX_CAPTURE_SEC` | Hard cap on prompt length |
| `SILENCE_RESET_SEC` | Auto-reset after this much silence |
| `TD_HOST` / `TD_PORT` | OSC target |
| `MODEL_NAME` | Any faster-whisper model (e.g. `tiny.en`, `small.en`) |

Gallery layout (rows, columns, scroll speed) lives in [`index.html`](index.html). Defaults: 5 rows × 3 columns, animation kicks in once you have more than 15 captures.

## Project layout

```
ClayDream/
├── ClayDream.toe          # TouchDesigner project
├── server.py              # Gallery HTTP server
├── index.html             # Gallery frontend
├── scripts/
│   └── voice_to_td.py     # Voice → OSC bridge
├── captures/              # Generated images (gitignored)
├── logo.png
└── background.png
```

## License

Personal project. No license attached — ask before reusing.
