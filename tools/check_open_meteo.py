"""Find out why Python cannot get the Open-Meteo forecast on this computer. Run: python check_open_meteo.py"""
import socket
import time

import requests
import urllib3.util.connection as conn

URL = "https://api.open-meteo.com/v1/forecast?latitude=14.6&longitude=121&daily=precipitation_sum"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}

try:
    print("Addresses:", sorted({a[4][0] for a in socket.getaddrinfo("api.open-meteo.com", 443)}))
except OSError as e:
    print("Address lookup failed:", e)
px = requests.utils.get_environ_proxies(URL)
print("Proxy seen by Python:", {k: v for k, v in px.items() if k in ("http", "https", "all")} or "none")
for name, family, headers in [("1. default", None, {}), ("2. IPv4 only", socket.AF_INET, {}),
                              ("3. IPv6 only", socket.AF_INET6, {}), ("4. browser user agent", None, UA)]:
    old = conn.allowed_gai_family
    if family:
        conn.allowed_gai_family = lambda f=family: f
    t = time.time()
    try:
        r = requests.get(URL, headers=headers, timeout=(8, 15))
        print(f"{name}: HTTP {r.status_code} in {time.time() - t:.1f} s")
    except Exception as e:
        print(f"{name}: {type(e).__name__} after {time.time() - t:.1f} s")
    finally:
        conn.allowed_gai_family = old
