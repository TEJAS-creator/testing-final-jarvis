#!/usr/bin/env python3
"""
Jarvis Zero-Latency Conversational Voice Listener
Features:
- Instant 0ms local wake-up acknowledgment: plays pre-rendered `on_it.mp3` directly via pygame.mixer.
- Real-time openWakeWord detection (Threshold: 0.20).
- Ultra-responsive Silero VAD boundary detection with 350ms silence cutoff.
- No network delay or subprocess spawn lag for wake-up confirmation.
- Direct multipart HTTP POST dispatch to n8n webhook.
"""

import os
import sys
import time
import subprocess
import wave
import requests
import numpy as np
import pyaudio
import pygame
import threading
import json
import collections
from dotenv import load_dotenv

# Suppress Pygame banner
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Load environment configuration
load_dotenv()

from jarvis_config import (
    JARVIS_CORE_DIR,
    get_target_repo,
    set_active_project,
    get_project_name,
    is_n8n_online,
    ensure_n8n_running,
    get_current_git_branch,
    launch_hud,
)

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/jarvis-git").strip()

PROJECT_ROOT = JARVIS_CORE_DIR
OUTPUT_AUDIO_FILE = os.path.join(PROJECT_ROOT, "recorded_command.wav")
ON_IT_AUDIO = os.path.join(PROJECT_ROOT, "on_it.mp3")
LISTENING_AUDIO = os.path.join(PROJECT_ROOT, "listening.mp3")
WAKE_CHIME_AUDIO = os.path.join(PROJECT_ROOT, "wake_chime.wav")

# Audio & Wake Word Parameters
THRESHOLD = 0.20
RATE = 16000
CHUNK = 1280  # 80ms chunks
FORMAT = pyaudio.paInt16
CHANNELS = 1

# VAD Parameters (Tuned for high sensitivity & zero word clipping)
SILENCE_TIMEOUT_MS = 1200      # 1200ms silence cutoff allows natural speech pauses without premature cutoff
INITIAL_WAIT_TIMEOUT_SEC = 5.0  # Allow up to 5 seconds for user to begin speaking after wake
MIN_SPEECH_CHUNKS = 3          # ~240ms minimum speech to avoid transient clicks
MAX_RECORDING_SEC = 15         # Safety cap
VAD_SPEECH_THRESHOLD = 0.18    # Lowered from 0.38 so soft syllables ('can you') are captured
RMS_ENERGY_THRESHOLD = 85.0    # Lowered from 350.0 so standard conversational speech is recognized
PREROLL_CHUNKS = 8             # 8 chunks * 80ms = 640ms pre-roll rolling buffer preserves initial words

pipeline_running = threading.Event()
current_speech_proc = None

def stop_all_speech():
    """Immediately terminates all active TTS speech processes and audio playback."""
    global current_speech_proc
    try:
        with open(os.path.join(PROJECT_ROOT, "jarvis_stop.flag"), "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass

    if current_speech_proc and current_speech_proc.poll() is None:
        try:
            current_speech_proc.terminate()
            current_speech_proc.kill()
        except Exception:
            pass
        current_speech_proc = None

    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass

    try:
        from speak import stop_all_speech as speak_stop
        speak_stop()
    except Exception:
        pass

def speak_phrase(phrase: str):
    """Speaks phrase with process tracking so it can be interrupted/stopped immediately."""
    global current_speech_proc
    if not phrase:
        return
    # Clear stop flag before new speech begins
    stop_file = os.path.join(PROJECT_ROOT, "jarvis_stop.flag")
    if os.path.exists(stop_file):
        try:
            os.remove(stop_file)
        except Exception:
            pass

    try:
        current_speech_proc = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT_ROOT, "speak.py"), phrase],
            cwd=PROJECT_ROOT
        )
        current_speech_proc.wait()
    except Exception as e:
        print(f"[Jarvis] Speech error: {e}", file=sys.stderr)
    finally:
        current_speech_proc = None

