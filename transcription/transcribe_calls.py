"""
Sprint 05 — Chirp 3 Speech-to-Text batch transcription.

Transcribes all WAV files in gs://feedback-intel-audio-calls/ using
Google Cloud Speech-to-Text V2 API with Chirp 3 model.

Chirp 3 over Chirp 2 because:
  - Speaker diarization support (Chirp 2 does NOT support it)
  - Available in EU multi-region (matches our bucket location)
  - Latest-gen accuracy

Tradeoff: Chirp 3 loses reliable word-level confidence scores
(Chirp 2 had them). We use ground truth JSONs for WER eval instead.

Usage:
    python transcribe_calls.py              # Transcribe all un-transcribed files
    python transcribe_calls.py --limit 5    # Transcribe first 5 files only
    python transcribe_calls.py --reset      # Wipe call_transcripts and re-run
"""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone

from google.cloud import storage, bigquery
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech

# ─── Config ─────────────────────────────────────────────────────────

PROJECT_ID = "feedback-intel-demo"
CHIRP_LOCATION = "eu"               # Chirp 3 GA in multi-region 'eu' — matches our buckets
AUDIO_BUCKET = "feedback-intel-audio-calls"
PROCESSED_BUCKET = "feedback-intel-audio-processed"
BQ_TABLE = f"{PROJECT_ID}.feedback.call_transcripts"

# Chirp 3 configuration
# Why Chirp 3 over Chirp 2:
#   - Diarization support (Chirp 2 doesn't have it)
#   - EU multi-region GA (Chirp 2 only had europe-west4)
#   - Latest-gen accuracy
# Tradeoff: word-level confidence less reliable than Chirp 2
CHIRP_MODEL = "chirp_3"
LANGUAGE = "en-US"

# ─── Clients ────────────────────────────────────────────────────────

speech_client = SpeechClient(
    client_options={"api_endpoint": f"{CHIRP_LOCATION}-speech.googleapis.com"}
)
# For multi-region 'eu', the endpoint becomes eu-speech.googleapis.com
storage_client = storage.Client()
bq_client = bigquery.Client(project=PROJECT_ID)


# ─── Core transcription ────────────────────────────────────────────

def transcribe_file(audio_uri: str) -> dict:
    """
    Transcribe a single audio file using Chirp 3 batch_recognize.

    Why batch_recognize (not recognize):
      - recognize: synchronous, max 60 seconds of audio
      - batch_recognize: async, handles any length, reads from GCS directly
      - Chirp 3 diarization only works with BatchRecognize + Recognize
      Our calls are 1-3 min, so batch is the right choice.

    Returns structured transcript data.
    """
    recognizer = f"projects/{PROJECT_ID}/locations/{CHIRP_LOCATION}/recognizers/_"

    config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=[LANGUAGE],
        model=CHIRP_MODEL,
        features=cloud_speech.RecognitionFeatures(
            enable_word_time_offsets=True,
            enable_word_confidence=True,
            enable_automatic_punctuation=True,
            diarization_config=cloud_speech.SpeakerDiarizationConfig(
                min_speaker_count=2,   # At least agent + customer
                max_speaker_count=4,   # Allow for transfers, supervisors
            ),
        ),
    )

    file_metadata = cloud_speech.BatchRecognizeFileMetadata(uri=audio_uri)

    request = cloud_speech.BatchRecognizeRequest(
        recognizer=recognizer,
        config=config,
        files=[file_metadata],
        recognition_output_config=cloud_speech.RecognitionOutputConfig(
            inline_response_config=cloud_speech.InlineOutputConfig(),
        ),
    )

    # Async operation — wait for completion (up to 5 min per file)
    operation = speech_client.batch_recognize(request=request)
    response = operation.result(timeout=300)

    return parse_chirp_response(response, audio_uri)


def parse_chirp_response(response, audio_uri: str) -> dict:
    """
    Parse Chirp batch response into structured transcript data.

    Extracts: full text, word-level segments with speaker labels,
    speaker count, duration, and average confidence.
    """
    file_result = response.results[audio_uri]

    full_text_parts = []
    segments = []
    word_confidences = []
    max_end_time = 0.0
    speakers = set()

    for result in file_result.transcript.results:
        if not result.alternatives:
            continue

        best_alt = result.alternatives[0]
        full_text_parts.append(best_alt.transcript)

        for word_info in best_alt.words:
            speaker_tag = word_info.speaker_label or "unknown"
            speakers.add(speaker_tag)

            start_s = word_info.start_offset.total_seconds() if word_info.start_offset else 0
            end_s = word_info.end_offset.total_seconds() if word_info.end_offset else 0
            max_end_time = max(max_end_time, end_s)

            conf = word_info.confidence if word_info.confidence else 0.0
            if conf > 0:
                word_confidences.append(conf)

            segments.append({
                "word": word_info.word,
                "speaker": speaker_tag,
                "start": round(start_s, 2),
                "end": round(end_s, 2),
                "confidence": round(conf, 3) if conf else None,
            })

    avg_conf = (sum(word_confidences) / len(word_confidences)) if word_confidences else 0.0

    return {
        "full_text": " ".join(full_text_parts),
        "segments": segments,
        "speaker_count": len(speakers),
        "duration_seconds": round(max_end_time, 1),
        "language": LANGUAGE,
        "avg_confidence": round(avg_conf, 3),
    }


# ─── GCS + BQ helpers ──────────────────────────────────────────────

