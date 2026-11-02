# Multi-stage build: Frontend + Backend

# Stage 1: Build Frontend (exact versions from package-lock.json)
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Every pinned dependency ships a binary wheel (psycopg2-binary included), so no compiler or
# libpq headers are needed in the image. curl stays for health checks / debugging.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/
RUN pip install -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Run as an unprivileged user; it owns /app so the SQLite fallback file stays writable.
RUN useradd --create-home --uid 10001 jarvis && chown -R jarvis:jarvis /app
USER jarvis

ENV PORT=8080
EXPOSE 8080

WORKDIR /app/backend
CMD ["python", "main.py"]
