from app.load_smoke import RequestResult, percentile, summarize


def test_load_summary_calculates_percentiles_and_error_rate() -> None:
    results = [
        RequestResult(duration_ms=float(duration), status_code=200)
        for duration in range(1, 101)
    ]
    results[-1] = RequestResult(duration_ms=100.0, status_code=500)

    summary = summarize(results)

    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert summary["requests"] == 100
    assert summary["errors"] == 1
    assert summary["error_rate"] == 0.01
    assert summary["p95_ms"] == 95.0
