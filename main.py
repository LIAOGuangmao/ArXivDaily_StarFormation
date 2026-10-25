from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import (
    ARXIV_API_URL,
    ARXIV_MAX_RESULTS,
    ARXIV_PAGE_SIZE,
    ARXIV_QUERY,
    EXCLUDED_KEYWORDS,
    HTTP_RETRIES,
    HTTP_RETRY_BASE_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    KEYWORDS,
    REPORT_PATH,
    STATE_HISTORY_LIMIT,
    STATE_PATH,
)

ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
WHITESPACE = re.compile(r"\s+")
ARXIV_ID = re.compile(r"(?P<id>\d{4}\.\d{4,5})(?:v\d+)?$")


class ArxivDailyError(RuntimeError):
    """Raised when a daily publication cannot be completed safely."""


@dataclass(frozen=True, order=True)
class Paper:
    identifier: str
    title: str
    authors: tuple[str, ...]
    subjects: tuple[str, ...]
    abstract: str
    published_at: datetime
    updated_at: datetime

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.identifier}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.identifier}"


def normalize_text(value: str | None) -> str:
    return WHITESPACE.sub(" ", (value or "").strip())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_arxiv_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ArxivDailyError(f"Invalid arXiv timestamp: {value!r}") from error

    if parsed.tzinfo is None:
        raise ArxivDailyError(f"arXiv timestamp has no timezone: {value!r}")

    return parsed.astimezone(timezone.utc)


def extract_identifier(entry_id: str) -> str:
    match = ARXIV_ID.search(entry_id.rstrip("/"))
    if not match:
        raise ArxivDailyError(f"Could not extract an arXiv identifier from {entry_id!r}")
    return match.group("id")


def build_query_url(start: int, max_results: int) -> str:
    parameters = {
        "search_query": ARXIV_QUERY,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urlencode(parameters)}"


def fetch_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/atom+xml, application/xml;q=0.9",
            "User-Agent": "ArXivDaily/2.0 (+https://github.com/LIAOGuangmao/ArXivDaily_StarFormation)",
        },
    )

    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ArxivDailyError(f"arXiv returned HTTP {status} for {url}")
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt == HTTP_RETRIES - 1:
                break
            time.sleep(HTTP_RETRY_BASE_SECONDS * (2**attempt))

    raise ArxivDailyError(f"Unable to retrieve arXiv feed: {last_error}") from last_error


def required_text(entry: ET.Element, path: str) -> str:
    node = entry.find(path, ATOM_NAMESPACE)
    value = normalize_text(node.text if node is not None else None)
    if not value:
        raise ArxivDailyError(f"Malformed Atom entry: missing {path}")
    return value


def parse_feed(payload: bytes) -> tuple[int, list[Paper]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ArxivDailyError("arXiv returned malformed XML") from error

    total_node = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
    if total_node is None or not normalize_text(total_node.text).isdigit():
        raise ArxivDailyError("arXiv feed does not contain a valid totalResults value")

    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM_NAMESPACE):
        entry_id = required_text(entry, "atom:id")
        authors = tuple(
            author_name
            for author in entry.findall("atom:author/atom:name", ATOM_NAMESPACE)
            if (author_name := normalize_text(author.text))
        )
        categories = tuple(
            category.attrib["term"]
            for category in entry.findall("atom:category", ATOM_NAMESPACE)
            if category.attrib.get("term")
        )

        papers.append(
            Paper(
                identifier=extract_identifier(entry_id),
                title=required_text(entry, "atom:title"),
                authors=authors,
                subjects=categories,
                abstract=required_text(entry, "atom:summary"),
                published_at=parse_arxiv_datetime(required_text(entry, "atom:published")),
                updated_at=parse_arxiv_datetime(required_text(entry, "atom:updated")),
            )
        )

    return int(normalize_text(total_node.text)), papers


def fetch_all_papers() -> list[Paper]:
    papers: list[Paper] = []
    total_results: int | None = None

    for start in range(0, ARXIV_MAX_RESULTS, ARXIV_PAGE_SIZE):
        page_total, page = parse_feed(fetch_bytes(build_query_url(start, ARXIV_PAGE_SIZE)))

        if total_results is None:
            total_results = page_total

        if not page:
            break

        papers.extend(page)

        if len(papers) >= total_results or len(page) < ARXIV_PAGE_SIZE:
            break

    unique: dict[str, Paper] = {}
    for paper in papers:
        previous = unique.get(paper.identifier)
        if previous is None or paper.updated_at > previous.updated_at:
            unique[paper.identifier] = paper

    return sorted(unique.values(), key=lambda paper: (paper.published_at, paper.identifier), reverse=True)


