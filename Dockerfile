FROM python:3.12-slim

# Ensure Python logs are unbuffered (useful for container logs)
ENV PYTHONUNBUFFERED=1

# Install minimal system dependencies (git for workspace clones, plus tools for assistant workflows)
# Note: Render CLI installer requires `unzip`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep shellcheck curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

# Create and use the app directory
WORKDIR /app

# Copy dependency metadata first for better build caching
COPY dev-requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r dev-requirements.txt

# Copy the rest of the repository
COPY . .

# Install the Render CLI (optional; used by render_cli tool and terminal_command)
RUN curl -fsSL https://raw.githubusercontent.com/render-oss/cli/main/bin/install.sh | sh

# Default workspace base dir for terminal_command / run_tests and default log level
ENV MCP_WORKSPACE_BASE_DIR=/workspace \
    LOG_LEVEL=INFO

EXPOSE 8000

CMD ["sh", "-c", "if [ \"${UVICORN_ACCESS_LOG:-1}\" = \"0\" ]; then ACCESS=\"--no-access-log\"; else ACCESS=\"--access-log\"; fi; uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} $ACCESS"]
