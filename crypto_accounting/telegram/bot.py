"""
Low-level Telegram Bot API client.
Uses only stdlib (urllib) — no external dependencies required.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot:
    """Minimal Telegram Bot API client."""

    def __init__(self, token: str) -> None:
        self.token = token

    def _call(self, method: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        url = _API_BASE.format(token=self.token, method=method)
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            log.warning("Telegram API %s error %s: %s", method, e.code, body)
            return {"ok": False, "description": body}
        except Exception as exc:
            log.warning("Telegram API %s failed: %s", method, exc)
            return {"ok": False, "description": str(exc)}

    # ------------------------------------------------------------------ #
    # Bot info
    # ------------------------------------------------------------------ #

    def get_me(self) -> Dict:
        return self._call("getMe")

    # ------------------------------------------------------------------ #
    # Webhook
    # ------------------------------------------------------------------ #

    def set_webhook(self, url: str, secret_token: Optional[str] = None) -> Dict:
        payload: Dict[str, Any] = {"url": url, "allowed_updates": ["message", "callback_query"]}
        if secret_token:
            payload["secret_token"] = secret_token
        return self._call("setWebhook", payload)

    def delete_webhook(self) -> Dict:
        return self._call("deleteWebhook")

    def get_webhook_info(self) -> Dict:
        return self._call("getWebhookInfo")

    # ------------------------------------------------------------------ #
    # Sending messages
    # ------------------------------------------------------------------ #

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
        disable_web_page_preview: bool = True,
    ) -> Dict:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call("sendMessage", payload)

    def send_to_many(self, chat_ids: List[int], text: str, **kwargs) -> None:
        """Fire-and-forget broadcast; errors are logged, not raised."""
        for cid in chat_ids:
            result = self.send_message(cid, text, **kwargs)
            if not result.get("ok"):
                log.warning("Failed to send to %s: %s", cid, result.get("description"))

    # ------------------------------------------------------------------ #
    # Polling (local dev only)
    # ------------------------------------------------------------------ #

    def get_updates(self, offset: int = 0, timeout: int = 30) -> List[Dict]:
        result = self._call("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]})
        if result.get("ok"):
            return result.get("result", [])
        return []

    def run_polling(self, handler) -> None:
        """Simple long-poll loop for local development."""
        import time
        log.info("Starting Telegram bot polling…")
        offset = 0
        while True:
            try:
                updates = self.get_updates(offset=offset)
                for upd in updates:
                    offset = upd["update_id"] + 1
                    try:
                        handler(upd)
                    except Exception:
                        log.exception("Handler error for update %s", upd.get("update_id"))
            except KeyboardInterrupt:
                break
            except Exception:
                log.exception("Polling error")
                time.sleep(5)


def build_keyboard(buttons: List[List[str]]) -> Dict:
    """Build a ReplyKeyboardMarkup from a 2-D list of button labels."""
    return {
        "keyboard": [[{"text": b} for b in row] for row in buttons],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def build_inline_keyboard(buttons: List[List[Dict[str, str]]]) -> Dict:
    """Build InlineKeyboardMarkup: each button is {text, callback_data}."""
    return {"inline_keyboard": [[b for b in row] for row in buttons]}
