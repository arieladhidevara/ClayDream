import argparse
from dataclasses import dataclass
import os
import re
import time
import wave
import queue
import tempfile
from typing import Any

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pythonosc.udp_client import SimpleUDPClient


# =========================
# CONFIG
# =========================

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SEC = 0.25

# Wake/start and stop words
START_WORD = "clay"
STOP_WORD = "dream"
WAKE_WORDS = ("clay", "play", "claim")

# Timing
IDLE_WINDOW_SEC = 3.0
CHECK_IDLE_EVERY_SEC = 0.6
CHECK_ACTIVE_EVERY_SEC = 0.8
MAX_CAPTURE_SEC = 20.0
SILENCE_RESET_SEC = 4.0

# Audio thresholds
MIN_IDLE_RMS = 0.015
VOICE_RMS_THRESHOLD = 0.01

# TouchDesigner OSC
TD_HOST = "127.0.0.1"
TD_PORT = 7000

# Prompt prefix
PROMPT_PREFIX = "statue, green marble sculpture, carved stone, museum artifact of "

# Whisper model
MODEL_NAME = "base.en"

# Optional mic device.
# - Set to an integer index to pin a device explicitly.
# - Set to a string to match part of the input device name.
# - Set to None to auto-pick a likely microphone.
# You can also override at runtime with:
#   CLAYDREAM_MIC="Microphone Array"
#   python voice_to_td.py --device 27
DEVICE = None

HOSTAPI_PREFERENCE = {
    "Windows WASAPI": 40,
    "Windows DirectSound": 30,
    "MME": 20,
    "Windows WDM-KS": 10,
}

PREFERRED_INPUT_TOKENS = (
    "microphone array",
    "usb microphone",
    "headset microphone",
    "microphone",
    "line in",
)

DEPRIORITIZED_INPUT_TOKENS = (
    "webcam",
    "ndi",
    "voicemod",
    "virtual",
    "sound mapper",
    "primary sound capture",
)


# =========================
# GLOBALS
# =========================

audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
osc = SimpleUDPClient(TD_HOST, TD_PORT)
model: WhisperModel | None = None


@dataclass(frozen=True)
class StreamConfig:
    device_index: int
    samplerate: int
    channels: int
    device_label: str
    reason: str


# =========================
# HELPERS
# =========================

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def rms(audio: np.ndarray) -> float:
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def trim_audio(audio: np.ndarray, max_sec: float) -> np.ndarray:
    max_len = int(max_sec * SAMPLE_RATE)
    if len(audio) <= max_len:
        return audio
    return audio[-max_len:]


def contains_wake_word(text: str) -> bool:
    text = normalize_text(text)
    return any(word in text for word in WAKE_WORDS)


def write_temp_wav(audio: np.ndarray) -> str:
    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()

    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())

    return tmp.name


def get_model() -> WhisperModel:
    global model
    if model is None:
        model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return model


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if len(audio) == 0 or source_rate == target_rate:
        return audio.astype(np.float32, copy=False)

    target_len = max(1, int(round(len(audio) * target_rate / source_rate)))
    source_positions = np.arange(len(audio), dtype=np.float32)
    target_positions = np.linspace(0, len(audio) - 1, num=target_len, dtype=np.float32)
    return np.interp(target_positions, source_positions, audio).astype(np.float32)


def transcribe_audio(audio: np.ndarray) -> str:
    if len(audio) < int(SAMPLE_RATE * 0.8):
        return ""

    wav_path = write_temp_wav(audio)
    try:
        segments, _info = get_model().transcribe(
            wav_path,
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300),
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text for seg in segments)
        return normalize_text(text)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def extract_prompt_body(transcript: str) -> str:
    text = normalize_text(transcript)

    for wake in WAKE_WORDS:
        if wake in text:
            text = text.split(wake, 1)[1].strip()
            break

    if STOP_WORD in text:
        text = text.split(STOP_WORD, 1)[0].strip()

    text = normalize_text(text)
    return text