def flush_audio_stream(stream: pyaudio.Stream):
    """Flushes any buffered audio frames from the stream to eliminate speaker echo and stale chunks."""
    try:
        while stream.get_read_available() > 0:
            stream.read(stream.get_read_available(), exception_on_overflow=False)
    except Exception:
        pass

def launch_hud_interface():
    """Seamlessly launches the Jarvis Sci-Fi HUD in a non-blocking background subprocess."""
    target_dir = get_target_repo()
    launch_hud(target_dir)

def ensure_wake_chime():
    """Generates a subtle, pleasant 140ms sci-fi chime if not present on disk."""
    if os.path.exists(WAKE_CHIME_AUDIO):
        return
    try:
        sample_rate = 24000
        duration = 0.14
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        freq1 = np.linspace(880, 1174, len(t))
        freq2 = np.linspace(1320, 1760, len(t))
        envelope = np.exp(-t * 20)
        signal = (0.5 * np.sin(2 * np.pi * freq1 * t) + 0.3 * np.sin(2 * np.pi * freq2 * t)) * envelope
        audio_data = (signal * 32767 * 0.35).astype(np.int16)
        with wave.open(WAKE_CHIME_AUDIO, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
    except Exception:
        pass

def play_instant_wake_acknowledgment():
    """Plays non-blocking 140ms sci-fi acknowledgment chime so user speech is NEVER blocked or lost."""
    ensure_wake_chime()
    target_audio = WAKE_CHIME_AUDIO if os.path.exists(WAKE_CHIME_AUDIO) else LISTENING_AUDIO
    if os.path.exists(target_audio):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, buffer=512)
            sound = pygame.mixer.Sound(target_audio)
            sound.set_volume(0.35)
            sound.play()  # Non-blocking play on mixer channel
        except Exception as e:
            print(f"[Jarvis] Local wake chime notice: {e}", file=sys.stderr)

def normalize_audio(raw_bytes: bytes) -> bytes:
    """Applies clean AGC digital gain boost so Whisper receives loud, crisp speech."""
    if not raw_bytes:
        return b""
    try:
        audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        max_val = np.max(np.abs(audio_data))
        if max_val > 40:
            target_peak = 24000.0
            gain = min(target_peak / max_val, 4.5)
            if gain > 1.05:
                audio_data = np.clip(audio_data * gain, -32767, 32767)
                return audio_data.astype(np.int16).tobytes()
    except Exception:
        pass
    return raw_bytes

