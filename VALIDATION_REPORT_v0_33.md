# NHRA Tech Data v0.33 — Validation Report

## Release scope

v0.33 is a reliability/usability milestone centered on the basic telemetry workflow: open real native files, get plausible engineering channels, put the waveform in the middle of the screen, move a cursor over it and read values without fighting the interface.

The release adds modern RacePak/DataLink `CAN_Device` support, hardens MoTeC M1 `.ld` parsing, improves canonical channel selection using units and measurement semantics, and significantly reduces the default desktop workspace.

## Real native-file qualification

The following files were pulled read-only from the NHRA race-data archive and exercised directly through `load_telemetry()`. The source binaries are **not** included in this distribution; only hashes and qualification results are retained.

| File | SHA-256 | Result |
| --- | --- | --- |
| `S1_#2626_20260905_151322.ld` | `a47e596d041526e75a805af2471c1b468c4ffc9d1dcb9e8bafccb7a24a91a434` | **PASS** — 181 linked records, 180 decodable native channels, 36,851 common-frame rows. One unsupported engine-synchronization diagnostic channel is explicitly skipped/warned instead of aborting the run. |
| `BeSea080219Q1.rpk` | `4e8b252972651f4f8dfc3cf656eadadedf00927d5ef62438aa51a821d3fb3137` | **PASS (structural)** — modern `CAN_Device`, 7 recorded channels, 10,200 rows. This older device family imports, but historical device-specific engineering transforms remain a qualification item. |
| `NHGai030726Q4.rpk` | `346f690cba5641f22f902bc2fad66dcdd5c0387171d79cbb5beb83b6ca73b7fa` | **PASS** — modern `CAN_Device`, 43 recorded channels, 38,400 rows. |
| `GSSea072426Q2.rpk` | `a5b37cc9144d7f812180ac7e596c2dfd3eb205429fc42466ecfb2d51433a0c23` | **PASS** — modern `CAN_Device`, 57 recorded channels, 24,750 rows. |
| `PRBri061326Q4.rpk` | `f5806c0a1796cb3ea196dcbbba644a2d2057afa436eb1ec483b7bd82c412a5fd` | **PASS** — modern `CAN_Device`, 62 recorded channels, 106,000 rows. |

The `.ld` above is the exact file name that reproduced the reported v0.32 MoTeC failure. Its canonical selection now chooses `Engine.Speed` for engine RPM and `Rear Wheel Speed` for vehicle/wheel speed rather than selecting a similarly named state/limit channel.

The exact RacePak filename visible in the reported screenshot, `NHSea061326Q4.rpk`, was not present in the connected archive search performed for this release, so this report **does not claim byte-for-byte qualification of that exact file**. The new parser was instead qualified against multiple real current `CAN_Device` files, including three 2026 recordings.

Detailed machine-readable results are stored in `validation/REAL_NATIVE_LOG_VALIDATION_v0_33.json`.

## Native engineering calibration sanity checks

Current 2026 RacePak qualification showed the expected two-stage linear calibration behavior rather than raw logger counts. Examples observed during development include a shock-position channel resolving to approximately 5.014–6.600 in, a front-wheel speed channel reaching approximately 306 mph, and a tire-temperature channel reaching approximately 382 °F in the corresponding real recordings.

These checks are engineering-plausibility evidence, not a blanket certification of every historical RacePak sensor/device class. Unknown or older combinations should continue to be qualified against known DataLink output before being used for quantitative conclusions.

## Automated regression

Final source-tree regression command:

```bash
python -m pytest -q
```

Result: **175 passed**.

Focused importer regression includes the new modern `CAN_Device` synthetic fixture and unit/measurement-aware channel-mapping case.

## Native import / plot pipeline self-test

```bash
python -m runlab.cli selftest
```

Result:

- RacePak native demo → **PASS**;
- MoTeC native demo → **PASS**;
- MaxxECU native demo → **PASS**;
- total → **3/3 PASS**.

The bundled synthetic MoTeC fixture continues to exercise an advisory header-count mismatch intentionally; the linked metadata count remains authoritative.

## Source compilation

```bash
python -m compileall -q .
```

Result: **PASS**.

This verifies Python syntax/import compilation across the packaged source tree. It is not a substitute for launching the Qt application.

## Desktop/UI validation limitation

PySide6/pyqtgraph are not installed in this build container, so the revised Qt desktop could not be launched and manipulated interactively here. The desktop source compiles, and the non-GUI parser/model layers are regression-tested, but the new hover cursor, central-waveform behavior and dock geometry must still receive a real Windows Qt smoke test.

This limitation is important for v0.33 because the UI changes are intentionally substantial. Any Qt-runtime issue found during the first Windows trial should be treated as a release-blocking regression, not papered over by the headless test count.

## Release-consistency audit

The release-tree audit completes with **0 errors**. With no external provenance environment variables supplied, it reports the expected warnings for upstream commit references that cannot be independently re-verified inside this isolated build environment. The pinned Tech Services provenance stored in the product manifest remains unchanged from v0.32; this release does not modify that API boundary.

Current portable/persistent format versions remain:

- catalog schema: **7**;
- workbook: **7**;
- analysis library: **2**;
- simulation-study package: **2**;
- fit-study package: **5**;
- Tech Services sync contract: **4**.

## Release conclusion

v0.33 is suitable as the next **development trial build** for native logger import and waveform usability. The MoTeC failure was reproduced with the real source file and corrected. Modern RacePak `CAN_Device` support is now grounded in real NHRA files rather than only synthetic/legacy fixtures. The highest-priority next validation is a Windows GUI smoke test plus the exact `NHSea061326Q4.rpk` binary if that file can be supplied or located.

## Exact-ZIP clean-room verification

The release archive is built from the cleaned source tree with test/cache bytecode excluded. The exact packaged archive is then extracted into a fresh directory and exercised independently.

- archive members: **189 files**;
- `__pycache__`, `.pytest_cache`, `.pyc`, `.pyo` members: **0**;
- ZIP CRC/integrity check: **PASS**;
- extracted `python -m pytest -q`: **175 passed**;
- extracted native pipeline self-test: **3/3 PASS**;
- extracted release audit: **0 errors / 2 explicit upstream-provenance warnings**.
