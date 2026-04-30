"""Placeholder media endpoint for MMS scenarios.

Real Twilio serves MMS media at signed, short-lived URLs. The twin serves
a fixed 1×1 transparent PNG at any well-formed media-SID path so consumer
code that fetches media succeeds in tests without the twin needing
durable media storage. Documented as a fidelity gap in SCENARIOS.md.
"""

import base64
import re

from flask import Blueprint, make_response

media_bp = Blueprint("media", __name__, url_prefix="/_twin/media")

# Twilio media SIDs are ME + 32 hex chars. The placeholder accepts any
# 32-hex SID with an ME prefix.
_MEDIA_SID_PATTERN = re.compile(r"^ME[0-9a-f]{32}$")

# 67-byte 1×1 transparent PNG.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII="
)


@media_bp.route("/<media_sid>", methods=["GET"])
def get_media(media_sid: str):
    if not _MEDIA_SID_PATTERN.match(media_sid):
        from flask import jsonify
        return jsonify({"error": "Invalid media SID"}), 400
    resp = make_response(_PNG_1X1)
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp
