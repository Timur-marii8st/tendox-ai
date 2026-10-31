/* eslint-disable @typescript-eslint/no-explicit-any -- Runtime hook/JSX harness models dynamically loaded components. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

type Deferred = { promise: Promise<any>; resolve: (value: any) => void };
function deferred(): Deferred { let resolve!: (value: any) => void; const promise = new Promise<any>(r => { resolve = r; }); return { promise, resolve }; }
function harness() {
  const slots: any[] = []; let pos = 0; let searchTask: Promise<any> = Promise.resolve();
  const nav: Deferred[] = []; const pages: Array<{ law: string; wait: Deferred }> = [];
  const row = (law: string, number: string) => ({ id: `${law}:${number}:1:${"a".repeat(64)}`, law, purchaseNumber: number, version: 1, xmlSha256: "a".repeat(64), title: number, priceValue: "1", statusLabel: "UNKNOWN" });
  const a = row("44", "0".repeat(18) + "1"), b = row("223", "0".repeat(10) + "1");
  const initial = (query: string) => ({ query, law: "all", result44: { rows: [a], matched: [a], matched_count: 1, next_cursor: "c44" }, result223: { rows: [b], matched: [b], matched_count: 1, next_cursor: "c223" } });
  const react = {
    useState(initialValue: any) { const i = pos++; if (!(i in slots)) slots[i] = initialValue; return [slots[i], (value: any) => { slots[i] = typeof value === "function" ? value(slots[i]) : value; }]; },
    useRef(value: any) { const i = pos++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useEffect() {}, useTransition() { return [false, (fn: () => Promise<any>) => { searchTask = fn(); }]; },
  };
  const jsx = (type: any, props: any) => ({ type, props: props ?? {} });
  const ws = {
    rowsFromResult(value: any) { return [...(value.result44?.rows ?? []), ...(value.result223?.rows ?? [])].map((r: any) => ({ ...r, deliveryRegions: value.navigation?.[r.id]?.delivery_regions })); },
    sortTenderRows: (rows: any[]) => rows,
    filterDeliveryRegion: (rows: any[], region: string, include: boolean) => !region ? rows : rows.filter(r => r.deliveryRegions?.some((v: any) => v.value === region) || (include && !r.deliveryRegions)),
    formatTenderDeadline: () => "UNKNOWN",
  };
  const actions = {
    searchWorkspace: async (query: string) => initial(query),
    searchGlobalWorkspace: async (query: string) => initial(query),
    enrichWorkspaceNavigation: () => { const d = deferred(); nav.push(d); return d.promise; },
    loadWorkspacePage: (_query: string, law: string) => { const wait = deferred(); pages.push({ law, wait }); return wait.promise; },
  };
  const source = readFileSync("src/app/tender-discovery/workspace.tsx", "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } });
  const exported: any = {};
  runInNewContext(compiled.outputText, { exports: exported, window: { matchMedia: () => ({ matches: false }), setTimeout, clearTimeout }, Date, Set, Math,
    require(name: string) {
      if (name === "react") return react;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
      if (name === "@/lib/tender-workspace") return ws;
      if (name === "./workspace-actions") return actions;
      if (name === "./paged-results") return { mergeSearchPage: (x: any, y: any) => ({ ...y, rows: [...x.rows, ...y.rows] }) };
      if (name.endsWith(".css")) return { __esModule: true, default: {} };
      return new Proxy({}, { get: () => () => null });
    },
  });
  function render() { pos = 0; return exported.TenderWorkspace({}); }
  function all(node: any): any[] { if (Array.isArray(node)) return node.flatMap(all); if (!node || typeof node !== "object") return []; return [node, ...all(node.props?.children)]; }
  function text(node: any): string { if (Array.isArray(node)) return node.map(text).join(" "); if (node == null || typeof node === "boolean") return ""; if (typeof node !== "object") return String(node); return text(node.props?.children); }
  function get(node: any, predicate: (n: any) => boolean) { const found = all(node).find(predicate); assert.ok(found); return found; }
  async function search(query: string) { let tree = render(); get(tree, n => n.props?.id === "tender-product").props.onChange({ target: { value: query } }); tree = render(); get(tree, n => n.type === "form").props.onSubmit({ preventDefault() {} }); await searchTask; return render(); }
  return { render, all, text, get, search, nav, pages, row, initial };
}
const flush = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };

test("workspace shows unfiltered rows while region evidence loads and filters only after completion", async t => {
  const h = harness(); let tree = h.render(); h.get(tree, n => n.props?.id === "tender-delivery").props.onChange({ target: { value: "Москва" } });
  const started = performance.now(); tree = await h.search("бумага"); t.diagnostic(`synthetic search to visible rows: ${(performance.now() - started).toFixed(1)} ms while navigation is unresolved`); assert.match(h.text(tree), /Пока показаны все результаты без фильтра региона/); assert.doesNotMatch(h.text(tree), /По вашему запросу совпадений нет/);
  assert.equal(h.all(tree).filter(n => n.type === "button" && n.props?.["aria-controls"] === "tender-detail").length, 2);
  h.nav[0].resolve({ navigation: {}, failed: 0 }); await flush(); tree = h.render();
  assert.match(h.text(tree), /По вашему запросу совпадений нет/);
});

test("workspace serializes concurrent law pages and old navigation cannot overwrite a new search", async () => {
  const h = harness(); await h.search("первый"); h.nav[0].resolve({ navigation: {}, failed: 1 }); await flush(); let tree = h.render(); assert.match(h.text(tree), /Не удалось уточнить/);
  const buttons = h.all(tree).filter(n => n.type === "button" && h.text(n).includes("Загрузить ещё")); assert.equal(buttons.length, 2);
  buttons[0].props.onClick(); buttons[1].props.onClick(); assert.equal(h.pages.length, 1); assert.equal(h.pages[0].law, "44");
  const extra = h.row("44", "0".repeat(18) + "2"); h.pages[0].wait.resolve({ query: "первый", law: "44", result44: { rows: [extra], matched: [extra], matched_count: 2, next_cursor: null } }); await flush();
  tree = h.render(); assert.match(h.text(tree), /Не удалось уточнить/); assert.equal(h.nav.length, 2);
  await h.search("второй"); assert.equal(h.nav.length, 3); h.nav[1].resolve({ navigation: { stale: {} }, failed: 1 }); await flush();
  tree = h.render(); assert.match(h.text(tree), /второй/); assert.doesNotMatch(h.text(tree), /Не удалось уточнить/); assert.match(h.text(tree), /Уточняем места поставки/);
  h.nav[2].resolve({ navigation: {}, failed: 0 }); await flush(); assert.doesNotMatch(h.text(h.render()), /Уточняем места поставки/);
});
