# ClayDream

A real-time AI sculpting installation. Shape clay with your hands, point a camera at it, and watch TouchDesigner reimagine it as a generated image — a marble bust, a creature, an artifact, whatever the prompt asks for. Captures stream into a wall-style gallery designed for a vertical display.

## The idea

Physical clay is the input. The camera sees the silhouette and surface you've sculpted, TouchDesigner runs it through an image-generation pipeline that's conditioned on what the camera sees, and the result is a stylized render of your sculpture. Reshape the clay, the output changes. Talk to it (optional), the prompt changes.

```
       hands
         │
         ▼
       clay  ──── camera ────►  TouchDesigner (AI gen)  ────► captures/
                                       ▲                            │
                                  voice prompt                       ▼
                                  (optional)                  HTTP gallery
```

## What's in this repo

| File | Role |
| --- | --- |
| `ClayDream.toe` | **The main project.** Camera capture, AI image generation, output to `captures/`. |
| `scripts/voice_to_td.py` | Optional voice control — sends a spoken prompt to TouchDesigner over OSC. |
| `server.py` + `index.html` | Gallery server that displays everything in `captures/` as a scrolling 5×3 grid for a vertical monitor. |
| `background.png`, `logo.png` | Display assets. |

## Running it

### 1. The main installation (TouchDesigner)

Open `ClayDream.toe` in TouchDesigner. Make sure:

- A camera is connected and the Video Device In is reading from it.
- The capture node is writing PNGs into `./captures/`.

This is the core experience — sculpt clay in front of the camera and the AI generation updates live.

### 2. The gallery (optional but recommended)

```bash
python server.py
```

Open `http://localhost:8000` on a vertical monitor. Press **F11** for fullscreen, or use kiosk mode:

```bash
chrome --kiosk http://localhost:8000
```

The page polls `captures/` every 2 seconds, so anything TouchDesigner saves shows up automatically. Layout is 5 rows × 3 columns; once you have more than 15 captures, alternating rows scroll left/right.

### 3. Voice prompts (optional)

If you want spoken prompts on top of the camera input:

```bash
python -m venv venv
venv\Scripts\activate                       # Windows
# source venv/bin/activate                  # macOS / Linux
pip install numpy sounddevice faster-whisper python-osc

python scripts/voice_to_td.py
```

Speak: **"Clay, _whatever you want_, dream."** Everything between `clay` and `dream` becomes the prompt body, prepended with `statue, green marble sculpture, carved stone, museum artifact of …`, and sent to TouchDesigner over OSC at `127.0.0.1:7000`.

Pin a specific mic if auto-pick guesses wrong:

```bash
python scripts/voice_to_td.py --list-devices
python scripts/voice_to_td.py --device 27
# or
CLAYDREAM_MIC="Microphone Array" python scripts/voice_to_td.py
```

The first run downloads the Whisper `base.en` model (~140 MB).

## Configuration

**Voice listener** — knobs at the top of [`scripts/voice_to_td.py`](scripts/voice_to_td.py):

| Setting | Purpose |
| --- | --- |
| `START_WORD` / `STOP_WORD` | Wake / commit phrases |
| `PROMPT_PREFIX` | What gets prepended to every spoken prompt |
| `MAX_CAPTURE_SEC` | Hard cap on prompt length |
| `SILENCE_RESET_SEC` | Auto-reset after this much silence |
| `TD_HOST` / `TD_PORT` | OSC target |
| `MODEL_NAME` | Any faster-whisper model (`tiny.en`, `small.en`, …) |

**Gallery** — layout, scroll speed, and animate threshold live in [`index.html`](index.html). Defaults are tuned for a vertical monitor.

## Project layout

```
ClayDream/
├── ClayDream.toe          # TouchDesigner project (main)
├── server.py              # Gallery HTTP server
├── index.html             # Gallery frontend
├── scripts/
│   └── voice_to_td.py     # Voice → OSC bridge (optional)
├── captures/              # Generated images (gitignored, created at runtime)
├── logo.png
└── background.png
```

## Requirements

- [TouchDesigner](https://derivative.ca/) (any recent build)
- A camera (webcam or external)
- Python 3.10+ — only needed for the gallery server and the optional voice listener

## License

Personal project. No license attached — ask before reusing.
