from __future__ import annotations

import hashlib
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
    return {
        "features": features,
        "confidence": round(sum(v["confidence"] for v in features.values()) / len(features), 3),
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
    if not changes:
        changes["manual_note"] = instruction
    return changes


def apply_changes(spec: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    import copy

    updated = copy.deepcopy(spec)
    for key, value in changes.items():
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
                "passed": passed,
                "mandatory": requirement["severity"] == "mandatory",
                "observed": observed,
                "expected": value,
            }
        )
    blocking = [check for check in checks if check["mandatory"] and not check["passed"]]
    return {"passed": not blocking, "checks": checks, "blocking_failures": blocking}
