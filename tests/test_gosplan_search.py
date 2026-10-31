"""Provider data stays source-bound and never becomes official admission."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from procurement.sources.gosplan_search import GosplanSearchError, read_detail, search_page

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def client_with(body, status=200):
    def reply(request):
        assert request.headers["apikey"] == "private-key"
        assert "private-key" not in str(request.url)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(reply))


def test_search_is_bounded_decimal_source_bound_and_deadline_unknown():
    row = {
        "purchase_number": "32616516922",
        "purchase_type": "purchaseNotice",
        "object_info": "Бумага\nА4",
        "max_price": 12.34,
        "currency_code": "RUB",
        "submission_close_at": "2026-11-03T08:00:00",
        "stage": 1,
    }
    with client_with([row]) as client:
        out = search_page(client, "private-key", "223", query="бумага", offset=0, now=NOW)
    assert out.items[0].price == "12.34"
    assert out.items[0].title == "Бумага А4"
    assert out.items[0].deadline_raw == "2026-11-03T08:00:00"
    assert out.items[0].deadline_status == out.items[0].submission_status == "UNKNOWN"
    assert out.items[0].source_sha256 == out.response_sha256 and out.observed_at == NOW
    assert out.coverage == "UNKNOWN"


def test_exact_number_uses_address_lookup_and_binds_identity():
    row = {
        "purchase_number": "32616516922",
        "purchase_type": "purchaseNotice",
        "object_info": "Бумага",
        "max_price": "12.34",
    }

    def reply(request):
        assert request.url.path.endswith("/purchases/32616516922")
        return httpx.Response(200, json=row)

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        result = search_page(client, "private-key", "223", query="32616516922", offset=0, now=NOW)
    assert result.items[0].number == "32616516922"
    assert not result.may_have_more


def test_detail_links_are_scoped_and_unsafe_urls_are_not_exposed():
    body = {
        "purchase_number": "32616516922",
        "docs": [
            {
                "source": {
                    "urlEIS": "https://lk.zakupki.gov.ru/223/purchase/private/notice",
                    "urlVSRZ": "https://corp.roseltorg.ru/#notice/822105",
                    "attachments": {
                        "document": [
                            {
                                "fileName": "Документ.pdf",
                                "url": "https://zakupki.gov.ru/223/filestore/public/1.0/download/fz223/file.html?uid=ABCD",
                            },
                            {"fileName": "bad", "url": "https://zakupki.gov.ru.evil.test/file"},
                            {"fileName": "local", "url": "http://127.0.0.1/a"},
                        ]
                    },
                }
            }
        ],
    }
    with client_with(body) as client:
        result = read_detail(client, "private-key", "223", "32616516922", now=NOW)
    assert result.eis_url is None
    assert result.platform_url == "https://corp.roseltorg.ru/#notice/822105"
    assert len(result.documents) == 1 and result.documents[0].name == "Документ.pdf"
    assert result.documents[0].source_sha256 == result.response_sha256
    assert not result.documents_truncated


def test_public_223_navigation_is_derived_only_for_explicit_public_flag():
    body = {
        "purchase_number": "32616516922",
        "docs": [{"source": {"hidePurchase": "false"}}],
    }
    with client_with(body) as client:
        result = read_detail(client, "private-key", "223", "32616516922", now=NOW)
    assert result.eis_url_origin == "NUMBER_DERIVED"
    assert result.eis_url.endswith("regNumber=32616516922")
    body["docs"].append({"source": {"hidePurchase": "true"}})
    with client_with(body) as client, pytest.raises(GosplanSearchError, match="NOTICE_RESTRICTED"):
        read_detail(client, "private-key", "223", "32616516922", now=NOW)


def test_wrong_detail_identity_and_source_errors_are_not_empty_results():
    with (
        client_with({"purchase_number": "32600000000", "docs": []}) as client,
        pytest.raises(GosplanSearchError, match="DETAIL_IDENTITY_MISMATCH"),
    ):
        read_detail(client, "private-key", "223", "32616516922", now=NOW)
    with (
        client_with({"error": "secret"}, status=429) as client,
        pytest.raises(GosplanSearchError, match="HTTP_429"),
    ):
        search_page(client, "private-key", "44", query="бумага", offset=0, now=NOW)


def test_invalid_values_and_token_reflection_fail_closed():
    row = {
        "purchase_number": "32616516922",
        "purchase_type": "purchaseNotice",
        "object_info": "private-key",
        "max_price": 1,
    }
    with (
        client_with([row]) as client,
        pytest.raises(GosplanSearchError, match="TOKEN_REFLECTION_REJECTED"),
    ):
        search_page(client, "private-key", "223", query="x", offset=0, now=NOW)
    with (
        client_with(
            json.loads(
                '[{"purchase_number":"32616516922","purchase_type":"purchaseNotice","object_info":"x","max_price":NaN}]'
            )
        ) as client,
        pytest.raises((GosplanSearchError, ValueError)),
    ):
        search_page(client, "private-key", "223", query="x", offset=0, now=NOW)


@pytest.mark.parametrize("law", ["44", "223"])
def test_search_provider_offset_limit_is_enforced_before_network(law):
    calls = []

    def reply(request):
        calls.append(request.url.params["skip"])
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        page = search_page(client, "private-key", law, query="бумага", offset=1000, now=NOW)
        with pytest.raises(GosplanSearchError, match="SCOPE_INVALID"):
            search_page(client, "private-key", law, query="бумага", offset=1001, now=NOW)
    assert page.coverage == "UNKNOWN" and calls == ["1000"]
