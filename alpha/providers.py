from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import dump


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
    def collect(self, campaign: dict[str, Any], seeds: list[str]) -> list[dict[str, Any]]: ...


class FixtureResearchProvider(ResearchProvider):
    """Known deterministic dataset containing relative outliers and a semantic cluster."""

    def collect(self, campaign: dict[str, Any], seeds: list[str]) -> list[dict[str, Any]]:
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


class Renderer:
    """Synthetic authorised renderer. Uses bundled/system FFmpeg, never downloads source media."""

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
            )
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x172033:s=720x1280:r=24:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
        ]
        watermark = spec.get("watermark")
        captions = spec.get("captions", {})
        base_label = "0:v"
        filters: list[str] = []
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
                f"[0:v]drawtext=text='{caption_text}':fontcolor=white:fontsize=30:"
                "box=1:boxcolor=black@0.65:boxborderw=16:x=(w-text_w)/2:y=h-220[captioned]"
            )
            base_label = "captioned"
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
                    f"[2:v]scale={size}:-1,format=rgba,colorchannelmixer=aa={opacity}[wm]",
                    f"[{base_label}][wm]overlay={x}:{y}[v]",
                ]
            )
            command += [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                "-map",
                "1:a",
            ]
        elif filters:
            filters.append(f"[{base_label}]null[v]")
            command += [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                "-map",
                "1:a",
            ]
        else:
            command += ["-map", "0:v", "-map", "1:a"]
        command += [
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
            "-metadata",
            "creation_time=1970-01-01T00:00:00Z",
            "-y",
            str(output),
        ]
        subprocess.run(command, check=True, timeout=90, capture_output=True)
        content = output.read_bytes()
        return RenderResult(str(output), "ffmpeg", hashlib.sha256(content).hexdigest())


def decode_upload(data_base64: str) -> bytes:
    value = re.sub(r"^data:[^;]+;base64,", "", data_base64)
    return base64.b64decode(value, validate=True)
