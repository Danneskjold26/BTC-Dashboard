#!/usr/bin/env python3
"""
Fetches Bitcoin MVRV ratio.
Sources tried in order:
  1. BGeometrics free API (multiple endpoint variants)
  2. Kraken VWAP 720d × calibration factor

CALIBRATION:
  Factor = 1.549, calibrated on 2026-03-22 (VWAP=0.82, real=1.27)
  Only needs updating when market transitions between major phases
  (bottom → bull, bull → top, top → bear) — roughly once per year.
  To recalibrate: open data/mvrv.json, check raw_vwap_mvrv field,
  then set FACTOR = current_checkonchain_value / raw_vwap_mvrv
"""

import json, os, urllib.request, urllib.error
from datetime import datetime, timezone

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

CALIBRATION_FACTOR = 1.549  # update when market changes major phase

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'application/json',
}

def get(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def valid(v):
    try:
        return 0.3 < float(v) < 15
    except:
        return False

def save(mvrv, source, note=None):
    p = {'mvrv': round(float(mvrv), 3), 'date': TODAY,
         'source': source, 'updated': UPDATED}
    if note:
        p['note'] = note
    with open(OUTFILE, 'w') as f:
        json.dump(p, f, indent=2)
    print(f'SAVED: mvrv={p["mvrv"]} source={source}')


# ── Source 1: BGeometrics free API (try multiple endpoint variants) ───────
BGEOMETRICS_ENDPOINTS = [
    'https://bitcoin-data.com/v1/mvrv-ratio',
    'https://bitcoin-data.com/v1/mvrv_ratio',
    'https://bitcoin-data.com/v1/mvrv',
    'https://bitcoin-data.com/v2/mvrv-ratio',
    'https://bitcoin-data.com/v2/mvrv',
]
print('Trying BGeometrics endpoints...')
for url in BGEOMETRICS_ENDPOINTS:
    try:
        d = get(url)
        # Handle various response shapes
        mvrv = None
        if isinstance(d, list) and d:
            last = d[-1]
            raw = last[1] if isinstance(last, list) else last.get('v', last.get('value', last.get('mvrv')))
            mvrv = float(raw) if raw is not None else None
        elif isinstance(d, dict):
            # Try common field names
            for field in ['v', 'value', 'mvrv', 'mvrv_ratio', 'data']:
                if field in d:
                    val = d[field]
                    if isinstance(val, list) and val:
                        mvrv = float(val[-1]) if not isinstance(val[-1], dict) else float(val[-1].get('v', 0))
                    elif isinstance(val, (int, float)):
                        mvrv = float(val)
                    break
        if mvrv and valid(mvrv):
            save(mvrv, f'BGeometrics ({url.split("/")[-1]})')
            exit(0)
        else:
            print(f'  {url} → unexpected format or invalid value: {str(d)[:80]}')
    except urllib.error.HTTPError as e:
        print(f'  {url} → HTTP {e.code}')
    except Exception as e:
        print(f'  {url} → {e}')


# ── Source 2: Kraken VWAP 720d × calibration factor ──────────────────────
print(f'\nTrying Kraken VWAP (calibration factor={CALIBRATION_FACTOR})...')
try:
    d = get('https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440')
    if d.get('error') and d['error']:
        raise Exception(str(d['error']))
    key = [k for k in d['result'].keys() if k != 'last'][0]
    rows = d['result'][key]
    # row: [time, open, high, low, close, vwap, volume, count]
    candles = [(float(r[2]), float(r[3]), float(r[4]), float(r[6]))
               for r in rows if float(r[6]) > 0]
    if len(candles) < 100:
        raise Exception(f'Too few candles: {len(candles)}')

    total_vol = total_tpvol = 0.0
    for h, l, c, v in candles:
        tp = (h + l + c) / 3.0
        total_tpvol += tp * v
        total_vol   += v
    if total_vol <= 0:
        raise Exception('Zero volume')

    vwap  = total_tpvol / total_vol
    price = float(candles[-1][2])
    raw   = price / vwap
    mvrv  = raw * CALIBRATION_FACTOR

    print(f'  Candles: {len(candles)} | Price: ${price:,.0f} | VWAP: ${vwap:,.0f}')
    print(f'  Raw MVRV: {raw:.3f} | Calibrated: {mvrv:.3f}')

    if not valid(mvrv):
        raise Exception(f'Out of range: {mvrv}')

    save(mvrv, f'Kraken VWAP 720d (×{CALIBRATION_FACTOR})',
         note=f'raw_vwap_mvrv={round(raw,3)} × {CALIBRATION_FACTOR}. '
              f'Recalibrar se diferença do CheckOnChain > 0.15: '
              f'novo_fator = checkonchain / {round(raw,3)}')
    exit(0)

except Exception as e:
    print(f'  Kraken failed: {e}')


# ── Keep previous value ───────────────────────────────────────────────────
print('All sources failed. Checking previous value...')
if os.path.exists(OUTFILE):
    try:
        prev = json.load(open(OUTFILE))
        if valid(prev.get('mvrv')):
            prev['note'] = 'kept from previous run — all fetches failed today'
            prev['updated'] = UPDATED
            json.dump(prev, open(OUTFILE, 'w'), indent=2)
            print(f"Kept previous mvrv={prev['mvrv']}")
            exit(0)
    except Exception as e:
        print(f'  Could not read previous: {e}')

print('No valid data — writing null')
json.dump({'mvrv': None, 'date': TODAY,
           'source': 'unavailable', 'updated': UPDATED},
          open(OUTFILE, 'w'))
exit(1)
