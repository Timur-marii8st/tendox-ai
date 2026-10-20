"""Check direct TLS reachability of public EIS hosts; no token is used."""

from __future__ import annotations

import json
import socket
import ssl

HOSTS = ("example.com", "int.zakupki.gov.ru", "zakupki.gov.ru")


def _check(host: str) -> str:
    try:
        with socket.create_connection((host, 443), timeout=5) as connection:
            connection.settimeout(5)
            with ssl.create_default_context().wrap_socket(
                connection, server_hostname=host
            ) as secured:
                return f"TLS_OK:{secured.version()}"
    except TimeoutError:
        return "TIMEOUT"
    except (OSError, ssl.SSLError) as error:
        return f"{type(error).__name__}"


def main() -> int:
    results = {host: _check(host) for host in HOSTS}
    print(json.dumps(results, ensure_ascii=False))
    return 0 if results["int.zakupki.gov.ru"].startswith("TLS_OK:") else 2


if __name__ == "__main__":
    raise SystemExit(main())
