"""End-to-end test for the keyless deposit detector + Key Vault dashboard.

Imports main.py, stubs out Telegram/email/DB side-effects, injects fake users
whose wallets are real on-chain addresses (public exchange wallets), then:
  1. reads live balances for every deposit network,
  2. checks the high-water-mark baseline / credit logic,
  3. drives the real HTTP endpoints (verify_pin, all_wallets, refresh_balance,
     manual_credit) over a locally started web server.

Run:  python test_integration.py
"""
import sys
import types
import threading
import time
from http.server import HTTPServer

import requests

# --- Stub bip_utils (heavy crypto lib, only used for wallet GENERATION, which
# this test never calls). This lets us import main.py without building it. ---
if "bip_utils" not in sys.modules:
    _stub = types.ModuleType("bip_utils")
    for _name in ("Bip39SeedGenerator", "Bip44", "Bip44Coins", "Bip44Changes"):
        setattr(_stub, _name, type(_name, (), {}))
    sys.modules["bip_utils"] = _stub

import main

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name} {extra}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


# ---------------------------------------------------------------------------
# Stub out every real-world side effect so crediting doesn't hit Telegram etc.
# ---------------------------------------------------------------------------
main.bot.send_message = lambda *a, **k: None
main.broadcast_real_deposit = lambda *a, **k: None
main.send_email_async = lambda *a, **k: None
main.process_referral_commission = lambda *a, **k: None
main.check_and_trigger_auto_buy = lambda *a, **k: None
main.save_database = lambda *a, **k: None
main.log_tx = lambda *a, **k: None
main.get_crypto_price = lambda c: 1.0 if 'USDT' in c else (0.12 if c == 'TRX' else 65000.0)

# Real public holder addresses (read-only; we never move funds).
BEP20_ADDR = "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3"   # Binance BSC hot
ERC20_ADDR = "0x28C6c06298d514Db089934071355E5743bf21d60"   # Binance 14 (ETH)
TRON_ADDR = "TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs"            # Binance TRON hot
BTC_ADDR = "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97"

main.user_db.clear()
main.user_db[111] = {
    'first_name': 'Alice', 'username': 'alice', 'deposit': 0.0, 'balance': 0.0,
    'wallets': {
        'USDT_BEP20': {'address': BEP20_ADDR, 'private_key': 'PK_BEP20', 'total_deposited': 0.0, 'admin_swept_total': 0.0},
        'USDT_TRC20': {'address': TRON_ADDR, 'private_key': 'PK_TRC20', 'total_deposited': 0.0, 'admin_swept_total': 0.0},
    },
}
main.user_db[222] = {
    'first_name': 'Bob', 'username': 'No Username', 'deposit': 0.0, 'balance': 0.0,
    'wallets': {
        'USDT_ERC20': {'address': ERC20_ADDR, 'private_key': 'PK_ERC20', 'total_deposited': 0.0, 'admin_swept_total': 0.0},
        'BTC': {'address': BTC_ADDR, 'private_key': 'PK_BTC', 'total_deposited': 0.0, 'admin_swept_total': 0.0},
        'TRX': {'address': TRON_ADDR, 'private_key': 'PK_TRX', 'total_deposited': 0.0, 'admin_swept_total': 0.0},
    },
}


print("\n[1] Live keyless balance reads (every deposit network)")
for uid, curr in [(111, 'USDT_BEP20'), (111, 'USDT_TRC20'), (222, 'USDT_ERC20'), (222, 'BTC'), (222, 'TRX')]:
    addr = main.user_db[uid]['wallets'][curr]['address']
    bal = main.get_onchain_balance(addr, curr)
    check(f"balance {curr}", isinstance(bal, float) and bal > 0, f"= {bal}")


