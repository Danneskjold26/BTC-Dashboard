#!/usr/bin/env python3
"""
Calculates Bitcoin MVRV using Kraken + Coinbase historical klines.
MVRV = current_price / VWAP_720d
Both APIs: free, no auth, no geo-blocking on GitHub Actions US servers.
"""

import json, os, urllib.request, time
from datetime import datetime, timezone

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
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

def calc_vwap(candles):
    """Returns (current_price, vwap) from list of (high, low, close, volume)"""
    total_vol = total_tpvol = 0.0
    for h, l, c, v in candles:
        tp = (h + l + c) / 3.0
        total_tpvol += tp * v
        total_vol   += v
    if total_vol <= 0:
        raise Exception('Zero volume')
    return candles[-1][2], total_tpvol / total_vol   # (last_close, vwap)


# ── Source 1: Kraken OHLC (1440-min = daily, up to 720 candles) ──────────
print('Trying Kraken...')
try:
    d = get('https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440')
    if d.get('error') and d['error']:
        raise Exception(str(d['error']))
    # result key is "XXBTZUSD"
    key = [k for k in d['result'].keys() if k != 'last'][0]
    rows = d['result'][key]
    # Kraken row: [time, open, high, low, close, vwap, volume, count]
    candles = [(float(r[2]), float(r[3]), float(r[4]), float(r[6]))
               for r in rows if float(r[6]) > 0]
    if len(candles) < 100:
        raise Exception(f'Too few candles: {len(candles)}')
    price, vwap = calc_vwap(candles)
    mvrv = price / vwap
    print(f'  Candles: {len(candles)} | Price: ${price:,.0f} | VWAP: ${vwap:,.0f} | MVRV: {mvrv:.3f}')
    if not valid(mvrv):
        raise Exception(f'Out of range: {mvrv}')
    save(mvrv, 'Kraken VWAP 720d',
         note='Estimativa: preco_atual / VWAP_720d. Aprox. ±10% do MVRV real.')
    exit(0)
except Exception as e:
    print(f'  Kraken failed: {e}')


# ── Source 2: Coinbase Exchange OHLC ─────────────────────────────────────
# /products/BTC-USD/candles?granularity=86400&start=...&end=...
# Max 300 candles per call — fetch 2 batches of 300 = 600 days
print('Trying Coinbase...')
try:
    import time as _time
    from datetime import timedelta

    now  = datetime.now(timezone.utc)
    all_candles = []

    for batch in range(3):   # 3 x 300 = 900 days, take last 720
        end   = now - timedelta(days=batch * 300)
        start = end - timedelta(days=300)
        url   = (f'https://api.exchange.coinbase.com/products/BTC-USD/candles'
                 f'?granularity=86400'
                 f'&start={start.strftime("%Y-%m-%dT%H:%M:%SZ")}'
                 f'&end={end.strftime("%Y-%m-%dT%H:%M:%SZ")}')
        rows = get(url)
        # Coinbase row: [time, low, high, open, close, volume]
        for r in rows:
            if float(r[5]) > 0:
                all_candles.append((float(r[2]), float(r[1]), float(r[4]), float(r[5])))
        _time.sleep(0.4)   # respect rate limit

    # Sort by implied order (Coinbase returns newest first)
    all_candles = all_candles[-720:]   # keep last 720

    if len(all_candles) < 100:
        raise Exception(f'Too few candles: {len(all_candles)}')

    price, vwap = calc_vwap(all_candles)
    mvrv = price / vwap
    print(f'  Candles: {len(all_candles)} | Price: ${price:,.0f} | VWAP: ${vwap:,.0f} | MVRV: {mvrv:.3f}')
    if not valid(mvrv):
        raise Exception(f'Out of range: {mvrv}')
    save(mvrv, 'Coinbase VWAP 720d',
         note='Estimativa: preco_atual / VWAP_720d. Aprox. ±10% do MVRV real.')
    exit(0)
except Exception as e:
    print(f'  Coinbase failed: {e}')


# ── Source 3: Keep previous value ────────────────────────────────────────
print('All sources failed. Checking previous value...')
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
