"""Fetch BCV USD/EUR and Binance P2P USDT/VES, write rates.json.

Runs from GitHub Actions on a schedule. Each source is independent: if one
fails, the previous value for that key is kept so the app never goes blank.
"""
import json, re, statistics, sys, time, urllib.request, ssl
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "rates.json"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
}
DEBUG = {}


def get(url, data=None, timeout=20, insecure=False):
    req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
    ctx = ssl._create_unverified_context() if insecure else None  # BCV's cert chain is often broken
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


def num(s):
    s = str(s).strip()
    if "," in s and "." in s:          # 1.234,56 -> 1234.56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                     # 967,45 -> 967.45
        s = s.replace(",", ".")
    return float(s)


def plausible(v):
    return 50 < v < 100000


# ---------- BCV sources (tried in order until usd AND eur are found) ----------

def bcv_official():
    """Scrape bcv.org.ve. Looks for the number that follows 'USD' / 'EUR' markers."""
    html = get("https://www.bcv.org.ve/", insecure=True)
    DEBUG["bcv_len"] = len(html)
    DEBUG["bcv_title"] = (re.search(r"<title>(.*?)</title>", html, re.S | re.I) or [None, ""])[1].strip()[:80]
    i = html.lower().find("dolar")
    DEBUG["bcv_snippet"] = re.sub(r"\s+", " ", html[i:i + 400]) if i >= 0 else "no 'dolar' in page"
    out = {}
    for key, marks in (("usd", ("USD", "dolar")), ("eur", ("EUR", "euro"))):
        for mk in marks:
            m = re.search(re.escape(mk) + r".{0,400}?(\d{1,3}(?:\.\d{3})*,\d{2,8}|\d+\.\d{2,8})", html, re.S)
            if m and plausible(num(m.group(1))):
                out[key] = num(m.group(1))
                break
    if not out:
        raise ValueError("no rates found in page")
    return out


def dolarapi_ve():
    out = {}
    j = json.loads(get("https://ve.dolarapi.com/v1/dolares/oficial"))
    p = j.get("promedio") or j.get("venta") or j.get("compra")
    if p and plausible(float(p)):
        out["usd"] = float(p)
    try:
        j = json.loads(get("https://ve.dolarapi.com/v1/euros/oficial"))
        p = j.get("promedio") or j.get("venta")
        if p and plausible(float(p)):
            out["eur"] = float(p)
    except Exception:  # noqa: BLE001
        pass
    return out


def dolarvzla():
    j = json.loads(get("https://api.dolarvzla.com/public/exchange-rate"))
    cur = j.get("current") or j
    out = {}
    if cur.get("usd"):
        out["usd"] = float(cur["usd"])
    if cur.get("eur"):
        out["eur"] = float(cur["eur"])
    return out


def bcv_rafnixg():
    j = json.loads(get("https://bcv-api.rafnixg.dev/rates/"))
    out = {}
    if j.get("dollar"):
        out["usd"] = float(j["dollar"])
    if j.get("euro"):
        out["eur"] = float(j["euro"])
    return out


BCV_SOURCES = (("bcv.org.ve", bcv_official), ("dolarapi", dolarapi_ve), ("dolarvzla", dolarvzla), ("rafnixg", bcv_rafnixg))


def eur_usd_market():
    """EUR/USD cross rate to derive BCV EUR when no source gives it."""
    for url, path in (("https://open.er-api.com/v6/latest/EUR", ("rates", "USD")),
                      ("https://api.frankfurter.app/latest?from=EUR&to=USD", ("rates", "USD"))):
        try:
            j = json.loads(get(url))
            v = float(j[path[0]][path[1]])
            if 0.7 < v < 1.6:
                return v
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("no EUR/USD source")


# ---------- Binance P2P ----------

# Binance payment-method identifiers for VES. If one is wrong, rates.json -> debug.binance_methods_seen
# lists the identifiers Binance actually returned so it can be corrected.
BANKS = {
    "Mercantil": ["Mercantil"],
    "PagoMovil": ["PagoMovil"],
    "Banesco": ["Banesco"],
    "Provincial": ["Provincial"],
    "BancoDeVenezuela": ["BancoDeVenezuela", "BANCODEVENEZUELA"],
}


def binance_ads(pay_types=None, trade_type="SELL", rows=10):
    body = json.dumps({
        "asset": "USDT", "fiat": "VES", "tradeType": trade_type, "page": 1, "rows": rows,
        "payTypes": pay_types or [], "publisherType": None,
    }).encode()
    j = json.loads(get("https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search", data=body))
    return j.get("data", [])


def binance_p2p():
    """Median of the top sell ads (you selling USDT for Bs): overall and per bank."""
    ads = binance_ads(rows=20)
    prices = [float(a["adv"]["price"]) for a in ads if a.get("adv", {}).get("price")]
    if not prices:
        raise ValueError("empty ad list")
    seen = set()
    for a in ads:
        for m in a.get("adv", {}).get("tradeMethods", []) or []:
            if m.get("identifier"):
                seen.add(m["identifier"])
    DEBUG["binance_methods_seen"] = sorted(seen)
    out = {"usdt": round(statistics.median(prices[:10]), 4), "usdt_min": min(prices), "usdt_max": max(prices), "usdt_banks": {}}
    for bank, ids in BANKS.items():
        try:
            bp = [float(a["adv"]["price"]) for a in binance_ads(pay_types=ids) if a.get("adv", {}).get("price")]
            if bp:
                out["usdt_banks"][bank] = round(statistics.median(bp), 4)
            time.sleep(0.4)
        except Exception as e:  # noqa: BLE001
            DEBUG[f"binance_{bank}"] = str(e)[:120]
    return out


# ---------- main ----------

def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    rates = dict(prev.get("rates", {}))
    sources = dict(prev.get("sources", {}))
    errors = []
    fresh = {}

    for name, fn in BCV_SOURCES:
        try:
            got = fn()
            for k in ("usd", "eur"):
                if k not in fresh and got.get(k) and plausible(got[k]):
                    fresh[k] = got[k]
                    sources[k] = name
            if "usd" in fresh and "eur" in fresh:
                break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")

    if "usd" in fresh and "eur" not in fresh:
        try:
            fresh["eur"] = round(fresh["usd"] * eur_usd_market(), 4)
            sources["eur"] = f"derived ({sources['usd']} × EUR/USD)"
        except Exception as e:  # noqa: BLE001
            errors.append(f"eur derive: {e}")

    rates.update(fresh)

    try:
        b = binance_p2p()
        rates.update(b)
        sources["usdt"] = "binance-p2p"
    except Exception as e:  # noqa: BLE001
        errors.append(f"binance: {e}")

    payload = {
        "updated_at": int(time.time() * 1000),
        "rates": rates,
        "sources": sources,
        "errors": errors,
        "debug": DEBUG,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not rates:
        sys.exit(1)


if __name__ == "__main__":
    main()
