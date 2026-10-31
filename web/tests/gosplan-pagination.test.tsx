import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { GosplanPagination } from "../src/app/tender-discovery/gosplan-pagination";

test("a full page can reach offset 1000 but never offers a request beyond it", () => {
  for (const law of ["44", "223"] as const) {
    let calls = 0;
    const props = { law, count: 20, mayHaveMore: true, disabled: false, className: "", onNext: () => { calls++; } };
    const before = GosplanPagination({ ...props, offset: 980 });
    assert.ok(before && before.type === "button");
    (before.props as { onClick: () => void }).onClick();
    assert.equal(calls, 1);
    const atLimit = renderToStaticMarkup(createElement(GosplanPagination, { ...props, offset: 1000 }));
    assert.match(atLimit, /Достигнут предел просмотра/);
    assert.match(atLimit, /Полнота выдачи не подтверждена/);
    assert.doesNotMatch(atLimit, /<button/);
    assert.equal(calls, 1);
    assert.equal(GosplanPagination({ ...props, offset: 1000, mayHaveMore: false }), null);
  }
});
