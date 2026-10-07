# ==============================================================================
# TP-Link Easy Smart Switch Web-to-SNMP Gateway
# Multi-port SNMP v2c/v3 Agent & Web Dashboard
# ==============================================================================

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies (build-essential needed for some cryptography wheels on alpine/slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application files
COPY . .

# Expose Web Dashboard Port and SNMP UDP Ports (161 through 180 for 12+ switches)
EXPOSE 8080/tcp
EXPOSE 6161-6180/udp

# Healthcheck against web dashboard API
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["python", "main.py"]
