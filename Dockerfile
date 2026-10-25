# CareCost API (D19): one FastAPI app, no database, data baked into the image.
#
#   docker build -t carecost-api .        # needs data/build/quote_pack.sqlite (the real pack);
#                                         # the build FAILS without it (R11: never bake the
#                                         # 7,791-row test extract into an image)
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

# Test images only (docker-compose.test.yml): CARECOST_ALLOW_EXTRACT=1 skips the pack check; the
# tests read the committed extract, and the server started from such an image serves it only
# because the same variable is set (it says so on /api/health: test_extract).
ARG CARECOST_ALLOW_EXTRACT=0
ENV PYTHONPATH=/repo/backend \
    CARECOST_QUOTE_PACK=/repo/data/build/quote_pack.sqlite \
    CARECOST_ALLOW_EXTRACT=${CARECOST_ALLOW_EXTRACT}
WORKDIR /repo/backend
RUN test "$CARECOST_ALLOW_EXTRACT" = 1 || test -f "$CARECOST_QUOTE_PACK" || { echo "missing $CARECOST_QUOTE_PACK: build the real pack \
(python -m app.quote.pack) before docker build" >&2; exit 1; }

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
