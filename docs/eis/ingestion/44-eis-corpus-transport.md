# Transport lifecycle for a bounded EIS corpus pass

Date: 2026-10-03. Scope: the existing sequential 44-FZ corpus runner and its
CLI entry point. No source intake, production writes or scheduler changes were
made as part of this slice.

## Previous lifecycle

`run_corpus()` called `sync_eis_window_via_browser()` for every selected window.
That compatibility helper opens and closes `eis_browser_transport()` around one
window, so a bounded pass with several windows recreated the browser and loaded
the official WSDL for every window. Source request order remained sequential,
but browser startup dominated the pass.

## Contract

`run_corpus()` now accepts an optional `EisFeedTransport`. Existing callers that
omit it retain the prior per-window compatibility path. When a caller supplies a
transport, every window goes through `sync_eis_window()` with that exact object.

The CLI creates one `eis_browser_transport()` context for one bounded `run`
pass, matching its existing `fresh` pass. The yielded `_BrowserSession` is lazy:
entering the context allocates no browser and performs no WSDL or source request.
The first `post` or `download` initializes it. Context exit closes initialized
browser resources on success and failure.

The change preserves:

- priority marker check before the resource gate and before an atomic window;
- database and disk resource gates;
- `max_windows`, sequential processing and two-second inter-window spacing;
- exact window sync, durable attempt records and fail-fast transport/service
  reasons;
- source quota and concurrency behavior: one pass still has one sequential
  source stream and does not add requests.

## Verification evidence

Focused synthetic tests pass the same transport identity through two windows,
verify a transport failure stops before window two, verify priority and resource
gates make zero source calls, and verify the CLI context closes when the runner
raises. Coverage remains `UNKNOWN`; these tests make no claim about full EIS
coverage or live throughput.
