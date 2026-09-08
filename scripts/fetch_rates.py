"""Fetch BCV USD/EUR and Binance P2P USDT/VES, write rates.json.

Runs from GitHub Actions on a schedule. Each source is independent: if one
fails, the previous value for that key is kept so the app never goes blank.
"""
import json, re, statistics, sys, time, urllib.request, ssl
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "rates.json"
UA = {"User-Agent": "Mozilla/5.0 (rates-bot)", "Accept": "application/json, text/html"}


def get(url, data=None, timeout=20, insecure=False):
    req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
    ctx = ssl._create_unverified_context() if insecure else None  # BCV's cert chain is often broken
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "replace")


def num(s):
    return float(str(s).replace(".", "").replace(",", ".")) if "," in str(s) else float(s)


def bcv_official():
    """Scrape bcv.org.ve: rates live in <div id="dolar"> / <div id="euro"> as strong text like 137,45300000."""
    html = get("https://www.bcv.org.ve/", insecure=True)
    out = {}
    for key, div in (("usd", "dolar"), ("eur", "euro")):
        m = re.search(rf'id="{div}".*?<strong>\s*([\d.,]+)\s*</strong>', html, re.S)
        if m:
            out[key] = num(m.group(1))
    if not out:
        raise ValueError("bcv.org.ve: no rates found in page")
    return out


def bcv_pydolarve():
    o = {}
    for cur, ep in (("usd", "dollar"), ("eur", "euro")):
        j = json.loads(get(f"https://pydolarve.org/api/v2/{ep}?page=bcv&monitor=usd"))
        p = j.get("price") or (j.get("monitors") or {}).get("usd", {}).get("price")
        if p:
            o[cur] = float(p)
    return o


def binance_p2p(trade_type="SELL", rows=10):
    """Median price of the top ads. SELL = you selling USDT for Bs (what matters when you pay in Bs)."""
    body = json.dumps({
        "asset": "USDT", "fiat": "VES", "tradeType": trade_type, "page": 1, "rows": rows,
        "payTypes": [], "publisherType": None,
    }).encode()
    j = json.loads(get("https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search", data=body))
    prices = [float(a["adv"]["price"]) for a in j.get("data", []) if a.get("adv", {}).get("price")]
    if not prices:
        raise ValueError("binance: empty ad list")
    return {"usdt": round(statistics.median(prices), 4), "usdt_min": min(prices), "usdt_max": max(prices)}


def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    rates = dict(prev.get("rates", {}))
    sources = dict(prev.get("sources", {}))
    errors = []

    for name, fn in (("bcv.org.ve", bcv_official), ("pydolarve", bcv_pydolarve)):
        try:
            got = fn()
            for k, v in got.items():
                if k in ("usd", "eur") and v > 0 and (k not in sources or sources[k] != "bcv.org.ve" or name == "bcv.org.ve"):
                    rates[k] = v
                    sources[k] = name
            if "usd" in got and "eur" in got:
                break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")

    try:
        got = binance_p2p()
        rates.update(got)
        sources["usdt"] = "binance-p2p"
    except Exception as e:  # noqa: BLE001
        errors.append(f"binance: {e}")

    payload = {
        "updated_at": int(time.time() * 1000),
        "rates": rates,
        "sources": sources,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2))
    # Fail loudly only if we have nothing at all.
    if not rates:
        sys.exit(1)


if __name__ == "__main__":
    main()
