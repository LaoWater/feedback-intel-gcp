"""
Sprint 02 — Generate 35 fake support call audio files using Google TTS (Chirp 3 HD voices).

Phase 1: Use Gemini 2.5 Flash Lite (google-genai SDK) to generate diverse call scripts
Phase 2: Use Google Cloud TTS with Chirp 3 HD voices to synthesize each script into a WAV file
Phase 3: Save ground truth JSON for WER evaluation in Sprint 06

Chirp 3 HD voices are Google's latest neural voices — far more natural prosody and
intonation than the older Studio voices. They use the naming pattern:
  <locale>-Chirp3-HD-<VoiceName>  (e.g. en-US-Chirp3-HD-Charon)

Outputs:
  - data/calls/*.wav           — audio files for Chirp STT transcription
  - data/ground_truth/*.json   — scripts with expected text (for WER eval)
  - data/call_manifest.json    — index of all generated calls

Upload WAVs to: gs://feedback-intel-audio-calls/
Keep ground truth local for evaluation.

Cost estimate: Chirp 3 HD is $0.000060/char, ~50k chars ≈ $3
"""

from google import genai
from google.genai import types
from google.cloud import texttospeech
import json, uuid, os, wave, io, time, sys
from datetime import datetime, timedelta
import random

# ── Config ───────────────────────────────────────────────────────────
PROJECT_ID = "feedback-intel-demo"
LOCATION = "europe-west1"
SCRIPT_MODEL = "gemini-2.5-flash-lite"  # cheap model for generating scripts
NUM_SCRIPTS = 35

# Resolve paths relative to this script's location (works from any CWD)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CALLS_DIR = os.path.join(SCRIPT_DIR, "calls")
GROUND_TRUTH_DIR = os.path.join(SCRIPT_DIR, "ground_truth")
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "call_manifest.json")

# ── TTS Voice Config (Chirp 3 HD) ───────────────────────────────────
# Two distinct Chirp 3 HD voices for agent vs customer.
# Using clearly different voice characters so Chirp STT diarization can distinguish speakers.
# Full list: Achernar, Achird, Algenib, Algieba, Alnilam, Aoede, Autonoe,
#   Callirrhoe, Charon, Despina, Enceladus, Erinome, Fenrir, Gacrux,
#   Iapetus, Kore, Laomedeia, Leda, Orus, Pulcherrima, Puck, Rasalgethi,
#   Sadachbia, Sadaltager, Schedar, Sulafat, Umbriel, Vindemiatrix, Zephyr
VOICES = {
    "agent": texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Chirp3-HD-Leda",
    ),
    "customer": texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Chirp3-HD-Charon",
    ),
}

AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # uncompressed PCM → WAV
    sample_rate_hertz=24000,  # Chirp 3 HD native rate (higher quality than 16k)
    speaking_rate=1.0,
)

# We'll write WAV at 24000 Hz to match TTS output, then Chirp STT handles resampling.
WAV_SAMPLE_RATE = 24000

# ── Script Generation Prompt ────────────────────────────────────────
SCRIPT_PROMPT = """Generate {n} realistic customer support call scripts for a SaaS company.

Each script is a dialogue between an "agent" and a "customer".

Each script MUST be a JSON object with:
- "turns": array of objects, each with "speaker" ("agent" or "customer") and "text" (1-3 sentences)
- "expected_department": one of "Engineering", "Product", "UX", "Support", "Billing", "Logistics"
- "expected_sentiment": one of "positive", "negative", "neutral", "mixed"
- "scenario": brief 1-line description of the call topic

Requirements:
- Each call should have 5-8 turns (alternating agent/customer)
- Agent always speaks first (greeting)
- Varied scenarios across ALL departments:
  * Engineering: app crashes, bugs, performance issues, API errors
  * Product: feature requests, missing functionality, roadmap questions
  * UX: confusing interface, navigation issues, accessibility problems
  * Support: account access, password reset, general how-to
  * Billing: charges, refunds, subscription changes, invoices
  * Logistics: shipping delays, tracking issues, delivery problems
- Varied sentiments: some angry customers, some calm, some thankful
- Realistic speech patterns — people don't talk like they write (use fillers like "um", "so basically", "you know")
- Include specific details: order numbers, dates, feature names, error messages

Return ONLY a valid JSON array. No markdown, no code fences, no explanation."""


