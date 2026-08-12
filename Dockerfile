FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.4.1 \
    && poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --no-interaction --no-ansi

COPY src/ ./src/

EXPOSE 8000

# Placeholder — SETUP-003 replaces this with the real app:
#   CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Kept alive here only so `docker-compose up` has something to run before src/main.py exists.
CMD ["tail", "-f", "/dev/null"]
