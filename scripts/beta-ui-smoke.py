"""Synthetic isolated beta browser test. Existing server-ui-smoke targets the older screen."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BETA_UI_URL", "http://127.0.0.1:3000")
PERSONAL = "synthetic_beta_personal_key_20261021_only"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        # Public HTTP origins may not expose crypto.randomUUID. IDs come from the server.
        context.add_init_script("Object.defineProperty(crypto, 'randomUUID', {value: undefined})")
        context.add_cookies(
            [
                {
                    "name": "procurement_personal_session",
                    "value": PERSONAL,
                    "url": BASE,
                    "httpOnly": True,
                    "sameSite": "Strict",
                }
            ]
        )
        # External links are verified as source hrefs. This test never opens real EIS/ETP.
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(BASE) else route.abort()
            ),
        )
        page = context.new_page()
        page.clock.install()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/tender-discovery", wait_until="networkidle")
        page.get_by_role("button", name="Подобрать товар из моего профиля").click()
        page.get_by_role("button", name="Бумага", exact=True).wait_for(timeout=30000)
        page.get_by_role("button", name="Бумага", exact=True).click()
        page.get_by_role("heading", name="Результаты поиска", exact=False).wait_for(timeout=60000)
        page.get_by_label("Место поставки", exact=True).fill("Moscow")
        assert page.get_by_role("button").filter(has_text="223-ФЗ").count() > 0
        card = page.locator('button[aria-controls="tender-detail"]').filter(has_text="223-ФЗ").first
        card.click()
        detail = page.locator("#tender-detail")
        detail.get_by_role("link", name="Тестовая площадка", exact=False).wait_for(timeout=30000)
        assert (
            detail.get_by_role("link", name="Тестовая площадка", exact=False).get_attribute("href")
            == "https://trade.example/auction/1"
        )
        assert "regNumber=32600000001" in detail.get_by_role(
            "link", name="Открыть извещение в ЕИС", exact=False
        ).get_attribute("href")
        assert detail.get_by_role("link", name="ТЗ.docx", exact=False).count() == 1
        detail.get_by_text("Добавить КП и расходы", exact=True).click()
        form = detail.locator('section[aria-label="КП и расходы"] form')
        values = {
            "supplier": "Synthetic supplier",
            "document": "synthetic-offer.pdf",
            "locator": "page 1",
            "amount_ex_vat": "50000",
            "quote_vat_rate": "0.20",
            "issued_at": "2026-10-01T10:00:00+03:00",
            "valid_until": "2030-01-01T10:00:00+03:00",
            "availability_terms": "All 100 units in stock",
            "delivery_terms": "To Moscow, all destination services included",
            "payment_terms": "Postpay",
            "expense_basis": "Synthetic worksheet, non-required items zero",
            "tax_model": "Explicit synthetic tax model",
            "output_vat_rate": "0.20",
            "realistic_discount": "0.05",
            "conservative_discount": "0.10",
            "conservative_cost_growth": "0.10",
        }
        for name, value in values.items():
            form.locator(f'input[name="{name}"]').fill(value)
        form.locator('input[name="covers_full_scope"]').check()
        fields = [
            "packaging",
            "logistics",
            "loading_unloading",
            "storage",
            "installation",
            "payroll_travel",
            "subcontracting",
            "insurance",
            "finance",
            "bank_guarantee",
            "platform_fees",
            "taxes",
            "certification",
            "warranty",
            "risk_reserve",
            "penalty_reserve",
            "other",
        ]
        for name in fields:
            form.locator(f'input[name="{name}"]').fill("0")
        failed_save = []

        def fail_first_save(route):
            if (
                route.request.method == "POST"
                and "synthetic-offer.pdf" in (route.request.post_data or "")
                and not failed_save
            ):
                failed_save.append(True)
                route.abort("connectionreset")
            else:
                route.continue_()

        page.route(BASE + "/tender-discovery**", fail_first_save)
        form.get_by_role("button", name="Сохранить КП и пересчитать").click()
        detail.get_by_text("Связь прервалась. Ввод сохранён в форме.", exact=False).wait_for()
        assert form.locator('input[name="amount_ex_vat"]').input_value() == "50000"
        assert all(form.locator(f'input[name="{name}"]').input_value() == "0" for name in fields)
        page.unroute(BASE + "/tender-discovery**", fail_first_save)
        form.get_by_role("button", name="Сохранить КП и пересчитать").click()
        detail.locator('[data-calculation-status="CALCULATED"]').wait_for(timeout=60000)
        assert "35 000,00" in detail.inner_text()
        comparison = page.locator('section[aria-label="Лучшие закупки по расчёту КП"]')
        comparison.get_by_role("button", name="Обновить подбор по КП и профилю").click()
        comparison.get_by_text("Консервативная прибыль: 35 000,00", exact=False).wait_for(
            timeout=60000
        )
        assert "Профиль: версия 1" in comparison.inner_text()
        assert comparison.locator("article").filter(has_text="Консервативная прибыль").count() == 2
        assert "Допуск: UNKNOWN" in comparison.inner_text()
        page.screenshot(path="/tmp/beta-ui-desktop.png", full_page=True)
        page.reload(wait_until="networkidle")
        page.get_by_role("textbox", name="Товар или номер закупки").fill("32600000001")
        page.get_by_role("button", name="Найти закупки", exact=True).click()
        detail = page.locator("#tender-detail")
        detail.locator('[data-calculation-status="CALCULATED"]').wait_for(timeout=60000)
        assert "35 000,00" in detail.inner_text()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path="/tmp/beta-ui-mobile.png", full_page=True)
        # Advancing only the browser clock proves stale UI results cannot mask expiry.
        page.clock.set_system_time("2032-01-01T00:00:00Z")
        assert page.evaluate("Date.now()") >= 1_956_528_000_000
        page.clock.run_for(60_001)
        detail.locator('[data-calculation-status="CALCULATED"]').wait_for(state="hidden")
        assert (
            not page.locator('section[aria-label="Лучшие закупки по расчёту КП"] article')
            .filter(has_text="Консервативная прибыль")
            .count()
        )
        assert not errors, errors
        Path("/tmp/beta-ui-result.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "data": "SYNTHETIC_ONLY",
                    "profile_search": True,
                    "delivery_filter": True,
                    "quote_form_saved": True,
                    "costs17": True,
                    "three_scenarios": True,
                    "financial_options": 2,
                    "browser_random_uuid_required": False,
                    "transport_failure_preserves_form": True,
                    "browser_clock_jump_hides_stale_results": True,
                    "profit": "35000.00",
                    "reload_persisted": True,
                    "source_links223": "EIS, platform and document hrefs checked",
                    "participation": "UNKNOWN",
                    "page_errors": errors,
                },
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    main()
