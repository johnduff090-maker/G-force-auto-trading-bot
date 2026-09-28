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


print("\n[5] User Account Lookup + Free Trial Cash")

# --- extra stubs needed by the claim/expiry paths ---
SENT, ANSWERS = [], []
main.bot.send_message = lambda uid, text, **kw: SENT.append((uid, str(text)))
main.bot.send_photo = lambda uid, img, **kw: SENT.append((uid, 'PHOTO:' + str(kw.get('caption', ''))))
main.bot.answer_callback_query = lambda cid, text=None, **kw: ANSWERS.append(str(text))
main.bot.edit_message_text = lambda *a, **k: None
main.bot.edit_message_caption = lambda *a, **k: None
main.requires_subscription_wall = lambda *a, **k: False
main.subscription_settings['enabled'] = False

# Give Alice an active plan + pending plan so the lookup has data
main.bot_plans['plan1'] = {'name': 'Starter Plan', 'min': 10, 'max': 1000, 'profit': 2.0, 'length': 48}
main.user_db[111]['active_plans'] = [{
    'id': 'x1', 'macro': 'plan1', 'amount': 75.0, 'profit_pct': 2.0,
    'length_hours': 48, 'start_time': time.time(), 'last_accrual': time.time(),
    'earned': 1.5, 'status': 'active'
}]

# /api/get_account
r = post('/api/get_account', {'pin': PIN, 'uid': 111})
check("get_account 200", r.status_code == 200)
acct = r.json()
check("get_account name", acct.get('name') == 'Alice (@alice)', f"= {acct.get('name')}")
check("get_account plan name", acct['active_plans'][0]['name'] == 'Starter Plan')
check("get_account invested amount", acct['active_plans'][0]['amount'] == 75.0)
check("get_account total invested", acct['total_active_invested'] == 75.0)
check("get_account 404 unknown", post('/api/get_account', {'pin': PIN, 'uid': 999999}).status_code == 404)

# /api/get_free_trial
r = post('/api/get_free_trial', {'pin': PIN})
check("get_free_trial 200", r.status_code == 200)
ft = r.json()
check("get_free_trial has settings", 'msg_offer' in ft.get('settings', {}))
check("get_free_trial lists users", len(ft.get('users', [])) == 2)

# /api/send_free_trial to one user -> creates offer + sends message in thread
r = post('/api/send_free_trial', {'pin': PIN, 'target_mode': 'individual', 'target_uid': 111,
                                  'amount': 50, 'expires_days': 3, 'image_url': '',
                                  'button_text': 'Claim Now', 'msg_offer': 'FREE {amount} for {days}d!',
                                  'msg_claimed': 'got it', 'msg_reminder': 'remind {days_left}', 'msg_expired': 'expired {amount}'})
check("send_free_trial 200", r.status_code == 200)
offer_id = r.json().get('offer_id')
check("send_free_trial offer created", offer_id in main.free_offers)
check("send_free_trial no claim_deadline (unlimited claim)", 'claim_deadline' not in main.free_offers.get(offer_id, {}))
check("send_free_trial persisted edited texts", main.free_trial_settings.get('button_text') == 'Claim Now')
time.sleep(1.5)  # let the sender thread finish
check("offer delivered to user", any(uid == 111 and 'FREE 50.00 for 3' in t for uid, t in SENT),
      f"= {[t for uid, t in SENT if uid == 111][-1:]}")

# simulate the user pressing the claim button via the real callback handler
class FakeCall:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid)
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=uid), message_id=1)
        self.id = 'cb1'

dep_before = main.user_db[111]['deposit']
main.handle_inline(FakeCall(f'claim_trial_{offer_id}', 111))
check("claim credits deposit", abs(main.user_db[111]['deposit'] - (dep_before + 50.0)) < 1e-9,
      f"= {main.user_db[111]['deposit']}")
ckey = f"{offer_id}_111"
check("claim recorded", ckey in main.free_trial_claims)
check("claim expiry ~3 days", abs(main.free_trial_claims[ckey]['expiry_time'] - (time.time() + 3 * 86400)) < 60)

# double claim is rejected
main.handle_inline(FakeCall(f'claim_trial_{offer_id}', 111))
check("double claim rejected", any('already claimed' in a for a in ANSWERS))

# expiry pass: make the claim overdue, run one sweep iteration
main.free_trial_claims[ckey]['expiry_time'] = time.time() - 1
threading.Thread(target=main.free_trial_expiry_loop, daemon=True).start()
time.sleep(2)
check("claim marked expired", main.free_trial_claims[ckey]['status'] == 'expired')
check("unused cash removed", abs(main.user_db[111]['deposit'] - dep_before) < 1e-9,
      f"= {main.user_db[111]['deposit']}")
check("expiry alert sent", any(uid == 111 and 'expired' in t.lower() for uid, t in SENT))

# daily reminder: fresh claim for Bob with an overdue reminder timestamp
offer2 = {'id': 'off2', 'amount': 25.0, 'expires_days': 3, 'image_url': '', 'created_at': time.time()}
main.free_offers['off2'] = offer2
main.handle_inline(FakeCall('claim_trial_off2', 222))
ck2 = 'off2_222'
main.free_trial_claims[ck2]['last_reminder'] = time.time() - 90000  # overdue for daily reminder
threading.Thread(target=main.free_trial_expiry_loop, daemon=True).start()
time.sleep(2)
check("daily reminder sent", any(uid == 222 and 'remind' in t.lower() for uid, t in SENT))
check("reminder updates timestamp", main.free_trial_claims[ck2]['last_reminder'] > time.time() - 60)
check("claim still active (not expired)", main.free_trial_claims[ck2]['status'] == 'claimed')

# broadcast to ALL users
r = post('/api/send_free_trial', {'pin': PIN, 'target_mode': 'all', 'amount': 10, 'expires_days': 1})
check("send_free_trial all queued", r.json().get('queued') == 2)

server.shutdown()

print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
raise SystemExit(1 if FAIL else 0)
