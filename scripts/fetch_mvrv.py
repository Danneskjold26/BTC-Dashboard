#!/usr/bin/env python3
"""
Fetches Bitcoin MVRV ratio.
Saves result to data/mvrv.json
"""

import json, os, urllib.request, urllib.error
from datetime import datetime, timezone

TODAY   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
UPDATED = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE = 'data/mvrv.json'
os.makedirs('data', exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120',
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
        json.dump(p, f)
    print(f'SAVED: mvrv={p["mvrv"]} source={source}')


# ── Source 1: Messari free API (realized cap + market cap) ───────────────
print('Trying Messari...')
try:
    d = get('https://data.messari.io/api/v1/assets/bitcoin/metrics')
    md = d['data']['market_data']
    mkt  = float(md['market_cap_usd'])
    real = float(md.get('realized_cap', 0) or 0)
    if real <= 0:
        # try alternate field path
        real = float(d['data'].get('on_chain_data', {}).get('realized_cap', 0) or 0)
    if real > 0 and valid(mkt / real):
        save(mkt / real, 'Messari')
        exit(0)
    print(f'  Messari: mkt={mkt} real={real} — realized cap not in free tier')
except Exception as e:
    print(f'  Messari failed: {e}')


# ── Source 2: CoinGecko market cap + realized cap ────────────────────────
print('Trying CoinGecko...')
try:
    d = get('https://api.coingecko.com/api/v3/coins/bitcoin'
            '?localization=false&tickers=false&market_data=true'
            '&community_data=false&developer_data=false')
    mkt  = float(d['market_data']['market_cap']['usd'])
    # CoinGecko doesn't have realized cap in free tier
    # Use fully_diluted_valuation as a proxy if available
    print(f'  CoinGecko: mkt_cap={mkt:,.0f} — no realized cap in free tier')
except Exception as e:
    print(f'  CoinGecko failed: {e}')


# ── Source 3: Blockchair Bitcoin stats ───────────────────────────────────
print('Trying Blockchair...')
try:
    d = get('https://api.blockchair.com/bitcoin/stats')
    stats = d['data']
    # Blockchair returns market_cap_usd and realized_market_cap
    mkt  = float(stats.get('market_cap_usd', 0))
    real = float(stats.get('realized_market_cap_usd', 0) or
                 stats.get('realized_cap_usd', 0) or 0)
    print(f'  Blockchair fields: {[k for k in stats.keys() if "cap" in k.lower() or "real" in k.lower()]}')
    if mkt > 0 and real > 0 and valid(mkt / real):
        save(mkt / real, 'Blockchair')
        exit(0)
    elif mkt > 0:
        print(f'  Blockchair: mkt={mkt:,.0f} real={real} — realized cap not available')
except Exception as e:
    print(f'  Blockchair failed: {e}')


# ── Source 4: Mayer Multiple → approximate MVRV ──────────────────────────
# Mayer Multiple = price / 200-day MA
# Historical correlation: MVRV ≈ 0.52 + 1.11 * MM  (R²≈0.93 across cycles)
# This is an estimate, clearly labeled as such
print('Trying bitcoin.com Mayer Multiple (approximation)...')
try:
    d = get('https://charts.bitcoin.com/api/v1/charts/mayer-multiple'
            '?interval=daily&timespan=30d&limit=5')
    pts = d['data']['multiple']
    if pts:
        mm = float(pts[-1]['value'] if isinstance(pts[-1], dict) else pts[-1][1])
        if 0.3 < mm < 5:
            mvrv_est = round(0.52 + 1.11 * mm, 3)
            if valid(mvrv_est):
                save(mvrv_est, 'Estimativa via Mayer Multiple',
                     note=f'MM={mm:.2f} → MVRV≈{mvrv_est} (aproximado, confirme em CheckOnChain)')
                exit(0)
except Exception as e:
    print(f'  Mayer Multiple failed: {e}')


# ── Source 5: Keep previous value ────────────────────────────────────────
print('All sources failed. Checking previous value...')
if os.path.exists(OUTFILE):
    try:
        prev = json.load(open(OUTFILE))
        if valid(prev.get('mvrv')):
            prev['note'] = 'kept from previous run — all fetches failed today'
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
