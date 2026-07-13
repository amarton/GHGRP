#!/usr/bin/env python3
"""
archive_ghgrp.py

Downloads and preserves EPA Greenhouse Gas Reporting Program (GHGRP) data
for long-term public archiving, with SHA-256 checksums and provenance
metadata for every file.

Built for The Howard Center for Investigative Journalism's data-rescue
project. This script is intentionally conservative: it downloads only
from EPA's own documented, publicly-published file URLs, records exactly
when and from where each file was retrieved, and never overwrites a
previous capture (so you can re-run this monthly/quarterly and keep a
dated history of what EPA has published over time -- useful both as an
archive and as a way to detect if EPA quietly alters data later).

USAGE:
    python archive_ghgrp.py                  # download everything
    python archive_ghgrp.py --list           # show what would be downloaded, don't fetch
    python archive_ghgrp.py --only summary   # download just one group (see GROUPS below)
    python archive_ghgrp.py --envirofacts    # also attempt Envirofacts API bulk pulls (see note below)

OUTPUT STRUCTURE:
    archive/
      YYYY-MM-DD/                  <- one folder per run, so nothing is ever overwritten
        raw/                      <- the actual downloaded files, unmodified
        manifest.json             <- provenance record: url, retrieval time, sha256, size, http status
        manifest.csv              <- same info, spreadsheet-friendly
      LATEST -> YYYY-MM-DD         <- symlink to the most recent complete run

A NOTE ON THE ENVIROFACTS API:
    EPA also exposes GHG data through a queryable REST API at
    https://data.epa.gov/efservice/ -- this can pull granular, table-level
    data (individual subpart tables, facility identifiers, etc.) beyond
    what's in the static bulk files below. The exact table names for GHG
    data should be confirmed against EPA's Envirofacts REST API Viewer
    (https://www.epa.gov/enviro) before relying on them, since table
    schemas are internal implementation details EPA can rename. This
    script includes a working query function and a starter list of
    table names to verify -- see fetch_envirofacts_table() and the
    ENVIROFACTS_TABLES list. Treat these table names as "to be confirmed"
    rather than guaranteed correct until you've checked one against the
    API Viewer.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Static bulk files EPA publishes directly (verified URLs as of July 2026).
# These are the highest-value, lowest-effort target: EPA already assembles
# these into ready-to-use spreadsheets, so no API pagination is needed.
# ---------------------------------------------------------------------------

STATIC_FILES = {
    "summary": [
        {
            "name": "data_summary_spreadsheets_2023.zip",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/2023_data_summary_spreadsheets.zip",
            "description": (
                "Multi-year data summary spreadsheet with high-level facility "
                "info, plus yearly spreadsheets with emissions by GHG and "
                "process. This is the single most useful file for a general "
                "archive -- start here if you only grab one thing."
            ),
        },
    ],
    "parent_company": [
        {
            "name": "ghgp_data_parent_company.xlsb",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/ghgp_data_parent_company.xlsb",
            "description": (
                "Each reporting facility's highest-level U.S. parent company "
                "and percent ownership. Useful for corporate-accountability "
                "angles (which parent companies operate the highest emitters)."
            ),
        },
    ],
    "unit_fuel": [
        {
            "name": "emissions_by_unit_and_fuel_type_c_d_aa.zip",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/emissions_by_unit_and_fuel_type_c_d_aa.zip",
            "description": (
                "Unit-level and fuel-level emissions for Pulp & Paper "
                "(Subpart AA), Electricity Generation (Subpart D), and "
                "General Stationary Fuel Combustion (Subpart C)."
            ),
        },
    ],
    "power_plant_crosswalk": [
        {
            "name": "ghgrp_oris_power_plant_crosswalk.xlsx",
            "url": "https://www.epa.gov/system/files/documents/2022-04/ghgrp_oris_power_plant_crosswalk_12_13_21.xlsx",
            "description": (
                "Crosswalk between GHGRP Facility IDs and EIA/ORIS IDs -- "
                "lets you join GHGRP data to EIA power plant generation "
                "data for cross-referencing."
            ),
        },
    ],
    "subpart_l_o": [
        {
            "name": "l_o_freq_request_data.xlsx",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/l_o_freq_request_data.xlsx",
            "description": (
                "Subpart L (Fluorinated Gas Production) and Subpart O "
                "(HCFC-22 Production / HFC-23 Destruction), all reporting years."
            ),
        },
    ],
    "subpart_e_s_bb_cc_ll": [
        {
            "name": "e_s_cems_bb_cc_ll_full_data_set.xlsx",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/e_s_cems_bb_cc_ll_full_data_set.xlsx",
            "description": (
                "Adipic Acid (E), Lime Manufacturing CEMS (S), Silicon "
                "Carbide (BB), Soda Ash (CC), Coal-based Liquid Fuel "
                "Suppliers (LL) -- all reporting years from 2010."
            ),
        },
    ],
    "subpart_i": [
        {
            "name": "i_freq_request_data.xlsx",
            "url": "https://www.epa.gov/system/files/other-files/2024-10/i_freq_request_data.xlsx",
            "description": (
                "Subpart I, Electronics Manufacturing, all reporting years from 2011."
            ),
        },
    ],
}

# ---------------------------------------------------------------------------
# Envirofacts REST API -- optional, for granular table-level pulls.
# CONFIRM these table names against https://www.epa.gov/enviro (the model /
# data element search) before trusting them. They're included as a documented
# starting point, not a guarantee.
# ---------------------------------------------------------------------------

ENVIROFACTS_BASE = "https://data.epa.gov/efservice"

ENVIROFACTS_TABLES = [
    # (table_name, output_filename, notes)
    ("pub_dim_facility", "envirofacts_pub_dim_facility.csv",
     "Facility dimension table -- names, addresses, identifiers. VERIFY table name first."),
    ("pub_facts_sector_ghg_emission", "envirofacts_pub_facts_sector_ghg_emission.csv",
     "Facility-level emissions by sector/gas. VERIFY table name first."),
]

USER_AGENT = "HowardCenter-GHGRP-Archive/1.0 (public-interest data preservation project)"
REQUEST_TIMEOUT = 120
CHUNK_SIZE = 1024 * 256


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url, dest_path, manifest_entry):
    """Download one file, streaming to disk, recording outcome in manifest_entry."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = resp.status
            with open(dest_path, "wb") as out:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
        size = os.path.getsize(dest_path)
        checksum = sha256_file(dest_path)
        manifest_entry.update({
            "http_status": status,
            "bytes": size,
            "sha256": checksum,
            "success": True,
            "error": None,
        })
        print(f"  OK  ({size:,} bytes, {time.time()-start:.1f}s)  {os.path.basename(dest_path)}")
    except urllib.error.HTTPError as e:
        manifest_entry.update({"http_status": e.code, "success": False, "error": str(e)})
        print(f"  FAIL [{e.code}] {url}: {e}")
    except Exception as e:  # noqa: BLE001 -- want to log and continue, not crash the whole run
        manifest_entry.update({"http_status": None, "success": False, "error": str(e)})
        print(f"  FAIL {url}: {e}")


