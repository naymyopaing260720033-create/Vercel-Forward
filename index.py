import os
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OWNER_ID = os.environ.get("OWNER_ID")
KV_REST_API_URL = os.environ.get("KV_REST_API_URL")
KV_REST_API_TOKEN = os.environ.get("KV_REST_API_TOKEN")

SOURCE_KEY = "telegram_bot:source_channel_id"
DEST_KEY = "telegram_bot:destination_channel_id"


def telegram_api(method: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not BOT_TOKEN:
        app.logger.error("TELEGRAM_BOT_TOKEN is not configured")
        return None

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def send_message(chat_id: int | str, text: str) -> None:
    telegram_api("sendMessage", {"chat_id": chat_id, "text": text})


def kv_request(command: list[str]) -> Optional[Any]:
    if not KV_REST_API_URL or not KV_REST_API_TOKEN:
        app.logger.error("KV_REST_API_URL or KV_REST_API_TOKEN is not configured")
        return None

    response = requests.post(
        KV_REST_API_URL,
        headers={"Authorization": f"Bearer {KV_REST_API_TOKEN}"},
        json=command,
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("result")


def kv_get(key: str) -> Optional[str]:
    value = kv_request(["GET", key])
    return str(value) if value is not None else None


def kv_set(key: str, value: str) -> None:
    kv_request(["SET", key, value])


def is_owner(message: Dict[str, Any]) -> bool:
    if not OWNER_ID:
        app.logger.error("OWNER_ID is not configured")
        return False

    user = message.get("from") or {}
    return str(user.get("id")) == str(OWNER_ID)


def parse_command(message: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    text = message.get("text") or ""
    if not text.startswith("/"):
        return None, None

    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else None
    return command, argument


def handle_command(message: Dict[str, Any]) -> None:
    command, argument = parse_command(message)
    if command not in {"/setsource", "/setdest"}:
        return

    chat_id = message.get("chat", {}).get("id")
    if not is_owner(message):
        if chat_id is not None:
            send_message(chat_id, "Unauthorized.")
        return

    if not argument:
        if chat_id is not None:
            send_message(chat_id, f"Usage: {command} <channel_id>")
        return

    if command == "/setsource":
        kv_set(SOURCE_KEY, argument)
        confirmation = f"Source channel set to {argument}"
    else:
        kv_set(DEST_KEY, argument)
        confirmation = f"Destination channel set to {argument}"

    if chat_id is not None:
        send_message(chat_id, confirmation)


def handle_channel_post(post: Dict[str, Any]) -> None:
    if "video" not in post:
        return

    source_channel_id = kv_get(SOURCE_KEY)
    destination_channel_id = kv_get(DEST_KEY)
    post_chat_id = str(post.get("chat", {}).get("id"))

    if not source_channel_id or not destination_channel_id:
        app.logger.warning("Source or destination channel is not configured")
        return

    if post_chat_id != str(source_channel_id):
        return

    telegram_api(
        "copyMessage",
        {
            "chat_id": destination_channel_id,
            "from_chat_id": source_channel_id,
            "message_id": post["message_id"],
        },
    )


@app.post("/api")
def webhook() -> tuple[Any, int]:
    update = request.get_json(silent=True) or {}

    if "message" in update:
        handle_command(update["message"])

    if "channel_post" in update:
        handle_channel_post(update["channel_post"])

    return jsonify({"ok": True}), 200


@app.get("/api")
def healthcheck() -> tuple[Any, int]:
    return jsonify({"ok": True, "service": "telegram-webhook-bot"}), 200
