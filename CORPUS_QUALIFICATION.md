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
## RacePak raw DDF qualification — v0.38

Raw RacePak `.DDF` support was qualified read-only against a same-recording NHRA PRO III DDF/RPK pair. The DDF descriptor table matched all 83 `_CONNECT4_COMMAND` identifiers embedded in the DataLink RPK configuration; 68 descriptors were marked as recorded and the DDF payload contained exactly 410 one-second frames at their native aggregate rate.

The decoded DDF channels were compared against the first 410 seconds of DataLink's RPK engineering values. All 68 recorded channels matched. The worst normalized RMS error was below `2.8e-7`, and the largest absolute difference was below `3.7e-5` engineering units (float32 reconstruction noise). This validates the qualified DDF rules used by `runlab.racepak_ddf`: signed int16 fixed-point samples, one-second channel blocks in descriptor order, and descriptor flags `00/FF/FE/FD/FC` corresponding to decimal exponents `0/1/2/3/4`.

A separate V300SD DDF + RCG sample was also structurally decoded and bound by `_CONNECT4_COMMAND` without channel-id or sample-rate mismatches. The raw corpus remains external/read-only and is not included in the repository.