def fetch_envirofacts_table(table_name, dest_path, manifest_entry, page_size=10000):
    """
    Pull a full Envirofacts table via the efservice REST API, paging through
    in page_size-row chunks (the API caps unrequested pulls at 10,000 rows
    and each request must complete in under 15 minutes per EPA's docs).
    Writes combined CSV output to dest_path.
    """
    first = 0
    rows_written = 0
    wrote_header = False
    try:
        with open(dest_path, "w", newline="", encoding="utf-8") as out:
            writer = None
            while True:
                last = first + page_size - 1
                url = f"{ENVIROFACTS_BASE}/{table_name}/rows/{first}:{last}/CSV"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                reader = csv.reader(text.splitlines())
                rows = list(reader)
                if not rows:
                    break
                if not wrote_header:
                    writer = csv.writer(out)
                    writer.writerow(rows[0])
                    wrote_header = True
                    data_rows = rows[1:]
                else:
                    data_rows = rows[1:]  # drop repeated header each page
                if not data_rows:
                    break
                writer.writerows(data_rows)
                rows_written += len(data_rows)
                if len(data_rows) < page_size:
                    break  # last page was partial -> done
                first += page_size
        size = os.path.getsize(dest_path)
        checksum = sha256_file(dest_path)
        manifest_entry.update({
            "http_status": 200,
            "bytes": size,
            "sha256": checksum,
            "rows": rows_written,
            "success": True,
            "error": None,
        })
        print(f"  OK  ({rows_written:,} rows)  {os.path.basename(dest_path)}")
    except Exception as e:  # noqa: BLE001
        manifest_entry.update({"success": False, "error": str(e)})
        print(f"  FAIL {table_name}: {e}")
        print(f"       -> Table name may be wrong. Verify at https://www.epa.gov/enviro")


