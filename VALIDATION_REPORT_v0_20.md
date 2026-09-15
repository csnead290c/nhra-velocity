# NHRA Tech Data v0.20 Validation Report

## Release scope

v0.20 adds synchronized AnalysisCase review on top of the v0.19 Asset→Run→Case timeline. It does not change permanent Run/Asset ownership, add file matching, or introduce a new evidence repository.

## Automated regression

- `python -m pytest -q`: **104/104 passed**.
- `python -m compileall -q .`: **PASS**.
- Catalog schema remains **v7**.
- Fresh schema contains `analysis_cases` and `analysis_case_markers` and does **not** create the retired `remote_assets` or `reconciliation_reviews` tables.

## Synchronized-review coverage

Automated tests verify:

- Case cursor → Run time → Asset time mapping.
- video duration/range and frame-index calculation from optional metadata;
- review extent including pre-launch media and case markers;
- frame stepping and previous/next marker navigation;
- interval-marker activation;
- nearest-sample numeric/IDR-compatible readout;
- remote Tech Services media remains non-viewable until its local cache exists.

## Native import / plot pipeline

Bundled native self-test: **3/3 PASS**.

- RacePak native demo: PASS.
- MoTeC native demo: PASS. The known qualification warning remains: header declares 99 channels while the linked list contains 6; linked-list count is used.
- MaxxECU native demo: PASS.

Corpus qualification: **10/10 PASS**, including the three native logger examples and seven generic/reference CSV files.

## Official NHRA run-import regression

### 2026 U.S. Nationals export

- source rows seen: **134**
- canonical rows imported: **123**
- duplicate partial rows merged: **6**
- canonical Runs after import: **123**
- identical re-import new Runs: **0**

### 2026 Indianapolis PSM test export

- source rows seen: **25**
- rows imported: **25**
- duplicate rows merged: **0**
- canonical Runs: **25**
- identical re-import new Runs: **0**

## Desktop / Qt limitation in this container

The source is syntax/bytecode compiled, but this validation container does not have PySide6 installed, so the Qt desktop—including Qt Multimedia video/audio rendering—cannot be interactively launched here. The media/review mapping logic is covered headlessly by the automated suite. On a normal desktop installation, `requirements-desktop.txt` installs PySide6 and pyqtgraph.

## Clean-room package

The release ZIP was extracted into a new clean directory and `python -m pytest -q` was rerun from the extracted tree: **104/104 passed**.