def send_state(state: str) -> None:
    osc.send_message("/state", state)


def send_prompt(prompt: str) -> None:
    osc.send_message("/prompt", prompt)


def build_audio_callback(stream_config: StreamConfig):
    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            print("Audio status:", status)

        if indata.ndim == 1:
            mono = indata.copy()
        elif indata.shape[1] == 1:
            mono = indata[:, 0].copy()
        else:
            mono = np.mean(indata, axis=1, dtype=np.float32)

        processed = resample_audio(
            np.asarray(mono, dtype=np.float32),
            source_rate=stream_config.samplerate,
            target_rate=SAMPLE_RATE,
        )
        audio_queue.put(processed)

    return audio_callback


def list_input_devices() -> None:
    print("\nAvailable audio devices:\n")
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            hostapi_name = hostapis[dev["hostapi"]]["name"]
            print(
                f"[{i}] {dev['name']} | hostapi={hostapi_name} "
                f"| inputs={dev['max_input_channels']} | default_sr={dev['default_samplerate']}"
            )
    print("")


def build_final_prompt(body: str) -> str:
    body = body.strip(" ,")
    return f"{PROMPT_PREFIX}{body}" if body else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Listen for ClayDream voice prompts.")
    parser.add_argument(
        "--device",
        help="Input device index or case-insensitive substring of the device name.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print available input devices and exit.",
    )
    return parser.parse_args()


def is_deprioritized_device(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in DEPRIORITIZED_INPUT_TOKENS)


def device_display_name(index: int, dev: dict[str, Any], hostapis: list[dict[str, Any]]) -> str:
    hostapi_name = hostapis[dev["hostapi"]]["name"]
    return f"[{index}] {dev['name']} ({hostapi_name})"


def normalize_device_hint(device_hint: Any) -> Any:
    if isinstance(device_hint, str):
        stripped = device_hint.strip()
        if not stripped:
            return None
        if stripped.isdigit():
            return int(stripped)
        return stripped
    return device_hint


def build_stream_setting_candidates(dev: dict[str, Any]) -> list[tuple[int, int]]:
    max_channels = int(dev["max_input_channels"])
    default_rate = int(round(float(dev["default_samplerate"])))

    samplerates: list[int] = []
    for rate in (SAMPLE_RATE, default_rate, 48000, 44100):
        if rate > 0 and rate not in samplerates:
            samplerates.append(rate)

    channels: list[int] = []
    for candidate in (CHANNELS, 2, max_channels):
        if 1 <= candidate <= max_channels and candidate not in channels:
            channels.append(candidate)

    return [(rate, channel_count) for rate in samplerates for channel_count in channels]


def find_stream_config(
    index: int,
    dev: dict[str, Any],
    hostapis: list[dict[str, Any]],
    reason_prefix: str,
) -> StreamConfig | None:
    label = device_display_name(index, dev, hostapis)
    for samplerate, channels in build_stream_setting_candidates(dev):
        try:
            sd.check_input_settings(
                device=index,
                samplerate=samplerate,
                channels=channels,
                dtype="float32",
            )
            return StreamConfig(
                device_index=index,
                samplerate=samplerate,
                channels=channels,
                device_label=label,
                reason=f"{reason_prefix}: {label} @ {samplerate} Hz / {channels}ch",
            )
        except sd.PortAudioError:
            continue
    return None


def stream_compatibility_score(stream_config: StreamConfig) -> int:
    score = 0
    if stream_config.samplerate == SAMPLE_RATE:
        score += 50
    elif stream_config.samplerate == 48000:
        score += 15
    else:
        score += 10

    if stream_config.channels == CHANNELS:
        score += 20
    else:
        score += 5

    return score


