#!/usr/bin/env python3
"""
Fetches Bitcoin MVRV ratio from multiple sources.
Saves result to data/mvrv.json
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

os.makedirs('data', exist_ok=True)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def save(mvrv, source, note=None):
    payload = {'mvrv': mvrv, 'date': TODAY, 'source': source, 'updated': UPDATED}
    if note:
        payload['note'] = note
    with open(OUTFILE, 'w') as f:
        json.dump(payload, f)
    print(f'Saved: MVRV={mvrv} source={source}')


def valid(v):
    return v is not None and not (v != v) and 0.3 < float(v) < 15


# ── Source 1: blockchain.info MVRV chart ─────────────────────────────────
print('Trying blockchain.info MVRV chart...')
try:
    d = fetch('https://api.blockchain.info/charts/mvrv?timespan=5days&sampled=false&format=json')
    vals = [v for v in d.get('values', []) if v.get('y', 0) > 0]
    if vals:
        v = round(float(vals[-1]['y']), 3)
        if valid(v):
            save(v, 'Blockchain.info')
            exit(0)
except Exception as e:
    print(f'  Failed: {e}')

# ── Source 2: blockchain.info market-cap / realized-cap ──────────────────
print('Trying blockchain.info market-cap / realized-cap...')
try:
    mkt  = fetch('https://api.blockchain.info/charts/market-cap?timespan=5days&sampled=false&format=json')
    real = fetch('https://api.blockchain.info/charts/realized-cap?timespan=5days&sampled=false&format=json')
    mkt_vals  = [v for v in mkt.get('values',  []) if v.get('y', 0) > 0]
    real_vals = [v for v in real.get('values', []) if v.get('y', 0) > 0]
    if mkt_vals and real_vals:
        v = round(mkt_vals[-1]['y'] / real_vals[-1]['y'], 3)
        if valid(v):
            save(v, 'Blockchain.info (calculado)')
            exit(0)
except Exception as e:
    print(f'  Failed: {e}')

# ── Source 3: CoinMetrics community API ──────────────────────────────────
print('Trying CoinMetrics...')
try:
    d = fetch('https://community-api.coinmetrics.io/v4/timeseries/asset-metrics'
              '?assets=btc&metrics=CapMrktCurUSD,CapRealUSD&frequency=1d&page_size=2')
    rows = d.get('data', [])
    if rows:
        r = rows[-1]
        v = round(float(r['CapMrktCurUSD']) / float(r['CapRealUSD']), 3)
        if valid(v):
            save(v, 'CoinMetrics')
            exit(0)
except Exception as e:
    print(f'  Failed: {e}')

# ── Source 4: BGeometrics ─────────────────────────────────────────────────
print('Trying BGeometrics...')
try:
    d = fetch('https://bitcoin-data.com/v1/mvrv-ratio')
    if isinstance(d, list) and d:
        last = d[-1]
        raw = last[1] if isinstance(last, list) else last.get('v', last.get('value'))
        v = round(float(raw), 3)
        if valid(v):
            save(v, 'BGeometrics')
            exit(0)
    elif isinstance(d, dict) and 'v' in d and d['v']:
        v = round(float(d['v'][-1]), 3)
        if valid(v):
            save(v, 'BGeometrics')
            exit(0)
except Exception as e:
    print(f'  Failed: {e}')

# ── Keep previous value if available ────────────────────────────────────
print('All sources failed. Checking previous value...')
if os.path.exists(OUTFILE):
    try:
        with open(OUTFILE) as f:
            prev = json.load(f)
        if valid(prev.get('mvrv')):
            prev['note'] = 'kept from previous run — fetch failed today'
            prev['updated'] = UPDATED
            with open(OUTFILE, 'w') as f:
                json.dump(prev, f)
            print(f"Kept previous MVRV={prev['mvrv']}")
            exit(0)
    except Exception as e:
        print(f'  Could not read previous: {e}')

# ── Write null as last resort ────────────────────────────────────────────
print('No valid data available — writing null')
with open(OUTFILE, 'w') as f:
    json.dump({'mvrv': None, 'date': TODAY, 'source': 'unavailable', 'updated': UPDATED}, f)
exit(1)
