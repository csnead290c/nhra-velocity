# RacePak Corpus Evidence in NHRA VELOCITY

RacePak raw `.ddf` recordings expose stable numeric `_CONNECT4_COMMAND` channel ids even when the matching DataLink configuration is missing. NHRA VELOCITY can mine known `.rcg`, self-describing `.rpk`, and already-configured `.ddf` files to recover useful evidence without pretending that a numeric id has one global engineering meaning.

## The important rule

**A RacePak channel id by itself is never enough to rename an unknown DDF channel automatically.**

For example, id `123456` may be called `OIL PRESSURE` on several known cars while many other cars place Oil Pressure at completely different ids. The corpus history is still useful, but it is evidence only.

A configless DDF therefore remains:

`RacePak Channel 123456`

and may carry metadata such as:

- suggested historical name: `OIL PRESSURE`
- seen in N distinct semantic configurations
- other names/units observed for the same id
- evidence level / conflict state

The visible source name and unit stay generic until stronger evidence exists.

## Authority order

1. Exact configuration pinned to this data log
2. Vehicle + Category RacePak profile
3. Driver + Category RacePak profile
4. One unambiguous sibling `.rcg`
5. **Exact known DDF descriptor-table fingerprint** previously bound to a matching sibling RCG
6. Numeric channel-id corpus history — **suggestion only**
7. `RacePak Channel <id>`

The fifth level is intentionally much stronger than id history. The complete DDF descriptor SHA-256 covers the raw descriptor table, including channel ids, sample rates, fixed-point flags, config-rate fields, descriptor order, and reserved bytes. VELOCITY learns such a fingerprint only from a real DDF that can be fully matched to a sibling RCG. If the same exact descriptor fingerprint is ever observed with conflicting source definitions, automatic recovery is disabled for that fingerprint.

## Common Channels remain separate

Recovering a source label does **not** select VELOCITY Common Channel roles. A source may be named `ENGINE RPM`, yet a particular car may deliberately use another source as the engineering Common Channel **Engine Speed**. That decision remains explicit and context-specific.

## Corpus audit

`RUN-NHRA-VELOCITY-DATA-AUDIT.cmd` produces:

- `qualification.csv/json`
- `inventory.csv/json`
- `racepak_channel_ids.csv/json`
- `racepak_descriptor_profiles.csv`

Quick mode scans every RCG plus a representative spread of RPKs. Full mode scans every RCG and RPK under the selected folder. DDF descriptor fingerprint discovery reads only the small descriptor table from DDFs that have sibling RCG candidates; it does not rewrite source files.

The installed evidence library can be replaced at any time by rerunning the audit. A legacy dev.22 v1 library is ignored/removed when the v2 evidence model is installed so the old ID-only fallback behavior cannot remain active accidentally.
