from src.validation.report_accuracy_checker import evaluate_report, run_report_accuracy_checks


def link(**overrides):
    base = {"above_90_events": 0, "above_80_events": 0, "above_70_events": 0, "total_base_events": 1440,
            "peak": 50.0, "average": 20.0, "p95": 40.0, "episodes": []}
    base.update(overrides)
    return base


def test_clean_data_passes(monkeypatch):
    monkeypatch.setattr("src.validation.report_accuracy_checker.SITE_ORDER", ["Pune"])
    data = {"Pune": {"Primary": link(), "Secondary": link()}}
    assert run_report_accuracy_checks(data, expected_minutes=1440) == []


def test_problems_are_reported(monkeypatch):
    monkeypatch.setattr("src.validation.report_accuracy_checker.SITE_ORDER", ["Pune", "Mumbai"])
    data = {"Pune": {"Primary": link(above_90_events=5, above_80_events=2, above_70_events=2,
                                     episodes=[{"minutes": 2}], total_base_events=1000),
                     "Secondary": link(peak=120.0)}}
    failed = {r.name for r in evaluate_report(data, expected_minutes=1440) if not r.passed}
    assert failed == {"All sites reporting", "Threshold counts consistent", "Values within 0-100%", "Sample coverage"}
