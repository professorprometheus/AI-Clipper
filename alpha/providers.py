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
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
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
    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str: ...

    def put_json(self, key: str, content: Any) -> str:
        return self.put_bytes(
            key,
            json.dumps(content, indent=2, sort_keys=True).encode("utf-8"),
            "application/json",
        )

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        return self.put_bytes(key, path.read_bytes(), content_type)

    @abstractmethod
    def get_bytes(self, uri: str) -> bytes: ...

    @abstractmethod
    def iter_bytes(self, uri: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]: ...

    @abstractmethod
    def exists(self, uri: str) -> bool: ...

    @abstractmethod
    def delete(self, uri: str) -> None: ...

    @abstractmethod
    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]: ...

    @abstractmethod
    def diagnostic(self) -> dict[str, Any]: ...


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

    def _uri_path(self, uri: str) -> Path:
        path = Path(uri).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage URI escapes root")
        return path

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        path = self._safe_path(key)
        path.write_bytes(content)
        return str(path)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        destination = self._safe_path(key)
        shutil.copyfile(path, destination)
        return str(destination)

    def get_bytes(self, uri: str) -> bytes:
        return self._uri_path(uri).read_bytes()

    def iter_bytes(self, uri: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        with self._uri_path(uri).open("rb") as stream:
            while chunk := stream.read(chunk_size):
                yield chunk

    def exists(self, uri: str) -> bool:
        try:
            return self._uri_path(uri).is_file()
        except ValueError:
            return False

    def delete(self, uri: str) -> None:
        self._uri_path(uri).unlink(missing_ok=True)

    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]:
        path = self._uri_path(uri)
        if not path.is_file():
            raise FileNotFoundError("storage object not found")
        yield path

    def diagnostic(self) -> dict[str, Any]:
        return {"provider": "local", "root": str(self.root.resolve())}


