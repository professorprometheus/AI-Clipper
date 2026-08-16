from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from typing import Any

SCORE_COMPONENTS = [
    "research_alignment",
    "example_alignment",
    "hook_quality",
    "standalone_clarity",
    "humour",
    "controversy",
    "emotional_strength",
    "informational_value",
    "novelty",
    "exact_moment_saturation",
    "source_quality",
    "campaign_relevance",
    "rule_risk",
    "diversification",
]

DEFAULT_WEIGHTS = {
    "research_alignment": 1.4,
    "example_alignment": 1.1,
    "hook_quality": 1.3,
    "standalone_clarity": 1.2,
    "humour": 0.5,
    "controversy": 0.4,
    "emotional_strength": 0.7,
    "informational_value": 0.9,
    "novelty": 0.8,
    "exact_moment_saturation": -1.0,
    "source_quality": 0.8,
    "campaign_relevance": 1.3,
    "rule_risk": -1.5,
    "diversification": 0.6,
}


def embedding(text: str, dimensions: int = 32) -> list[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0 if digest[2] % 2 else -1.0
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / magnitude, 6) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def research_signals(
    metrics: dict[str, Any], baseline: dict[str, Any], age_hours: float
) -> dict[str, float]:
    views = float(metrics.get("views", 0))
    median = max(float(baseline.get("median_views", 0)), 1.0)
    return {
        "relative_outlier": round(views / median, 4),
        "view_velocity": round(views / max(age_hours, 1.0), 4),
        "engagement_rate": round(
            (float(metrics.get("likes", 0)) + float(metrics.get("comments", 0))) / max(views, 1), 4
        ),
    }


def cluster_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[observation["labels"]["topic"]].append(observation)
    clusters = []
    for label, members in grouped.items():
        avg_outlier = sum(row["derived"]["relative_outlier"] for row in members) / len(members)
        saturated = "saturated" in label or len(members) > 5
        clusters.append(
            {
                "label": label,
                "evidence_ids": [row["id"] for row in members],
                "metrics": {
                    "post_count": len(members),
                    "avg_relative_outlier": round(avg_outlier, 4),
                    "cross_creator_count": len({row["creator"] for row in members}),
                    "saturation": 1.0 if saturated else round(min(len(members) / 10, 0.8), 2),
                },
                "lifecycle_state": "emerging"
                if len(members) >= 3 and avg_outlier >= 5
                else ("saturated" if saturated else "stable"),
            }
        )
    return sorted(clusters, key=lambda item: item["metrics"]["avg_relative_outlier"], reverse=True)


