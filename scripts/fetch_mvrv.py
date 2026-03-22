#!/usr/bin/env python3
"""
Calculates Bitcoin MVRV using Kraken/Coinbase historical klines.
MVRV = (current_price / VWAP_720d) * CALIBRATION_FACTOR

CALIBRATION_FACTOR corrects for the systematic difference between
exchange VWAP and on-chain realized price (UTXOs cost basis).
Calibrated on 2026-03-22: VWAP gave 0.82, CheckOnChain showed 1.27
Factor = 1.27 / 0.82 = 1.549
Recalibrate periodically by comparing output with CheckOnChain.
"""

import json, os, urllib.request, time as _time
from datetime import datetime, timezone, timedelta

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

# ── Calibration factor ────────────────────────────────────────────────────
# Corrects VWAP-based estimate toward true on-chain realized price.
# Last calibrated: 2026-03-22 (VWAP=0.82, CheckOnChain=1.27)
# To recalibrate: FACTOR = CheckOnChain_value / raw_vwap_value
CALIBRATION_FACTOR = 1.549

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

def save(mvrv, raw_vwap_mvrv, source):
    p = {
        'mvrv': round(float(mvrv), 3),
        'date': TODAY,
        'source': source,
        'updated': UPDATED,
        'raw_vwap_mvrv': round(float(raw_vwap_mvrv), 3),
        'calibration_factor': CALIBRATION_FACTOR,
        'note': (f'Calculado: (preco_atual/VWAP_720d) x {CALIBRATION_FACTOR}. '
                 f'Calibrado em 2026-03-22. '
                 f'Verificar periodicamente em CheckOnChain.')
    }
    with open(OUTFILE, 'w') as f:
        json.dump(p, f, indent=2)
    print(f'SAVED: mvrv={p["mvrv"]} (raw={raw_vwap_mvrv:.3f} x {CALIBRATION_FACTOR}) source={source}')

def calc_vwap_mvrv(candles):
    """candles: list of (high, low, close, volume). Returns (price, raw_mvrv)."""
    total_vol = total_tpvol = 0.0
    for h, l, c, v in candles:
        tp = (h + l + c) / 3.0
        total_tpvol += tp * v
        total_vol   += v
    if total_vol <= 0:
        raise Exception('Zero total volume')
    vwap  = total_tpvol / total_vol
    price = candles[-1][2]  # last close
    return price, price / vwap


# ── Source 1: Kraken ──────────────────────────────────────────────────────
print('Trying Kraken...')
try:
    d = get('https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440')
    if d.get('error') and d['error']:
        raise Exception(str(d['error']))
    key = [k for k in d['result'].keys() if k != 'last'][0]
    rows = d['result'][key]
    # Kraken row: [time, open, high, low, close, vwap, volume, count]
    candles = [(float(r[2]), float(r[3]), float(r[4]), float(r[6]))
               for r in rows if float(r[6]) > 0]
    if len(candles) < 100:
        raise Exception(f'Too few candles: {len(candles)}')
    price, raw = calc_vwap_mvrv(candles)
    mvrv = raw * CALIBRATION_FACTOR
    print(f'  Candles: {len(candles)} | Price: ${price:,.0f} | Raw MVRV: {raw:.3f} | Calibrated: {mvrv:.3f}')
    if not valid(mvrv):
        raise Exception(f'Out of range after calibration: {mvrv}')
    save(mvrv, raw, 'Kraken VWAP 720d (calibrado)')
    exit(0)
except Exception as e:
    print(f'  Kraken failed: {e}')


# ── Source 2: Coinbase ────────────────────────────────────────────────────
print('Trying Coinbase...')
try:
    now = datetime.now(timezone.utc)
    all_candles = []
    for batch in range(3):
        end   = now - timedelta(days=batch * 300)
        start = end  - timedelta(days=300)
        url   = (f'https://api.exchange.coinbase.com/products/BTC-USD/candles'
                 f'?granularity=86400'
                 f'&start={start.strftime("%Y-%m-%dT%H:%M:%SZ")}'
                 f'&end={end.strftime("%Y-%m-%dT%H:%M:%SZ")}')
        rows = get(url)
        for r in rows:
            if float(r[5]) > 0:
                all_candles.append((float(r[2]), float(r[1]), float(r[4]), float(r[5])))
        _time.sleep(0.4)
    all_candles = sorted(all_candles, key=lambda x: x[2])[-720:]
    if len(all_candles) < 100:
        raise Exception(f'Too few candles: {len(all_candles)}')
    price, raw = calc_vwap_mvrv(all_candles)
    mvrv = raw * CALIBRATION_FACTOR
    print(f'  Candles: {len(all_candles)} | Price: ${price:,.0f} | Raw MVRV: {raw:.3f} | Calibrated: {mvrv:.3f}')
    if not valid(mvrv):
        raise Exception(f'Out of range after calibration: {mvrv}')
    save(mvrv, raw, 'Coinbase VWAP 720d (calibrado)')
    exit(0)
except Exception as e:
    print(f'  Coinbase failed: {e}')


# ── Keep previous value ───────────────────────────────────────────────────
print('All sources failed. Checking previous value...')
if os.path.exists(OUTFILE):
    try:
        prev = json.load(open(OUTFILE))
        if valid(prev.get('mvrv')):
            prev['note'] = 'kept from previous run — fetch failed today'
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
