from alpha.domain import apply_changes, deterministic_qa, parse_edit_instruction


def test_edit_parser_supports_initial_natural_language_changes():
    spec = {
        "start_ms": 10_000,
        "end_ms": 40_000,
        "duration_ms": 30_000,
        "watermark": {"size_pct": 0.2, "position": "bottom_right"},
        "captions": {"size": "medium"},
    }
    changes = parse_edit_instruction(
        'start 3 seconds earlier and make the watermark smaller, captions larger, headline to "Watch this"',
        spec,
    )
    assert changes["start_ms"] == 7_000
    assert changes["watermark.size_pct"] == 0.16
    assert changes["captions.size"] == "large"
    assert changes["headline.text"] == "Watch this"
    updated = apply_changes(spec, changes)
    assert updated["duration_ms"] == 33_000
    assert updated["watermark"]["size_pct"] == 0.16


def test_ai_requirement_never_masquerades_as_deterministic_check():
    spec = {
        "source_item_id": "approved",
        "duration_ms": 20_000,
        "aspect_ratio": "9:16",
        "width": 720,
        "height": 1280,
    }
    report = deterministic_qa(
        spec,
        [
            {
                "key": "strong_hook",
                "requirement_type": "ai_evaluated",
                "operator": "eq",
                "value": True,
                "severity": "mandatory",
            }
        ],
        {"approved"},
    )
    assert report["passed"]
    assert all(check["key"] != "strong_hook" for check in report["checks"])