def infer_style(example_analyses: list[dict[str, Any]]) -> dict[str, Any]:
    if not example_analyses:
        return {
            "features": {
                "opening_type": {"value": "direct_insight", "confidence": 0.35, "evidence_ids": []},
                "caption_density": {"value": "medium", "confidence": 0.3, "evidence_ids": []},
                "clip_length_seconds": {"value": 30, "confidence": 0.3, "evidence_ids": []},
            },
            "confidence": 0.3,
        }
    fields = ["opening_type", "emotion", "headline", "caption_pattern", "crop", "pacing", "ending"]
    features: dict[str, Any] = {}
    for field in fields:
        values = [str(row["analysis"][field]) for row in example_analyses]
        value, count = Counter(values).most_common(1)[0]
        features[field] = {
            "value": value,
            "confidence": round(count / len(values), 3),
            "evidence_ids": [
                row["id"] for row in example_analyses if str(row["analysis"][field]) == value
            ],
        }
    durations = [float(row["analysis"]["duration_seconds"]) for row in example_analyses]
    features["clip_length_seconds"] = {
        "value": round(sum(durations) / len(durations), 2),
        "confidence": 0.8,
        "evidence_ids": [row["id"] for row in example_analyses],
    }
    enrichment_fields = sorted(
        {key for row in example_analyses for key in row["analysis"].get("enrichment_features", {})}
    )
    enrichment: dict[str, Any] = {}
    for field in enrichment_fields:
        evidence = [
            (row["id"], row["analysis"]["enrichment_features"][field])
            for row in example_analyses
            if field in row["analysis"].get("enrichment_features", {})
        ]
        available = [
            (row_id, value) for row_id, value in evidence if value["status"] != "unavailable"
        ]
        if not available:
            enrichment[field] = {
                "status": "unavailable",
                "value": None,
                "confidence": 0.0,
                "evidence_ids": [row_id for row_id, _value in evidence],
            }
            continue
        values = [str(value.get("value")) for _row_id, value in available]
        common, count = Counter(values).most_common(1)[0]
        enrichment[field] = {
            "status": "observed"
            if any(value["status"] == "observed" for _row_id, value in available)
            else "inferred",
            "value": available[values.index(common)][1].get("value"),
            "confidence": round(
                sum(float(value.get("confidence", 0)) for _row_id, value in available)
                / len(available)
                * (count / len(available)),
                3,
            ),
            "evidence_ids": [
                row_id for row_id, value in available if str(value.get("value")) == common
            ],
        }
    features["enrichment"] = enrichment
    top_level_confidences = [
        float(value["confidence"])
        for key, value in features.items()
        if key != "enrichment" and "confidence" in value
    ]
    enrichment_confidences = [float(value["confidence"]) for value in enrichment.values()]
    return {
        "features": features,
        "confidence": round(
            sum(top_level_confidences + enrichment_confidences)
            / max(1, len(top_level_confidences) + len(enrichment_confidences)),
            3,
        ),
    }


def candidate_scores(
    text: str,
    research_similarity: float,
    example_count: int,
    source_index: int,
    saturation: float,
) -> dict[str, float]:
    lower = text.lower()
    return {
        "research_alignment": round(max(0.0, research_similarity), 3),
        "example_alignment": round(min(example_count / 5, 1), 3),
        "hook_quality": 0.9
        if any(word in lower for word in ("surprising", "miss", "fails"))
        else 0.55,
        "standalone_clarity": 0.8 if len(text.split()) >= 8 else 0.5,
        "humour": 0.85 if "funny" in lower else 0.2,
        "controversy": 0.65 if "fails" in lower else 0.15,
        "emotional_strength": 0.6 if "surprising" in lower else 0.3,
        "informational_value": 0.85
        if any(word in lower for word in ("proof", "method", "point"))
        else 0.5,
        "novelty": round(max(0.1, 0.9 - saturation), 3),
        "exact_moment_saturation": round(saturation, 3),
        "source_quality": 0.75,
        "campaign_relevance": round(max(0.45, research_similarity), 3),
        "rule_risk": 0.0,
        "diversification": round(min(0.5 + source_index * 0.04, 0.95), 3),
    }