def list_audio_files() -> list[str]:
    """List all WAV files in the audio bucket."""
    bucket = storage_client.bucket(AUDIO_BUCKET)
    blobs = bucket.list_blobs()
    return [
        f"gs://{AUDIO_BUCKET}/{blob.name}"
        for blob in blobs
        if blob.name.endswith((".wav", ".mp3", ".flac"))
    ]


def get_already_transcribed() -> set[str]:
    """Get set of audio URIs successfully transcribed (skip error rows)."""
    query = """
    SELECT audio_file_uri FROM `feedback.call_transcripts`
    WHERE error_message IS NULL
    """
    rows = bq_client.query(query).result()
    return {row.audio_file_uri for row in rows}


def extract_call_id(audio_uri: str) -> str:
    """Extract call UUID from gs://bucket/call_{uuid}.wav"""
    filename = audio_uri.split("/")[-1]  # call_{uuid}.wav
    return filename.replace("call_", "").replace(".wav", "")


def insert_transcript(row: dict):
    """Stream insert a single transcript row into BigQuery."""
    errors = bq_client.insert_rows_json(BQ_TABLE, [row])
    if errors:
        raise RuntimeError(f"BQ insert error: {errors}")


def move_to_processed(audio_uri: str):
    """Copy audio file to processed bucket, delete from source."""
    blob_name = audio_uri.split(f"gs://{AUDIO_BUCKET}/")[-1]
    src_bucket = storage_client.bucket(AUDIO_BUCKET)
    dst_bucket = storage_client.bucket(PROCESSED_BUCKET)

    src_blob = src_bucket.blob(blob_name)
    src_bucket.copy_blob(src_blob, dst_bucket, blob_name)
    src_blob.delete()


def reset_transcripts():
    """Delete all rows from call_transcripts."""
    query = "DELETE FROM `feedback.call_transcripts` WHERE TRUE"
    bq_client.query(query).result()
    print("Wiped call_transcripts table.")


# ─── Main batch processor ──────────────────────────────────────────

def transcribe_all(limit: int = 0, skip_move: bool = False):
    """
    Transcribe all un-transcribed audio files.

    Args:
        limit: Max files to process (0 = all)
        skip_move: If True, don't move files to processed bucket
    """
    all_files = list_audio_files()
    already_done = get_already_transcribed()

    pending = [f for f in all_files if f not in already_done]
    if limit > 0:
        pending = pending[:limit]

    print(f"Found {len(all_files)} audio files, {len(already_done)} already transcribed")
    print(f"Processing {len(pending)} files\n")

    if not pending:
        print("Nothing to transcribe!")
        return

    total_ok = 0
    total_err = 0

    for i, audio_uri in enumerate(pending, 1):
        call_id = extract_call_id(audio_uri)
        print(f"[{i}/{len(pending)}] Transcribing {call_id}...", end=" ", flush=True)

        start_time = time.time()

        try:
            transcript = transcribe_file(audio_uri)
            processing_ms = int((time.time() - start_time) * 1000)

            row = {
                "id": call_id,
                "audio_file_uri": audio_uri,
                "transcript_full": transcript["full_text"],
                "transcript_segments": json.dumps(transcript["segments"]),
                "speaker_count": transcript["speaker_count"],
                "duration_seconds": transcript["duration_seconds"],
                "language_code": transcript["language"],
                "chirp_model": CHIRP_MODEL,
                "confidence_avg": transcript["avg_confidence"],
                "customer_id": f"CUST-{call_id[:8]}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "processing_time_ms": processing_ms,
                "error_message": None,
            }

            insert_transcript(row)

            if not skip_move:
                move_to_processed(audio_uri)

            total_ok += 1
            print(f"OK ({transcript['duration_seconds']}s audio, "
                  f"{transcript['speaker_count']} speakers, "
                  f"conf={transcript['avg_confidence']}, "
                  f"{processing_ms}ms)")

        except Exception as e:
            processing_ms = int((time.time() - start_time) * 1000)
            total_err += 1
            print(f"FAILED: {e}")

            # Log error row so we don't retry forever
            error_row = {
                "id": call_id,
                "audio_file_uri": audio_uri,
                "transcript_full": "",
                "transcript_segments": "[]",
                "speaker_count": 0,
                "duration_seconds": 0.0,
                "language_code": "",
                "chirp_model": CHIRP_MODEL,
                "confidence_avg": 0.0,
                "customer_id": f"CUST-{call_id[:8]}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "processing_time_ms": processing_ms,
                "error_message": str(e)[:1000],
            }
            try:
                insert_transcript(error_row)
            except Exception as insert_err:
                print(f"  (also failed to log error: {insert_err})")

    print(f"\n═══ Done ═══")
    print(f"  Success: {total_ok}")
    print(f"  Failed:  {total_err}")
    print(f"  Total:   {total_ok + total_err}")


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Batch transcribe calls with Chirp 3")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max files to transcribe (0 = all)")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe call_transcripts before running")
    parser.add_argument("--skip-move", action="store_true",
                        help="Don't move files to processed bucket after transcription")
    args = parser.parse_args()

    print(f"═══ Chirp Speech-to-Text Pipeline ═══")
    print(f"  Model:    {CHIRP_MODEL}")
    print(f"  Region:   {CHIRP_LOCATION}")
    print(f"  Bucket:   gs://{AUDIO_BUCKET}/")
    print(f"  Limit:    {'all' if args.limit == 0 else args.limit}")
    print()

    if args.reset:
        confirm = input("This will DELETE all transcripts. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            return
        reset_transcripts()
        print()

    transcribe_all(limit=args.limit, skip_move=args.skip_move)


if __name__ == "__main__":
    main()
