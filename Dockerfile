FROM python:3.11-slim

WORKDIR /repo

COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY data/registries ./data/registries
COPY data/seed ./data/seed
COPY backend/alembic.ini ./backend/
COPY backend/alembic ./backend/alembic
COPY backend/app ./backend/app
COPY scripts ./scripts

ENV PYTHONPATH=/repo/backend

WORKDIR /repo/backend
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
