# Multi-stage build for optimized FastAPI application
# FROM python:3.11-slim as builder

# Set working directory
# WORKDIR /app

# # Install system dependencies required for building Python packages
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     g++ \
#     build-essential \
#     libffi-dev \
#     libssl-dev \
#     && rm -rf /var/lib/apt/lists/*

# # Copy requirements first for better caching
# COPY requirements.txt .

# # Install Python dependencies
# RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libffi-dev \
    libssl-dev \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (install globally so console scripts are on PATH)
RUN pip install --no-cache-dir -r requirements.txt

# # Install runtime dependencies only
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libgomp1 \
#     && rm -rf /var/lib/apt/lists/*

# # Copy Python dependencies from builder
# COPY --from=builder /root/.local /root/.local

# Copy application code
COPY . .

# Make sure scripts are executable if needed
# RUN if [ -d "scripts" ]; then chmod +x scripts/*.py; fi

# Update PATH to include local Python packages
ENV PATH=/root/.local/bin:$PATH

# Set Python environment variables
# ENV PYTHONUNBUFFERED=1
# ENV PYTHONDONTWRITEBYTECODE=1

# Expose port (AWS App Runner typically uses port 8080)
EXPOSE 8080

# Health check
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()"

# Run the application with uvicorn
# AWS App Runner expects the app to listen on 0.0.0.0:8080
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
