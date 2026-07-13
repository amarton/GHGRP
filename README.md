# GHGRP Public Data Archive

A preservation snapshot of the U.S. EPA's Greenhouse Gas Reporting Program
(GHGRP) public data, maintained in case future reporting requirements are
rescinded, historical data is altered or removed, or access is otherwise
degraded.

## Why this exists

In September 2025, EPA proposed to end mandatory GHG reporting for 46 of the
47 industries currently covered, citing regulatory cost savings. A final
rule is expected around mid-2026. The historical dataset (2010–2024) is
currently public and intact, but there's no guarantee it stays that way,
and several other federal datasets have been altered or quietly stripped of
detail in the past two years. This archive exists to have a dated,
checksummed copy of the data as it existed at capture time, regardless of
what happens next.

## What's in here

- `archive_ghgrp.py` — the script that does the downloading
- `archive/YYYY-MM-DD/raw/` — one dated folder per capture run, containing
  the actual data files, untouched
- `archive/YYYY-MM-DD/manifest.json` and `manifest.csv` — for every file:
  source URL, retrieval timestamp (UTC), SHA-256 checksum, file size, and
  HTTP status. This is what makes the archive citable — anyone can verify a
  file hasn't been altered since capture by re-hashing it.
- `archive/LATEST.txt` — plain-text pointer to the most recent complete run

## Running it

```bash
pip install -r requirements.txt   # stdlib only, but kept for future deps
python archive_ghgrp.py           # downloads everything
python archive_ghgrp.py --list    # preview what would be downloaded, no network calls
python archive_ghgrp.py --only summary   # just the main data summary spreadsheets
```

Re-run this monthly or quarterly. Every run creates a new dated folder — the
script never overwrites a previous capture, so the archive doubles as a
change-detection tool over time. If EPA quietly edits a number or drops a
column, diffing two runs' `raw/` folders will show it.

## Data sources covered

| Group | Contents | Years |
|---|---|---|
| `summary` | Multi-year facility-level data summary spreadsheets | 2010–2023 |
| `parent_company` | Reported parent company / ownership per facility | Current |
| `unit_fuel` | Unit- and fuel-level emissions (Subparts C, D, AA) | 2010–2023 |
| `power_plant_crosswalk` | GHGRP-to-EIA/ORIS facility ID crosswalk | — |
| `subpart_l_o` | Fluorinated gas production, HCFC-22/HFC-23 | All years |
| `subpart_e_s_bb_cc_ll` | Adipic acid, lime, silicon carbide, soda ash, coal-liquid fuels | 2010– |
| `subpart_i` | Electronics manufacturing | 2011– |

These are EPA's own "frequently requested" bulk files, sourced from
`epa.gov/ghgreporting/data-sets`. They cover the great majority of publicly
reportable GHGRP data across all 32 Envirofacts-listed industry types.

### Not yet covered: full Envirofacts API table pulls

EPA's Envirofacts REST API (`data.epa.gov/efservice`) exposes more granular,
queryable tables than the static bulk files above. The script includes a
working query function (`fetch_envirofacts_table`) and a starter list of
table names in `ENVIROFACTS_TABLES`, but **those table names need to be
confirmed** against EPA's Envirofacts model/data element search
(https://www.epa.gov/enviro) before being trusted — they're EPA's internal
schema and can be renamed without notice, unlike the stable, documented
bulk-file URLs above. Treat `--envirofacts` as an experimental add-on until
someone verifies the table names once against the API Viewer.

## Automated monthly runs

`.github/workflows/monthly-archive.yml` runs the script automatically on
the 1st of every month via GitHub Actions, and commits any new archive run
back to the repo. It can also be triggered manually from the Actions tab
(useful right after EPA's annual October data release, or right after any
rulemaking decision). This is the piece that makes the archive actually
durable — a one-off download is a snapshot; a monthly automated run is a
living record that survives past whoever set it up.

To turn it on: nothing extra needed beyond pushing this repo to GitHub with
Actions enabled (on by default for public repos). Check the Actions tab
after the first scheduled run to confirm it's committing successfully.

## Where to publish this

- **GitHub**: commit the `archive/` folder (or link to it via Git LFS or
  Releases if file sizes get large — some of the yearly ZIPs can run tens
  of megabytes).
- **Internet Archive**: mirror the same dated folders there as a second,
  independent point of failure. A single point of hosting failure (a
  GitHub outage, an account issue) shouldn't take down the only copy.
- Consider a university data repository (UMD may have one) for a third,
  institutionally-backed copy with its own persistent identifier (DOI),
  which makes the archive more citable in academic and legal contexts.

## Provenance and citation

Every file's manifest entry records the exact EPA URL and UTC timestamp it
was pulled from. When citing this archive (in a story, a dataset citation,
or to another researcher), reference the specific dated run folder and its
manifest, not just "this GitHub repo" — that's what lets someone else
verify exactly what was captured and when.

## License / attribution

Code and documentation in this repository are MIT licensed (see `LICENSE`).
The underlying data is a U.S. government work and is in the public domain.
This repository's organization, scripts, and documentation can be
attributed to The Howard Center for Investigative Journalism.