def analyse_enrichment_features(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Label only what available evidence supports; metadata cannot observe edit tracks."""
    supplied = analysis.get("live_evidence", {}).get("enrichment_observations", {})
    fields = (
        "music_presence",
        "music_intensity",
        "music_changes",
        "reaction_inserts",
        "meme_inserts",
        "broll_frequency",
        "insert_timing",
        "insert_duration",
        "zoom_punch_in_frequency",
        "freeze_frames",
        "sound_effects",
        "visual_emphasis",
    )
    result: dict[str, dict[str, Any]] = {}
    for field in fields:
        if field in supplied:
            result[field] = {
                "status": "observed",
                "value": supplied[field],
                "confidence": 0.95,
                "evidence": "provider-supplied measurable edit observation",
            }
        else:
            result[field] = {
                "status": "unavailable",
                "value": None,
                "confidence": 0.0,
                "evidence": "public metadata/transcript does not expose this edit-track feature",
            }
    # Text/style evidence supports weak strategy inference, never an observation claim.
    if float(analysis.get("humour", 0)) >= 0.7:
        result["reaction_inserts"] = {
            "status": "inferred",
            "value": "potentially_present",
            "confidence": 0.35,
            "evidence": "humour-oriented successful example; insert itself was not measurable",
        }
    if analysis.get("pacing") == "fast":
        result["zoom_punch_in_frequency"] = {
            "status": "inferred",
            "value": "possibly_frequent",
            "confidence": 0.3,
            "evidence": "fast pacing heuristic; camera transform was not measurable",
        }
    if analysis.get("headline") not in {None, "not_measurable_from_metadata"}:
        result["visual_emphasis"] = {
            "status": "inferred",
            "value": "likely",
            "confidence": 0.4,
            "evidence": "headline/style heuristic; exact emphasis track was not measurable",
        }
    return result


def enrichment_suitability(text: str) -> dict[str, dict[str, Any]]:
    lower = text.lower()
    humour = any(word in lower for word in ("funny", "absurd", "joke", "ridiculous"))
    context = any(word in lower for word in ("proof", "method", "example", "context", "because"))
    emotional = any(
        word in lower for word in ("surprising", "fails", "miss", "important", "memorable")
    )
    return {
        "static_visual_risk": {
            "status": "unavailable",
            "value": None,
            "reason": "no shot-change or motion track is available at candidate scoring time",
        },
        "humour_insert_opportunity": {
            "status": "inferred",
            "value": 0.85 if humour else 0.2,
            "reason": "derived from timestamped transcript language",
        },
        "context_visualisation_opportunity": {
            "status": "inferred",
            "value": 0.8 if context else 0.25,
            "reason": "derived from explanation/example language",
        },
        "broll_suitability": {
            "status": "inferred",
            "value": 0.75 if context else 0.2,
            "reason": "contextual claims can be illustrated when authorised assets exist",
        },
        "music_suitability": {
            "status": "inferred",
            "value": 0.65 if emotional else 0.25,
            "reason": "emotional language is a weak music-strategy signal",
        },
        "enrichment_overload_risk": {
            "status": "unavailable",
            "value": None,
            "reason": "risk depends on the eventual plan and campaign limits",
        },
    }


def weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(abs(weights.get(key, 0)) for key in SCORE_COMPONENTS) or 1
    raw = sum(scores.get(key, 0) * weights.get(key, 0) for key in SCORE_COMPONENTS)
    return round(max(0.0, min(1.0, raw / total_weight + 0.25)), 5)


def parse_edit_instruction(instruction: str, current: dict[str, Any]) -> dict[str, Any]:
    text = instruction.lower()
    changes: dict[str, Any] = {}
    time_match = re.search(r"start\s+(\d+(?:\.\d+)?)\s*seconds?\s+(earlier|later)", text)
    if time_match:
        delta = float(time_match.group(1)) * 1000
        changes["start_ms"] = max(
            0, int(current["start_ms"] + (-delta if time_match.group(2) == "earlier" else delta))
        )
    end_match = re.search(r"end\s+(\d+(?:\.\d+)?)\s*seconds?\s+(earlier|later)", text)
    if end_match:
        delta = float(end_match.group(1)) * 1000
        changes["end_ms"] = max(
            1000, int(current["end_ms"] + (-delta if end_match.group(2) == "earlier" else delta))
        )
    if "watermark smaller" in text:
        changes["watermark.size_pct"] = round(
            max(0.03, current.get("watermark", {}).get("size_pct", 0.18) * 0.8), 3
        )
    if "watermark larger" in text:
        changes["watermark.size_pct"] = round(
            min(1.0, current.get("watermark", {}).get("size_pct", 0.18) * 1.2), 3
        )
    for position in ("top left", "top right", "bottom left", "bottom right", "center"):
        if f"watermark {position}" in text or f"watermark to the {position}" in text:
            changes["watermark.position"] = position.replace(" ", "_")
    if "captions larger" in text:
        changes["captions.size"] = "large"
    if "captions smaller" in text:
        changes["captions.size"] = "small"
    headline = re.search(r"headline(?: text)?\s*(?:to|:)?\s*[\"']([^\"']+)[\"']", instruction, re.I)
    if headline:
        changes["headline.text"] = headline.group(1)
    crop = re.search(r"crop\s+(left|right|up|down|center)", text)
    if crop:
        changes["crop.adjustment"] = crop.group(1)
    if "remove context" in text:
        changes["context_segment"] = "removed"
    if "restore context" in text:
        changes["context_segment"] = "restored"
    remove_types: list[str] = []
    if "remove music" in text or "no music" in text:
        remove_types.append("music")
    if "remove the meme" in text or "remove meme" in text or "less memes" in text:
        remove_types.extend(["meme_image", "meme_video", "reaction"])
    if "remove b-roll" in text or "remove broll" in text:
        remove_types.append("broll")
    if "remove sound effects" in text or "remove sfx" in text:
        remove_types.append("sfx")
    if "remove the zoom" in text or "remove zoom" in text or "remove punch-in" in text:
        remove_types.extend(["punch_in", "dynamic_crop", "speaker_focus"])
    if "remove external images" in text:
        remove_types.extend(["image", "graphic"])
    if remove_types:
        changes["enrichment_remove_types"] = sorted(set(remove_types))
    if "music quieter" in text or "quieter music" in text or "lower the music" in text:
        changes["enrichment_music_volume_delta_db"] = -6.0
    if "music louder" in text or "louder music" in text:
        changes["enrichment_music_volume_delta_db"] = 3.0
    if "more b-roll" in text or "more broll" in text:
        changes["enrichment_request_asset_type"] = "broll"
    if "change music" in text or "replace music" in text:
        changes["enrichment_replace_asset_type"] = "music"
    if "replace meme" in text or "change meme" in text:
        changes["enrichment_replace_asset_type"] = "meme"
    if "replace reaction" in text or "change reaction" in text:
        changes["enrichment_replace_asset_type"] = "reaction"
    if "replace sound effect" in text or "change sound effect" in text:
        changes["enrichment_replace_asset_type"] = "sfx"
    if "replace b-roll" in text or "change b-roll" in text or "replace broll" in text:
        changes["enrichment_replace_asset_type"] = "broll"
    if "regenerate enrichment" in text:
        changes["enrichment_regenerate"] = True
    if ("add a zoom" in text or "add zoom" in text or "add a punch-in" in text) and (
        "punchline" in text or "hook" in text
    ):
        duration = int(current.get("duration_ms", 1000))
        at_hook = "hook" in text and "punchline" not in text
        changes["enrichment_add_native"] = {
            "type": "punch_in",
            "start_ms": 250 if at_hook else max(0, duration - 1500),
            "duration_ms": min(1000, duration),
            "mode": "native",
            "purpose": "emphasise the hook" if at_hook else "emphasise the punchline",
            "reason": "requested during human review",
            "parameters": {"scale": 1.12},
        }
    timing = re.search(
        r"move\s+(music|meme|reaction|b[ -]?roll|zoom|punch[ -]?in)\s+to\s+(\d+(?:\.\d+)?)\s*seconds?",
        text,
    )
    if timing:
        names = {
            "meme": ["meme_image", "meme_video"],
            "reaction": ["reaction"],
            "b-roll": ["broll"],
            "b roll": ["broll"],
            "broll": ["broll"],
            "zoom": ["punch_in"],
            "punch-in": ["punch_in"],
            "punch in": ["punch_in"],
            "music": ["music"],
        }
        changes["enrichment_move"] = {
            "types": names[timing.group(1)],
            "start_ms": round(float(timing.group(2)) * 1000),
        }
    if not changes:
        changes["manual_note"] = instruction
    return changes


def apply_changes(spec: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    import copy

    updated = copy.deepcopy(spec)
    enrichment = updated.setdefault("enrichment", {})
    events = enrichment.setdefault("events", [])
    remove_types = set(changes.get("enrichment_remove_types", []))
    if remove_types:
        events[:] = [event for event in events if event.get("type") not in remove_types]
    if "enrichment_music_volume_delta_db" in changes:
        controls = enrichment.get("controls", {})
        minimum = float(controls.get("music_volume_min_db", -60))
        maximum = float(controls.get("music_volume_max_db", 0))
        for event in events:
            if event.get("type") == "music":
                current_volume = float(event.setdefault("parameters", {}).get("volume_db", -20))
                event["parameters"]["volume_db"] = max(
                    minimum,
                    min(
                        maximum, current_volume + float(changes["enrichment_music_volume_delta_db"])
                    ),
                )
    if "enrichment_add_native" in changes:
        event = copy.deepcopy(changes["enrichment_add_native"])
        event["id"] = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        events.append(event)
    if "enrichment_move" in changes:
        move = changes["enrichment_move"]
        for event in events:
            if event.get("type") in move["types"]:
                event["start_ms"] = max(
                    0,
                    min(
                        int(move["start_ms"]),
                        int(updated.get("duration_ms", 0)) - int(event.get("duration_ms", 0)),
                    ),
                )
    for key, value in changes.items():
        if key.startswith("enrichment_"):
            continue
        if "." not in key:
            updated[key] = value
            continue
        parent, child = key.split(".", 1)
        updated.setdefault(parent, {})[child] = value
    updated["duration_ms"] = max(1000, updated["end_ms"] - updated["start_ms"])
    return updated


def deterministic_qa(
    spec: dict[str, Any], requirements: list[dict[str, Any]], approved_source_ids: set[str]
) -> dict[str, Any]:
    checks = [
        {
            "key": "source_provenance",
            "passed": spec.get("source_item_id") in approved_source_ids,
            "mandatory": True,
            "observed": spec.get("source_item_id"),
        },
        {
            "key": "aspect_ratio",
            "passed": spec.get("aspect_ratio") == "9:16",
            "mandatory": True,
            "observed": spec.get("aspect_ratio"),
        },
        {
            "key": "resolution",
            "passed": spec.get("width", 0) >= 720 and spec.get("height", 0) >= 1280,
            "mandatory": True,
            "observed": f"{spec.get('width')}x{spec.get('height')}",
        },
    ]
    render_probe = spec.get("render", {}).get("probe")
    if render_probe is not None:
        expected_duration = int(spec.get("duration_ms", 0))
        actual_duration = int(render_probe.get("duration_ms", 0))
        checks.extend(
            [
                {
                    "key": "render_media_valid",
                    "passed": bool(render_probe.get("valid")),
                    "mandatory": True,
                    "observed": render_probe.get("probe_method"),
                },
                {
                    "key": "rendered_resolution",
                    "passed": render_probe.get("width") == spec.get("width")
                    and render_probe.get("height") == spec.get("height"),
                    "mandatory": True,
                    "observed": f"{render_probe.get('width')}x{render_probe.get('height')}",
                    "expected": f"{spec.get('width')}x{spec.get('height')}",
                },
                {
                    "key": "rendered_duration",
                    "passed": abs(actual_duration - expected_duration) <= 750,
                    "mandatory": True,
                    "observed": actual_duration,
                    "expected": expected_duration,
                },
                {
                    "key": "rendered_audio",
                    "passed": bool(render_probe.get("has_audio")),
                    "mandatory": bool(spec.get("audio", {}).get("normalise", True)),
                    "observed": bool(render_probe.get("has_audio")),
                },
            ]
        )
    enrichment = spec.get("enrichment", {})
    controls = enrichment.get("controls", {})
    events = enrichment.get("events", [])
    native_types = {
        "punch_in",
        "dynamic_crop",
        "freeze_frame",
        "text_emphasis",
        "keyword_highlight",
        "progress_caption",
        "pull_quote",
        "blur_background",
        "speaker_focus",
        "fast_cut",
        "reaction_hold",
    }
    external_events = [event for event in events if event.get("type") not in native_types]
    insert_events = [event for event in external_events if event.get("type") != "music"]
    max_inserts = int(controls.get("max_inserts", 0))
    max_insert_ms = round(float(controls.get("max_insert_duration_seconds", 2.0)) * 1000)
    prohibited = set(controls.get("prohibited_asset_types", []))
    permitted_external_types = {
        "music",
        "meme_image",
        "meme_video",
        "reaction",
        "broll",
        "sfx",
        "image",
        "graphic",
    }
    logical_checks: list[dict[str, Any]] = [
        {
            "key": "enrichment_insert_limit",
            "passed": len(insert_events) <= max_inserts,
            "mandatory": True,
            "observed": len(insert_events),
            "expected": max_inserts,
        },
        {
            "key": "render_object_persisted",
            "passed": bool(
                spec.get("render", {}).get(
                    "storage_verified", render_probe.get("valid") if render_probe else True
                )
            ),
            "mandatory": render_probe is not None,
            "observed": spec.get("render", {}).get("file_uri"),
        },
    ]
    for event in events:
        event_type = str(event.get("type"))
        start_ms = int(event.get("start_ms", 0))
        duration_ms = int(event.get("duration_ms", 0))
        is_native = event_type in native_types
        allowed = is_native or event_type in permitted_external_types
        if not is_native:
            media_kind = event.get("media_kind")
            if event_type == "music":
                allowed = bool(controls.get("music_allowed"))
            elif event_type == "sfx":
                allowed = bool(controls.get("sound_effects_allowed"))
            elif event_type == "broll":
                allowed = bool(controls.get("broll_allowed"))
            elif event_type in {"meme_image", "meme_video", "reaction"}:
                allowed = bool(controls.get("memes_allowed"))
            if media_kind == "video":
                allowed = allowed and bool(controls.get("external_video_allowed"))
            else:
                allowed = allowed and bool(controls.get("external_images_allowed"))
            if event_type in {"music", "sfx"}:
                # Audio permissions are expressed by their dedicated controls.
                allowed = event_type not in prohibited and (
                    bool(controls.get("music_allowed"))
                    if event_type == "music"
                    else bool(controls.get("sound_effects_allowed"))
                )
        logical_checks.extend(
            [
                {
                    "key": f"enrichment_bounds:{event.get('id', event_type)}",
                    "passed": start_ms >= 0
                    and duration_ms > 0
                    and start_ms + duration_ms <= int(spec.get("duration_ms", 0)),
                    "mandatory": True,
                    "observed": {"start_ms": start_ms, "duration_ms": duration_ms},
                },
                {
                    "key": f"enrichment_type_permitted:{event.get('id', event_type)}",
                    "passed": allowed and event_type not in prohibited,
                    "mandatory": True,
                    "observed": event_type,
                },
            ]
        )
        if not is_native:
            provenance = event.get("provenance", {})
            required_source = str(controls.get("required_asset_source") or "").lower().strip()
            source_haystack = " ".join(
                str(value or "")
                for value in (
                    provenance.get("licence"),
                    provenance.get("source_url"),
                    provenance.get("library"),
                )
            ).lower()
            restrictions = provenance.get("campaign_restrictions", {})
            campaign_id = spec.get("metadata", {}).get("campaign_id")
            permitted_campaigns = restrictions.get("campaign_ids", [])
            prohibited_campaigns = restrictions.get("prohibited_campaign_ids", [])
            logical_checks.extend(
                [
                    {
                        "key": f"asset_rights:{event.get('id', event_type)}",
                        "passed": bool(provenance.get("licence"))
                        and bool(provenance.get("rights_attestation"))
                        and bool(provenance.get("permitted_commercial_use")),
                        "mandatory": True,
                        "observed": provenance.get("licence"),
                    },
                    {
                        "key": f"asset_storage:{event.get('id', event_type)}",
                        "passed": bool(event.get("asset_uri"))
                        and bool(event.get("storage_verified")),
                        "mandatory": True,
                        "observed": event.get("asset_uri"),
                    },
                    {
                        "key": f"asset_attribution:{event.get('id', event_type)}",
                        "passed": not provenance.get("attribution_requirement")
                        or bool(provenance.get("attribution_text")),
                        "mandatory": True,
                        "observed": provenance.get("attribution_text"),
                    },
                    {
                        "key": f"asset_required_source:{event.get('id', event_type)}",
                        "passed": not required_source or required_source in source_haystack,
                        "mandatory": True,
                        "observed": source_haystack,
                        "expected": required_source or None,
                    },
                    {
                        "key": f"asset_campaign_scope:{event.get('id', event_type)}",
                        "passed": campaign_id not in prohibited_campaigns
                        and (not permitted_campaigns or campaign_id in permitted_campaigns),
                        "mandatory": True,
                        "observed": campaign_id,
                    },
                ]
            )
            if event_type != "music":
                logical_checks.append(
                    {
                        "key": f"enrichment_duration:{event.get('id', event_type)}",
                        "passed": duration_ms <= max_insert_ms,
                        "mandatory": True,
                        "observed": duration_ms,
                        "expected": max_insert_ms,
                    }
                )
        if event_type == "music":
            parameters = event.get("parameters", {})
            volume = float(parameters.get("volume_db", 0))
            minimum = float(controls.get("music_volume_min_db", -60))
            maximum = float(controls.get("music_volume_max_db", 0))
            logical_checks.extend(
                [
                    {
                        "key": "music_volume_range",
                        "passed": minimum <= volume <= maximum,
                        "mandatory": True,
                        "observed": volume,
                        "expected": [minimum, maximum],
                    },
                    {
                        "key": "music_speech_ducking",
                        "passed": not controls.get("ducking_required")
                        or bool(parameters.get("ducking")),
                        "mandatory": True,
                        "observed": bool(parameters.get("ducking")),
                    },
                ]
            )
    checks.extend(logical_checks)
    for requirement in requirements:
        if requirement["requirement_type"] != "deterministic":
            continue
        key = requirement["key"]
        value = requirement["value"]
        observed: Any = None
        passed = True
        if key in {"max_duration_seconds", "duration_max"}:
            observed = spec["duration_ms"] / 1000
            passed = observed <= float(value)
        elif key in {"min_duration_seconds", "duration_min"}:
            observed = spec["duration_ms"] / 1000
            passed = observed >= float(value)
        elif key == "watermark_present":
            observed = bool(spec.get("watermark", {}).get("enabled"))
            passed = observed == bool(value)
        elif key == "watermark_position":
            observed = spec.get("watermark", {}).get("position")
            passed = observed == value
        elif key == "captions_required":
            observed = bool(spec.get("captions", {}).get("enabled"))
            passed = observed == bool(value)
        elif key == "aspect_ratio":
            observed = spec.get("aspect_ratio")
            passed = observed == value
        else:
            observed = spec.get("metadata", {}).get(key)
            if requirement["operator"] == "present":
                passed = observed is not None
            elif requirement["operator"] == "contains":
                passed = str(value).lower() in str(observed).lower()
            elif observed is not None:
                passed = observed == value
            else:
                passed = True
        checks.append(
            {
                "key": key,
                "requirement_id": requirement.get("id"),
                "passed": passed,
                "mandatory": requirement["severity"] == "mandatory",
                "observed": observed,
                "expected": value,
            }
        )
    blocking = [check for check in checks if check["mandatory"] and not check["passed"]]
    return {"passed": not blocking, "checks": checks, "blocking_failures": blocking}
