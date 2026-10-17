# OmniClaim AI - container image for Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user; it only needs to write to data/runtime.
RUN useradd --create-home --uid 10001 omniclaim \
    && mkdir -p /app/data/runtime \
    && chown -R omniclaim:omniclaim /app/data/runtime
USER omniclaim

EXPOSE 8080
CMD ["python", "server.py"]
