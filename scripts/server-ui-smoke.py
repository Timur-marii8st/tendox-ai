"""Exercise the server-side Next.js search action against the migrated index."""

import re

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto("http://web:3000/tender-discovery", wait_until="domcontentloaded")
            section = page.locator("section").filter(
                has=page.get_by_role("heading", name="Поиск по сохранённым XML ЕИС")
            )
            section.get_by_role("textbox", name="Что вы поставляете").fill("бумага")
            section.get_by_role("button", name="Искать в индексе").click()
            section.get_by_role("status").get_by_text("Охват всей ЕИС: UNKNOWN.").wait_for(
                timeout=60_000
            )
            status = section.get_by_role("status").inner_text()
            match = re.search(r"актуальных карточек в индексе: (\d+)", status)
            assert match is not None and int(match.group(1)) >= 1462
            assert "Свежесть всей ЕИС: UNKNOWN" in status
            assert "Подробно сравнено кандидатов:" in status
            assert section.locator("article").count() > 0
            quotation = section.locator("article").filter(
                has_text="Электронный запрос котировок, 44-ФЗ"
            )
            assert quotation.count() > 0
            assert "/zk20/" in quotation.first.get_by_role(
                "link", name="Официальная карточка ЕИС"
            ).get_attribute("href")
            # GET is a cached-state read; it must not initiate external downloads.
            first = section.locator("article").first
            first.get_by_role("button", name="Проверить сохранённый разбор").click()
            first.get_by_text("Полнота и review: UNKNOWN.", exact=False).wait_for(timeout=30_000)
            assert first.get_by_role("button", name="Скачать и разобрать документы").count() == 1
            section.get_by_role("button", name="Подготовить документы первых 3 кандидатов").click()
            section.get_by_text("В очереди:", exact=False).wait_for(timeout=30_000)
            cached = section.locator("article").filter(has_text="0148300000626001036")
            if cached.count():
                cached.get_by_role("button", name="Проверить сохранённый разбор").click()
                cached.get_by_text("Получено 5 из 5", exact=False).wait_for(timeout=30_000)
                cached.get_by_role("button", name="Показать сохранённые условия").nth(1).click()
                cached.get_by_text(
                    "Фрагменты для проверки; роль документа и требования ещё не утверждены."
                ).wait_for(timeout=30_000)
                assert cached.locator("blockquote").count() > 0
                print("UI_CACHE_OK snippets=", cached.locator("blockquote").count())
                cached.get_by_role("button", name="Связать с карточкой и расчётом").click()
                cached.get_by_text("Связка с XML №0148300000626001036", exact=False).wait_for(
                    timeout=30_000
                )
                assert "Требования не утверждены" in cached.inner_text()
                assert "Нет действующего КП поставщика" in cached.inner_text()
                assert "НМЦК не является прибылью" in cached.inner_text()
                print("UI_EVIDENCE_BRIDGE_OK")
                cached.get_by_role("textbox", name="Товар, ₽ без НДС").fill("140000.00")
                cached.get_by_role("textbox", name="Прочие расходы, ₽ без НДС").fill("10000.00")
                cached.get_by_role("textbox", name="Ставка НДС, доля").fill("0.20")
                cached.get_by_role("textbox", name="Источник оценки / допущения").fill(
                    "Синтетический smoke-тест без КП"
                )
                cached.get_by_role("checkbox").check()
                cached.get_by_role("button", name="Посчитать три предварительных сценария").click()
                cached.get_by_text("Статус оценки: ESTIMATE", exact=False).wait_for(timeout=30_000)
                assert "base:" in cached.inner_text()
                assert "realistic:" in cached.inner_text()
                assert "conservative:" in cached.inner_text()
                assert "допуск и КП: UNKNOWN" in cached.inner_text()
                print("UI_PRELIMINARY_SCENARIOS_OK")
            print("UI_SEARCH_OK articles=", section.locator("article").count())
        finally:
            browser.close()


if __name__ == "__main__":
    main()
