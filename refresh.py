#!/usr/bin/env python3
"""
Pulls the latest rows from the Go-Live Board's Google Form response sheet
(published as CSV) and regenerates go-live-board/rendered.html from
template.html with the fresh roster embedded.

This script only writes the local rendered.html file — it does NOT publish
anything. After running it, publish rendered.html to config.json's
"artifactUrl" via the Artifact tool to make the update live.

Usage: python3 refresh.py
"""
import csv
import io
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
TEMPLATE_PATH = os.path.join(HERE, "template.html")
OUTPUT_PATH = os.path.join(HERE, "index.html")

# Dropdown option (lowercased) -> IANA timezone
TZ_DROPDOWN = {
    "hawaii": "Pacific/Honolulu",
    "alaska": "America/Anchorage",
    "pacific": "America/Los_Angeles",
    "mountain": "America/Denver",
    "central": "America/Chicago",
    "eastern": "America/New_York",
    "uk": "Europe/London",
    "central europe": "Europe/Paris",
}

# Substring match (lowercased free text) -> IANA timezone, checked in order
TZ_FREE_TEXT = [
    ("eastern", "America/New_York"), ("est", "America/New_York"), ("edt", "America/New_York"),
    ("central", "America/Chicago"), ("cst", "America/Chicago"), ("cdt", "America/Chicago"),
    ("mountain", "America/Denver"), ("mst", "America/Denver"), ("mdt", "America/Denver"),
    ("arizona", "America/Phoenix"),
    ("pacific", "America/Los_Angeles"), ("pst", "America/Los_Angeles"), ("pdt", "America/Los_Angeles"),
    ("alaska", "America/Anchorage"),
    ("hawaii", "Pacific/Honolulu"),
    ("london", "Europe/London"), ("uk", "Europe/London"), ("gmt", "UTC"), ("bst", "Europe/London"),
    ("berlin", "Europe/Paris"), ("paris", "Europe/Paris"), ("cet", "Europe/Paris"), ("cest", "Europe/Paris"),
    ("india", "Asia/Kolkata"), ("ist", "Asia/Kolkata"),
    ("japan", "Asia/Tokyo"), ("tokyo", "Asia/Tokyo"), ("jst", "Asia/Tokyo"),
    ("sydney", "Australia/Sydney"), ("australia", "Australia/Sydney"), ("aest", "Australia/Sydney"),
    ("utc", "UTC"),
]

DEFAULT_TZ = "America/Chicago"  # used only if nothing above matches an "Other" entry


def resolve_tz(dropdown_value, other_text):
    v = (dropdown_value or "").strip().lower()
    if v in TZ_DROPDOWN:
        return TZ_DROPDOWN[v]
    t = (other_text or "").strip().lower()
    for needle, tz in TZ_FREE_TEXT:
        if needle in t:
            return tz
    return DEFAULT_TZ


TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM|am|pm)?$')


def parse_time(value):
    value = (value or "").strip()
    m = TIME_RE.match(value)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    ampm = m.group(3)
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and hh != 12:
            hh += 12
        if ampm == "AM" and hh == 12:
            hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh, mm


def slugify_handle(h):
    return re.sub(r"^@+", "", (h or "").strip()).lower()


def find_col(header, exact=None, startswith=None):
    for i, name in enumerate(header):
        if exact is not None and name == exact:
            return i
        if startswith is not None and name.startswith(startswith):
            return i
    return None


def main():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    req = urllib.request.Request(config["csvUrl"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")

    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        print("CSV was empty; nothing to do.")
        return

    header = rows[0]
    i_ts = find_col(header, exact="Timestamp") or 0
    i_name = find_col(header, exact="Name")
    i_handle = find_col(header, exact="TikTok @handle")
    i_time = find_col(header, exact="Usually goes live at")
    i_tz = find_col(header, exact="Your Timezone")
    i_other = find_col(header, startswith='If "Other"')

    entries = {}
    skipped = 0
    for row in rows[1:]:
        if not row or all(not c.strip() for c in row):
            continue
        try:
            name = row[i_name].strip() if i_name is not None else ""
            handle_raw = row[i_handle].strip() if i_handle is not None else ""
            time_raw = row[i_time] if i_time is not None else ""
            tz_dropdown = row[i_tz] if i_tz is not None else ""
            tz_other = row[i_other] if i_other is not None else ""
            timestamp = row[i_ts] if i_ts is not None else ""
        except IndexError:
            skipped += 1
            continue

        if not name or not handle_raw:
            skipped += 1
            continue
        parsed = parse_time(time_raw)
        if not parsed:
            skipped += 1
            continue
        hh, mm = parsed
        tz = resolve_tz(tz_dropdown, tz_other)
        handle_key = slugify_handle(handle_raw)
        if not handle_key:
            skipped += 1
            continue

        entries[handle_key] = {
            "name": name,
            "handle": handle_raw.lstrip("@"),
            "handleKey": handle_key,
            "hh": hh,
            "mm": mm,
            "tz": tz,
            "addedAt": timestamp,
        }

    roster = sorted(entries.values(), key=lambda e: e["addedAt"])

    with open(TEMPLATE_PATH) as f:
        template = f.read()

    json_safe = json.dumps(roster).replace("<", "\\u003c")
    marker = '<script id="roster-data" type="application/json">'
    start = template.index(marker) + len(marker)
    end = template.index("</script>", start)
    rendered = template[:start] + json_safe + template[end:]

    with open(OUTPUT_PATH, "w") as f:
        f.write(rendered)

    print("wrote %s with %d entries (%d rows skipped)" % (OUTPUT_PATH, len(roster), skipped))


if __name__ == "__main__":
    main()
