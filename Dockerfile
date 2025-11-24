# Multi-stage Dockerfile for GitHub MCP server

# Builder stage (optional but keeps final image smaller)
FROM python:3.13-slim AS builder

WORKDIR /app

# System dependencies: git is required for clone/push in workspace tools
RUN apt-get update \n    && apt-get install -y --no-install-recommends git \n    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

# Runtime image
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Default port inside the container
ENV PORT=8000

EXPOSE 8000

# Uvicorn entrypoint
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