def main():
    parser = argparse.ArgumentParser(description="Archive EPA GHGRP data with checksums and provenance.")
    parser.add_argument("--only", help="Only download this group (see keys in STATIC_FILES).")
    parser.add_argument("--list", action="store_true", help="List planned downloads without fetching.")
    parser.add_argument("--envirofacts", action="store_true",
                         help="Also attempt Envirofacts API table pulls (unverified table names).")
    parser.add_argument("--outdir", default="archive", help="Base output directory (default: ./archive)")
    args = parser.parse_args()

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_dir = os.path.join(args.outdir, run_date)
    raw_dir = os.path.join(run_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    groups = STATIC_FILES if not args.only else {args.only: STATIC_FILES.get(args.only, [])}
    if args.only and args.only not in STATIC_FILES:
        print(f"Unknown group '{args.only}'. Available: {', '.join(STATIC_FILES.keys())}")
        sys.exit(1)

    manifest = []

    for group, files in groups.items():
        for f in files:
            entry = {
                "group": group,
                "name": f["name"],
                "source_url": f["url"],
                "description": f["description"],
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if args.list:
                print(f"[{group}] {f['name']}  <-  {f['url']}")
                manifest.append(entry)
                continue
            print(f"[{group}] fetching {f['name']} ...")
            dest = os.path.join(raw_dir, f["name"])
            download_file(f["url"], dest, entry)
            manifest.append(entry)

    if args.envirofacts and not args.list:
        print("\nAttempting Envirofacts API pulls (unverified table names) ...")
        for table_name, out_name, notes in ENVIROFACTS_TABLES:
            entry = {
                "group": "envirofacts_api",
                "name": out_name,
                "source_url": f"{ENVIROFACTS_BASE}/{table_name}",
                "description": notes,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            print(f"[envirofacts_api] fetching table '{table_name}' ...")
            dest = os.path.join(raw_dir, out_name)
            fetch_envirofacts_table(table_name, dest, entry)
            manifest.append(entry)

    if args.list:
        print(f"\n{len(manifest)} files would be downloaded. Nothing was fetched (--list mode).")
        return

    # Write manifest (JSON + CSV) documenting provenance for every file.
    manifest_json_path = os.path.join(run_dir, "manifest.json")
    with open(manifest_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "archive_run_date_utc": run_date,
            "generated_by": "archive_ghgrp.py",
            "purpose": (
                "Preservation snapshot of EPA GHGRP public data, captured in "
                "case future reporting requirements are rescinded or "
                "historical data is altered/removed."
            ),
            "files": manifest,
        }, f, indent=2)

    manifest_csv_path = os.path.join(run_dir, "manifest.csv")
    with open(manifest_csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["group", "name", "source_url", "description", "retrieved_at_utc",
                      "http_status", "bytes", "sha256", "rows", "success", "error"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in manifest:
            writer.writerow(row)

    # Update a LATEST pointer file (plain text, since symlinks don't always
    # survive being zipped/uploaded to GitHub cleanly).
    with open(os.path.join(args.outdir, "LATEST.txt"), "w", encoding="utf-8") as f:
        f.write(run_date + "\n")

    succeeded = sum(1 for m in manifest if m.get("success"))
    print(f"\nDone. {succeeded}/{len(manifest)} files retrieved successfully.")
    print(f"Manifest: {manifest_json_path}")


if __name__ == "__main__":
    main()
