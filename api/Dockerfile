FROM python:3.11-slim

WORKDIR /app

# Copy API + search module (needed for /api/search endpoint)
COPY api/requirements.txt ./api/
COPY api/main.py ./api/
COPY search/search_feedback.py ./search/

RUN pip install --no-cache-dir -r api/requirements.txt

EXPOSE 8080

# Cloud Run sets PORT=8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
