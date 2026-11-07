"""Print the MoneroOcean hashrate for a wallet as JSON (stdlib only).

Output is always a single JSON object on stdout, e.g. {"hashrate": "19.85 kH/s"},
so it can be used directly as a YASB CustomWidget command with return_format: json.

Wallet resolution order:
  1. first command-line argument
  2. MONERO_WALLET environment variable
  3. DEFAULT_WALLET below
"""

import json
import os
import sys
import urllib.request

DEFAULT_WALLET = "47WAy3LX7uLU8Drp7LNDonBocgSq6MEpM97VwKaRqhiy1Co9PeQ63HdC2ecuhdhqSsYjrwbaZctFuMGfWgVcq6zGMGYg8oG"
API_URL = "https://api.moneroocean.stream/miner/{wallet}/stats"

# MoneroOcean's API rejects the default "Python-urllib/x.y" user agent with HTTP 403.
HEADERS = {
    "User-Agent": "MoneroOceanWidget/1.0",
    "Accept": "application/json",
}


def format_hashrate(value):
    """Format a raw H/s value using an appropriate unit."""
    h = float(value)
    for unit in ("H/s", "kH/s", "MH/s", "GH/s"):
        if h < 1000:
            return f"{h:.2f} {unit}"
        h /= 1000
    return f"{h:.2f} TH/s"


def get_wallet():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    env_wallet = os.environ.get("MONERO_WALLET", "").strip()
    return env_wallet or DEFAULT_WALLET


def fetch_hashrate(wallet):
    """Return the wallet's current hashrate in H/s as a float."""
    request = urllib.request.Request(API_URL.format(wallet=wallet), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    return float(data.get("hash") or 0)


def main():
    try:
        result = format_hashrate(fetch_hashrate(get_wallet()))
    except Exception as exc:  # network error, bad JSON, etc.
        print(f"monero_hashrate: {exc}", file=sys.stderr)
        result = "N/A"
    print(json.dumps({"hashrate": result}))


if __name__ == "__main__":
    main()
