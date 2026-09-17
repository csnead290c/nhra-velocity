# RacePak Channel-ID Knowledge in NHRA VELOCITY

RacePak raw `.ddf` recordings expose stable numeric channel ids (`_CONNECT4_COMMAND`) even when the matching DataLink configuration is missing. NHRA VELOCITY can mine known `.rcg` files and self-describing `.rpk` files to build an empirical source-channel dictionary.

## Authority order

1. Exact configuration pinned to this data log
2. Vehicle + Category RacePak profile
3. Driver + Category RacePak profile
4. One unambiguous sibling `.rcg`
5. Verified empirical NHRA channel-id consensus
6. `RacePak Channel <id>`

The empirical layer is deliberately low authority. It supplies a source name/unit only when at least three distinct configuration signatures agree with no name or unit conflict. Two-source agreement is reported but not applied automatically.

## Common Channels remain separate

A global RacePak ID match does **not** select VELOCITY's Common Channel roles. For example, the corpus may prove that a numeric ID is consistently named `ENGINE RPM`, but a particular car may still use another source for the engineering Common Channel **Engine Speed**. That decision remains explicit and context-specific.

## Corpus audit

`RUN-NHRA-VELOCITY-DATA-AUDIT.cmd` now produces:

- `qualification.csv/json`
- `inventory.csv/json`
- `racepak_channel_ids.csv/json`

Quick mode scans every RCG and a representative spread of RPKs. Full mode scans every RCG and RPK under the selected folder. The installed consensus library can be replaced at any time by rerunning the audit; source data is never modified.
