"""Guards for unauthenticated endpoints.

The HRMS public apply/assess links are the first anonymous surface in this app, so the
protections that authenticated routes get from the JWT have to be provided explicitly. Each
function here addresses a specific weakness in the reference project, named in its docstring.

Deliberately dependency-free and in-process: a Redis-backed limiter would be better under
multiple workers, but an in-process one is a genuine improvement over none and adds no
infrastructure. The limits are generous enough that a real applicant never meets them.
"""
import secrets
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

# Anonymous uploads. The reference accepts 12 files × 15 MB on `apply` with no auth and no
# limit — roughly 225 MB per anonymous request, repeatable.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024          # 5 MB, ample for a CV
ALLOWED_UPLOAD_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

# Sliding-window rate limits, per client IP, per bucket.
_WINDOW_SECONDS = 3600
_LIMITS = {
    "apply": 5,          # applications per hour from one address
    "assess": 20,        # assessment page loads / submissions
    "lookup": 60,        # reading a public posting
}
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def public_token(nbytes: int = 16) -> str:
    """A public link code.

    `secrets` is cryptographically random. The reference uses `Math.random()` (40 bits for
    offers/assessments, 30 for postings); V8's PRNG state is recoverable from a handful of
    outputs, so holding one legitimate code gives a path to predicting neighbours.
    """
    return secrets.token_urlsafe(nbytes)


def client_ip(request: Request) -> str:
    """Best-effort client address. Trusts the first X-Forwarded-For hop, since the app is
    normally served behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, bucket: str) -> None:
    """Throttle an anonymous caller. Raises 429 once the hourly limit is reached.

    The reference has no rate limiting anywhere — its only trace is a dead `rate_limited: 429`
    constant — leaving login brute-force, public-token guessing and upload flooding unthrottled.
    """
    limit = _LIMITS.get(bucket, 30)
    key = f"{bucket}:{client_ip(request)}"
    now = time.time()
    window = _hits[key]

    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()

    if len(window) >= limit:
        retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)

    # Keep the table from growing without bound on a long-running process.
    if len(_hits) > 10_000:
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > _WINDOW_SECONDS]:
            _hits.pop(k, None)


def decode_upload(data_uri: Optional[str], allowed: Optional[dict] = None) -> Optional[dict]:
    """Validate and decode a base64 upload from an anonymous caller.

    Returns {"blob", "content_type", "extension"} or None when nothing was sent. Raises 400 with
    a usable message on anything invalid.

    Type is taken from the data: URI and checked against an ALLOW-LIST. The reference permits
    `image/svg+xml` and `application/octet-stream` — the latter meaning *any* file passes — then
    serves them inline with the attacker's content type and no `nosniff`, which is stored XSS.
    """
    import base64
    import binascii

    if not data_uri:
        return None

    allowed = allowed or ALLOWED_UPLOAD_TYPES
    content_type = "application/octet-stream"
    payload = data_uri

    if data_uri.startswith("data:"):
        try:
            header, payload = data_uri.split(",", 1)
            content_type = header[5:].split(";")[0].strip().lower()
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed upload.")

    if content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Please upload one of: {', '.join(sorted(allowed.values()))}.")

    try:
        blob = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Upload could not be read.")

    if not blob:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

    return {"blob": blob, "content_type": content_type, "extension": allowed[content_type]}


def safe_public_error(message: str) -> HTTPException:
    """A 400 whose text is safe to show an anonymous caller.

    The reference echoes raw exception messages on all four of its public routes, leaking
    internals. Callers here pass a message written for the applicant.
    """
    return HTTPException(status_code=400, detail=message)
