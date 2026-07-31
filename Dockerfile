# Deploy anywhere — 120MB, no database needed
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Set GROQ_API_KEY env var at deploy time
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
