# CareCost API (D19): one FastAPI app, no database, data baked into the image.
#
#   docker build -t carecost-api .        # pack from data/build/quote_pack.sqlite when present,
#                                         # else built from the committed extract
#   docker run -p 8000:8000 carecost-api
#
# The real pack is written by `python -m app.quote.pack` (ETL side, P7 data release) into
# data/build/quote_pack.sqlite before the image is built. Keys come only from env at run time.
FROM python:3.11-slim

WORKDIR /repo

COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
RUN pip install --no-cache-dir ./backend

COPY data ./data
COPY content ./content
COPY contracts ./contracts

ENV PYTHONPATH=/repo/backend \
    CARECOST_QUOTE_PACK=/repo/data/build/quote_pack.sqlite
WORKDIR /repo/backend
RUN test -f "$CARECOST_QUOTE_PACK" || python -m app.quote.pack --from-extract --out "$CARECOST_QUOTE_PACK"

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
