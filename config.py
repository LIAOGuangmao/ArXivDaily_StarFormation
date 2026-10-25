from pathlib import Path

KEYWORDS = [
    "star formation",
    "star-forming",
    "molecular cloud",
    "interstellar medium",
    "cloud",
    "clump",
    "core",
    "filament",
    "atomic gas",
    "n-pdf",
    "initial conditions",
    "irdc",
    "deuterium",
    "prestellar",
    "starless",
    "turbulence",
    "magnetic",
    "virial",
    "mach number",
    "initial mass function",
]

EXCLUDED_KEYWORDS = [
    "galaxies",
    "galaxy cluster",
    " agn ",
    "standard candle",
    "x-ray binar",
    "solar corona",
]

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_QUERY = "cat:astro-ph.*"
ARXIV_PAGE_SIZE = 100
ARXIV_MAX_RESULTS = 2_000
HTTP_TIMEOUT_SECONDS = 30
HTTP_RETRIES = 3
HTTP_RETRY_BASE_SECONDS = 2

REPORT_PATH = Path("README.md")
STATE_PATH = Path(".arxiv-daily-state.json")
STATE_HISTORY_LIMIT = 10_000
