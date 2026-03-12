HIGH-LEVEL ENGINEERING GUIDE
Feedback Intelligence Pipeline – Apache Beam + Pub/Sub + Dataflow
Project: feedback-intel-gcp

Objective
Complete the missing components of the pipeline by implementing:
1. Pub/Sub message transport
2. Apache Beam streaming pipeline (pipeline.py)
3. Deployment on Google Cloud Dataflow

The architecture follows a modern event-driven streaming design.

------------------------------------------------------------
1. SYSTEM ARCHITECTURE
------------------------------------------------------------

The final architecture should look like this:

    Data Sources
        │
        ▼
    Ingestion Service
    (Cloud Run / API)
        │
        ▼
    Pub/Sub Topic
    feedback-raw
        │
        ▼
    Apache Beam Pipeline
    (pipeline.py)
        │
        ▼
    Dataflow Runner
    (managed workers)
        │
        ▼
    BigQuery
    feedback.raw_feedback


Flow Explanation

1. Feedback arrives from external sources
2. Ingestion service publishes event to Pub/Sub
3. Apache Beam pipeline reads Pub/Sub stream
4. Pipeline parses, validates, and transforms data
5. Data is written into BigQuery
6. Analytics and AI systems consume the data

This design provides:

• decoupled services
• scalable ingestion
• real-time processing
• reliable retries


------------------------------------------------------------
2. PUB/SUB LAYER
------------------------------------------------------------

Purpose

Pub/Sub is the message transport layer. It buffers incoming events and
decouples ingestion from processing.

Without Pub/Sub:

    API → BigQuery

With Pub/Sub:

    API → Pub/Sub → Processing → BigQuery

Benefits:

• handles traffic spikes
• enables multiple consumers
• prevents ingestion bottlenecks
• guarantees message delivery


Required Resources

Topic

    feedback-raw

Subscription

    feedback-raw-sub


Create Resources

    gcloud pubsub topics create feedback-raw

    gcloud pubsub subscriptions create feedback-raw-sub \
        --topic=feedback-raw


Example Event

Messages published to Pub/Sub should follow this structure:

    {
      "id": "uuid",
      "source": "zendesk",
      "text": "Customer cannot complete checkout",
      "customer_id": "cust_123",
      "created_at": "2026-03-11T12:00:00Z",
      "metadata": {}
    }


------------------------------------------------------------
3. INGESTION SERVICE (PRODUCER)
------------------------------------------------------------

The ingestion service receives feedback from external systems
and publishes events to Pub/Sub.

Typical deployment:

    Cloud Run service
    or
    ingestion worker


Example Python Publisher

    from google.cloud import pubsub_v1
    import json

    publisher = pubsub_v1.PublisherClient()

    topic_path = publisher.topic_path(
        "PROJECT_ID",
        "feedback-raw"
    )

    payload = {
        "id": "uuid",
        "source": "zendesk",
        "text": "Checkout page broken",
        "customer_id": "cust_001"
    }

    publisher.publish(
        topic_path,
        json.dumps(payload).encode("utf-8")
    )


Once published, the event becomes available to the pipeline.


------------------------------------------------------------
4. APACHE BEAM PIPELINE
------------------------------------------------------------

The processing pipeline is implemented using Apache Beam.

Beam is a unified programming model for building distributed
data processing pipelines.

Google Cloud Dataflow is the managed runtime that executes
Beam pipelines at scale.

Relationship:

    Apache Beam → pipeline code
    Dataflow → execution engine


Pipeline Responsibilities

The pipeline must perform the following operations:

1. Read messages from Pub/Sub
2. Decode message payload
3. Parse JSON
4. Validate required fields
5. Transform records if needed
6. Write results to BigQuery


------------------------------------------------------------
5. PIPELINE IMPLEMENTATION (pipeline.py)
------------------------------------------------------------

