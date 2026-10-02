# ClearCase backend (+ the built frontend) for Hugging Face Spaces or any Docker host. Listens on 7860.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY --chown=user backend backend
COPY --chown=user scripts scripts
COPY --chown=user --from=web /web/dist frontend/dist
RUN mkdir -p /app/backend/data && chown -R user /app
USER user
# Secrets (Clio, Groq, APP_PASSWORD, FIRM_SIGNING_KEY_PEM, HF_TOKEN, PERSIST_DATASET...) come from the host's settings.
ENV CLIO_SOURCE=live \
    DATABASE_URL=sqlite:///./backend/data/clearcase.db \
    SIGNING_KEY_PATH=./backend/data/firm_ed25519.pem \
    AUTO_SYNC_ON_START=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
