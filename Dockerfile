FROM python:3.12-slim

# Ensure Python logs are unbuffered (useful for container logs)
ENV PYTHONUNBUFFERED=1

# Install minimal system dependencies (git for workspace clones)
RUN apt-get update \n    && apt-get install -y --no-install-recommends git \n    && rm -rf /var/lib/apt/lists/*

# Create and use the app directory
WORKDIR /app

# Copy dependency metadata first for better build caching
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the repository
COPY . .

# Default workspace base dir for run_command / run_tests and default log level
ENV MCP_WORKSPACE_BASE_DIR=/workspace \
    LOG_LEVEL=INFO

# Expose the default HTTP port (can be overridden with PORT env at runtime)
EXPOSE 8000

# Start the FastMCP / Starlette app via uvicorn.
# PORT is provided by the host environment (Render, Docker, etc.).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