This is the expected structure for the Beam pipeline.

    import apache_beam as beam
    from apache_beam.options.pipeline_options import PipelineOptions
    import json


    class ParseMessage(beam.DoFn):

        def process(self, element):
            try:
                record = json.loads(element.decode("utf-8"))
                yield record
            except Exception:
                pass


    class ValidateRecord(beam.DoFn):

        def process(self, record):

            required_fields = [
                "id",
                "source",
                "text",
                "created_at"
            ]

            if all(field in record for field in required_fields):
                yield record


    def run():

        options = PipelineOptions(
            streaming=True,
            save_main_session=True
        )

        with beam.Pipeline(options=options) as pipeline:

            (
                pipeline

                | "ReadFromPubSub"
                >> beam.io.ReadFromPubSub(
                    topic="projects/PROJECT_ID/topics/feedback-raw"
                )

                | "ParseJSON"
                >> beam.ParDo(ParseMessage())

                | "ValidateRecord"
                >> beam.ParDo(ValidateRecord())

                | "WriteToBigQuery"
                >> beam.io.WriteToBigQuery(
                    table="PROJECT_ID:feedback.raw_feedback",
                    write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                    create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER
                )

            )


    if __name__ == "__main__":
        run()


Pipeline Steps Explained

ReadFromPubSub

Reads messages from the Pub/Sub topic.

ParseJSON

Converts raw byte messages into JSON dictionaries.

ValidateRecord

Ensures required fields exist before processing.

WriteToBigQuery

Streams valid records into the BigQuery table.


------------------------------------------------------------
6. BIGQUERY STRUCTURE
------------------------------------------------------------

Dataset

    feedback

Table

    raw_feedback


Schema

    id STRING
    source STRING
    text STRING
    customer_id STRING
    created_at TIMESTAMP
    metadata JSON


Example Table Creation

    CREATE TABLE `feedback.raw_feedback` (
      id STRING NOT NULL,
      source STRING NOT NULL,
      text STRING NOT NULL,
      customer_id STRING,
      created_at TIMESTAMP NOT NULL,
      metadata JSON
    );


------------------------------------------------------------
7. DATAFLOW EXECUTION
------------------------------------------------------------

The pipeline should be deployed using the Dataflow runner.

Command

    python pipeline.py \
        --runner DataflowRunner \
        --project PROJECT_ID \
        --region us-central1 \
        --temp_location gs://PIPELINE_BUCKET/temp \
        --staging_location gs://PIPELINE_BUCKET/staging \
        --streaming


Dataflow will then:

• launch distributed workers
• continuously read Pub/Sub messages
• apply Beam transforms
• write results to BigQuery


The pipeline will run continuously as a streaming job.


------------------------------------------------------------
8. REQUIRED CLOUD RESOURCES
------------------------------------------------------------

BigQuery

    Dataset
        feedback

    Table
        raw_feedback


Pub/Sub

    Topic
        feedback-raw

    Subscription
        feedback-raw-sub


Cloud Storage

    Temporary bucket for Dataflow

        gs://feedback-intel-dataflow


------------------------------------------------------------
9. DEPLOYMENT SEQUENCE
------------------------------------------------------------

Recommended order of deployment:

Step 1

Create BigQuery dataset and tables

Step 2

Create Pub/Sub topic and subscription

Step 3

Deploy ingestion service (Cloud Run)

Step 4

Deploy Apache Beam pipeline (Dataflow job)

Step 5

Send test event

Step 6

Confirm record appears in BigQuery


------------------------------------------------------------
10. TESTING THE PIPELINE
------------------------------------------------------------

Publish a test event:

    gcloud pubsub topics publish feedback-raw \
        --message '{"id":"test","source":"manual","text":"test feedback","created_at":"2026-03-11T12:00:00Z"}'


Then verify:

    SELECT *
    FROM feedback.raw_feedback
    ORDER BY created_at DESC
    LIMIT 10


------------------------------------------------------------
11. FINAL ARCHITECTURE SUMMARY
------------------------------------------------------------

    External Sources
           │
           ▼
       Cloud Run
       Ingestion
           │
           ▼
        Pub/Sub
      feedback-raw
           │
           ▼
       Apache Beam
        pipeline.py
           │
           ▼
        Dataflow
     distributed workers
           │
           ▼
        BigQuery
      raw_feedback
           │
           ▼
     Analytics / AI


------------------------------------------------------------
END OF GUIDE
------------------------------------------------------------