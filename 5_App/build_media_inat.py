#!/usr/bin/env python3
"""
iNaturalist media pipeline for Finding gap project.
Fetches CC0/CC-BY licensed photos from iNaturalist API.

Usage:
  python build_media_inat.py [--full] [--subset SIZE]

  Default: runs validation set (~25 curated threatened species)
  --full: runs entire species list (~40k)
  --subset SIZE: runs specified number of species
"""

import json
import sys
import time
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path


# Configuration
INAT_API_BASE = "https://api.inaturalist.org/v1"
PLACE_ID = 6891  # South Korea
QUALITY_GRADE = "research"
PHOTO_LICENSES = "cc0,cc-by"
USER_AGENT = "FindingGap-media/1.0 (yssfranchis96@gmail.com)"
RATE_LIMIT_SLEEP = 1.1  # seconds between requests
PHOTOS_PER_SPECIES = 4

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SPECIES_INDEX_PATH = PROJECT_ROOT / "5_App" / "demo" / "data" / "species_index.json"
OUTPUT_PATH = PROJECT_ROOT / "1_Data" / "processed" / "media_inat.json"

# Curated validation set (threatened/protected species)
CURATED_KTSN = {
    "120000057604", "120000058009", "120000057603", "120000001361", "120000164710",
    "120000217056", "120000001413", "120000001616", "120000528810", "120000035703",
    "120000029018", "120000037975", "120000043330", "120000042572", "120000133054",
    "120000053268", "120000212787", "120000053330", "120000053507", "120000059485",
    "120000059453", "120000059469", "120000060801", "120000060754", "120000060761",
}


def load_species_index(subset_size=None, full=False):
    """Load species index and return species for processing."""
    with open(SPECIES_INDEX_PATH, 'r', encoding='utf-8') as f:
        all_species = json.load(f)

    if full:
        if subset_size:
            return all_species[:subset_size]
        return all_species
    else:
        # Use curated validation set
        curated = [s for s in all_species if s['k'] in CURATED_KTSN]
        if subset_size:
            return curated[:subset_size]
        return curated


def fetch_inat_observations(scientific_name):
    """Fetch observations from iNaturalist for a given scientific name."""
    params = [
        f"taxon_name={scientific_name.replace(' ', '%20')}",
        f"place_id={PLACE_ID}",
        f"quality_grade={QUALITY_GRADE}",
        f"photo_license={PHOTO_LICENSES}",
        "per_page=30",
        "order_by=votes",
    ]
    url = f"{INAT_API_BASE}/observations?{'&'.join(params)}"

    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except (URLError, HTTPError, TimeoutError) as e:
        print(f"  Error fetching observations for {scientific_name}: {e}")
        return None


def fetch_inat_taxa(scientific_name):
    """Fallback: fetch taxa info for taxon_photos."""
    params = [
        f"q={scientific_name.replace(' ', '%20')}",
        "rank=species",
    ]
    url = f"{INAT_API_BASE}/taxa?{'&'.join(params)}"

    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('results', [])
    except (URLError, HTTPError, TimeoutError) as e:
        print(f"  Fallback taxa fetch failed for {scientific_name}: {e}")
        return []


def extract_photos_from_observations(observations):
    """Extract photos from observations response."""
    photos = []
    if not observations or 'results' not in observations:
        return photos

    photo_ids_seen = set()
    for obs in observations['results']:
        if 'photos' not in obs:
            continue
        for photo in obs['photos']:
            pid = photo.get('id')
            if not pid or pid in photo_ids_seen:
                continue

            photo_ids_seen.add(pid)

            # Verify license
            lic_code = photo.get('license_code', '').lower()
            if lic_code not in ['cc0', 'cc-by']:
                continue

            record = {
                'id': pid,
                'attribution': photo.get('attribution', ''),
                'license': 'cc0' if lic_code == 'cc0' else 'cc-by',
            }
            photos.append(record)

            if len(photos) >= PHOTOS_PER_SPECIES:
                break

        if len(photos) >= PHOTOS_PER_SPECIES:
            break

    return photos


def extract_photos_from_taxa(taxa_results):
    """Extract photos from taxa response (fallback)."""
    photos = []

    for taxon in taxa_results:
        if 'taxon_photos' not in taxon:
            continue
        for tp in taxon['taxon_photos']:
            if 'photo' not in tp:
                continue
            photo = tp['photo']

            # Verify license
            lic_code = photo.get('license_code', '').lower()
            if lic_code not in ['cc0', 'cc-by']:
                continue

            pid = photo.get('id')
            record = {
                'id': pid,
                'attribution': photo.get('attribution', ''),
                'license': 'cc0' if lic_code == 'cc0' else 'cc-by',
            }
            photos.append(record)

            if len(photos) >= PHOTOS_PER_SPECIES:
                break

        if len(photos) >= PHOTOS_PER_SPECIES:
            break

    return photos


