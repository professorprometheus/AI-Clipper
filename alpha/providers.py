from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import dump, load
from .domain import parse_edit_instruction


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{host}{path}{query}"


def stable_id(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class StorageAdapter(ABC):
    @abstractmethod
    def put_bytes(self, key: str, content: bytes) -> str: ...

    @abstractmethod
    def put_json(self, key: str, content: Any) -> str: ...


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("storage key escapes root")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def put_bytes(self, key: str, content: bytes) -> str:
        path = self._safe_path(key)
        path.write_bytes(content)
        return str(path)

    def put_json(self, key: str, content: Any) -> str:
        path = self._safe_path(key)
        path.write_text(json.dumps(content, indent=2, sort_keys=True), encoding="utf-8")
        return str(path)


class SourceProvider(ABC):
    @abstractmethod
    def resolve(self, source_type: str, url: str, title: str | None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def transcript(self, item: dict[str, Any], seeds: list[str]) -> list[dict[str, Any]]: ...


class FixtureSourceProvider(SourceProvider):
    """Permitted synthetic provider used by CI/demo; it never downloads third-party media."""

    def resolve(self, source_type: str, url: str, title: str | None) -> list[dict[str, Any]]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        root_id = query.get("v", query.get("list", [stable_id(url)]))[0]
        count = 3 if source_type == "youtube_playlist" else 1
        return [
            {
                "external_id": f"{root_id}-{index + 1}" if count > 1 else root_id,
                "source_url": url
                if count == 1
                else f"https://youtube.com/watch?v={root_id}-{index + 1}",
                "title": title or f"Fixture source {root_id} part {index + 1}",
                "duration_ms": 180_000 + (index * 30_000),
                "channel": "fixture-authorised-channel",
                "metadata": {"provider": "fixture", "synthetic": True, "playlist_index": index},
            }
            for index in range(count)
        ]

    def transcript(self, item: dict[str, Any], seeds: list[str]) -> list[dict[str, Any]]:
        topic = seeds[0] if seeds else "audience growth"
        phrases = [
            f"Most people miss this surprising point about {topic}; here is the useful proof.",
            f"The common approach fails because context changes the result for {item['title']}.",
            "The practical payoff is a repeatable three-step method with a clear ending.",
            "One funny counterexample makes the insight memorable without losing clarity.",
        ]
        return [
            {"start_ms": index * 18_000, "end_ms": (index + 1) * 18_000, "text": text}
            for index, text in enumerate(phrases)
        ]


class ManualImportSourceProvider(FixtureSourceProvider):
    """Fallback contract for user-authorised metadata/transcript imports."""

    def resolve(self, source_type: str, url: str, title: str | None) -> list[dict[str, Any]]:
        items = super().resolve(source_type, url, title)
        for item in items:
            item["metadata"] = {
                "provider": "manual_import_required",
                "synthetic": False,
                "instruction": "Import authorised metadata/transcript through the provider boundary.",
            }
        return items


class ResearchProvider(ABC):
    @abstractmethod
    def collect(
        self,
        campaign: dict[str, Any],
        seeds: list[str],
        queries: list[str] | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...


class AIAdapter(ABC):
    @abstractmethod
    def analyse_example(self, example: dict[str, Any], index: int) -> dict[str, Any]: ...

    @abstractmethod
    def generate_research_queries(
        self, campaign: dict[str, Any], seeds: list[str], examples: list[dict[str, Any]]
    ) -> list[str]: ...

    @abstractmethod
    def evaluate_soft_requirements(
        self, spec: dict[str, Any], requirements: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    @abstractmethod
    def interpret_edit_request(
        self, instruction: str, current_spec: dict[str, Any]
    ) -> dict[str, Any]: ...


class LocalHeuristicAIAdapter(AIAdapter):
    """Free deterministic development adapter; outputs remain explicitly heuristic/AI-labelled."""

    def analyse_example(self, example: dict[str, Any], index: int) -> dict[str, Any]:
        live = example.get("live_evidence")
        if live:
            text = str(live.get("transcript", "")).strip()
            lowered = text.lower()
            first_line = text.split(".", 1)[0]
            words = first_line.split()
            if any(token in lowered for token in ("wrong", "mistake", "truth", "never")):
                opening_type = "contrarian_claim"
            elif first_line.lower().startswith(("how ", "why ")):
                opening_type = "question_or_explanation"
            elif re.search(r"\b\d+\b", first_line):
                opening_type = "numbered_promise"
            else:
                opening_type = "direct_topic_hook"
            humour = 0.8 if any(token in lowered for token in ("funny", "lol", "comedy")) else 0.2
            controversy = (
                0.7
                if any(token in lowered for token in ("wrong", "controvers", "exposed"))
                else 0.25
            )
            duration_seconds = 30
            duration = str(live.get("raw", {}).get("duration", ""))
            match = re.fullmatch(
                r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?",
                duration,
            )
            if match:
                duration_seconds = int(
                    int(match.group("hours") or 0) * 3600
                    + int(match.group("minutes") or 0) * 60
                    + float(match.group("seconds") or 0)
                )
            return {
                "hook": first_line[:180] or "metadata-derived opening",
                "topic": live.get("labels", {}).get("topic", "successful example"),
                "subtopic": "metadata-derived",
                "emotion": "humour"
                if humour >= 0.8
                else ("tension" if controversy >= 0.7 else "informational"),
                "controversy": controversy,
                "humour": humour,
                "context": "estimated_from_public_metadata",
                "structure": [opening_type, "description_or_voice_text", "payoff_unknown"],
                "duration_seconds": duration_seconds,
                "opening_type": opening_type,
                "headline": "short" if len(words) <= 12 else "long",
                "caption_pattern": "not_measurable_from_metadata",
                "crop": "not_measurable_from_metadata",
                "pacing": "not_measurable_from_metadata",
                "ending": "not_measurable_from_metadata",
                "evidence": {
                    "example_id": example["id"],
                    "url": example["url"],
                    "provider": live.get("raw", {}).get("provider"),
                    "provenance": live.get("raw", {}).get("provenance"),
                },
                "confidence": 0.78,
                "adapter": "local_live_metadata_heuristic_v1",
            }
        return {
            "hook": "contrarian promise",
            "topic": "campaign-aligned insight",
            "subtopic": "practical proof",
            "emotion": "surprise",
            "controversy": 0.45,
            "humour": 0.25,
            "context": "minimal",
            "structure": ["hook", "proof", "payoff"],
            "duration_seconds": 28 + (index % 3) * 2,
            "opening_type": "direct_claim",
            "headline": "short_bold",
            "caption_pattern": "medium_chunks",
            "crop": "speaker_centered_9_16",
            "pacing": "fast",
            "ending": "payoff",
            "evidence": {"example_id": example["id"], "url": example["url"]},
            "confidence": 0.72,
            "adapter": "local_heuristic_v1",
        }

    def generate_research_queries(
        self, campaign: dict[str, Any], seeds: list[str], examples: list[dict[str, Any]]
    ) -> list[str]:
        queries = {f"{seed} viral clips" for seed in seeds} | {
            f"{seed} emerging angles" for seed in seeds
        }
        queries.add(f"{campaign['name']} successful clipping accounts")
        queries.update(
            f"{row['creator']} successful clips on {row['platform']}"
            for row in examples
            if row.get("creator")
        )
        return sorted(queries)

    def evaluate_soft_requirements(
        self, spec: dict[str, Any], requirements: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "label": "ai_evaluated",
            "adapter": "local_heuristic_v1",
            "advisory_only": True,
            "checks": [
                {
                    "key": row["key"],
                    "result": "uncertain_heuristic",
                    "confidence": 0.35,
                }
                for row in requirements
            ],
        }

    def interpret_edit_request(
        self, instruction: str, current_spec: dict[str, Any]
    ) -> dict[str, Any]:
        return parse_edit_instruction(instruction, current_spec)


class FixtureResearchProvider(ResearchProvider):
    """Known deterministic dataset containing relative outliers and a semantic cluster."""

    def collect(
        self,
        campaign: dict[str, Any],
        seeds: list[str],
        queries: list[str] | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        topic = seeds[0] if seeds else "audience growth"
        rows = [
            ("small-a", 1_600, 100, 4, "surprising proof", topic),
            ("small-b", 2_100, 150, 6, "surprising proof", topic),
            ("small-c", 2_800, 200, 8, "surprising proof", topic),
            ("large", 220_000, 180_000, 48, "generic advice", "saturated advice"),
            ("normal-a", 700, 650, 24, "routine update", "general"),
            ("normal-b", 900, 850, 20, "routine update", "general"),
        ]
        return [
            {
                "platform": "fixture_social",
                "url": f"https://research.invalid/{campaign['id']}/{index}",
                "creator": creator,
                "published_hours_ago": age_hours,
                "metrics": {"views": views, "likes": int(views * 0.08), "comments": index + 2},
                "baseline": {"median_views": baseline, "sample_size": 20},
                "transcript": f"{angle}: evidence about {label}",
                "labels": {"angle": angle, "topic": label},
                "raw": {"fixture_row": index, "permitted_fixture": True},
            }
            for index, (creator, views, baseline, age_hours, angle, label) in enumerate(rows)
        ]


class ManualResearchProvider(ResearchProvider):
    """No-network provider; observations enter through the audited import endpoint."""

    def collect(
        self,
        campaign: dict[str, Any],
        seeds: list[str],
        queries: list[str] | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return []


class EmailAdapter(ABC):
    @abstractmethod
    def send(self, recipient: str, subject: str, body: str, idempotency_key: str) -> str: ...


class FileEmailAdapter(EmailAdapter):
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def send(self, recipient: str, subject: str, body: str, idempotency_key: str) -> str:
        path = self.root / f"{stable_id(idempotency_key, 24)}.json"
        if not path.exists():
            path.write_text(
                dump(
                    {
                        "to": recipient,
                        "subject": subject,
                        "body": body,
                        "idempotency_key": idempotency_key,
                    }
                ),
                encoding="utf-8",
            )
        return str(path)


class ResendEmailAdapter(EmailAdapter):
    endpoint = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str,
        from_email: str,
        timeout_seconds: float = 10.0,
    ):
        if not api_key:
            raise ValueError("RESEND_API_KEY is required when the Resend email provider is enabled")
        if not from_email:
            raise ValueError(
                "RESEND_FROM_EMAIL is required when the Resend email provider is enabled"
            )
        self._api_key = api_key
        self.from_email = from_email
        self.timeout_seconds = max(1.0, timeout_seconds)

    def send(self, recipient: str, subject: str, body: str, idempotency_key: str) -> str:
        if not 1 <= len(idempotency_key) <= 256:
            raise ValueError("Resend idempotency keys must contain between 1 and 256 characters")
        payload = dump(
            {
                "from": self.from_email,
                "to": [recipient],
                "subject": subject,
                "text": body,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "User-Agent": "alpha-clipper/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = load(response.read().decode("utf-8"), {})
        except urllib.error.HTTPError as exc:
            error_name = "unknown_error"
            try:
                error_name = str(load(exc.read().decode("utf-8"), {}).get("name", error_name))
            except Exception:
                pass
            raise RuntimeError(f"Resend API returned HTTP {exc.code} ({error_name})") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError("Resend API request failed") from exc
        email_id = result.get("id")
        if not isinstance(email_id, str) or not email_id:
            raise RuntimeError("Resend API response did not include an email id")
        return f"resend:{email_id}"


class PublicationAdapter(ABC):
    @abstractmethod
    def publish_or_export(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...


class ManualExportAdapter(PublicationAdapter):
    def __init__(self, storage: StorageAdapter):
        self.storage = storage

    def publish_or_export(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        uri = self.storage.put_json(f"exports/{stable_id(idempotency_key, 24)}.json", payload)
        return {
            "status": "export_ready",
            "export_uri": uri,
            "instructions": "Download the approved clip and metadata, then post manually using the platform UI.",
        }


@dataclass
class RenderResult:
    file_uri: str
    renderer: str
    sha256: str
    probe: dict[str, Any]


class Renderer:
    """FFmpeg renderer for generated fixtures and explicitly authorised local source media."""

    def __init__(self, storage: LocalStorageAdapter):
        self.storage = storage

    def _ffmpeg(self) -> str | None:
        executable = shutil.which("ffmpeg")
        if executable:
            return executable
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    def _watermark_ppm(self, key: str) -> Path:
        path = self.storage._safe_path(key)
        width, height = 180, 60
        header = f"P6\n{width} {height}\n255\n".encode()
        pixels = bytearray()
        for y in range(height):
            for x in range(width):
                border = x < 4 or y < 4 or x >= width - 4 or y >= height - 4
                pixels.extend((250, 204, 21) if border else (15, 23, 42))
        path.write_bytes(header + pixels)
        return path

    @staticmethod
    def _overlay(position: str, padding: int) -> tuple[str, str]:
        positions = {
            "top_left": (str(padding), str(padding)),
            "top_right": (f"W-w-{padding}", str(padding)),
            "bottom_left": (str(padding), f"H-h-{padding}"),
            "bottom_right": (f"W-w-{padding}", f"H-h-{padding}"),
            "center": ("(W-w)/2", "(H-h)/2"),
        }
        return positions.get(position, positions["bottom_right"])

    def probe_media(self, path: Path) -> dict[str, Any]:
        ffmpeg = self._ffmpeg()
        if not ffmpeg or not path.exists():
            return {
                "valid": False,
                "probe_method": "unavailable",
                "duration_ms": 0,
                "width": 0,
                "height": 0,
                "has_audio": False,
            }
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        details = result.stderr
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", details)
        video_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})(?:[,\s]|$)", details)
        duration_ms = 0
        if duration_match:
            hours, minutes, seconds = duration_match.groups()
            duration_ms = round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
        return {
            "valid": bool(duration_match and video_match),
            "probe_method": "ffmpeg_stderr",
            "duration_ms": duration_ms,
            "width": int(video_match.group(1)) if video_match else 0,
            "height": int(video_match.group(2)) if video_match else 0,
            "has_audio": "Audio:" in details,
        }

    def render(self, campaign_id: str, variant_id: str, spec: dict[str, Any]) -> RenderResult:
        output = self.storage._safe_path(f"renders/{campaign_id}/{variant_id}.mp4")
        ffmpeg = self._ffmpeg()
        duration = max(1.0, min(float(spec["duration_ms"]) / 1000, 60.0))
        if not ffmpeg:
            manifest = dump({"fixture_render": True, "spec": spec}).encode()
            output.with_suffix(".render.json").write_bytes(manifest)
            return RenderResult(
                str(output.with_suffix(".render.json")),
                "manifest_fallback",
                hashlib.sha256(manifest).hexdigest(),
                {
                    "valid": False,
                    "probe_method": "manifest_fallback",
                    "duration_ms": 0,
                    "width": 0,
                    "height": 0,
                    "has_audio": False,
                },
            )
        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        source_asset = spec.get("source_asset_uri")
        source_probe = spec.get("source_probe", {})
        filters: list[str] = []
        if source_asset and Path(source_asset).exists():
            command += [
                "-ss",
                f"{max(0, int(spec['start_ms'])) / 1000:.3f}",
                "-i",
                str(source_asset),
            ]
            crop = spec.get("crop", {}).get("adjustment", "center")
            x = "0" if crop == "left" else ("in_w-out_w" if crop == "right" else "(in_w-out_w)/2")
            y = "0" if crop == "up" else ("in_h-out_h" if crop == "down" else "(in_h-out_h)/2")
            filters.append(
                "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                f"crop=720:1280:x={x}:y={y}[base]"
            )
            base_label = "base"
            if source_probe.get("has_audio"):
                audio_map = "0:a:0?"
                next_input = 1
            else:
                command += [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration}",
                ]
                audio_map = "1:a"
                next_input = 2
            renderer_name = "ffmpeg_authorised_source"
        else:
            command += [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x172033:s=720x1280:r=24:d={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={duration}",
            ]
            base_label = "0:v"
            audio_map = "1:a"
            next_input = 2
            renderer_name = "ffmpeg_fixture"
        watermark = spec.get("watermark")
        captions = spec.get("captions", {})
        if captions.get("enabled"):
            caption_text = str(captions.get("text") or "ALPHA captions")[:110]
            caption_text = (
                caption_text.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace("%", "\\%")
                .replace("\n", " ")
            )
            filters.append(
                f"[{base_label}]drawtext=text='{caption_text}':fontcolor=white:fontsize=30:"
                "box=1:boxcolor=black@0.65:boxborderw=16:x=(w-text_w)/2:y=h-220[captioned]"
            )
            base_label = "captioned"
        headline = spec.get("headline", {})
        if headline.get("enabled") and headline.get("text"):
            headline_text = (
                str(headline["text"])[:80]
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
                .replace("%", "\\%")
            )
            filters.append(
                f"[{base_label}]drawtext=text='{headline_text}':fontcolor=white:fontsize=46:"
                "box=1:boxcolor=black@0.72:boxborderw=18:x=(w-text_w)/2:y=120[headlined]"
            )
            base_label = "headlined"
        if watermark and watermark.get("enabled", True):
            configured_asset = watermark.get("asset_uri")
            asset = Path(configured_asset) if configured_asset else None
            if not asset or not asset.exists():
                asset = self._watermark_ppm(f"renders/{campaign_id}/{variant_id}-watermark.ppm")
            x, y = self._overlay(
                watermark.get("position", "bottom_right"), int(watermark.get("padding", 24))
            )
            size = max(40, math.floor(720 * float(watermark.get("size_pct", 0.18))))
            opacity = float(watermark.get("opacity", 0.85))
            command += ["-i", str(asset)]
            filters.extend(
                [
                    f"[{next_input}:v]scale={size}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm]",
                    f"[{base_label}][wm]overlay={x}:{y}[v]",
                ]
            )
            command += [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                "-map",
                audio_map,
            ]
        elif filters:
            filters.append(f"[{base_label}]null[v]")
            command += [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                "-map",
                audio_map,
            ]
        else:
            command += ["-map", "0:v", "-map", audio_map]
        command += [
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-fflags",
            "+bitexact",
            "-flags:v",
            "+bitexact",
            "-flags:a",
            "+bitexact",
            "-threads",
            "1",
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-y",
            str(output),
        ]
        subprocess.run(command, check=True, timeout=90, capture_output=True)
        content = output.read_bytes()
        probe = self.probe_media(output)
        return RenderResult(str(output), renderer_name, hashlib.sha256(content).hexdigest(), probe)


def decode_upload(data_base64: str) -> bytes:
    value = re.sub(r"^data:[^;]+;base64,", "", data_base64)
    return base64.b64decode(value, validate=True)
