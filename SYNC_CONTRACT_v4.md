# NHRA Tech Services synchronization contract v4

This is a **development contract** used to exercise the desktop mirror until the real `nhratechservices.com` backend/API is available for inspection. It does not claim that these will be the production HTTP routes or exact wire field names.

## Principle

The server owns Run→Asset relationships. Assets are nested under the Run they already belong to. The desktop performs no filename/path matching.

## Example snapshot

```json
{
  "contract_version": 4,
  "cursor": "catalog:100",
  "events": [
    {
      "remote_id": "evt-1",
      "revision": "9",
      "event_code": "II1",
      "name": "U.S. Nationals",
      "season": 2026,
      "runs": [
        {
          "remote_id": "run-1",
          "revision": "4",
          "driver_name": "Gaige Herrera",
          "category": "PSM",
          "car_number": "1",
          "round": "Q1",
          "run_datetime": "2026-09-04T22:00:00Z",
          "timing": {"quarter_mile_s": 6.74},
          "weather": {"temperature_f": 81.0},
          "assets": [
            {
              "remote_id": "asset-rpk-1",
              "revision": "2",
              "asset_type": "telemetry",
              "filename": "whatever_the_team_named_it.rpk",
              "sha256": "...",
              "size_bytes": 123456,
              "mime_type": "application/octet-stream",
              "vendor": "RacePak",
              "uploaded_at": "2026-09-04T22:05:00Z"
            }
          ]
        }
      ]
    }
  ]
}
```

## Apply semantics

- `contract_version` must be `4`.
- Event and Run server `remote_id` values map to stable local mirror IDs.
- Official `timing` and `weather`, when supplied, are authoritative.
- `assets` are already owned by the containing Run.
- Each server Asset requires `remote_id`; filename is descriptive only.
- Replaying the same snapshot is idempotent.
- Omitted `assets` means "asset manifest not supplied in this payload" and does not delete existing mirrored assets.
- Asset deletion/tombstone semantics are intentionally undefined until the actual backend is inspected.
- If a known Asset's authoritative SHA-256 changes, the desktop invalidates the old local cache/decoded telemetry state.

## Asset fetch

The future production adapter will fetch bytes by server Asset ID (or equivalent backend object reference). The desktop validates the downloaded SHA-256 before placing the bytes in its content-addressed cache.

## Future push direction

Only explicitly supported derived data should be pushed back: for example approved analysis/model snapshots, annotations, or reports. v0.19 does not assume that the desktop can upload raw Run Assets or mutate server Run ownership.