class S3StorageAdapter(StorageAdapter):
    """Private S3-compatible object storage using durable s3:// URIs."""

    def __init__(
        self,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        client: Any | None = None,
    ):
        if not bucket or not endpoint_url:
            raise ValueError("S3 storage requires S3_BUCKET and S3_ENDPOINT_URL")
        if client is None and not (access_key_id and secret_access_key):
            raise ValueError("S3 storage requires S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.region = region
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(signature_version="s3v4"),
            )
        self.client = client

    @staticmethod
    def _key(key: str) -> str:
        cleaned = key.replace("\\", "/").lstrip("/")
        if not cleaned or any(part in {"", ".", ".."} for part in cleaned.split("/")):
            raise ValueError("invalid object-storage key")
        return cleaned

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"

    def _uri_key(self, uri: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("object URI belongs to a different bucket")
        return self._key(uri.removeprefix(prefix))

    def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        object_key = self._key(key)
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": object_key, "Body": content}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return self._uri(object_key)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        object_key = self._key(key)
        extra = {"ContentType": content_type} if content_type else None
        if extra:
            self.client.upload_file(str(path), self.bucket, object_key, ExtraArgs=extra)
        else:
            self.client.upload_file(str(path), self.bucket, object_key)
        return self._uri(object_key)

    def get_bytes(self, uri: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._uri_key(uri))
        body = response["Body"]
        try:
            return body.read()
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    def iter_bytes(self, uri: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        response = self.client.get_object(Bucket=self.bucket, Key=self._uri_key(uri))
        body = response["Body"]
        try:
            while chunk := body.read(chunk_size):
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    def exists(self, uri: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._uri_key(uri))
            return True
        except Exception:
            return False

    def delete(self, uri: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._uri_key(uri))

    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]:
        suffix = Path(self._uri_key(uri)).suffix
        with TemporaryDirectory(prefix="alpha-object-") as directory:
            path = Path(directory) / f"object{suffix}"
            self.client.download_file(self.bucket, self._uri_key(uri), str(path))
            yield path

    def diagnostic(self) -> dict[str, Any]:
        self.client.head_bucket(Bucket=self.bucket)
        return {
            "provider": "s3",
            "bucket": self.bucket,
            "endpoint_host": urlparse(self.endpoint_url).hostname,
        }


def build_storage(settings: Any) -> StorageAdapter:
    if settings.storage_provider == "local":
        return LocalStorageAdapter(settings.storage_path)
    if settings.storage_provider == "s3":
        return S3StorageAdapter(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_bucket,
            settings.s3_access_key_id,
            settings.s3_secret_access_key,
        )
    raise ValueError(f"Unsupported storage provider: {settings.storage_provider}")


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
    """FFmpeg renderer with ephemeral staging and durable output storage."""

    def __init__(self, storage: StorageAdapter):
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

    def _watermark_ppm(self, path: Path) -> Path:
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
        return self.probe_asset(path, require_video=True)

    def probe_asset(self, path: Path, require_video: bool = False) -> dict[str, Any]:
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
            "valid": bool(
                duration_match and (video_match or (not require_video and "Audio:" in details))
            ),
            "probe_method": "ffmpeg_stderr",
            "duration_ms": duration_ms,
            "width": int(video_match.group(1)) if video_match else 0,
            "height": int(video_match.group(2)) if video_match else 0,
            "has_audio": "Audio:" in details,
            "media_kind": "video"
            if video_match
            else ("audio" if "Audio:" in details else "unknown"),
        }

    def render(self, campaign_id: str, variant_id: str, spec: dict[str, Any]) -> RenderResult:
        with TemporaryDirectory(prefix="alpha-render-") as directory, ExitStack() as stack:
            workdir = Path(directory)
            output = workdir / f"{variant_id}.mp4"
            ffmpeg = self._ffmpeg()
            duration = max(1.0, min(float(spec["duration_ms"]) / 1000, 60.0))
            if not ffmpeg:
                manifest = dump({"fixture_render": True, "spec": spec}).encode()
                uri = self.storage.put_bytes(
                    f"renders/{campaign_id}/{variant_id}.render.json",
                    manifest,
                    "application/json",
                )
                return RenderResult(
                    uri,
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
            source_path = (
                stack.enter_context(self.storage.materialize(source_asset))
                if source_asset and self.storage.exists(source_asset)
                else None
            )
            if source_path:
                command += [
                    "-ss",
                    f"{max(0, int(spec['start_ms'])) / 1000:.3f}",
                    "-i",
                    str(source_path),
                ]
                crop = spec.get("crop", {}).get("adjustment", "center")
                x = (
                    "0"
                    if crop == "left"
                    else ("in_w-out_w" if crop == "right" else "(in_w-out_w)/2")
                )
                y = "0" if crop == "up" else ("in_h-out_h" if crop == "down" else "(in_h-out_h)/2")
                filters.append(
                    "[0:v]scale=720:1280:force_original_aspect_ratio=increase,"
                    f"crop=720:1280:x={x}:y={y}[base]"
                )
                base_label = "base"
                if source_probe.get("has_audio"):
                    audio_label = "0:a"
                    next_input = 1
                else:
                    command += [
                        "-f",
                        "lavfi",
                        "-i",
                        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration}",
                    ]
                    audio_label = "1:a"
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
                audio_label = "1:a"
                next_input = 2
                renderer_name = "ffmpeg_fixture"

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

            events = spec.get("enrichment", {}).get("events", [])
            visual_types = {
                "meme_image",
                "meme_video",
                "reaction",
                "broll",
                "image",
                "graphic",
            }
            visual_number = 0
            music_inputs: list[tuple[int, dict[str, Any]]] = []
            sfx_inputs: list[tuple[int, dict[str, Any]]] = []
            for event in events:
                event_type = event.get("type")
                if event_type in {"punch_in", "dynamic_crop", "speaker_focus", "fast_cut"}:
                    visual_number += 1
                    start = max(0.0, float(event.get("start_ms", 0)) / 1000)
                    end = min(duration, start + float(event.get("duration_ms", 0)) / 1000)
                    scale = max(
                        1.01, min(1.5, float(event.get("parameters", {}).get("scale", 1.12)))
                    )
                    width, height = round(720 * scale), round(1280 * scale)
                    filters.extend(
                        [
                            f"[{base_label}]split=2[punch_under{visual_number}][punch_src{visual_number}]",
                            f"[punch_src{visual_number}]scale={width}:{height},crop=720:1280"
                            f"[punch_zoom{visual_number}]",
                            f"[punch_under{visual_number}][punch_zoom{visual_number}]overlay=0:0:"
                            f"enable='between(t,{start:.3f},{end:.3f})'[native{visual_number}]",
                        ]
                    )
                    base_label = f"native{visual_number}"
                    continue
                if event_type in {
                    "text_emphasis",
                    "keyword_highlight",
                    "pull_quote",
                    "progress_caption",
                    "reaction_hold",
                }:
                    visual_number += 1
                    start = max(0.0, float(event.get("start_ms", 0)) / 1000)
                    end = min(duration, start + float(event.get("duration_ms", 0)) / 1000)
                    emphasis = str(event.get("parameters", {}).get("text", "KEY POINT"))[:60]
                    emphasis = (
                        emphasis.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
                    )
                    filters.append(
                        f"[{base_label}]drawtext=text='{emphasis}':fontcolor=yellow:fontsize=42:"
                        "box=1:boxcolor=black@0.72:boxborderw=14:x=(w-text_w)/2:y=160:"
                        f"enable='between(t,{start:.3f},{end:.3f})'[native{visual_number}]"
                    )
                    base_label = f"native{visual_number}"
                    continue
                if event_type == "blur_background":
                    visual_number += 1
                    start = max(0.0, float(event.get("start_ms", 0)) / 1000)
                    end = min(duration, start + float(event.get("duration_ms", 0)) / 1000)
                    filters.append(
                        f"[{base_label}]boxblur=8:enable='between(t,{start:.3f},{end:.3f})'"
                        f"[native{visual_number}]"
                    )
                    base_label = f"native{visual_number}"
                    continue
                if event_type == "freeze_frame":
                    visual_number += 1
                    event_duration = min(
                        duration - 0.1,
                        max(0.1, float(event.get("duration_ms", 0)) / 1000),
                    )
                    start = min(
                        duration - event_duration - 0.05,
                        max(0.05, float(event.get("start_ms", 0)) / 1000),
                    )
                    post_start = start + event_duration
                    hold_padding = max(0.0, event_duration - (1 / 24))
                    filters.extend(
                        [
                            f"[{base_label}]split=3[freeze_pre{visual_number}]"
                            f"[freeze_frame{visual_number}][freeze_post{visual_number}]",
                            f"[freeze_pre{visual_number}]trim=start=0:end={start:.3f},"
                            f"setpts=PTS-STARTPTS[freeze_a{visual_number}]",
                            f"[freeze_frame{visual_number}]trim=start={start:.3f}:"
                            f"end={start + (1 / 24):.3f},setpts=PTS-STARTPTS,"
                            f"tpad=stop_mode=clone:stop_duration={hold_padding:.3f}"
                            f"[freeze_b{visual_number}]",
                            f"[freeze_post{visual_number}]trim=start={post_start:.3f}:"
                            f"end={duration:.3f},setpts=PTS-STARTPTS[freeze_c{visual_number}]",
                            f"[freeze_a{visual_number}][freeze_b{visual_number}]"
                            f"[freeze_c{visual_number}]concat=n=3:v=1:a=0[native{visual_number}]",
                        ]
                    )
                    base_label = f"native{visual_number}"
                    continue
                uri = event.get("asset_uri")
                if event_type not in visual_types | {"music", "sfx"} or not uri:
                    continue
                asset_path = stack.enter_context(self.storage.materialize(uri))
                input_index = next_input
                next_input += 1
                if event_type in {"music", "sfx"}:
                    command += ["-stream_loop", "-1", "-i", str(asset_path)]
                    (music_inputs if event_type == "music" else sfx_inputs).append(
                        (input_index, event)
                    )
                    continue
                if event.get("media_kind") == "video":
                    command += ["-stream_loop", "-1", "-i", str(asset_path)]
                else:
                    command += ["-loop", "1", "-i", str(asset_path)]
                visual_number += 1
                start = max(0.0, float(event.get("start_ms", 0)) / 1000)
                event_duration = max(0.1, float(event.get("duration_ms", 0)) / 1000)
                end = min(duration, start + event_duration)
                mode = event.get("mode", "overlay")
                if mode == "full_screen":
                    transform = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
                    x_pos, y_pos = "0", "0"
                elif mode == "picture_in_picture":
                    transform = "scale=300:-1"
                    x_pos, y_pos = "W-w-28", "28"
                else:
                    transform = "scale=360:-1"
                    x_pos, y_pos = "W-w-28", "80"
                filters.extend(
                    [
                        f"[{input_index}:v]{transform},trim=duration={event_duration:.3f},"
                        f"setpts=PTS-STARTPTS+{start:.3f}/TB[insert{visual_number}]",
                        f"[{base_label}][insert{visual_number}]overlay={x_pos}:{y_pos}:"
                        f"enable='between(t,{start:.3f},{end:.3f})':eof_action=pass"
                        f"[enriched{visual_number}]",
                    ]
                )
                base_label = f"enriched{visual_number}"

            audio_output: str | None = None
            if music_inputs:
                music_index, music_event = music_inputs[0]
                parameters = music_event.get("parameters", {})
                volume_db = float(parameters.get("volume_db", -20))
                fade_in = max(0.0, float(parameters.get("fade_in_ms", 0)) / 1000)
                fade_out = max(0.0, float(parameters.get("fade_out_ms", 0)) / 1000)
                music_filters = [f"volume={volume_db}dB", f"atrim=duration={duration:.3f}"]
                if fade_in:
                    music_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
                if fade_out:
                    music_filters.append(
                        f"afade=t=out:st={max(0, duration - fade_out):.3f}:d={fade_out:.3f}"
                    )
                filters.append(f"[{music_index}:a]{','.join(music_filters)}[musicbed]")
                if parameters.get("ducking", True):
                    filters.extend(
                        [
                            f"[{audio_label}]asplit=2[speechmix][speechside]",
                            "[musicbed][speechside]sidechaincompress=threshold=0.02:ratio=8:"
                            "attack=20:release=250[duckedmusic]",
                            "[speechmix][duckedmusic]amix=inputs=2:duration=first:"
                            "dropout_transition=0[audio_enriched]",
                        ]
                    )
                else:
                    filters.append(
                        f"[{audio_label}][musicbed]amix=inputs=2:duration=first:"
                        "dropout_transition=0[audio_enriched]"
                    )
                audio_output = "audio_enriched"
            for number, (sfx_index, sfx_event) in enumerate(sfx_inputs, start=1):
                parameters = sfx_event.get("parameters", {})
                start_ms = max(0, int(sfx_event.get("start_ms", 0)))
                sfx_duration = max(0.1, float(sfx_event.get("duration_ms", 500)) / 1000)
                volume_db = float(parameters.get("volume_db", -8))
                filters.append(
                    f"[{sfx_index}:a]atrim=duration={sfx_duration:.3f},volume={volume_db}dB,"
                    f"adelay={start_ms}|{start_ms}[sfx{number}]"
                )
                source_audio = audio_output or audio_label
                filters.append(
                    f"[{source_audio}][sfx{number}]amix=inputs=2:duration=first:"
                    f"dropout_transition=0[audio_sfx{number}]"
                )
                audio_output = f"audio_sfx{number}"

            watermark = spec.get("watermark")
            if watermark and watermark.get("enabled", True):
                configured_asset = watermark.get("asset_uri")
                asset = (
                    stack.enter_context(self.storage.materialize(configured_asset))
                    if configured_asset and self.storage.exists(configured_asset)
                    else self._watermark_ppm(workdir / f"{variant_id}-watermark.ppm")
                )
                x, y = self._overlay(
                    watermark.get("position", "bottom_right"), int(watermark.get("padding", 24))
                )
                size = max(40, math.floor(720 * float(watermark.get("size_pct", 0.18))))
                opacity = float(watermark.get("opacity", 0.85))
                command += ["-i", str(asset)]
                filters.extend(
                    [
                        f"[{next_input}:v]scale={size}:-1,format=rgba,"
                        f"colorchannelmixer=aa={opacity}[wm]",
                        f"[{base_label}][wm]overlay={x}:{y}[v]",
                    ]
                )
            else:
                filters.append(f"[{base_label}]null[v]")
            command += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map"]
            command += [f"[{audio_output}]" if audio_output else audio_label]
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
            uri = self.storage.put_file(
                f"renders/{campaign_id}/{variant_id}.mp4", output, "video/mp4"
            )
            return RenderResult(uri, renderer_name, hashlib.sha256(content).hexdigest(), probe)


def decode_upload(data_base64: str) -> bytes:
    value = re.sub(r"^data:[^;]+;base64,", "", data_base64)
    return base64.b64decode(value, validate=True)
