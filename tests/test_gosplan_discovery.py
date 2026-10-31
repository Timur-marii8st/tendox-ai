import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from procurement.sources.gosplan_discovery import GosplanError, classify, fetch_page, parse_page

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def row(number="32616349722", **kwargs):
    return {
        "purchase_number": number,
        "purchase_type": "purchaseNotice",
        "updated_at": "2026-10-21T12:00:00",
        **kwargs,
    }


def test_candidate_is_untrusted_and_existing_version_is_unknown():
    page = parse_page(json.dumps([row()]).encode(), "223", NOW, 1)
    assert page.may_have_more
    assert classify(page, {"32616349722"})[0][1] == "VERSION_UNKNOWN"
    assert classify(page, set())[0][1] == "MISSING_NOTICE"
    assert page.candidates[0].updated_raw == "2026-10-21T12:00:00"


@pytest.mark.parametrize(
    "data", [[row(), row()], [row("123")], [row(purchase_type="../")], [None], {}]
)
def test_reject_partial_or_ambiguous_page(data):
    with pytest.raises(GosplanError):
        parse_page(json.dumps(data).encode(), "223", NOW, 2)


def test_http_uses_header_not_query_and_stops_on_rate_limit():
    def handler(request):
        assert request.headers["apikey"] == "secret"
        assert "secret" not in str(request.url)
        return httpx.Response(429)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(GosplanError, match="HTTP_429"),
    ):
        fetch_page(client, "secret", "223", start=NOW - timedelta(days=1), end=NOW, now=NOW)


def test_rejects_naive_scope_and_large_response():
    with pytest.raises(GosplanError):
        parse_page(b"[]", "223", NOW.replace(tzinfo=None), 2)
    with pytest.raises(GosplanError, match="RESPONSE_SIZE_INVALID"):
        parse_page(b" " * (2 * 1024 * 1024 + 1), "223", NOW, 2)


@pytest.mark.parametrize(("law", "number"), [("44", "0000000000000000001"), ("223", "00000000001")])
def test_null_provider_purchase_type_remains_invalid_and_not_a_candidate(law, number):
    # The live 44 diagnostic returned purchase_type=null. The prior response was not retained.
    payload = json.dumps([row(number, purchase_type=None)]).encode()
    with pytest.raises(GosplanError, match=r"^TYPE_INVALID$"):
        parse_page(payload, law, NOW, 1)


@pytest.mark.parametrize("law", ["44", "223"])
def test_offset_over_provider_limit_never_sends_request(law):
    seen = []
    transport = httpx.MockTransport(lambda request: seen.append(request))
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(GosplanError, match="SCOPE_INVALID"),
    ):
        fetch_page(client, "secret", law, start=NOW - timedelta(days=1), end=NOW,
                   offset=1100, now=NOW)
    assert not seen