def record_dynamic_command(stream: pyaudio.Stream, vad_engine, preroll_chunks: list = None) -> bytes:
    """Dynamically records microphone audio with pre-roll buffer so words right after wake word are NEVER lost."""
    try:
        with open(os.path.join(PROJECT_ROOT, "last_status.txt"), "w", encoding="utf-8") as f:
            f.write("[LISTENING] Listening for command...")
    except Exception:
        pass

    print(f"[Jarvis] Dynamic VAD active: Listening for command ({SILENCE_TIMEOUT_MS}ms pause tolerance)...")
    
    # Pre-roll ring buffer: keeps ~640ms audio from before speech confirmation
    rolling_preroll = collections.deque(preroll_chunks or [], maxlen=PREROLL_CHUNKS)
    frames = []
    has_spoken = False
    speech_chunks_count = 0
    silence_duration_ms = 0
    start_time = time.time()
    max_chunks = int((RATE / CHUNK) * MAX_RECORDING_SEC)

    # Adaptive ambient noise threshold
    if preroll_chunks and len(preroll_chunks) > 0:
        rms_vals = [np.sqrt(np.mean(np.frombuffer(c, dtype=np.int16).astype(np.float32) ** 2)) for c in preroll_chunks]
        ambient_rms = float(np.mean(rms_vals)) if rms_vals else 60.0
        effective_rms_thresh = max(RMS_ENERGY_THRESHOLD, min(ambient_rms * 1.35, 200.0))
    else:
        effective_rms_thresh = RMS_ENERGY_THRESHOLD

    for _ in range(max_chunks):
        raw_data = stream.read(CHUNK, exception_on_overflow=False)
        audio_chunk = np.frombuffer(raw_data, dtype=np.int16)

        try:
            speech_prob = vad_engine.predict(audio_chunk, frame_size=320)
        except Exception:
            speech_prob = 0.0

        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
        is_speech = (speech_prob >= VAD_SPEECH_THRESHOLD) or (rms >= effective_rms_thresh)

        if is_speech:
            if not has_spoken:
                print("[Jarvis] Speech detected, recording command...")
                try:
                    with open(os.path.join(PROJECT_ROOT, "last_status.txt"), "w", encoding="utf-8") as f:
                        f.write("[LISTENING] Recording command...")
                except Exception:
                    pass
                has_spoken = True
                # Prepend the pre-roll buffer so words like 'can you create' are completely intact!
                frames.extend(list(rolling_preroll))
            speech_chunks_count += 1
            silence_duration_ms = 0
            frames.append(raw_data)
        else:
            if has_spoken:
                frames.append(raw_data)
                if speech_chunks_count >= MIN_SPEECH_CHUNKS:
                    silence_duration_ms += 80
                    if silence_duration_ms >= SILENCE_TIMEOUT_MS:
                        print(f"[Jarvis] End-of-speech detected ({silence_duration_ms}ms silence). Stopping capture.")
                        break
            else:
                rolling_preroll.append(raw_data)
                if time.time() - start_time > INITIAL_WAIT_TIMEOUT_SEC:
                    print(f"[Jarvis] Initial speech wait timeout ({INITIAL_WAIT_TIMEOUT_SEC}s). Stopping capture.")
                    break

        if time.time() - start_time > MAX_RECORDING_SEC:
            print("[Jarvis] Maximum recording safety timeout reached.")
            break

    try:
        with open(os.path.join(PROJECT_ROOT, "last_status.txt"), "w", encoding="utf-8") as f:
            f.write("[PROCESSING] Processing command...")
    except Exception:
        pass

    raw_recorded = b"".join(frames)
    return normalize_audio(raw_recorded)

def save_wav(raw_bytes: bytes, audio: pyaudio.PyAudio, filepath: str):
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(raw_bytes)

def dispatch_to_n8n(audio_path: str):
    """Sends recorded command to n8n webhook."""
    if not N8N_WEBHOOK_URL:
        return
    try:
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "audio/wav")}
            resp = requests.post(N8N_WEBHOOK_URL, files=files, timeout=10)
            print(f"[Jarvis] n8n webhook response: HTTP {resp.status_code}")
    except Exception:
        pass