def build_photo_urls(photo_id):
    """Build small and medium URLs for a photo.

    CC/CC0 photos (open-data) are served from the iNaturalist AWS Open Data bucket.
    static.inaturalist.org does NOT serve these (hotlink fails) — the S3 open-data
    host does. small/medium derivatives are always .jpg regardless of original format.
    """
    base = f"https://inaturalist-open-data.s3.amazonaws.com/photos/{photo_id}"
    return {
        'small': f"{base}/small.jpg",
        'medium': f"{base}/medium.jpg",
    }


def fetch_species_media(species, existing_output):
    """Fetch media for a single species."""
    ktsn = species['k']
    sci_name = species['s']

    # Skip if already processed
    if ktsn in existing_output:
        return None

    print(f"Fetching {sci_name} ({ktsn})...")

    # Try observations endpoint first
    time.sleep(RATE_LIMIT_SLEEP)
    observations = fetch_inat_observations(sci_name)
    photos = extract_photos_from_observations(observations) if observations else []

    # Fallback to taxa endpoint
    if not photos:
        print(f"  No observations found, trying taxa fallback...")
        time.sleep(RATE_LIMIT_SLEEP)
        taxa = fetch_inat_taxa(sci_name)
        photos = extract_photos_from_taxa(taxa)

    if not photos:
        print(f"  No CC0/CC-BY photos found")
        return None

    # Build output records
    records = []
    for photo in photos[:PHOTOS_PER_SPECIES]:
        urls = build_photo_urls(photo['id'])
        record = {
            'src': 'inat',
            'type': 'photo',
            'thumb': urls['small'],
            'full': urls['medium'],
            'by': photo['attribution'],
            'lic': photo['license'],
            'link': f"https://www.inaturalist.org/photos/{photo['id']}",
        }
        records.append(record)

    if records:
        print(f"  Found {len(records)} photos")
        return {ktsn: records}

    return None


def verify_url(url):
    """Verify a URL is accessible (HTTP 200)."""
    try:
        req = Request(url, method='HEAD', headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception:
        # Try GET instead if HEAD fails
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False


def main():
    """Main pipeline."""
    # Parse arguments
    full = '--full' in sys.argv
    subset_size = None
    if '--subset' in sys.argv:
        idx = sys.argv.index('--subset')
        if idx + 1 < len(sys.argv):
            try:
                subset_size = int(sys.argv[idx + 1])
            except ValueError:
                pass

    # Load species
    species_list = load_species_index(subset_size=subset_size, full=full)
    print(f"Processing {len(species_list)} species...")

    # Load existing output (for resumable runs)
    existing_output = {}
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
            existing_output = json.load(f)
        print(f"Resuming from {len(existing_output)} existing records")

    # Fetch media for each species
    output = dict(existing_output)
    stats = {
        'attempted': 0,
        'with_photos': 0,
        'no_cc_photo': 0,
        'errors': 0,
    }

    for i, species in enumerate(species_list, 1):
        print(f"\n[{i}/{len(species_list)}]")

        try:
            result = fetch_species_media(species, existing_output)
            stats['attempted'] += 1

            if result:
                output.update(result)
                stats['with_photos'] += 1
            else:
                stats['no_cc_photo'] += 1
        except Exception as e:
            print(f"  Unexpected error: {e}")
            stats['errors'] += 1

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Output: {OUTPUT_PATH}")
    print(f"Attempted: {stats['attempted']}")
    print(f"With photos: {stats['with_photos']}")
    print(f"No CC photo: {stats['no_cc_photo']}")
    print(f"Errors: {stats['errors']}")
    print(f"Records in output: {len(output)}")

    # Spot-check URLs
    if output:
        print("\n" + "="*60)
        print("SPOT-CHECK (verifying 2 sample URLs)...")
        print("="*60)
        for ktsn, records in list(output.items())[:1]:
            for i, record in enumerate(records[:2]):
                url = record['thumb']
                print(f"\nChecking {url}")
                accessible = verify_url(url)
                print(f"  HTTP 200: {accessible}")

    # Print sample records
    if output:
        print("\n" + "="*60)
        print("SAMPLE RECORDS (first 2 species)")
        print("="*60)
        for ktsn, records in list(output.items())[:2]:
            print(f"\n{ktsn}:")
            for record in records[:1]:
                print(f"  {json.dumps(record, ensure_ascii=False, indent=4)}")


if __name__ == '__main__':
    main()
