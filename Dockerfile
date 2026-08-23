FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

RUN addgroup --system cherry && adduser --system --ingroup cherry cherry

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY agents ./agents
RUN python -m pip install --upgrade pip && python -m pip install .

USER cherry
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