def run_autonomous_pipeline(audio_path: str):
    """
    Direct, ultra-responsive autonomous execution pipeline:
    1. Transcribes audio dynamically with Groq Whisper -> writes to last_transcript.txt (HUD updates immediately!)
    2. Routes intent dynamically with Groq LLM -> writes to last_intent.json
    3. Speaks task acknowledgment (e.g. "On it, sir. Committing and pushing changes...")
    4. Executes validated action (Git command / Antigravity task)
    5. Speaks completion announcement (e.g. "Task completed successfully, sir." / direct spoken answer)
    """
    pipeline_running.set()
    # Avoid duplicate execution: the local autonomous pipeline handles the entire lifecycle
    if os.getenv("DISPATCH_TO_N8N", "false").lower() == "true":
        threading.Thread(target=dispatch_to_n8n, args=(audio_path,), daemon=True).start()

    try:
        # Step 1: Transcribe audio
        print("\n[Jarvis Pipeline] Step 1: Transcribing audio with Groq Whisper...")
        t_proc = subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "transcribe.py"), audio_path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        transcript = t_proc.stdout.strip()
        if not transcript:
            print("[Jarvis Pipeline] No speech detected in audio capture.")
            return

        print(f"[Jarvis Pipeline] Voice Transcript: \"{transcript}\"")
        transcript_file = os.path.join(PROJECT_ROOT, "last_transcript.txt")
        try:
            with open(transcript_file, "w", encoding="utf-8") as f:
                f.write(transcript)
        except Exception:
            pass

        # Step 2: Route intent dynamically with Groq LLM
        print("[Jarvis Pipeline] Step 2: Routing intent with Groq LLM...")
        subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "intent_router.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )

        intent_file = os.path.join(PROJECT_ROOT, "last_intent.json")
        if not os.path.exists(intent_file):
            print("[Jarvis Pipeline] Error: last_intent.json not found.", file=sys.stderr)
            return

        with open(intent_file, "r", encoding="utf-8") as f:
            intent = json.load(f)

        itype = intent.get("type", "general_qa")
        spk_start = intent.get("speaking_start", "")
        spk_resp = intent.get("speaking_response", "")

        # Step 3: Handle Action vs QA vs Stop
        if itype == "stop_action":
            print("[Jarvis Pipeline] Stop action detected: Immediately halting all speech.")
            stop_all_speech()
            try:
                with open(os.path.join(PROJECT_ROOT, "last_status.txt"), "w", encoding="utf-8") as sf:
                    sf.write("[STOPPED] Speech halted by user.")
            except Exception:
                pass
            return

        elif itype == "git_query":
            answer = spk_resp or "Checking git status, sir."
            print(f"[Jarvis Pipeline] Speaking answer: {answer}")
            speak_phrase(answer)

        elif itype == "confirm_action":
            prompt_phrase = spk_resp or "Are you sure you want to proceed, sir? Please say yes to confirm or no to cancel."
            print(f"[Jarvis Pipeline] Confirmation required: {prompt_phrase}")
            speak_phrase(prompt_phrase)

        elif itype == "git_action":
            # Acknowledge task start: "On it, sir..."
            start_phrase = spk_start or "On it, sir. Committing and pushing your changes."
            print(f"[Jarvis Pipeline] Announcing start: {start_phrase}")
            speak_phrase(start_phrase)

            # Step 4: Execute Git operation
            print("[Jarvis Pipeline] Step 3: Executing Git CLI operation...")
            git_proc = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "execute_git.py")], cwd=PROJECT_ROOT)

            # Step 5: Announce completion or error
            if git_proc.returncode == 0:
                done_phrase = spk_resp or "Task completed successfully, sir."
                print(f"[Jarvis Pipeline] Announcing completion: {done_phrase}")
                speak_phrase(done_phrase)
            else:
                err_phrase = "Git operation could not be completed, sir."
                try:
                    status_path = os.path.join(PROJECT_ROOT, "last_status.txt")
                    if os.path.exists(status_path):
                        with open(status_path, "r", encoding="utf-8") as sf:
                            st = sf.read().strip()
                            if "[GIT ERROR]" in st:
                                err_phrase = f"Git error: {st.replace('[GIT ERROR]', '').strip()[:80]}, sir."
                except Exception:
                    pass
                print(f"[Jarvis Pipeline] Announcing failure: {err_phrase}")
                speak_phrase(err_phrase)

        elif itype == "antigravity_task":
            start_phrase = spk_start or "On it, sir. Delegating task to Antigravity Agent."
            print(f"[Jarvis Pipeline] Announcing start: {start_phrase}")
            speak_phrase(start_phrase)

            print("[Jarvis Pipeline] Step 3: Executing Antigravity Agent Bridge...")
            subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "execute_agent.py")], cwd=PROJECT_ROOT)

            done_phrase = spk_resp or "Task delegated to Antigravity Agent, sir."
            print(f"[Jarvis Pipeline] Announcing completion: {done_phrase}")
            speak_phrase(done_phrase)

        else:  # general_qa or codebase_qa
            if spk_resp:
                print(f"[Jarvis Pipeline] Spoken QA Answer: {spk_resp}")
                speak_phrase(spk_resp)

    except Exception as e:
        print(f"[Jarvis Pipeline] Error during autonomous pipeline execution: {e}", file=sys.stderr)
    finally:
        pipeline_running.clear()
        print("[Jarvis] Autonomous pipeline complete. Standing by for next command...")

