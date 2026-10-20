"""Операторская конфигурация маршрута только для браузерных клиентов ЕИС."""

from __future__ import annotations

import os
from urllib.parse import urlsplit


class EisBrowserConfigError(ValueError):
    """Безопасный код ошибки без адреса или credentials из окружения."""


def eis_browser_proxy_server() -> str | None:
    """Credentials в URL запрещены; отсутствие настройки сохраняет прямой путь."""
    value = os.environ.get("EIS_BROWSER_PROXY")
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https", "socks5"}
            or not parts.hostname
            or parts.port is None
            or parts.username is not None
            or parts.password is not None
            or parts.path
            or parts.query
            or parts.fragment
            or any(character.isspace() for character in value)
        ):
            raise ValueError
    except ValueError as error:
        raise EisBrowserConfigError("PROXY_CONFIG_INVALID") from error
    return value
