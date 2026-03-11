gcloud projects create feedback-intel-demo --name="Feedback Intel"
gcloud config set project feedback-intel-demo


gcloud config set compute/region europe-west1

gcloud services enable `
  bigquery.googleapis.com `
  storage.googleapis.com `
  cloudfunctions.googleapis.com `
  aiplatform.googleapis.com `
  discoveryengine.googleapis.com `
  run.googleapis.com `
  speech.googleapis.com `
  texttospeech.googleapis.com `
  pubsub.googleapis.com




bq mk --location=EU feedback-intel-demo:feedback
bq show feedback-intel-demo:feedback
