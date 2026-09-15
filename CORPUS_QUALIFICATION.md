# Telemetry Corpus Qualification

Format support must be proven against real racing data, not only generated examples.

## Qualification goal

For each supported logger/vendor family, maintain a representative corpus containing ordinary qualifying/elimination runs plus difficult cases such as partial runs, incidents, unusual channel/sample-rate configurations, corrupt/truncated files and format-version variation.

The production source of permanent Run Assets will be NHRA Tech Services. Corpus qualification is a decoder-development activity; it is not a separate repository or runtime connection.

## Qualification record

`runlab.qualification` records, without modifying the raw file:

- path/filename for the local qualification sample;
- SHA-256;
- pass/fail/error;
- detected vendor/decoder;
- plotability;
- row/channel counts;
- native/canonical channel counts;
- duration and maximum native rate;
- warnings/errors.

Use:

```bash
python -m runlab.cli qualify <files-or-folders> --recursive --json-out qualification.json --csv-out qualification.csv
```

A decoder is not considered broadly production-qualified merely because a generated demo passes. Real-file coverage should be expanded as representative server Assets become available through the Tech Services workflow.

## Raw-data rule

Qualification samples are read-only. Decoder tests must never modify source logger files. Hash-identical copies need only be decoded once for format behavior, though separate test cases may still be useful for cache/provenance tests.