def resolve_explicit_device(
    device_hint: Any,
    input_devices: list[tuple[int, dict[str, Any]]],
    hostapis: list[dict[str, Any]],
) -> StreamConfig:
    normalized_hint = normalize_device_hint(device_hint)
    if normalized_hint is None:
        raise ValueError("Device hint cannot be empty.")

    if isinstance(normalized_hint, int):
        for index, dev in input_devices:
            if index == normalized_hint:
                stream_config = find_stream_config(
                    index,
                    dev,
                    hostapis,
                    reason_prefix="explicit index",
                )
                if stream_config is None:
                    raise ValueError(
                        f"Input device index {normalized_hint} exists but no supported stream format was found."
                    )
                return stream_config
        raise ValueError(f"Input device index {normalized_hint} was not found.")

    query = normalized_hint.lower()
    exact_matches: list[tuple[int, dict[str, Any]]] = []
    partial_matches: list[tuple[int, dict[str, Any]]] = []

    for index, dev in input_devices:
        name = str(dev["name"])
        lowered = name.lower()
        if lowered == query:
            exact_matches.append((index, dev))
        elif query in lowered:
            partial_matches.append((index, dev))

    matches = exact_matches or partial_matches
    if not matches:
        raise ValueError(f"No input device matched '{normalized_hint}'.")

    stream_matches: list[tuple[int, StreamConfig]] = []
    for index, dev in matches:
        stream_config = find_stream_config(
            index,
            dev,
            hostapis,
            reason_prefix="explicit match",
        )
        if stream_config is None:
            continue

        score = HOSTAPI_PREFERENCE.get(hostapis[dev["hostapi"]]["name"], 0)
        score += stream_compatibility_score(stream_config)
        stream_matches.append((score, stream_config))

    if not stream_matches:
        raise ValueError(f"Input device '{normalized_hint}' matched, but no supported stream format was found.")

    stream_matches.sort(key=lambda item: item[0], reverse=True)
    return stream_matches[0][1]


def auto_pick_input_device(
    input_devices: list[tuple[int, dict[str, Any]]],
    hostapis: list[dict[str, Any]],
) -> StreamConfig:
    default_input, _default_output = sd.default.device
    best_score = None
    best_choice: StreamConfig | None = None

    for index, dev in input_devices:
        stream_config = find_stream_config(
            index,
            dev,
            hostapis,
            reason_prefix="auto-picked",
        )
        if stream_config is None:
            continue

        name = str(dev["name"])
        lowered = name.lower()
        hostapi_name = hostapis[dev["hostapi"]]["name"]
        score = HOSTAPI_PREFERENCE.get(hostapi_name, 0)
        score += stream_compatibility_score(stream_config)

        for rank, token in enumerate(PREFERRED_INPUT_TOKENS):
            if token in lowered:
                score += 60 - (rank * 8)
                break

        if is_deprioritized_device(name):
            score -= 100
        elif isinstance(default_input, int) and index == default_input:
            score += 25

        if best_score is None or score > best_score:
            best_score = score
            best_choice = stream_config

    if best_choice is None:
        raise RuntimeError("No supported audio input stream format was found.")

    if isinstance(default_input, int) and best_choice.device_index != default_input:
        return StreamConfig(
            device_index=best_choice.device_index,
            samplerate=best_choice.samplerate,
            channels=best_choice.channels,
            device_label=best_choice.device_label,
            reason=(
                "auto-picked because the system default looked less suitable: "
                f"{best_choice.device_label} @ {best_choice.samplerate} Hz / {best_choice.channels}ch"
            ),
        )

    return StreamConfig(
        device_index=best_choice.device_index,
        samplerate=best_choice.samplerate,
        channels=best_choice.channels,
        device_label=best_choice.device_label,
        reason=(
            "auto-picked preferred input: "
            f"{best_choice.device_label} @ {best_choice.samplerate} Hz / {best_choice.channels}ch"
        ),
    )


