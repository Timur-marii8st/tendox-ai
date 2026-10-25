import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { changedFacts, factLabel, profileFields, validSnapshot, type ProfileSnapshot } from "../src/lib/company-profile";

function partial(): ProfileSnapshot {
  const facts = Object.fromEntries(profileFields.map(field => [field.path, { knowledge: "UNKNOWN", value: null, reason: "NOT_PROVIDED", sources: [] }]));
  return { schema_version: "company-profile-snapshot-v1", company_id: "synthetic", version: 1, parent_version: null, created_at: "2026-10-14T10:00:00Z", created_by: "operator", effective_at: "2026-10-14T10:00:00Z", currency: "RUB", amount_basis: "EX_VAT", facts, snapshot_sha256: "a".repeat(64), audit_event_id: "synthetic-audit", critical_settings_status: "OWNER_AUTHORIZATION_UNAVAILABLE" } as ProfileSnapshot;
}
function source(path: string) { return { company_id: "synthetic", kind: "manual_declaration" as const, source_sha256: "b".repeat(64), recorded_at: "2026-10-14T10:00:00Z", recorded_by: "operator", provenance: { document_id: "synthetic-command", locator: path, extractor: "manual" as const, confidence: 1 } }; }

test("display keeps unknown, zero, false and confirmed empty list distinct", () => {
  assert.equal(factLabel(), "Не указано");
  assert.equal(factLabel({ knowledge: "KNOWN", value: "0", reason: null }), "0");
  assert.equal(factLabel({ knowledge: "KNOWN", value: false, reason: null }), "Нет");
  assert.equal(factLabel({ knowledge: "KNOWN", value: [], reason: null }), "Подтверждённый пустой список");
});

test("wire refuses known values without evidence and foreign evidence", () => {
  const s = partial();
  assert.equal(validSnapshot(s), true);
  s.facts["identity.name"] = { knowledge: "KNOWN", value: "Пример", reason: null, sources: [] };
  assert.equal(validSnapshot(s), false);
  s.facts["identity.name"].sources = [source("identity.name")];
  assert.equal(validSnapshot(s), true);
  s.facts["identity.name"].sources[0].company_id = "foreign";
  assert.equal(validSnapshot(s), false);
});

test("wire refuses numeric money and wrong boolean/list types", () => {
  const s = partial();
  for (const [path, value] of [["finance.min_contract_amount", 0], ["geography.all_russia", "false"], ["supplied_goods", ""]] as const) {
    const candidate = structuredClone(s);
    candidate.facts[path] = { knowledge: "KNOWN", value, reason: null, sources: [source(path)] } as unknown as typeof candidate.facts[string];
    assert.equal(validSnapshot(candidate), false);
  }
});

test("diff blocks policy writes and does not mutate saved input", () => {
  const s = partial();
  const draft = { "identity.name": { knowledge: "KNOWN" as const, value: "Новое", reason: null }, "finance.min_contract_amount": { knowledge: "KNOWN" as const, value: "0", reason: null } };
  assert.deepEqual(Object.keys(changedFacts(s, draft, ["finance.min_contract_amount"])), ["identity.name"]);
  assert.equal(s.facts["identity.name"].knowledge, "UNKNOWN");
});

function ownerAction() {
  const saved: Array<{ confirmation_sha256: string; changes: Record<string, { value: string }> }> = [];
  const source = readFileSync("src/app/company-profile/actions.ts", "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const exported: { saveProfileAction?: (state: object, form: FormData) => Promise<{ error?: string } | undefined> } = {};
  runInNewContext(compiled.outputText, {
    exports: exported,
    require: (name: string) => {
      if (name === "node:crypto") return { createHash };
      if (name === "next/headers") return { cookies: async () => ({}) };
      if (name === "next/navigation") return { redirect: () => undefined };
      if (name === "next/cache") return { revalidatePath: () => undefined };
      if (name === "@/lib/company-profile") return { profileFields };
      assert.equal(name, "@/lib/company-profile-api");
      return {
        ProfileApiError: class extends Error {},
        readCapabilities: async () => ({ company_id: "tenant-review", actor_id: "owner-review", critical_settings_editable: true }),
        saveProfile: async (command: typeof saved[number]) => { saved.push(command); return { version: 1 }; },
      };
    },
  });
  return { saved, save: exported.saveProfileAction! };
}

function decimalForm(value: string, path = "finance.min_contract_amount") {
  const form = new FormData();
  form.set("command-key", "12345678-1234-1234-1234-123456789abc");
  form.set("confirmed", "yes");
  form.set("command", JSON.stringify({ schema_version: "company-profile-save-command-v1", expected_version: 0, changes: { [path]: { knowledge: "KNOWN", value, reason: null } } }));
  return form;
}

function expectedConfirmation(canonical: string, path: string) {
  const hash = (value: object) => createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");
  const commandSha = hash({ changes: { [path]: { knowledge: "KNOWN", reason: null, value: canonical } }, expected_version: 0, schema_version: "company-profile-save-command-v1" });
  return hash({ actor_id: "owner-review", command_sha256: commandSha, company_id: "tenant-review" });
}

test("owner action confirms normalized exact decimal values accepted by the domain", async () => {
  const values = [
    [".15", "0.15", "finance.min_margin"],
    ["1e-1", "0.1", "finance.min_margin"],
    ["+0000.1500", "0.15", "finance.min_margin"],
    ["1e0", "1", "finance.min_margin"],
    ["0.9999999999999999999999999999", "0.9999999999999999999999999999", "finance.price_floor_margin"],
    ["-.0e+4", "0", "finance.min_contract_amount"],
    ["-0.0000", "0", "finance.min_contract_amount"],
    ["15.", "15", "finance.min_contract_amount"],
    ["1_000.0_0", "1000", "finance.min_contract_amount"],
    ["9007199254740993.01", "9007199254740993.01", "finance.min_contract_amount"],
    ["1234567890123456789012345678.5", "1234567890123456789012345678", "finance.min_contract_amount"],
    ["1234567890123456789012345679.5", "1234567890123456789012345680", "finance.min_contract_amount"],
    ["9.9999999999999999999999999995", "10", "finance.min_contract_amount"],
  ];
  for (const [value, canonical, path] of values) {
    const { saved, save } = ownerAction();
    assert.equal(await save({}, decimalForm(value, path)), undefined, value);
    assert.equal(saved.length, 1, value);
    assert.equal(saved[0].changes[path].value, value, "original decimal text is sent to domain validation");
    assert.equal(saved[0].confirmation_sha256, expectedConfirmation(canonical, path), value);
    // Fixed hashes from ProfileSaveCommand.confirmation_digest with these exact identities.
    if (value === ".15") assert.equal(saved[0].confirmation_sha256, "131e71cc05563a1adab55a6e24310f2bdd2fed080d73287ed00b33bc170f9a10");
    if (value === "1e-1") assert.equal(saved[0].confirmation_sha256, "8a18acfff65a11bde76afe3707a54bad302033a5b71db67b550e22d3daee074a");
  }
});

test("owner action rejects unsupported numeric syntax visibly before saving", async () => {
  for (const value of ["1e1001", "1e-1001", "١٢٣", "Infinity", "NaN"]) {
    const { saved, save } = ownerAction();
    const result = await save({}, decimalForm(value));
    assert.match(result?.error ?? "", /десятичное число/);
    assert.equal(saved.length, 0);
  }
});
