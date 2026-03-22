#!/usr/bin/env python3
"""
Calculates Bitcoin MVRV using Binance historical klines.
MVRV = current_price / VWAP_730d
Binance API: free, no auth, works from GitHub Actions.
"""

import json, os, urllib.request
from datetime import datetime, timezone

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
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
        json.dump(p, f)
    print(f'SAVED: mvrv={p["mvrv"]} source={source}')

# ── Binance klines: 730 daily candles ────────────────────────────────────
# Each kline: [open_time, open, high, low, close, volume, ...]
# VWAP = sum(typical_price * volume) / sum(volume)
# typical_price = (high + low + close) / 3
print('Fetching 730-day klines from Binance...')
try:
    klines = get('https://api.binance.com/api/v3/klines'
                 '?symbol=BTCUSDT&interval=1d&limit=730')

    if len(klines) < 100:
        raise Exception(f'Too few candles: {len(klines)}')

    print(f'  Got {len(klines)} daily candles')

    total_vol   = 0.0
    total_tpvol = 0.0

    for k in klines:
        high   = float(k[2])
        low    = float(k[3])
        close  = float(k[4])
        volume = float(k[5])   # base asset volume (BTC)
        tp     = (high + low + close) / 3.0
        total_tpvol += tp * volume
        total_vol   += volume

    if total_vol <= 0:
        raise Exception('Zero total volume')

    vwap          = total_tpvol / total_vol
    current_price = float(klines[-1][4])   # last close
    mvrv          = current_price / vwap

    print(f'  Current price : ${current_price:,.0f}')
    print(f'  VWAP 730d     : ${vwap:,.0f}')
    print(f'  MVRV estimate : {mvrv:.3f}')

    if not valid(mvrv):
        raise Exception(f'Value out of range: {mvrv}')

    save(mvrv, 'Binance VWAP 730d',
         note='Estimativa: preco_atual / VWAP_730d. Aprox. ±10% do MVRV real.')
    exit(0)

except Exception as e:
    print(f'  Binance failed: {e}')

# ── Keep previous value ───────────────────────────────────────────────────
print('Binance failed. Checking previous value...')
if os.path.exists(OUTFILE):
    try:
        prev = json.load(open(OUTFILE))
        if valid(prev.get('mvrv')):
            prev['note'] = 'kept from previous run — fetch failed today'
            prev['updated'] = UPDATED
            json.dump(prev, open(OUTFILE, 'w'))
            print(f"Kept previous mvrv={prev['mvrv']}")
            exit(0)
    except Exception as e:
        print(f'  Could not read previous: {e}')

print('No valid data — writing null')
json.dump({'mvrv': None, 'date': TODAY,
           'source': 'unavailable', 'updated': UPDATED},
          open(OUTFILE, 'w'))
exit(1)
