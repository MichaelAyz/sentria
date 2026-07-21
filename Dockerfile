# Build stage
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim
WORKDIR /app

RUN useradd -m -s /bin/bash sentriauser
USER sentriauser

COPY --from=builder /root/.local /home/sentriauser/.local
ENV PATH=/home/sentriauser/.local/bin:$PATH

COPY service/ ./service/

ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > ./service/version.txt

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
