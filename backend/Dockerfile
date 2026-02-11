# Backend Dockerfile
FROM python:3.12-slim

ARG PIP_INDEX_URL

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5

COPY requirements.txt /app/requirements.txt
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir --retries 5 --timeout 60 --index-url "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install --no-cache-dir --retries 5 --timeout 60 -r requirements.txt; \
    fi

COPY app /app/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
