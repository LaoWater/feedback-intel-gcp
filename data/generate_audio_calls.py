"""
Sprint 02 — Generate 30-50 fake support call audio files using Google TTS.

Phase 1: Use Gemini to generate diverse call scripts (agent + customer dialogues)
Phase 2: Use Google TTS to synthesize each script into a WAV file
Phase 3: Save ground truth JSON for WER evaluation in Sprint 06

Outputs:
  - data/calls/*.wav           — audio files for Chirp transcription
  - data/ground_truth/*.json   — scripts with expected text (for WER eval)

Upload WAVs to: gs://feedback-intel-audio-calls/
Keep ground truth local for evaluation.

Cost estimate: ~$1-2 for TTS (Studio voices at $16/1M chars, we'll use ~50k chars)
"""

import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import texttospeech
import json, uuid, os, wave, io, time, sys
from datetime import datetime, timedelta
import random

# ── Config ───────────────────────────────────────────────────────────
PROJECT_ID = "feedback-intel-demo"
LOCATION = "europe-west1"
NUM_SCRIPTS = 35  # target number of call scripts to generate
CALLS_DIR = "data/calls"
GROUND_TRUTH_DIR = "data/ground_truth"

# ── TTS Voice Config ────────────────────────────────────────────────
# Two distinct voices so Chirp diarization has something to work with.
# Studio voices = higher quality, better prosody (costs more but worth it for realism)
VOICES = {
    "agent": texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Studio-O",  # professional female voice
    ),
    "customer": texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Studio-M",  # male voice for contrast
    ),
}

AUDIO_CONFIG = texttospeech.AudioConfig(
    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
    sample_rate_hertz=16000,  # Chirp optimal sample rate
    speaking_rate=1.0,
)

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


def generate_scripts(model, n=NUM_SCRIPTS):
    """Generate call scripts via Gemini."""
    print(f"Generating {n} call scripts via Gemini...")

    # Generate in batches of 10 to avoid token limits
    all_scripts = []
    batch_size = 10
    num_batches = (n + batch_size - 1) // batch_size

    for i in range(num_batches):
        remaining = min(batch_size, n - len(all_scripts))
        response = model.generate_content(
            SCRIPT_PROMPT.format(n=remaining),
            generation_config={"temperature": 1.0, "max_output_tokens": 8192},
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]

        try:
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

        if i < num_batches - 1:
            time.sleep(1)

    return all_scripts[:n]


def add_silence(duration_ms=500, sample_rate=16000):
    """Generate silence (zeros) for a given duration."""
    num_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * num_samples  # 16-bit silence


def generate_call_audio(tts_client, script, output_path):
    """Synthesize a call script into a single WAV file with TTS."""
    segments = []

    for turn in script["turns"]:
        speaker = turn["speaker"]
        voice = VOICES.get(speaker, VOICES["customer"])

        synthesis_input = texttospeech.SynthesisInput(text=turn["text"])
        response = tts_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=AUDIO_CONFIG
        )
        segments.append(response.audio_content)

    # Concatenate WAV segments with small silence gaps between turns
    silence = add_silence(400)  # 400ms pause between speakers
    with wave.open(output_path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)  # 16-bit
        out.setframerate(16000)
        for i, seg in enumerate(segments):
            with wave.open(io.BytesIO(seg), "rb") as inp:
                out.writeframes(inp.readframes(inp.getnframes()))
            if i < len(segments) - 1:
                out.writeframes(silence)

    return output_path


def save_ground_truth(call_id, script):
    """Save the script as ground truth JSON for WER evaluation."""
    ground_truth = {
        "call_id": call_id,
        "expected_department": script.get("expected_department", "Unknown"),
        "expected_sentiment": script.get("expected_sentiment", "unknown"),
        "scenario": script.get("scenario", ""),
        "turns": script["turns"],
        # Full concatenated text for WER comparison
        "full_text": " ".join(t["text"] for t in script["turns"]),
        "generated_at": datetime.now().isoformat(),
    }

    path = os.path.join(GROUND_TRUTH_DIR, f"{call_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2, ensure_ascii=False)

    return path


def main():
    print("=== Call Audio Generator ===")
    print(f"Target: {NUM_SCRIPTS} call scripts → WAV + ground truth")
    print()

    # Ensure output dirs exist
    os.makedirs(CALLS_DIR, exist_ok=True)
    os.makedirs(GROUND_TRUTH_DIR, exist_ok=True)

    # Phase 1: Generate scripts with Gemini
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.0-flash-001")
    scripts = generate_scripts(model, NUM_SCRIPTS)
    print(f"\nGenerated {len(scripts)} scripts total.\n")

    if not scripts:
        print("ERROR: No scripts generated. Check Gemini API access.")
        sys.exit(1)

    # Phase 2: Synthesize audio with TTS
    print("Synthesizing audio with Google TTS...")
    tts_client = texttospeech.TextToSpeechClient()

    manifest = []  # track all generated files

    for i, script in enumerate(scripts):
        call_id = str(uuid.uuid4())
        wav_path = os.path.join(CALLS_DIR, f"call_{call_id}.wav")

        try:
            generate_call_audio(tts_client, script, wav_path)
            gt_path = save_ground_truth(call_id, script)
            manifest.append({
                "call_id": call_id,
                "wav_file": wav_path,
                "ground_truth": gt_path,
                "department": script.get("expected_department", "Unknown"),
                "sentiment": script.get("expected_sentiment", "unknown"),
                "num_turns": len(script["turns"]),
            })
            print(f"  [{i+1}/{len(scripts)}] {wav_path} — {script.get('scenario', 'N/A')[:60]}")

        except Exception as e:
            print(f"  [{i+1}/{len(scripts)}] ERROR: {e}")
            continue

        # Small delay between TTS calls
        if i < len(scripts) - 1:
            time.sleep(0.3)

    # Save manifest
    manifest_path = os.path.join("data", "call_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Summary
    print(f"\n=== Done ===")
    print(f"WAV files: {len(manifest)} in {CALLS_DIR}/")
    print(f"Ground truth: {len(manifest)} in {GROUND_TRUTH_DIR}/")
    print(f"Manifest: {manifest_path}")

    # Department distribution
    from collections import Counter
    dept_counts = Counter(m["department"] for m in manifest)
    print(f"Departments: {dict(dept_counts)}")


if __name__ == "__main__":
    main()