def generate_scripts(client, n=NUM_SCRIPTS):
    """Generate call scripts via Gemini in batches."""
    print(f"Generating {n} call scripts via {SCRIPT_MODEL}...")

    all_scripts = []
    batch_size = 10
    num_batches = (n + batch_size - 1) // batch_size

    for i in range(num_batches):
        remaining = min(batch_size, n - len(all_scripts))
        try:
            response = client.models.generate_content(
                model=SCRIPT_MODEL,
                contents=SCRIPT_PROMPT.format(n=remaining),
                config=types.GenerateContentConfig(
                    temperature=1.0,
                    max_output_tokens=8192,
                ),
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            scripts = json.loads(text)

            # Validate structure
            valid = []
            for s in scripts:
                if "turns" in s and len(s["turns"]) >= 3:
                    if all("speaker" in t and "text" in t for t in s["turns"]):
                        valid.append(s)
            all_scripts.extend(valid)
            print(f"  Script batch {i+1}/{num_batches} — got {len(valid)} — total: {len(all_scripts)}")

        except json.JSONDecodeError as e:
            print(f"  [WARN] Batch {i+1} JSON parse failed: {e}")
        except Exception as e:
            print(f"  [WARN] Batch {i+1} error: {e}")

        if i < num_batches - 1:
            time.sleep(1)

    return all_scripts[:n]


def add_silence(duration_ms=500, sample_rate=WAV_SAMPLE_RATE):
    """Generate silence (zeros) for a given duration."""
    num_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * num_samples  # 16-bit silence


def generate_call_audio(tts_client, script, output_path):
    """Synthesize a call script into a single WAV file using Chirp 3 HD voices."""
    segments = []

    for turn in script["turns"]:
        speaker = turn["speaker"]
        voice = VOICES.get(speaker, VOICES["customer"])

        synthesis_input = texttospeech.SynthesisInput(text=turn["text"])
        response = tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=AUDIO_CONFIG
        )
        segments.append(response.audio_content)

    # Concatenate WAV segments with silence gaps between turns
    silence = add_silence(400)  # 400ms pause between speakers (natural turn-taking gap)
    with wave.open(output_path, "wb") as out:
        out.setnchannels(1)       # mono
        out.setsampwidth(2)       # 16-bit
        out.setframerate(WAV_SAMPLE_RATE)
        for i, seg in enumerate(segments):
            with wave.open(io.BytesIO(seg), "rb") as inp:
                out.writeframes(inp.readframes(inp.getnframes()))
            if i < len(segments) - 1:
                out.writeframes(silence)

    return output_path


def save_ground_truth(call_id, script):
    """Save the script as ground truth JSON for WER evaluation in Sprint 06."""
    ground_truth = {
        "call_id": call_id,
        "expected_department": script.get("expected_department", "Unknown"),
        "expected_sentiment": script.get("expected_sentiment", "unknown"),
        "scenario": script.get("scenario", ""),
        "turns": script["turns"],
        # Full concatenated text — this is what we compare Chirp's output against
        "full_text": " ".join(t["text"] for t in script["turns"]),
        "generated_at": datetime.now().isoformat(),
    }

    path = os.path.join(GROUND_TRUTH_DIR, f"{call_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2, ensure_ascii=False)

    return path


def main():
    print("=== Call Audio Generator ===")
    print(f"Target: {NUM_SCRIPTS} call scripts -> WAV (Chirp 3 HD) + ground truth JSON")
    print(f"Script model: {SCRIPT_MODEL}")
    print(f"TTS voices: {VOICES['agent'].name} (agent), {VOICES['customer'].name} (customer)")
    print(f"Sample rate: {WAV_SAMPLE_RATE} Hz")
    print()

    # Ensure output dirs exist
    os.makedirs(CALLS_DIR, exist_ok=True)
    os.makedirs(GROUND_TRUTH_DIR, exist_ok=True)

    # Phase 1: Generate scripts with Gemini (google-genai SDK)
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    scripts = generate_scripts(client, NUM_SCRIPTS)
    print(f"\nGenerated {len(scripts)} scripts total.\n")

    if not scripts:
        print("ERROR: No scripts generated. Check Gemini API access.")
        sys.exit(1)

    # Phase 2: Synthesize audio with Google TTS (Chirp 3 HD)
    print("Synthesizing audio with Chirp 3 HD voices...")
    tts_client = texttospeech.TextToSpeechClient()

    manifest = []

    for i, script in enumerate(scripts):
        call_id = str(uuid.uuid4())
        wav_path = os.path.join(CALLS_DIR, f"call_{call_id}.wav")

        try:
            generate_call_audio(tts_client, script, wav_path)
            gt_path = save_ground_truth(call_id, script)

            # Get file size for logging
            file_size_kb = os.path.getsize(wav_path) / 1024

            manifest.append({
                "call_id": call_id,
                "wav_file": wav_path,
                "ground_truth": gt_path,
                "department": script.get("expected_department", "Unknown"),
                "sentiment": script.get("expected_sentiment", "unknown"),
                "scenario": script.get("scenario", ""),
                "num_turns": len(script["turns"]),
                "file_size_kb": round(file_size_kb, 1),
            })
            print(
                f"  [{i+1}/{len(scripts)}] {file_size_kb:.0f}KB — "
                f"{script.get('scenario', 'N/A')[:60]}"
            )

        except Exception as e:
            print(f"  [{i+1}/{len(scripts)}] ERROR: {e}")
            continue

        # Small delay between TTS calls
        if i < len(scripts) - 1:
            time.sleep(0.3)

    # Save manifest
    manifest_path = MANIFEST_PATH
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Summary
    print(f"\n=== Done ===")
    print(f"WAV files:     {len(manifest)} in {CALLS_DIR}/")
    print(f"Ground truth:  {len(manifest)} in {GROUND_TRUTH_DIR}/")
    print(f"Manifest:      {manifest_path}")

    total_size_mb = sum(m["file_size_kb"] for m in manifest) / 1024
    print(f"Total audio:   {total_size_mb:.1f} MB")

    from collections import Counter

    dept_counts = Counter(m["department"] for m in manifest)
    print(f"Departments:   {dict(dept_counts)}")


if __name__ == "__main__":
    main()
