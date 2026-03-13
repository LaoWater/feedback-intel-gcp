"""
Sprint 08 — Pub/Sub Publisher: Simulates an ingestion service.

In production, a Cloud Run API would receive feedback from external
sources (Zendesk, app reviews, surveys) and publish to Pub/Sub.
This script simulates that for testing the Beam pipeline.

Usage:
    # Single message
    python pipeline/publish_feedback.py \
        --message '{"id":"test-1","source":"manual","text":"App crashed on login","customer_id":"cust_001","created_at":"2026-03-13T12:00:00Z"}'

    # Multiple messages from a JSON file (one object per line)
    python pipeline/publish_feedback.py --file test_messages.jsonl

    # Quick test (publishes a pre-built test message)
    python pipeline/publish_feedback.py --test
"""

from google.cloud import pubsub_v1
import argparse
import json
import uuid
from datetime import datetime, timezone

PROJECT_ID = "feedback-intel-demo"
TOPIC_ID = "feedback-raw"

# Required fields that the Beam pipeline will validate
REQUIRED_FIELDS = ["id", "source", "text", "created_at"]


def publish_message(publisher, topic_path, payload: dict):
    """Publish a single message to Pub/Sub.

    The message is JSON-encoded and sent as bytes.
    Pub/Sub messages are always bytes — the pipeline decodes them.
    """
    data = json.dumps(payload).encode("utf-8")
    future = publisher.publish(topic_path, data)
    message_id = future.result()  # blocks until published
    print(f"  Published message {payload.get('id', '?')} -> Pub/Sub message ID: {message_id}")
    return message_id


def build_test_message():
    """Build a realistic test message with a unique ID."""
    return {
        "id": f"beam-test-{uuid.uuid4().hex[:8]}",
        "source": "manual",
        "text": "The checkout page throws a 500 error when applying discount codes. "
                "Tried three different codes, same result each time.",
        "customer_id": f"cust_{uuid.uuid4().hex[:6]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"test": True, "sprint": "08-beam-pipeline"},
    }


def main():
    parser = argparse.ArgumentParser(description="Publish feedback to Pub/Sub")
    parser.add_argument("--message", type=str, help="JSON string to publish")
    parser.add_argument("--file", type=str, help="Path to JSONL file (one JSON object per line)")
    parser.add_argument("--test", action="store_true", help="Publish a pre-built test message")
    parser.add_argument("--count", type=int, default=1, help="Number of test messages (with --test)")
    args = parser.parse_args()

    if not any([args.message, args.file, args.test]):
        parser.error("Provide --message, --file, or --test")

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    print(f"Publishing to: {topic_path}\n")

    published = 0

    if args.test:
        for i in range(args.count):
            payload = build_test_message()
            publish_message(publisher, topic_path, payload)
            published += 1

    elif args.message:
        payload = json.loads(args.message)
        # Warn if missing required fields (publish anyway — let the pipeline validate)
        missing = [f for f in REQUIRED_FIELDS if f not in payload]
        if missing:
            print(f"  Warning: missing fields {missing} — pipeline will reject this message")
        publish_message(publisher, topic_path, payload)
        published += 1

    elif args.file:
        with open(args.file, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    publish_message(publisher, topic_path, payload)
                    published += 1
                except json.JSONDecodeError as e:
                    print(f"  Skipping line {line_num}: invalid JSON — {e}")

    print(f"\nDone. Published {published} message(s) to {TOPIC_ID}.")


if __name__ == "__main__":
    main()
