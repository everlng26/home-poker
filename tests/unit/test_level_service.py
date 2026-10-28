from app.services.level_service import STRUCTURE_PRESETS


def test_default_presets_cover_four_to_six_hour_tournament() -> None:
    totals: dict[str, int] = {}
    for preset in STRUCTURE_PRESETS.values():
        total_seconds = sum(level["duration_seconds"] for level in preset)
        totals[next(name for name, levels in STRUCTURE_PRESETS.items() if levels is preset)] = total_seconds
        assert 4 * 60 * 60 <= total_seconds <= 6 * 60 * 60
        for level in preset:
            if level["kind"] == "play":
                assert level["ante"] == level["big_blind"]
    assert totals["fast"] < totals["standard"] < totals["deep"]
    assert totals["fast"] == 4 * 60 * 60
    assert totals["standard"] == 5 * 60 * 60
    assert totals["deep"] == 6 * 60 * 60
