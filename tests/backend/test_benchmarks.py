from app.backend.services.benchmarks import load_benchmarks


def test_benchmarks_keep_diagnostic_blend_out_of_headline() -> None:
    rows = load_benchmarks()
    assert rows
    diagnostic = [row for row in rows if "INVERSE_MAE_BLEND" in row["model"]]
    assert diagnostic
    assert all(not row["headline_eligible"] for row in diagnostic)


def test_benchmarks_include_completed_multimodal_ablation() -> None:
    rows = load_benchmarks()
    ablation = [row for row in rows if row["group"] == "multimodal_ablation"]
    assert len(ablation) == 20
    assert {row["horizon_days"] for row in ablation} == {7, 14}
    assert all(not row["headline_eligible"] for row in ablation)
