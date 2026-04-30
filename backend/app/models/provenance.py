from enum import Enum


class SourceType(str, Enum):
    MRF = "mrf"
    TIC = "tic"
    BENCHMARK = "benchmark"
    MANUAL = "manual"


class RateQuality(str, Enum):
    NEGOTIATED = "negotiated"
    GROSS_ONLY = "gross_only"
    BENCHMARK_ONLY = "benchmark_only"
    UNKNOWN = "unknown"
