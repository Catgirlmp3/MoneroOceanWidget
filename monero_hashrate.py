import json
import sys
import requests

WALLET = sys.argv[1] if len(sys.argv) > 1 else ""
API_URL = f"https://api.moneroocean.stream/miner/{WALLET}/stats"

def fmt(h):
    h = float(h)
    for unit in ("H/s", "kH/s", "MH/s", "GH/s"):
        if h < 1000:
            return f"{h:.2f} {unit}"
        h /= 1000
    return f"{h:.2f} TH/s"

try:
    r = requests.get(API_URL, timeout=10)
    r.raise_for_status()
    print(json.dumps({"hashrate": fmt(r.json()["hash"])}))
except Exception:
    print(json.dumps({"hashrate": "N/A"}))
