from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import main as updater


class ArxivDailyTests(TestCase):
    def setUp(self) -> None:
        self.paper = updater.Paper(
            identifier="2606.00177",
            title="Magnesium Silicate Clouds in the Atmosphere of HD 209458b",
            authors=("Katy L. Chubb",),
            subjects=("astro-ph.EP", "astro-ph.IM"),
            abstract=(
                "Cloud chemistry and magnetic turbulence in the interstellar medium "
                "are discussed without galaxies."
            ),
            published_at=datetime(2026, 6, 2, 1, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 2, 1, 0, tzinfo=timezone.utc),
        )

    def test_extract_identifier_removes_version(self) -> None:
        self.assertEqual(
            updater.extract_identifier("http://arxiv.org/abs/2606.00177v2"),
            "2606.00177",
        )

    def test_extract_identifier_rejects_malformed_value(self) -> None:
        with self.assertRaises(updater.ArxivDailyError):
            updater.extract_identifier("http://arxiv.org/abs/not-an-arxiv-id")

    def test_matching_keyword_selects_paper(self) -> None:
        selected = updater.select_papers([self.paper], keywords=("magnetic",), excluded_keywords=())
        self.assertEqual(selected, [self.paper])

    def test_exclusion_overrides_keyword_match(self) -> None:
        selected = updater.select_papers(
            [self.paper],
            keywords=("cloud",),
            excluded_keywords=("galaxies",),
        )
        self.assertEqual(selected, [])

    def test_empty_keyword_configuration_is_rejected(self) -> None:
        with self.assertRaises(updater.ArxivDailyError):
            updater.select_papers([self.paper], keywords=(), excluded_keywords=())

    def test_report_uses_the_utc_listing_date_and_safe_links(self) -> None:
        report = updater.render_report(
            [self.paper],
            datetime(2026, 6, 2, 2, 0, tzinfo=timezone.utc),
        )

        self.assertIn("# Showing new listings for Tuesday, 2 June 2026", report)
        self.assertIn("https://arxiv.org/abs/2606.00177", report)
        self.assertIn("https://arxiv.org/pdf/2606.00177", report)
        self.assertIn("### Today: 1 papers", report)

    def test_state_round_trip_and_atomic_replacement(self) -> None:
        state_path = Path(self.id()) / "state.json"
        try:
            updater.save_state(
                state_path,
                {"2606.00177", "2606.00178"},
                datetime(2026, 6, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(
                updater.load_state(state_path),
                {"2606.00177", "2606.00178"},
            )
        finally:
            if state_path.exists():
                state_path.unlink()
            if state_path.parent.exists():
                state_path.parent.rmdir()

    def test_run_deduplicates_previously_published_papers(self) -> None:
        report_path = Path(self.id() + "-README.md")
        state_path = Path(self.id() + "-state.json")

        try:
            updater.save_state(
                state_path,
                {self.paper.identifier},
                datetime(2026, 6, 2, tzinfo=timezone.utc),
            )

            with (
                patch.object(updater, "REPORT_PATH", report_path),
                patch.object(updater, "STATE_PATH", state_path),
                patch.object(updater, "fetch_all_papers", return_value=[self.paper]),
            ):
                self.assertEqual(
                    updater.run(datetime(2026, 6, 2, 2, 0, tzinfo=timezone.utc)),
                    0,
                )

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("### Today: 0 papers", report)
            self.assertNotIn(self.paper.title, report)
        finally:
            for path in (report_path, state_path):
                if path.exists():
                    path.unlink()


if __name__ == "__main__":
    main()
