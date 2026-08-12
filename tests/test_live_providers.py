from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import pytest

from alpha.live_providers import (
    LiveResearchProvider,
    ProviderRequestError,
    YouTubeAPIClient,
    YouTubeSourceProvider,
    parse_webvtt,
)
from alpha.pipeline import Providers
from alpha.providers import LocalHeuristicAIAdapter, SourceProvider

from .conftest import campaign_payload


class TokenResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"access_token":"refreshed-access-token","expires_in":3600}'


class TikTokTokenResponse(TokenResponse):
    def read(self):
        return b'{"access_token":"tiktok-client-token","expires_in":7200,"token_type":"Bearer"}'


def youtube_resource(video_id: str, title: str = "Why this method works") -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": "A real description with a practical payoff.",
            "channelTitle": "Real Creator",
            "channelId": "channel-1",
            "publishedAt": (datetime.now(UTC) - timedelta(hours=6)).isoformat(),
            "tags": ["creator", "growth"],
        },
        "contentDetails": {"duration": "PT1M2.5S", "caption": "true"},
        "statistics": {"viewCount": "12000", "likeCount": "900", "commentCount": "80"},
        "status": {"privacyStatus": "public", "embeddable": True},
    }


def test_live_youtube_playlist_metadata_dedup_and_caption_contract():
    calls = []

    def transport(url, params, headers, method, body):
        calls.append((url, params, headers, method, body))
        if url.endswith("/playlistItems"):
            if not params.get("pageToken"):
                return {
                    "items": [
                        {"contentDetails": {"videoId": "video-a"}},
                        {"contentDetails": {"videoId": "video-b"}},
                    ],
                    "nextPageToken": "next",
                }
            return {"items": [{"contentDetails": {"videoId": "video-a"}}]}
        if url.endswith("/videos"):
            return {"items": [youtube_resource(video_id) for video_id in params["id"].split(",")]}
        raise AssertionError(url)

    client = YouTubeAPIClient("test-youtube-key", transport=transport)
    provider = YouTubeSourceProvider(client)
    items = provider.resolve(
        "youtube_playlist",
        "https://www.youtube.com/playlist?list=playlist-1",
        None,
    )

    assert [item["external_id"] for item in items] == ["video-a", "video-b"]
    assert items[0]["source_url"] == "https://www.youtube.com/watch?v=video-a"
    assert items[0]["duration_ms"] == 62_500
    assert items[0]["metadata"]["provider"] == "youtube_data_api_v3"
    assert items[0]["metadata"]["caption_available"]
    assert provider.transcript(items[0], []) == []
    assert provider.last_events[-1]["status"] == "requires_authorization"
    assert all(call[1]["key"] == "test-youtube-key" for call in calls)


def test_webvtt_preserves_exact_timestamps():
    segments = parse_webvtt(
        "WEBVTT\n\n00:00:01.250 --> 00:00:03.500\nA real caption.\n\n"
        "00:01:02.000 --> 00:01:05.125\nSecond line.\n"
    )
    assert segments == [
        {"start_ms": 1250, "end_ms": 3500, "text": "A real caption."},
        {"start_ms": 62000, "end_ms": 65125, "text": "Second line."},
    ]


