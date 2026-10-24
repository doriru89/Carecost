# Broken MRF fixtures (failure-recovery tests)

Byte prefixes of `../mrf/brigham_11102.csv`, the shapes a truncated download takes:

| file | how made | what it must do |
|---|---|---|
| `brigham_11102_cut_in_header.csv` | `head -c 900` (ends inside the metadata rows) | `stage` raises `StageError`, never a bare `StopIteration` |
| `brigham_11102_cut_mid_row.csv` | `head -c 20000` (ends inside a data row) | the last-row column-count check raises `StageError` |

Used by `tests/etl/test_recovery.py`. They are not in `../mrf/MANIFEST.yaml` (generated, golden only).
