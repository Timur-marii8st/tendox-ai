"""Сетевой маршрут публичных источников задаётся окружением оператора."""

from __future__ import annotations

import os

import httpx


def public_source_client() -> httpx.Client:
    """Учитывать proxy/CA окружения, сохраняя TLS и запрет redirects.

    Нет выбора другого маршрута после отказа или отключения проверки TLS.
    Значения proxy и сертификатов не входят в ошибки, результаты и журналы.
    """
    setting = os.environ.get("SOURCE_HTTP_TRUST_ENV", "true").strip().lower()
    if setting not in {"true", "false"}:
        raise httpx.TransportError("SOURCE_HTTP_CONFIGURATION_INVALID")
    try:
        return httpx.Client(
            timeout=15, follow_redirects=False, verify=True, trust_env=setting == "true"
        )
    except (ValueError, OSError, ImportError):
        # Конструктор может включить URL с credentials в сообщение исключения.
        raise httpx.TransportError("SOURCE_HTTP_CONFIGURATION_INVALID") from None