def test_live_research_collects_official_youtube_tiktok_and_public_web_evidence():
    def transport(url, params, headers, method, body):
        if url.endswith("/search"):
            return {"items": [{"id": {"videoId": "trend-video"}}]}
        if url.endswith("/videos"):
            return {"items": [youtube_resource(video_id) for video_id in params["id"].split(",")]}
        if url.endswith("/channels"):
            return {
                "items": [
                    {
                        "id": "channel-1",
                        "contentDetails": {"relatedPlaylists": {"uploads": "uploads-1"}},
                    }
                ]
            }
        if url.endswith("/playlistItems"):
            return {"items": [{"contentDetails": {"videoId": "baseline-video"}}]}
        if url == "https://www.tiktok.com/oembed":
            return {"title": "Funny creator hook #growth", "author_name": "Clipper One"}
        if "gdeltproject.org" in url:
            return {
                "articles": [
                    {
                        "url": "https://news.example/growth",
                        "title": "The creator growth method everyone missed",
                        "domain": "news.example",
                        "seendate": datetime.now(UTC).isoformat(),
                    }
                ]
            }
        raise AssertionError(url)

    youtube = YouTubeAPIClient("test-youtube-key", transport=transport)
    provider = LiveResearchProvider(youtube, transport=transport, results_per_query=5)
    examples = [
        {
            "url": "https://www.tiktok.com/@clipper/video/123",
            "platform": "tiktok",
            "creator": "clipper",
        }
    ]
    rows = provider.collect(
        {"id": "campaign-1", "name": "Real campaign"},
        ["creator growth"],
        ["creator growth viral clips"],
        examples,
    )

    assert {row["platform"] for row in rows} == {"youtube", "tiktok", "wider_web"}
    youtube_row = next(row for row in rows if row["platform"] == "youtube")
    assert youtube_row["metrics"]["views"] == 12000
    assert youtube_row["raw"]["provenance"] == "official_api"
    assert youtube_row["baseline"]["scope"] == "channel_recent_uploads"
    tiktok_row = next(row for row in rows if row["platform"] == "tiktok")
    assert tiktok_row["raw"]["provenance"] == "official_public_oembed"
    web_row = next(row for row in rows if row["platform"] == "wider_web")
    assert web_row["raw"]["signal_type"] == "mention_not_engagement"
    assert any(
        event["provider"] == "tiktok" and event["status"] == "requires_approved_access"
        for event in provider.last_events
    )


def test_tiktok_research_api_contract_uses_approved_bearer_token():
    calls = []

    def transport(url, params, headers, method, body):
        calls.append((url, params, headers, method, body))
        if url.endswith("/search"):
            return {"items": []}
        if "gdeltproject.org" in url:
            return {"articles": []}
        if "tiktokapis.com" in url:
            return {
                "data": {
                    "videos": [
                        {
                            "id": "987",
                            "username": "research_creator",
                            "video_description": "How to grow with a surprising hook",
                            "create_time": int(datetime.now(UTC).timestamp()),
                            "view_count": 50000,
                            "like_count": 5000,
                            "comment_count": 120,
                            "share_count": 800,
                        }
                    ]
                }
            }
        raise AssertionError(url)

    youtube = YouTubeAPIClient("test-youtube-key", transport=transport)
    provider = LiveResearchProvider(
        youtube,
        tiktok_token="approved-research-token",
        transport=transport,
    )
    rows = provider.collect({"id": "campaign-1"}, ["creator growth"], [], [])
    tiktok = next(row for row in rows if row["platform"] == "tiktok")
    assert tiktok["metrics"]["views"] == 50000
    request = next(call for call in calls if "tiktokapis.com" in call[0])
    assert request[2]["Authorization"] == "Bearer approved-research-token"
    assert request[3] == "POST"
    assert request[4]["query"]["and"][0]["field_name"] == "keyword"


def test_wider_web_falls_back_to_public_google_news_rss():
    def transport(url, params, headers, method, body):
        if url.endswith("/search"):
            return {"items": []}
        if "gdeltproject.org" in url:
            raise ProviderRequestError("provider returned HTTP 429")
        raise AssertionError(url)

    def text_transport(url, params, headers):
        assert url == "https://news.google.com/rss/search"
        assert params["q"] == "creator growth"
        return """<rss><channel><item><title>Creator growth is accelerating</title>
        <link>https://news.example/story</link><pubDate>Wed, 13 Aug 2026 10:00:00 GMT</pubDate>
        <source>News Example</source></item></channel></rss>"""

    youtube = YouTubeAPIClient("test-youtube-key", transport=transport)
    provider = LiveResearchProvider(
        youtube,
        transport=transport,
        text_transport=text_transport,
    )
    rows = provider.collect({"id": "campaign-1"}, ["creator growth"], [], [])
    assert rows[0]["raw"]["provider"] == "google_news_rss"
    assert any(
        event["provider"] == "gdelt" and event["status"] == "failed"
        for event in provider.last_events
    )
    assert any(
        event["provider"] == "google_news" and event["status"] == "ok"
        for event in provider.last_events
    )


