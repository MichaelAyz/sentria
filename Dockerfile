# Build stage - install dependencies
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage - minimal runtime environment
FROM python:3.11-slim
WORKDIR /app

# Create non-root user for security
RUN useradd -m -s /bin/bash sentriauser

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/sentriauser/.local
ENV PATH=/home/sentriauser/.local/bin:$PATH

# Copy application service and static UI assets
COPY --chown=sentriauser:sentriauser service/ ./service/
COPY --chown=sentriauser:sentriauser static/ ./static/

# Ensure runtime directory for SQLite feedback storage has appropriate permissions
RUN mkdir -p ./service/data && chown -R sentriauser:sentriauser ./service/data

USER sentriauser

ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > ./service/version.txt

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]

