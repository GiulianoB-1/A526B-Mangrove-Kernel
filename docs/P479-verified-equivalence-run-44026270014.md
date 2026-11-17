# P479 strict equivalence passed, but Image bytes differ (NO FLASH)

**Source of truth:** GitHub Actions run [44026270014](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/44026270014), commit `5e5db938a24068ae5a804b003e5cbe16d7f31438` on `agent/p479-wx-full-provenance-proof`. Original baseline P479 run `43638159300`, commit `e2e9f3fad600489deb8fa0816245a87cef6b9b95`.

The original fail-closed `scripts/p479_equivalence_gate.py` returned `status: PASS`, `errors: []` with **all required checks passing**:

| Check | Result |
|---|---|
| Final `.config` compared byte-for-byte with original P479 | PASS |
| `System.map`, all symbols and addresses, byte-for-byte | PASS |
| All allocated ELF section sizes, including `.text`, `.rodata`, `.data`, `.bss` | PASS |
| Required H4, charging shadow, Q6, CDC TLMM wake, GPIO debugfs Image markers | PASS |
| Native `p479_h4_tick` linked | PASS |
| SHA-pinned reference `.config` and `System.map` inputs | PASS |
| SHA-pinned original embedded IKHEADERS compared against 7,932 generated header files | PASS, only documented generated provenance differences |

**Evidence artifact:** [P479-WX-EQUIVALENCE-PROOF-44026270014](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/44026270014/artifacts/14304912899) and [P479-IKHEADERS-SEMANTIC-PROOF](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/44026270014/artifacts/14304439132).

### Cryptographic identities

* Original P479 `.config` and verified rebuilt `.config`: `62e75568506c051408588d2eb77fa94fb8ada762fcff997739a5b595a742d50b`.
* Original P479 `System.map` and verified rebuilt `System.map`: `26ae9bda166d764bf695d6c51b8799632bc6f1ea276747a9f8fd1d0caf6d3a3e`.
* Original P479 `Image`: `c1e29a64f611f402cdc8e5db1f42fea5b6ec9f48b19df60d5b9aa6da2d8585ae`.
* Rebuilt `Image`: `2b094dc42cd6079ab5dd2092a69a68b2ae6a3676ffe8da7215db84f78a8c1070` (66,687,488 bytes).

**Important qualification:** Original and rebuilt Image raw hashes differ. The unchanged equivalence gate reports `image_hash_identical: false` as a *non-gating* forensic field. The PASS establishes config, symbol-address, allocated-ELF-section-size and compiled-marker equivalence, **not full byte-for-byte identity of the Image or ELF file**. Do not represent this as a reproducible bit-identical kernel.

### Provenance and blocked publication

* Source: permanent `phase446wx-source-backup` release, source archive `12271681215`, SHA-pinned.
* Original P479 binaries: `p479-equivalence-reference` release, reference ZIP `14131467025`, SHA-pinned.
* The verified source archive generated, passed all local SHA256 validations, and reached release upload in run `44026270014`. The release API returned **HTTP 403 `Resource not accessible by integration`**. No `p479-verified-source-baseline` release was created by that run.
* Recovery branch `agent/p479-wx-archive-fallback-no-flash` adds an always-upload SHA256-checked source archive Actions artifact. Its eventual artifact is **temporary**, not a permanent release. Publication still requires an authorized release-writing token.

**NO FLASH.** P480 changes, hardware authorization, and source-repository cutover remain separately gated and are not implied by this proof. Original legacy releases, artifacts and branches must not be deleted.
