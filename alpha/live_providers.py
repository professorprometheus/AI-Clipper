from __future__ import annotations

import html
import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from .providers import ResearchProvider, SourceProvider

JsonRequest = Callable[[str, dict[str, Any] | None, dict[str, str] | None, str, Any], Any]
TextRequest = Callable[[str, dict[str, Any] | None, dict[str, str] | None], str]


class ProviderRequestError(RuntimeError):
    pass


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: Any = None,
) -> Any:
    if params:
        query = urllib.parse.urlencode(
            {key: value for key, value in params.items() if value is not None}, doseq=True
        )
        url = f"{url}{'&' if '?' in url else '?'}{query}"
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Accept": "application/json", **(headers or {})},
    )
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        reason = "provider_error"
        try:
            error = json.loads(exc.read().decode("utf-8"))
            reason = str(
                error.get("error", {}).get("errors", [{}])[0].get("reason")
                or error.get("error", {}).get("code")
                or error.get("error", {}).get("message")
                or error.get("error", {}).get("code")
                or reason
            )[:120]
        except Exception:
            pass
        raise ProviderRequestError(f"provider returned HTTP {exc.code} ({reason})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderRequestError("provider request was unavailable") from exc


def request_text(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ProviderRequestError("public feed request was unavailable") from exc


def _iso_duration_ms(value: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        value,
    )
    if not match:
        return 0
    parts = {key: float(number or 0) for key, number in match.groupdict().items()}
    return int(
        (parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"])
        * 1000
    )


def _age_hours(value: str | int | float | None) -> float:
    try:
        if isinstance(value, (int, float)):
            published = datetime.fromtimestamp(value, UTC)
        else:
            published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return max(1.0, (datetime.now(UTC) - published).total_seconds() / 3600)
    except (TypeError, ValueError, OSError):
        return 1.0


def _youtube_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        query_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
    return None


def _playlist_id(url: str) -> str | None:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("list", [None])[0]


class YouTubeAPIClient:
    root = "https://www.googleapis.com/youtube/v3"

    def __init__(
        self,
        api_key: str,
        oauth_token: str = "",
        oauth_client_id: str = "",
        oauth_client_secret: str = "",
        oauth_refresh_token: str = "",
        transport: JsonRequest = request_json,
    ):
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is required for live YouTube ingestion")
        self.api_key = api_key
        self.oauth_token = oauth_token
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self.oauth_refresh_token = oauth_refresh_token
        self._oauth_expires_at: datetime | None = None
        self.transport = transport

    @property
    def has_caption_authorization(self) -> bool:
        return bool(
            self.oauth_token
            or (self.oauth_client_id and self.oauth_client_secret and self.oauth_refresh_token)
        )

    def _caption_token(self) -> str:
        if (
            self.oauth_client_id
            and self.oauth_client_secret
            and self.oauth_refresh_token
            and (not self._oauth_expires_at or datetime.now(UTC) >= self._oauth_expires_at)
        ):
            payload = urllib.parse.urlencode(
                {
                    "client_id": self.oauth_client_id,
                    "client_secret": self.oauth_client_secret,
                    "refresh_token": self.oauth_refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    token_data = json.loads(response.read().decode("utf-8"))
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                raise ProviderRequestError("YouTube OAuth token refresh failed") from exc
            token = token_data.get("access_token")
            if not token:
                raise ProviderRequestError("YouTube OAuth refresh returned no access token")
            self.oauth_token = token
            self._oauth_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(60, int(token_data.get("expires_in", 3600)) - 60)
            )
        if not self.oauth_token:
            raise ProviderRequestError("YouTube caption access requires OAuth authorization")
        return self.oauth_token

    def get(self, resource: str, params: dict[str, Any], oauth: bool = False) -> dict[str, Any]:
        headers = {}
        if oauth:
            headers["Authorization"] = f"Bearer {self._caption_token()}"
        return self.transport(
            f"{self.root}/{resource}",
            {**params, "key": self.api_key},
            headers,
            "GET",
            None,
        )

    def video_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index in range(0, len(video_ids), 50):
            response = self.get(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics,status",
                    "id": ",".join(video_ids[index : index + 50]),
                    "maxResults": 50,
                },
            )
            results.extend(response.get("items", []))
        return results

    def playlist_video_ids(self, playlist_id: str) -> list[str]:
        video_ids: list[str] = []
        page_token: str | None = None
        while True:
            response = self.get(
                "playlistItems",
                {
                    "part": "contentDetails,snippet,status",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                    "pageToken": page_token,
                },
            )
            video_ids.extend(
                item.get("contentDetails", {}).get("videoId", "")
                for item in response.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                return list(dict.fromkeys(video_ids))

    def search(
        self, query: str, region: str, published_after: str, limit: int
    ) -> list[dict[str, Any]]:
        response = self.get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "order": "date",
                "publishedAfter": published_after,
                "regionCode": region,
                "maxResults": limit,
            },
        )
        ids = [row.get("id", {}).get("videoId") for row in response.get("items", [])]
        return self.video_details([video_id for video_id in ids if video_id])

    def channel_baselines(
        self, channel_ids: list[str], sample_size: int = 20
    ) -> dict[str, dict[str, Any]]:
        if not channel_ids:
            return {}
        response = self.get(
            "channels",
            {
                "part": "contentDetails",
                "id": ",".join(list(dict.fromkeys(channel_ids))[:50]),
                "maxResults": 50,
            },
        )
        baselines: dict[str, dict[str, Any]] = {}
        for channel in response.get("items", []):
            uploads = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if not uploads:
                continue
            playlist = self.get(
                "playlistItems",
                {
                    "part": "contentDetails",
                    "playlistId": uploads,
                    "maxResults": min(50, sample_size),
                },
            )
            ids = [
                item.get("contentDetails", {}).get("videoId")
                for item in playlist.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            views = [
                float(item.get("statistics", {}).get("viewCount", 0))
                for item in self.video_details(ids)
            ]
            if views:
                baselines[channel["id"]] = {
                    "median_views": statistics.median(views),
                    "sample_size": len(views),
                    "scope": "channel_recent_uploads",
                }
        return baselines

    def captions_vtt(self, video_id: str) -> str:
        tracks = self.get(
            "captions",
            {"part": "snippet", "videoId": video_id},
            oauth=True,
        ).get("items", [])
        usable = [row for row in tracks if not row.get("snippet", {}).get("isDraft")]
        if not usable:
            return ""
        usable.sort(
            key=lambda row: (
                row.get("snippet", {}).get("language") not in {"en", "en-GB", "en-US"},
                row.get("snippet", {}).get("trackKind") == "ASR",
            )
        )
        caption_id = usable[0]["id"]
        params = urllib.parse.urlencode({"tfmt": "vtt", "key": self.api_key})
        request = urllib.request.Request(
            f"{self.root}/captions/{caption_id}?{params}",
            headers={"Authorization": f"Bearer {self._caption_token()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise ProviderRequestError("YouTube caption download was not authorized") from exc


def _youtube_item(resource: dict[str, Any], provider: str) -> dict[str, Any]:
    snippet = resource.get("snippet", {})
    details = resource.get("contentDetails", {})
    statistics_data = resource.get("statistics", {})
    video_id = resource["id"]
    return {
        "external_id": video_id,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "title": html.unescape(snippet.get("title", video_id)),
        "duration_ms": _iso_duration_ms(details.get("duration", "")),
        "channel": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "metadata": {
            "provider": provider,
            "video_id": video_id,
            "channel_id": snippet.get("channelId"),
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
            "caption_available": details.get("caption") == "true",
            "statistics": statistics_data,
            "status": resource.get("status", {}),
            "retrieved_at": datetime.now(UTC).isoformat(),
        },
    }


def _parse_vtt_timestamp(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    seconds = float(parts[-1]) + int(parts[-2]) * 60
    if len(parts) == 3:
        seconds += int(parts[0]) * 3600
    return int(seconds * 1000)


def parse_webvtt(value: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    lines = value.replace("\r", "").split("\n")
    index = 0
    while index < len(lines):
        if "-->" not in lines[index]:
            index += 1
            continue
        times = lines[index].split("-->")
        text_lines: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(text_lines))).strip()
        if text:
            segments.append(
                {
                    "start_ms": _parse_vtt_timestamp(times[0].strip()),
                    "end_ms": _parse_vtt_timestamp(times[1].strip().split()[0]),
                    "text": text,
                }
            )
        index += 1
    return segments


class YouTubeSourceProvider(SourceProvider):
    def __init__(self, client: YouTubeAPIClient):
        self.client = client
        self.last_events: list[dict[str, Any]] = []

    def resolve(self, source_type: str, url: str, title: str | None) -> list[dict[str, Any]]:
        if source_type == "youtube_playlist":
            playlist_id = _playlist_id(url)
            if not playlist_id:
                raise ValueError("approved YouTube playlist URL is missing a list id")
            ids = self.client.playlist_video_ids(playlist_id)
        else:
            video_id = _youtube_id(url)
            if not video_id:
                raise ValueError("approved YouTube video URL is invalid")
            ids = [video_id]
        resources = self.client.video_details(ids)
        resolved = [_youtube_item(resource, "youtube_data_api_v3") for resource in resources]
        if len(resolved) != len(ids):
            missing = sorted(set(ids) - {row["external_id"] for row in resolved})
            self.last_events.append(
                {
                    "provider": "youtube",
                    "operation": "resolve",
                    "status": "partial",
                    "missing": missing,
                }
            )
        if not resolved:
            raise ProviderRequestError("YouTube returned no accessible approved videos")
        return resolved

    def transcript(self, item: dict[str, Any], seeds: list[str]) -> list[dict[str, Any]]:
        if not self.client.has_caption_authorization:
            self.last_events.append(
                {
                    "provider": "youtube",
                    "operation": "captions",
                    "status": "requires_authorization",
                    "external_id": item["external_id"],
                }
            )
            return []
        try:
            return parse_webvtt(self.client.captions_vtt(item["external_id"]))
        except ProviderRequestError as exc:
            self.last_events.append(
                {
                    "provider": "youtube",
                    "operation": "captions",
                    "status": "unavailable",
                    "external_id": item["external_id"],
                    "error": str(exc),
                }
            )
            return []


class LiveResearchProvider(ResearchProvider):
    def __init__(
        self,
        youtube: YouTubeAPIClient,
        *,
        tiktok_token: str = "",
        tiktok_client_key: str = "",
        tiktok_client_secret: str = "",
        instagram_token: str = "",
        instagram_user_id: str = "",
        region: str = "GB",
        lookback_days: int = 14,
        results_per_query: int = 10,
        transport: JsonRequest = request_json,
        text_transport: TextRequest = request_text,
    ):
        self.youtube = youtube
        self.tiktok_token = tiktok_token
        self.tiktok_client_key = tiktok_client_key
        self.tiktok_client_secret = tiktok_client_secret
        self._tiktok_expires_at: datetime | None = None
        self.instagram_token = instagram_token
        self.instagram_user_id = instagram_user_id
        self.region = region
        self.lookback_days = lookback_days
        self.results_per_query = results_per_query
        self.transport = transport
        self.text_transport = text_transport
        self.last_events: list[dict[str, Any]] = []
        self._example_rows: list[dict[str, Any]] = []

    def _event(self, provider: str, operation: str, status: str, **details: Any) -> None:
        self.last_events.append(
            {"provider": provider, "operation": operation, "status": status, **details}
        )

    def _youtube_observation(self, resource: dict[str, Any], topic: str) -> dict[str, Any]:
        snippet = resource.get("snippet", {})
        stats = resource.get("statistics", {})
        title = html.unescape(snippet.get("title", ""))
        return {
            "platform": "youtube",
            "url": f"https://www.youtube.com/watch?v={resource['id']}",
            "creator": snippet.get("channelTitle") or snippet.get("channelId") or "unknown",
            "published_hours_ago": _age_hours(snippet.get("publishedAt")),
            "metrics": {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
            },
            "baseline": {},
            "transcript": f"{title}. {snippet.get('description', '')}".strip(),
            "labels": {"angle": _angle(title), "topic": topic},
            "raw": {
                "provider": "youtube_data_api_v3",
                "resource_id": resource["id"],
                "channel_id": snippet.get("channelId"),
                "tags": snippet.get("tags", []),
                "duration": resource.get("contentDetails", {}).get("duration"),
                "provenance": "official_api",
            },
        }

    def _collect_youtube(
        self, queries: list[str], examples: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        published_after = (
            (datetime.now(UTC) - timedelta(days=self.lookback_days))
            .isoformat()
            .replace("+00:00", "Z")
        )
        for query in queries[:5]:
            try:
                resources = self.youtube.search(
                    query, self.region, published_after, self.results_per_query
                )
                rows.extend(self._youtube_observation(row, query) for row in resources)
                self._event("youtube", "search", "ok", query=query, count=len(resources))
            except ProviderRequestError as exc:
                self._event("youtube", "search", "failed", query=query, error=str(exc))
        ids = [_youtube_id(str(row.get("url", ""))) for row in examples]
        ids = [video_id for video_id in ids if video_id]
        if ids:
            try:
                resources = self.youtube.video_details(list(dict.fromkeys(ids)))
                rows.extend(
                    self._youtube_observation(row, "successful example") for row in resources
                )
                self._event("youtube", "successful_examples", "ok", count=len(resources))
            except ProviderRequestError as exc:
                self._event("youtube", "successful_examples", "failed", error=str(exc))
        return rows

    def _collect_tiktok(
        self, seeds: list[str], examples: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for example in examples:
            url = str(example.get("url", ""))
            if "tiktok.com/" not in url:
                continue
            try:
                result = self.transport(
                    "https://www.tiktok.com/oembed", {"url": url}, None, "GET", None
                )
                rows.append(
                    {
                        "platform": "tiktok",
                        "url": url,
                        "creator": result.get("author_name", "unknown"),
                        "published_hours_ago": 1,
                        "metrics": {"views": 1, "likes": 0, "comments": 0},
                        "baseline": {"median_views": 1, "sample_size": 1},
                        "transcript": result.get("title", ""),
                        "labels": {
                            "angle": _angle(result.get("title", "")),
                            "topic": "successful example",
                        },
                        "raw": {
                            "provider": "tiktok_oembed",
                            "provenance": "official_public_oembed",
                            "metadata": result,
                        },
                    }
                )
                self._event("tiktok", "oembed_example", "ok", url=url)
            except ProviderRequestError as exc:
                self._event("tiktok", "oembed_example", "failed", url=url, error=str(exc))
        token = self._tiktok_access_token()
        if not token:
            self._event("tiktok", "research_search", "requires_approved_access")
            return rows
        end = datetime.now(UTC).strftime("%Y%m%d")
        start = (datetime.now(UTC) - timedelta(days=self.lookback_days)).strftime("%Y%m%d")
        fields = "id,video_description,create_time,region_code,share_count,view_count,like_count,comment_count,hashtag_names,username,voice_to_text,video_duration"
        for seed in seeds[:3]:
            try:
                result = self.transport(
                    "https://open.tiktokapis.com/v2/research/video/query/",
                    {"fields": fields},
                    {"Authorization": f"Bearer {token}"},
                    "POST",
                    {
                        "query": {
                            "and": [
                                {"operation": "EQ", "field_name": "keyword", "field_values": [seed]}
                            ]
                        },
                        "max_count": self.results_per_query,
                        "start_date": start,
                        "end_date": end,
                        "is_random": False,
                    },
                )
                error = result.get("error", {})
                if error and error.get("code") not in {None, "ok"}:
                    raise ProviderRequestError(
                        f"TikTok Research API rejected the query ({error.get('code')})"
                    )
                videos = result.get("data", {}).get("videos", [])
                for video in videos:
                    video_id = str(video.get("id") or video.get("video_id"))
                    rows.append(
                        {
                            "platform": "tiktok",
                            "url": f"https://www.tiktok.com/@{video.get('username', 'unknown')}/video/{video_id}",
                            "creator": video.get("username", "unknown"),
                            "published_hours_ago": _age_hours(video.get("create_time")),
                            "metrics": {
                                "views": video.get("view_count", 0),
                                "likes": video.get("like_count", 0),
                                "comments": video.get("comment_count", 0),
                                "shares": video.get("share_count", 0),
                            },
                            "baseline": {},
                            "transcript": video.get("voice_to_text")
                            or video.get("video_description", ""),
                            "labels": {
                                "angle": _angle(video.get("video_description", "")),
                                "topic": seed,
                            },
                            "raw": {
                                "provider": "tiktok_research_api_v2",
                                "provenance": "official_approved_api",
                                "video": video,
                            },
                        }
                    )
                self._event("tiktok", "research_search", "ok", query=seed, count=len(videos))
            except ProviderRequestError as exc:
                self._event("tiktok", "research_search", "failed", query=seed, error=str(exc))
        return rows

    def _tiktok_access_token(self) -> str:
        if (
            self.tiktok_client_key
            and self.tiktok_client_secret
            and (not self._tiktok_expires_at or datetime.now(UTC) >= self._tiktok_expires_at)
        ):
            payload = urllib.parse.urlencode(
                {
                    "client_key": self.tiktok_client_key,
                    "client_secret": self.tiktok_client_secret,
                    "grant_type": "client_credentials",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                "https://open.tiktokapis.com/v2/oauth/token/",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    token_data = json.loads(response.read().decode("utf-8"))
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                self._event("tiktok", "client_token", "failed", error=type(exc).__name__)
                return ""
            self.tiktok_token = token_data.get("access_token", "")
            if not self.tiktok_token:
                self._event(
                    "tiktok",
                    "client_token",
                    "failed",
                    error=str(token_data.get("error", "no_access_token")),
                )
                return ""
            self._tiktok_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(60, int(token_data.get("expires_in", 7200)) - 60)
            )
            self._event("tiktok", "client_token", "ok")
        return self.tiktok_token

    def _collect_instagram(
        self, seeds: list[str], examples: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not (self.instagram_token and self.instagram_user_id):
            self._event("instagram", "hashtag_search", "requires_professional_account_access")
            return rows
        root = "https://graph.facebook.com/v23.0"
        for seed in seeds[:3]:
            hashtag = re.sub(r"[^a-zA-Z0-9_]", "", seed.split()[0]).lower()
            if not hashtag:
                continue
            try:
                search = self.transport(
                    f"{root}/ig_hashtag_search",
                    {
                        "user_id": self.instagram_user_id,
                        "q": hashtag,
                        "access_token": self.instagram_token,
                    },
                    None,
                    "GET",
                    None,
                )
                hashtag_id = next(iter(search.get("data", [])), {}).get("id")
                if not hashtag_id:
                    continue
                result = self.transport(
                    f"{root}/{hashtag_id}/recent_media",
                    {
                        "user_id": self.instagram_user_id,
                        "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                        "access_token": self.instagram_token,
                        "limit": self.results_per_query,
                    },
                    None,
                    "GET",
                    None,
                )
                media = result.get("data", [])
                for item in media:
                    caption = item.get("caption", "")
                    rows.append(
                        {
                            "platform": "instagram",
                            "url": item.get("permalink") or f"instagram://media/{item['id']}",
                            "creator": f"hashtag:{hashtag}",
                            "published_hours_ago": _age_hours(item.get("timestamp")),
                            "metrics": {
                                "views": item.get("like_count", 0) + item.get("comments_count", 0),
                                "likes": item.get("like_count", 0),
                                "comments": item.get("comments_count", 0),
                            },
                            "baseline": {},
                            "transcript": caption,
                            "labels": {"angle": _angle(caption), "topic": seed},
                            "raw": {
                                "provider": "instagram_graph_api",
                                "provenance": "official_professional_account_api",
                                "media": item,
                                "metric_note": "engagement proxy; view count unavailable",
                            },
                        }
                    )
                self._event("instagram", "hashtag_search", "ok", query=seed, count=len(media))
            except ProviderRequestError as exc:
                self._event("instagram", "hashtag_search", "failed", query=seed, error=str(exc))
        return rows

    def _collect_web(self, seeds: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for seed in seeds[:3]:
            articles: list[dict[str, Any]] = []
            try:
                result = self.transport(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    {
                        "query": seed,
                        "mode": "artlist",
                        "format": "json",
                        "maxrecords": self.results_per_query,
                        "timespan": f"{self.lookback_days}d",
                    },
                    None,
                    "GET",
                    None,
                )
                articles = result.get("articles", [])
                self._event("gdelt", "article_search", "ok", query=seed, count=len(articles))
            except ProviderRequestError as exc:
                self._event("gdelt", "article_search", "failed", query=seed, error=str(exc))
            provider = "gdelt_doc_2"
            if not articles:
                try:
                    feed = self.text_transport(
                        "https://news.google.com/rss/search",
                        {
                            "q": seed,
                            "hl": "en-GB",
                            "gl": self.region,
                            "ceid": f"{self.region}:en",
                        },
                        {"User-Agent": "alpha-clipper/0.1"},
                    )
                    root = ET.fromstring(feed)
                    articles = [
                        {
                            "url": item.findtext("link"),
                            "title": item.findtext("title", ""),
                            "domain": item.findtext("source", "unknown"),
                            "seendate": (
                                parsedate_to_datetime(item.findtext("pubDate", ""))
                                if item.findtext("pubDate")
                                else datetime.now(UTC)
                            ).isoformat(),
                        }
                        for item in root.findall(".//item")[: self.results_per_query]
                    ]
                    provider = "google_news_rss"
                    self._event("google_news", "rss_search", "ok", query=seed, count=len(articles))
                except (ProviderRequestError, ET.ParseError, ValueError) as exc:
                    self._event("google_news", "rss_search", "failed", query=seed, error=str(exc))
            for article in articles:
                title = article.get("title", "")
                rows.append(
                    {
                        "platform": "wider_web",
                        "url": article.get("url"),
                        "creator": article.get("domain", "unknown"),
                        "published_hours_ago": _age_hours(article.get("seendate")),
                        "metrics": {"views": 1, "likes": 0, "comments": 0},
                        "baseline": {"median_views": 1, "sample_size": 1},
                        "transcript": title,
                        "labels": {"angle": _angle(title), "topic": seed},
                        "raw": {
                            "provider": provider,
                            "provenance": "public_news_index",
                            "signal_type": "mention_not_engagement",
                            "article": article,
                        },
                    }
                )
        return rows

    def inspect_examples(self, examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_events = []
        rows = self._collect_youtube([], examples)
        rows.extend(self._collect_tiktok([], examples))
        self._example_rows = rows
        return rows

    def collect(
        self,
        campaign: dict[str, Any],
        seeds: list[str],
        queries: list[str] | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_events = []
        examples = examples or []
        search_queries = queries or seeds
        rows = [*self._example_rows]
        if not self._example_rows:
            rows.extend(self._collect_youtube([], examples))
        rows.extend(self._collect_youtube(search_queries, []))
        rows.extend(self._collect_tiktok(seeds, examples))
        rows.extend(self._collect_instagram(seeds, examples))
        rows.extend(self._collect_web(seeds))
        deduplicated = {row["url"]: row for row in rows if row.get("url")}
        rows = list(deduplicated.values())
        youtube_channels = [
            row["raw"].get("channel_id")
            for row in rows
            if row["platform"] == "youtube" and row["raw"].get("channel_id")
        ]
        try:
            youtube_baselines = self.youtube.channel_baselines(youtube_channels)
            self._event(
                "youtube",
                "creator_baselines",
                "ok",
                channels=len(youtube_baselines),
            )
        except ProviderRequestError as exc:
            youtube_baselines = {}
            self._event("youtube", "creator_baselines", "failed", error=str(exc))
        for row in rows:
            channel_id = row.get("raw", {}).get("channel_id")
            if channel_id in youtube_baselines:
                row["baseline"] = youtube_baselines[channel_id]
        creator_views: dict[tuple[str, str], list[float]] = {}
        for row in rows:
            creator_views.setdefault((row["platform"], row["creator"]), []).append(
                float(row["metrics"].get("views", 0))
            )
        for row in rows:
            if not row.get("baseline"):
                sample = creator_views[(row["platform"], row["creator"])]
                row["baseline"] = {
                    "median_views": statistics.median(sample) if sample else 0,
                    "sample_size": len(sample),
                    "scope": "collected_window",
                }
        return rows


def _angle(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("why", "truth", "wrong", "mistake", "never")):
        return "contrarian or explanatory hook"
    if any(word in lowered for word in ("how", "steps", "guide", "method")):
        return "practical method"
    if any(word in lowered for word in ("funny", "lol", "comedy")):
        return "humour"
    return "topic-led hook"
