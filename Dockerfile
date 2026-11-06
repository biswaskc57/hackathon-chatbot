# Web API for the Lovable UI. Build: docker build -t smarttech-api .
# Run:   docker run -p 8000:8000 --env-file .env smarttech-api
# Logs are written inside the container and are lost when it is replaced; mount a volume on /app/logs to keep them.
FROM python:3.11-slim
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY api.py assistant.py config.py llm_client.py retrieval.py settings.json pii.py router.py menu_check.py tickets.py ./
COPY data/corpus.jsonl data/search_questions.jsonl data/glossary.csv data/
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