print("\n[2] High-water-mark baseline / migration logic")
# Fresh USDT wallet with nothing credited -> baseline 0
w = {'total_deposited': 0.0}
check("fresh USDT baseline == 0", main._credited_baseline(w, 'USDT_BEP20', 500.0) == 0.0)
# USDT wallet with $50 already credited -> baseline 50 (1:1)
w = {'total_deposited': 50.0}
check("USDT baseline == credited USD", main._credited_baseline(w, 'USDT_BEP20', 500.0) == 50.0)
# non-USDT with prior credit -> baseline == onchain (avoid double credit)
w = {'total_deposited': 30.0}
check("non-USDT prior credit baseline == onchain", main._credited_baseline(w, 'BTC', 1.25) == 1.25)
# non-USDT fresh -> 0
w = {'total_deposited': 0.0}
check("fresh non-USDT baseline == 0", main._credited_baseline(w, 'BTC', 1.25) == 0.0)


print("\n[3] credit_deposit updates user balances")
main.user_db[111]['deposit'] = 0.0
main.user_db[111]['wallets']['USDT_BEP20']['total_deposited'] = 0.0
usd = main.credit_deposit(111, 'USDT_BEP20', 12.5)
check("credit_deposit returns usd", abs(usd - 12.5) < 1e-9, f"= {usd}")
check("user deposit incremented", abs(main.user_db[111]['deposit'] - 12.5) < 1e-9)
check("wallet total_deposited incremented", abs(main.user_db[111]['wallets']['USDT_BEP20']['total_deposited'] - 12.5) < 1e-9)
# reset for HTTP tests
main.user_db[111]['deposit'] = 0.0
main.user_db[111]['wallets']['USDT_BEP20']['total_deposited'] = 0.0
main.user_db[111]['wallets']['USDT_BEP20'].pop('credited_crypto', None)


print("\n[4] Real HTTP endpoints via the actual dashboard handler")
server = HTTPServer(('127.0.0.1', 8099), main.AdminDashboardHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.5)
base = "http://127.0.0.1:8099"
PIN = main.ADMIN_PIN


def post(path, body):
    return requests.post(base + path, json=body, timeout=20)


# verify_pin
r = post('/api/verify_pin', {'pin': PIN})
check("verify_pin correct", r.status_code == 200)
r = post('/api/verify_pin', {'pin': 'wrong-pin'})
check("verify_pin rejects bad pin", r.status_code == 401)

# all_wallets: every user with generated wallets, keys present
r = post('/api/all_wallets', {'pin': PIN})
check("all_wallets 200", r.status_code == 200)
data = r.json()
uids = {u['uid'] for u in data.get('users', [])}
check("all_wallets lists both users", uids == {111, 222}, f"= {uids}")
alice = next(u for u in data['users'] if u['uid'] == 111)
check("all_wallets exposes private key", any(w['private_key'] == 'PK_BEP20' for w in alice['wallets']))
check("all_wallets shows display name", alice['name'] == 'Alice (@alice)', f"= {alice['name']}")
bob = next(u for u in data['users'] if u['uid'] == 222)
check("all_wallets name without username", bob['name'] == 'Bob', f"= {bob['name']}")
check("all_wallets requires pin", post('/api/all_wallets', {'pin': 'x'}).status_code == 401)

# refresh_balance: live read of a single wallet
r = post('/api/refresh_balance', {'pin': PIN, 'uid': 111, 'network': 'USDT_BEP20'})
check("refresh_balance 200", r.status_code == 200)
rb = r.json()
check("refresh_balance success + positive", rb.get('success') and rb.get('live_balance', 0) > 0, f"= {rb.get('live_balance')}")
check("refresh_balance uncredited detected", rb.get('uncredited', 0) > 0, f"= {rb.get('uncredited')}")

# manual_credit: credit the uncredited on-chain amount, then nothing left to credit
before = main.user_db[111]['deposit']
r = post('/api/manual_credit', {'pin': PIN, 'uid': 111, 'network': 'USDT_BEP20'})
check("manual_credit 200", r.status_code == 200)
mc = r.json()
check("manual_credit success", mc.get('success') is True, f"= {mc}")
check("manual_credit moved balance up", main.user_db[111]['deposit'] > before, f"= {main.user_db[111]['deposit']}")
# second credit should find nothing new (idempotent)
r2 = post('/api/manual_credit', {'pin': PIN, 'uid': 111, 'network': 'USDT_BEP20'})
check("manual_credit idempotent (no double credit)", r2.json().get('success') is False, f"= {r2.json()}")

server.shutdown()

print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
raise SystemExit(1 if FAIL else 0)
