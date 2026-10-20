# Immutable EIS release code regression fixtures

These exact source members preserve owned historical release implementations for synthetic PostgreSQL equivalence tests. They let tests compare a current optimized reader/hold predicate with the prior released behavior captured before the next rollout.

The files are test-only regression oracles, not runtime modules, production code, private data, or independently authored reference implementations. Their value is that they preserve the exact released implementation bytes and known historical behavior; they do not independently establish that the behavior is correct.

`manifest.json` records the historical release identity, source archive/member, byte count, SHA-256, timestamp provenance, and consuming test environment binding. Tests must verify the SHA before import. Never format, normalize line endings, or auto-fix these files. A missing fixture or hash mismatch is a failed equivalence gate.

These fixtures are consumed only by the disposable S206/S208/S209 PostgreSQL regression tests using synthetic tenant data. Do not use them in application imports or runtime packaging.
