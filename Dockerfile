# Multi-stage build for Incident Response Orchestrator

# Build stage
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Production stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r iro && useradd -r -g iro iro

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy source code
COPY --chown=iro:iro . /app

# Create necessary directories
RUN mkdir -p /app/logs /app/config /app/web/static && \
    chown -R iro:iro /app

# Switch to non-root user
USER iro

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO
ENV LOG_FORMAT=json

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# Default command
CMD ["python", "-m", "iro.main"]

# Labels
LABEL maintainer="Your Organization <support@yourorg.com>"
LABEL description="Incident Response Orchestrator for Kubernetes"
LABEL version="1.0.0"
LABEL org.opencontainers.image.source="https://github.com/MouadDB/iro"
LABEL org.opencontainers.image.documentation="https://iro.readthedocs.io/"
LABEL org.opencontainers.image.licenses="Apache-2.0"