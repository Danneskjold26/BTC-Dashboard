#!/usr/bin/env python3
"""
Busca o MVRV do Bitcoin e salva em data/mvrv.json.

Fonte principal: BGeometrics (MVRV on-chain real, plano gratuito).
  - Usa o endpoint /last e confere a DATA do dado: se tiver mais de
    MAX_AGE_DAYS dias, o valor é descartado (evita gravar dado velho como se fosse de hoje).

Reserva: estimativa Kraken (preço / VWAP de 720 dias) × fator de calibração.
  - O fator se calibra SOZINHO: todo dia em que a BGeometrics responde, o script
    calcula fator = MVRV real ÷ estimativa crua e guarda no mvrv.json.
    Se um dia a BGeometrics falhar, a estimativa usa esse último fator salvo.
  - Opcional: a variável MVRV_CALIBRATION (GitHub → Settings → Secrets and
    variables → Actions → Variables) força um fator manual.
"""

import json, os, urllib.request
from datetime import datetime, timezone

NOW      = datetime.now(timezone.utc)
TODAY    = NOW.strftime('%Y-%m-%d')
UPDATED  = NOW.strftime('%Y-%m-%dT%H:%M:%SZ')
OUTFILE  = 'data/mvrv.json'
MAX_AGE_DAYS = 4
DEFAULT_FACTOR = 1.549
os.makedirs('data', exist_ok=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)', 'Accept': 'application/json'}


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def valid(v):
    try:
        return 0.3 < float(v) < 15
    except (TypeError, ValueError):
        return False


def load_previous():
    try:
        with open(OUTFILE) as f:
            return json.load(f)
    except Exception:
        return {}


def row_date(row):
    """Extrai a data (YYYY-MM-DD) de uma linha da BGeometrics, em vários formatos possíveis."""
    for k in ('d', 'date', 'day', 'theDay', 'time'):
        v = row.get(k)
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
    for k in ('unixTs', 'ts', 't', 'timestamp'):
        v = row.get(k)
        try:
            v = float(v)
            if v > 1e11:
                v /= 1000
            return datetime.fromtimestamp(v, tz=timezone.utc).strftime('%Y-%m-%d')
        except (TypeError, ValueError):
            pass
    return None


def row_value(row):
    for k in ('mvrv', 'mvrvRatio', 'mvrv_ratio', 'value', 'v'):
        if k in row and valid(row[k]):
            return float(row[k])
    return None


def fetch_bgeometrics():
    """Retorna (mvrv, data) do dado MAIS RECENTE, ou levanta exceção."""
    last_err = None
    for url in ('https://bitcoin-data.com/v1/mvrv/last', 'https://bitcoin-data.com/v1/mvrv'):
        try:
            d = get(url)
            rows = d
            if isinstance(d, dict):
                for k in ('content', 'data', 'results'):
                    if isinstance(d.get(k), list):
                        rows = d[k]
                        break
                else:
                    rows = [d]
            rows = [r for r in rows if isinstance(r, dict) and row_value(r) and row_date(r)]
            if not rows:
                raise ValueError(f'formato inesperado: {str(d)[:120]}')
            newest = max(rows, key=row_date)          # não depende da ordem da lista
            mvrv, date = row_value(newest), row_date(newest)
            age = (NOW.date() - datetime.strptime(date, '%Y-%m-%d').date()).days
            print(f'  {url} → mvrv={mvrv} data={date} ({age} dias)')
            if age > MAX_AGE_DAYS:
                raise ValueError(f'dado desatualizado ({date}, {age} dias)')
            return mvrv, date
        except Exception as e:
            print(f'  {url} → falhou: {e}')
            last_err = e
    raise last_err


def fetch_kraken_raw():
    """Estimativa crua: preço atual / VWAP dos últimos ~720 dias (Kraken)."""
    d = get('https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440')
    if d.get('error'):
        raise ValueError(str(d['error']))
    key = [k for k in d['result'] if k != 'last'][0]
    # linha: [time, open, high, low, close, vwap, volume, count]
    rows = [r for r in d['result'][key] if float(r[6]) > 0]
    if len(rows) < 100:
        raise ValueError(f'poucos candles: {len(rows)}')
    tpv = vol = 0.0
    for r in rows:
        h, l, c, v = float(r[2]), float(r[3]), float(r[4]), float(r[6])
        tpv += (h + l + c) / 3 * v
        vol += v
    price = float(rows[-1][4])
    raw = price / (tpv / vol)
    print(f'  Kraken: {len(rows)} candles, preço ${price:,.0f}, estimativa crua {raw:.3f}')
    return raw


def save(payload):
    payload.setdefault('updated', UPDATED)
    with open(OUTFILE, 'w') as f:
        json.dump(payload, f, indent=2)
    print('SALVO:', json.dumps(payload, ensure_ascii=False))


prev = load_previous()

print('1) Estimativa Kraken (usada para calibrar e como reserva)...')
try:
    raw = fetch_kraken_raw()
except Exception as e:
    print(f'  Kraken falhou: {e}')
    raw = None

print('2) MVRV real na BGeometrics...')
try:
    mvrv, date = fetch_bgeometrics()
    payload = {'mvrv': round(mvrv, 3), 'date': date, 'source': 'BGeometrics (on-chain)'}
    if raw:
        payload['raw_vwap_mvrv'] = round(raw, 4)
        payload['auto_calibration'] = round(mvrv / raw, 4)   # guardado para os dias em que a BGeometrics falhar
    save(payload)
    raise SystemExit(0)
except SystemExit:
    raise
except Exception as e:
    print(f'  BGeometrics indisponível: {e}')

print('3) Usando a estimativa Kraken calibrada...')
manual = os.environ.get('MVRV_CALIBRATION', '').strip().replace(',', '.')
try:
    factor, origin = float(manual), 'manual (MVRV_CALIBRATION)'
except ValueError:
    if valid(prev.get('auto_calibration')):
        factor, origin = float(prev['auto_calibration']), 'automática (último dia com BGeometrics)'
    else:
        factor, origin = DEFAULT_FACTOR, 'padrão (mar/2026)'

if raw and valid(raw * factor):
    payload = {'mvrv': round(raw * factor, 3), 'date': TODAY,
               'source': 'Estimativa Kraken calibrada', 'raw_vwap_mvrv': round(raw, 4),
               'calibration_used': round(factor, 4), 'calibration_origin': origin}
    if valid(prev.get('auto_calibration')):
        payload['auto_calibration'] = prev['auto_calibration']
    save(payload)
    raise SystemExit(0)

print('4) Tudo falhou — mantendo o valor anterior, marcado como antigo.')
if valid(prev.get('mvrv')):
    prev['note'] = 'valor mantido da última execução bem-sucedida'
    prev['updated'] = UPDATED
    save(prev)
    raise SystemExit(0)

save({'mvrv': None, 'date': TODAY, 'source': 'indisponível'})
raise SystemExit(1)
