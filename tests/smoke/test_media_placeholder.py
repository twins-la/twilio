"""Smoke test for /_twin/media/<media_sid> placeholder PNG endpoint."""


class TestMediaPlaceholder:
    def test_valid_media_sid_returns_png(self, client):
        sid = "ME" + "0" * 32
        resp = client.get(f"/_twin/media/{sid}")
        assert resp.status_code == 200
        assert resp.headers.get("Content-Type") == "image/png"
        body = resp.get_data()
        # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        assert body[:8] == b"\x89PNG\r\n\x1a\n"
        # 1×1 transparent PNG is a small file
        assert len(body) < 200

    def test_invalid_media_sid_rejected(self, client):
        for bad in ("not-a-sid", "MM" + "0" * 32, "ME" + "x" * 32, "ME" + "0" * 31):
            resp = client.get(f"/_twin/media/{bad}")
            assert resp.status_code in (400, 404), bad