def main():
    import openwakeword
    from openwakeword.model import Model
    from openwakeword.vad import VAD

    # Parse target project argument if provided
    for i, a in enumerate(sys.argv):
        if a == "--project" and i + 1 < len(sys.argv):
            set_active_project(sys.argv[i + 1])
            break

    active_repo = get_target_repo()
    proj_name = get_project_name(active_repo)

    print("==================================================")
    print("   JARVIS ULTRA-LOW LATENCY CONVERSATIONAL AGENT  ")
    print(f"   Active Project     : [{proj_name.upper()}]")
    print(f"   Target Workspace   : {active_repo}")
    print(f"   Wake Sensitivity   : Threshold {THRESHOLD} (High)")
    print(f"   Local Acknowledgment: 0ms Pre-rendered Audio")
    print(f"   VAD Silence Cutoff : {SILENCE_TIMEOUT_MS}ms")
    print(f"   n8n Automation     : {'ONLINE' if is_n8n_online() else 'STANDBY'} ({N8N_WEBHOOK_URL})")
    print("==================================================")

    # Launch Sci-Fi Desktop HUD Interface in background
    launch_hud_interface()

    # Initialize Pygame audio mixer pre-warmed for 24kHz
    try:
        pygame.mixer.init(frequency=24000, buffer=1024)
    except Exception as e:
        print(f"[Jarvis] Pygame mixer init note: {e}", file=sys.stderr)

    try:
        openwakeword.utils.download_models()
    except Exception:
        pass

    try:
        oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        vad_engine = VAD()
    except Exception as e:
        print(f"[Jarvis] Fatal: Unable to initialize voice engines: {e}", file=sys.stderr)
        return

    audio = pyaudio.PyAudio()
    try:
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
    except Exception as e:
        print(f"[Jarvis] Fatal: Cannot open microphone input: {e}", file=sys.stderr)
        audio.terminate()
        return

    preroll_window = collections.deque(maxlen=PREROLL_CHUNKS)
    print("[Jarvis] Microphone active. Standing by for wake word...")

    try:
        while True:
            raw_data = stream.read(CHUNK, exception_on_overflow=False)
            preroll_window.append(raw_data)
            audio_array = np.frombuffer(raw_data, dtype=np.int16)

            prediction = oww_model.predict(audio_array)
            score = prediction.get("hey_jarvis", 0.0)

            # If Jarvis is currently speaking, require slightly higher confidence (0.28)
            # to prevent self-triggering while allowing user voice interruption (barge-in)
            effective_threshold = 0.28 if (current_speech_proc is not None or pipeline_running.is_set()) else THRESHOLD

            if score >= effective_threshold:
                print(f"\n[Jarvis] Wake word detected! (Confidence: {score:.2f} >= {effective_threshold})")
                
                # Interrupt and stop any ongoing speech immediately!
                stop_all_speech()
                pipeline_running.clear()

                # 1. Instant local non-blocking audio acknowledgment
                play_instant_wake_acknowledgment()

                # 2. Dynamic VAD Recording with pre-roll buffer preservation
                audio_bytes = record_dynamic_command(stream, vad_engine, preroll_chunks=list(preroll_window))
                save_wav(audio_bytes, audio, OUTPUT_AUDIO_FILE)
                preroll_window.clear()

                # Reset internal buffers before launching pipeline
                oww_model.reset()
                vad_engine.reset_states()

                # 3. Launch autonomous pipeline in background thread
                pipeline_thread = threading.Thread(
                    target=run_autonomous_pipeline,
                    args=(OUTPUT_AUDIO_FILE,),
                    daemon=True
                )
                pipeline_thread.start()

    except KeyboardInterrupt:
        print("\n[Jarvis] Voice listener terminated by user.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()
        pygame.mixer.quit()

if __name__ == "__main__":
    main()