def paper_searchable_text(paper: Paper) -> str:
    return " ".join(
        (
            paper.title,
            paper.abstract,
            " ".join(paper.authors),
            " ".join(paper.subjects),
        )
    ).casefold()


def select_papers(
    papers: Iterable[Paper],
    keywords: Sequence[str] = KEYWORDS,
    excluded_keywords: Sequence[str] = EXCLUDED_KEYWORDS,
) -> list[Paper]:
    normalized_keywords = tuple(keyword.casefold().strip() for keyword in keywords if keyword.strip())
    normalized_exclusions = tuple(
        keyword.casefold().strip() for keyword in excluded_keywords if keyword.strip()
    )

    if not normalized_keywords:
        raise ArxivDailyError("Keyword configuration must not be empty")

    selected: list[Paper] = []
    for paper in papers:
        text = paper_searchable_text(paper)
        if any(exclusion in text for exclusion in normalized_exclusions):
            continue
        if any(keyword in text for keyword in normalized_keywords):
            selected.append(paper)

    return sorted(selected, key=lambda paper: (paper.published_at, paper.identifier), reverse=True)


def load_state(path: Path) -> set[str]:
    if not path.exists():
        return set()

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        identifiers = document.get("published_identifiers", [])
    except (OSError, json.JSONDecodeError) as error:
        raise ArxivDailyError(f"Cannot read state file {path}: {error}") from error

    if not isinstance(identifiers, list) or not all(isinstance(item, str) for item in identifiers):
        raise ArxivDailyError(f"State file {path} has an invalid published_identifiers value")

    return set(identifiers)


def atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def save_state(path: Path, identifiers: Iterable[str], generated_at: datetime) -> None:
    limited_identifiers = sorted(set(identifiers))[-STATE_HISTORY_LIMIT:]
    document = {
        "schema_version": 1,
        "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat(),
        "published_identifiers": limited_identifiers,
    }
    atomic_write(path, json.dumps(document, indent=2, sort_keys=True) + "\n")


def render_report(papers: Sequence[Paper], generated_at: datetime) -> str:
    report_date = generated_at.astimezone(timezone.utc)
    date_label = report_date.strftime("%A, %-d %B %Y") if os.name != "nt" else report_date.strftime("%A, %#d %B %Y")

    lines = [
        f"# Showing new listings for {date_label}",
        "",
        "Auto update Star Formation & Molecular Cloud arXiv papers every weekday.",
        "",
        f"Keyword list: {list(KEYWORDS)!r}",
        "",
        f"Excluded: {list(EXCLUDED_KEYWORDS)!r}",
        "",
        f"### Today: {len(papers)} papers",
        "",
    ]

    for paper in papers:
        lines.extend(
            [
                f"#### {paper.title}",
                f" - **Authors:** {', '.join(paper.authors) or 'Not listed'}",
                f" - **Subjects:** {'; '.join(paper.subjects) or 'Not listed'}",
                f" - **Arxiv link:** {paper.abs_url}",
                f" - **Pdf link:** {paper.pdf_url}",
                "",
                " - **Abstract**",
                f" {paper.abstract}",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            f"Generated at {format_datetime(report_date, usegmt=True)}.",
            "",
        ]
    )
    return "\n".join(lines)


def run(generated_at: datetime | None = None) -> int:
    now = (generated_at or utc_now()).astimezone(timezone.utc)
    all_papers = fetch_all_papers()
    candidates = select_papers(all_papers)

    already_published = load_state(STATE_PATH)
    new_papers = [paper for paper in candidates if paper.identifier not in already_published]

    atomic_write(REPORT_PATH, render_report(new_papers, now))
    save_state(
        STATE_PATH,
        already_published | {paper.identifier for paper in new_papers},
        now,
    )

    print(f"Published {len(new_papers)} new paper(s) to {REPORT_PATH}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a deduplicated daily arXiv report.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the remote feed and print the report without writing files.",
    )
    arguments = parser.parse_args()

    try:
        if arguments.dry_run:
            papers = select_papers(fetch_all_papers())
            print(render_report(papers, utc_now()))
            return 0
        return run()
    except ArxivDailyError as error:
        print(f"arXiv daily update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