def test_live_mode_requires_youtube_key_and_builds_live_adapters(settings):
    with pytest.raises(ValueError, match="YOUTUBE_API_KEY"):
        Providers.build(replace(settings, provider_mode="live"))

    providers = Providers.build(
        replace(settings, provider_mode="live", youtube_api_key="test-youtube-key")
    )
    assert isinstance(providers.source, YouTubeSourceProvider)
    assert isinstance(providers.research, LiveResearchProvider)


def test_youtube_caption_oauth_refresh_contract(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return TokenResponse()

    monkeypatch.setattr("alpha.live_providers.urllib.request.urlopen", fake_urlopen)
    client = YouTubeAPIClient(
        "test-youtube-key",
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_refresh_token="refresh-token",
    )
    assert client.has_caption_authorization
    assert client._caption_token() == "refreshed-access-token"
    assert client._caption_token() == "refreshed-access-token"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://oauth2.googleapis.com/token"
    assert timeout == 20
    assert parse_qs(request.data.decode("utf-8")) == {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "refresh_token": ["refresh-token"],
        "grant_type": ["refresh_token"],
    }


class PartialSourceProvider(SourceProvider):
    def resolve(self, source_type, url, title):
        if "playlist" in url:
            raise ProviderRequestError("playlist is private")
        return [
            {
                "external_id": "accessible-video",
                "source_url": url,
                "title": title or "Accessible video",
                "duration_ms": 60_000,
                "channel": "Creator",
                "metadata": {"provider": "youtube_data_api_v3"},
            }
        ]

    def transcript(self, item, seeds):
        return []


def test_source_resolution_failure_is_isolated_per_approved_source(client, app):
    campaign_id = client.post("/api/campaigns", json=campaign_payload()).json()["id"]
    app.state.pipeline.providers.source = PartialSourceProvider()
    output = app.state.pipeline.resolve_sources(campaign_id, "job-id")
    assert output == {"source_items": 1, "approved_sources": 2, "failed_sources": 1}
    statuses = {
        row["status"]
        for row in app.state.db.all(
            "SELECT status FROM approved_sources WHERE campaign_id=?", (campaign_id,)
        )
    }
    assert statuses == {"resolved", "resolution_failed"}


def test_tiktok_research_client_credentials_refresh_automatically(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return TikTokTokenResponse()

    monkeypatch.setattr("alpha.live_providers.urllib.request.urlopen", fake_urlopen)
    provider = LiveResearchProvider(
        YouTubeAPIClient("test-youtube-key"),
        tiktok_client_key="research-client-key",
        tiktok_client_secret="research-client-secret",
    )
    assert provider._tiktok_access_token() == "tiktok-client-token"
    assert provider._tiktok_access_token() == "tiktok-client-token"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://open.tiktokapis.com/v2/oauth/token/"
    assert timeout == 20
    assert parse_qs(request.data.decode("utf-8")) == {
        "client_key": ["research-client-key"],
        "client_secret": ["research-client-secret"],
        "grant_type": ["client_credentials"],
    }


def test_successful_example_analysis_uses_live_metadata_and_marks_unknown_visuals():
    analysis = LocalHeuristicAIAdapter().analyse_example(
        {
            "id": "example-1",
            "url": "https://www.youtube.com/watch?v=video-1",
            "live_evidence": {
                "transcript": "Why everyone is wrong about creator growth. A practical payoff.",
                "labels": {"topic": "creator growth"},
                "raw": {
                    "provider": "youtube_data_api_v3",
                    "provenance": "official_api",
                    "duration": "PT42S",
                },
            },
        },
        0,
    )
    assert analysis["opening_type"] == "contrarian_claim"
    assert analysis["duration_seconds"] == 42
    assert analysis["caption_pattern"] == "not_measurable_from_metadata"
    assert analysis["evidence"]["provenance"] == "official_api"