def resolve_input_device(device_hint: Any) -> StreamConfig:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    input_devices = [
        (index, dev)
        for index, dev in enumerate(devices)
        if dev["max_input_channels"] > 0
    ]

    if not input_devices:
        raise RuntimeError("No audio input devices were found.")

    if device_hint is not None:
        return resolve_explicit_device(device_hint, input_devices, hostapis)

    env_hint = os.getenv("CLAYDREAM_MIC")
    if env_hint:
        return resolve_explicit_device(env_hint, input_devices, hostapis)

    return auto_pick_input_device(input_devices, hostapis)


# =========================
# MAIN
# =========================

def main(device_hint: Any = DEVICE) -> None:
    idle_audio = np.zeros(0, dtype=np.float32)
    capture_audio = np.zeros(0, dtype=np.float32)

    state = "idle"
    last_idle_check = 0.0
    last_active_check = 0.0
    last_voice_time = time.monotonic()

    print("Starting voice listener...")
    print(f"TouchDesigner target: {TD_HOST}:{TD_PORT}")
    print(f"Say '{START_WORD}' to start, '{STOP_WORD}' to finish and send.\n")

    stream_config = resolve_input_device(device_hint)
    stream_blocksize = int(round(stream_config.samplerate * BLOCK_SEC))
    print(f"Using input device: {stream_config.reason}")
    print("Use --list-devices to inspect inputs, or override with --device / CLAYDREAM_MIC.\n")

    send_state("idle")

    with sd.InputStream(
        device=stream_config.device_index,
        samplerate=stream_config.samplerate,
        channels=stream_config.channels,
        dtype="float32",
        blocksize=stream_blocksize,
        callback=build_audio_callback(stream_config),
    ):
        print("Listening...\n")

        while True:
            chunk = audio_queue.get()
            now = time.monotonic()

            if state == "idle":
                idle_audio = np.concatenate([idle_audio, chunk])
                idle_audio = trim_audio(idle_audio, IDLE_WINDOW_SEC)

                if now - last_idle_check >= CHECK_IDLE_EVERY_SEC:
                    last_idle_check = now

                    current_rms = rms(idle_audio)
                    if current_rms < MIN_IDLE_RMS:
                        continue

                    text = transcribe_audio(idle_audio)

                    if text:
                        print(f"[idle] {text} | rms={current_rms:.4f}")

                    if contains_wake_word(text):
                        state = "active"
                        capture_audio = idle_audio.copy()
                        last_active_check = 0.0
                        last_voice_time = now
                        send_state("listening")
                        print("Wake word detected. Capturing prompt...\n")

            else:
                capture_audio = np.concatenate([capture_audio, chunk])
                capture_audio = trim_audio(capture_audio, MAX_CAPTURE_SEC)

                chunk_rms = rms(chunk)
                if chunk_rms > VOICE_RMS_THRESHOLD:
                    last_voice_time = now

                if now - last_active_check >= CHECK_ACTIVE_EVERY_SEC:
                    last_active_check = now
                    text = transcribe_audio(capture_audio)

                    if text:
                        print(f"[active] {text}")

                    if STOP_WORD in text:
                        body = extract_prompt_body(text)

                        if body:
                            final_prompt = build_final_prompt(body)
                            send_prompt(final_prompt)
                            print(f"\nSENT TO TD:\n{final_prompt}\n")
                        else:
                            print("\nStop word found, but prompt body was empty.\n")

                        state = "idle"
                        idle_audio = np.zeros(0, dtype=np.float32)
                        capture_audio = np.zeros(0, dtype=np.float32)
                        send_state("idle")
                        print("Reset to idle.\n")

                    elif now - last_voice_time > SILENCE_RESET_SEC:
                        print("\nSilence timeout. Reset to idle.\n")
                        state = "idle"
                        idle_audio = np.zeros(0, dtype=np.float32)
                        capture_audio = np.zeros(0, dtype=np.float32)
                        send_state("idle")


if __name__ == "__main__":
    args = parse_args()
    if args.list_devices:
        list_input_devices()
    else:
        main(device_hint=args.device if args.device is not None else DEVICE)
