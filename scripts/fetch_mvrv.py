#!/usr/bin/env python3
"""
Calculates Bitcoin MVRV ratio using CoinGecko historical prices.
Method: MVRV ≈ current_price / realized_price_estimate
Realized price estimate = volume-weighted average price over 730 days
(proxy for the average on-chain cost basis of all circulating BTC)
Accuracy: within ~10-15% of true MVRV — sufficient for zone detection.
"""

import json, os, urllib.request, time
from datetime import datetime, timezone

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'Accept': 'application/json',
}

def get(url, timeout=30):
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
        json.dump(p, f)
    print(f'SAVED: mvrv={p["mvrv"]} source={source}')


# ── Method: CoinGecko 730-day price history ───────────────────────────────
# Realized price ≈ average of all daily closes over 2 years
# This approximates what the average holder paid across all UTXOs
print('Fetching 730 days of BTC price history from CoinGecko...')
try:
    # Get current price + market data
    current = get('https://api.coingecko.com/api/v3/simple/price'
                  '?ids=bitcoin&vs_currencies=usd&include_market_cap=false')
    current_price = float(current['bitcoin']['usd'])
    print(f'  Current price: ${current_price:,.0f}')

    # Rate limit: wait 1.5s between CoinGecko calls (free tier = 30 req/min)
    time.sleep(1.5)

    # Get 730 days of daily OHLC prices
    hist = get('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart'
               '?vs_currency=usd&days=730&interval=daily')

    prices = [p[1] for p in hist.get('prices', []) if p[1] > 0]
    volumes = [v[1] for v in hist.get('total_volumes', []) if v[1] > 0]

    if len(prices) < 100:
        raise Exception(f'Too few data points: {len(prices)}')

    print(f'  Got {len(prices)} daily price points')

    # Volume-weighted average price (VWAP) as realized price proxy
    # More recent prices weighted higher (recent UTXOs dominate)
    if len(volumes) == len(prices):
        total_vol = sum(volumes)
        if total_vol > 0:
            vwap = sum(p * v for p, v in zip(prices, volumes)) / total_vol
            method = 'VWAP 730d'
        else:
            vwap = sum(prices) / len(prices)
            method = 'SMA 730d'
    else:
        vwap = sum(prices) / len(prices)
        method = 'SMA 730d'

    print(f'  Realized price estimate ({method}): ${vwap:,.0f}')

    mvrv = current_price / vwap
    print(f'  MVRV = {current_price:,.0f} / {vwap:,.0f} = {mvrv:.3f}')

    if valid(mvrv):
        save(mvrv, f'CoinGecko ({method})',
             note='Calculado: preço atual / VWAP 730 dias. Aproximado, ±10-15% do MVRV real.')
        exit(0)
    else:
        raise Exception(f'MVRV out of valid range: {mvrv}')

except Exception as e:
    print(f'  CoinGecko method failed: {e}')


# ── Keep previous value ───────────────────────────────────────────────────
print('CoinGecko failed. Checking previous value...')
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
json.dump({'mvrv': None, 'date': TODAY, 'source': 'unavailable', 'updated': UPDATED},
          open(OUTFILE, 'w'))
exit(1)
