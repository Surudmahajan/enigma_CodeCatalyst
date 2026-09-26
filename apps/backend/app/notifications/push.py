"""Best-effort push delivery through the Expo push service.

Push payloads carry a title, a short generic body and navigation ids — never
message content or commercial details — because they transit third-party
infrastructure and appear on lock screens.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("symbio.push")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_push(tokens: list[str], title: str, body: str, data: dict) -> None:
    settings = get_settings()
    if settings.push_provider != "expo" or not tokens:
        return
    headers = {"Content-Type": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"
    messages = [{"to": t, "title": title, "body": body, "data": data, "sound": "default"} for t in tokens]
    try:
        for start in range(0, len(messages), 100):  # Expo accepts up to 100 messages per request
            httpx.post(EXPO_PUSH_URL, json=messages[start:start + 100], headers=headers, timeout=10).raise_for_status()
    except httpx.HTTPError:
        logger.warning("Push delivery failed", extra={"event": "push_failed"})
