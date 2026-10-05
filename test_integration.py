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
REAL_AUTO_BUY = main.check_and_trigger_auto_buy  # keep the real one for [6]
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
check("get_account exposes plan id", acct['active_plans'][0].get('id') == 'x1')
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

# expiry pass: make the claim overdue, run one sweep
main.free_trial_claims[ckey]['expiry_time'] = time.time() - 1
main.sweep_free_trial_claims_once()
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
main.sweep_free_trial_claims_once()
check("daily reminder sent", any(uid == 222 and 'remind' in t.lower() for uid, t in SENT))
check("reminder updates timestamp", main.free_trial_claims[ck2]['last_reminder'] > time.time() - 60)
check("claim still active (not expired)", main.free_trial_claims[ck2]['status'] == 'claimed')

# broadcast to ALL users
r = post('/api/send_free_trial', {'pin': PIN, 'target_mode': 'all', 'amount': 10, 'expires_days': 1})
check("send_free_trial all queued", r.json().get('queued') == 2)


print("\n[6] Plan purchase alerts + admin termination")

main.ADMIN_IDS = [999]
main.user_db[222]['active_plans'] = []

# --- admin alert fires when a plan is activated (auto-buy path, end-to-end) ---
main.user_db[222]['deposit'] = 500.0
main.user_db[222]['pending_plan'] = 'plan1'
SENT.clear()
REAL_AUTO_BUY(222)
new_plan = main.user_db[222]['active_plans'][-1]
check("auto-buy activated plan", new_plan['status'] == 'active' and new_plan['macro'] == 'plan1')
check("auto-buy deducted deposit", abs(main.user_db[222]['deposit']) < 1e-9, f"= {main.user_db[222]['deposit']}")
check("admin purchase alert sent",
      any(uid == 999 and 'NEW PLAN ACTIVATED' in t and 'Starter Plan' in t for uid, t in SENT),
      f"= {[t for uid, t in SENT if uid == 999][-1:]}")

# --- terminate_plan endpoint: guards ---
check("terminate_plan rejects bad pin",
      post('/api/terminate_plan', {'pin': 'x', 'uid': 222, 'plan_id': new_plan['id']}).status_code == 401)
check("terminate_plan unknown user",
      post('/api/terminate_plan', {'pin': PIN, 'uid': 424242, 'plan_id': 'zz'}).status_code == 400)
check("terminate_plan unknown plan",
      post('/api/terminate_plan', {'pin': PIN, 'uid': 222, 'plan_id': 'zz'}).status_code == 400)

# --- real termination: refund once, stop accrual, notify user + admin ---
dep_before = main.user_db[222]['deposit']
SENT.clear()
r = post('/api/terminate_plan', {'pin': PIN, 'uid': 222, 'plan_id': new_plan['id'],
                                 'reason': 'Trading plan cancel due to violation'})
check("terminate_plan 200", r.status_code == 200, f"= {r.text}")
check("terminate refunded principal", abs(r.json().get('refunded', 0) - 500.0) < 1e-9)
check("refund added to deposit", abs(main.user_db[222]['deposit'] - (dep_before + 500.0)) < 1e-9)
check("plan status terminated", new_plan['status'] == 'terminated')
check("reason stored on plan", new_plan.get('terminated_reason') == 'Trading plan cancel due to violation')
check("user got termination notice with reason",
      any(uid == 222 and 'violation' in t for uid, t in SENT))
check("admin got termination notice",
      any(uid == 999 and 'PLAN TERMINATED' in t for uid, t in SENT))

# idempotent: second termination -> 400, deposit unchanged
r2 = post('/api/terminate_plan', {'pin': PIN, 'uid': 222, 'plan_id': new_plan['id']})
check("terminate_plan idempotent (no double refund)",
      r2.status_code == 400 and abs(main.user_db[222]['deposit'] - (dep_before + 500.0)) < 1e-9)

# terminated plan accrues nothing even with hours elapsed
new_plan['last_accrual'] = time.time() - 7200
bal_before = main.user_db[222]['balance']
main.process_accruals(222)
check("no accrual after termination", main.user_db[222]['balance'] == bal_before)
check("earned unchanged after termination", new_plan['earned'] == 0.0)

# terminate Alice's plan too
r = post('/api/terminate_plan', {'pin': PIN, 'uid': 111, 'plan_id': 'x1'})
check("alice plan terminated + refunded", r.json().get('refunded') == 75.0)


print("\n[7] Free trial expiry never touches real deposit money")

main.user_db[333] = {'first_name': 'Carol', 'username': 'carol', 'deposit': 100.0,
                     'balance': 0.0, 'active_plans': [], 'wallets': {}}

# claim a $50 trial -> deposit 150, trial_credit 50
main.free_offers['off3'] = {'id': 'off3', 'amount': 50.0, 'expires_days': 2,
                            'image_url': '', 'created_at': time.time()}
main.handle_inline(FakeCall('claim_trial_off3', 333))
check("claim tracked in trial_credit", main.user_db[333].get('trial_credit') == 50.0)
check("deposit after claim", main.user_db[333]['deposit'] == 150.0)

# --- scenario A: user spends the whole trial on a plan -> expiry removes NOTHING ---
u_dep = main.user_db[333]['deposit']
main.user_db[333]['deposit'] -= 50.0
main._spend_trial_first(main.user_db[333], min(u_dep, 50.0))
check("trial_credit drains on plan spend", main.user_db[333].get('trial_credit') == 0.0)
check("deposit after plan buy", main.user_db[333]['deposit'] == 100.0)

ck3 = 'off3_333'
main.free_trial_claims[ck3]['expiry_time'] = time.time() - 1
main.sweep_free_trial_claims_once()
check("spent trial expiry removes nothing", main.user_db[333]['deposit'] == 100.0)
check("spent-trial claim still marked expired", main.free_trial_claims[ck3]['status'] == 'expired')
check("claim recorded 0 removed", main.free_trial_claims[ck3].get('removed') == 0.0)

# --- scenario B: partial spend -> expiry removes only the unspent remainder ---
main.user_db[333]['trial_credit'] = 0.0
main.free_offers['off4'] = {'id': 'off4', 'amount': 40.0, 'expires_days': 2,
                            'image_url': '', 'created_at': time.time()}
main.handle_inline(FakeCall('claim_trial_off4', 333))
# spend $25 of it -> trial_credit 40-25 = 15, deposit 100+40-25 = 115
u_dep = main.user_db[333]['deposit']
main.user_db[333]['deposit'] -= 25.0
main._spend_trial_first(main.user_db[333], min(u_dep, 25.0))
check("partial spend leaves remainder", main.user_db[333].get('trial_credit') == 15.0)

ck4 = 'off4_333'
main.free_trial_claims[ck4]['expiry_time'] = time.time() - 1
main.sweep_free_trial_claims_once()
check("expiry removes only unspent remainder", main.user_db[333]['deposit'] == 100.0,
      f"= {main.user_db[333]['deposit']}")
check("removed == unspent 15", main.free_trial_claims[ck4].get('removed') == 15.0)

# --- scenario C: fully unspent trial + real money -> only the trial amount goes ---
main.free_offers['off5'] = {'id': 'off5', 'amount': 30.0, 'expires_days': 2,
                            'image_url': '', 'created_at': time.time()}
main.handle_inline(FakeCall('claim_trial_off5', 333))
ck5 = 'off5_333'
main.free_trial_claims[ck5]['expiry_time'] = time.time() - 1
main.sweep_free_trial_claims_once()
check("unspent trial fully removed", main.user_db[333]['deposit'] == 100.0)
check("real deposit untouched", main.free_trial_claims[ck5].get('removed') == 30.0)

# --- scenario D: legacy claim (pre-fix, no trial_credit) -> lenient, removes 0 ---
main.user_db[333].pop('trial_credit', None)
main.free_trial_claims['legacy_333'] = {'uid': 333, 'offer_id': 'legacy', 'amount': 20.0,
                                        'claim_time': time.time() - 999999,
                                        'expiry_time': time.time() - 1, 'status': 'claimed'}
main.sweep_free_trial_claims_once()
check("legacy claim removes nothing (safe default)", main.user_db[333]['deposit'] == 100.0)


print("\n[8] Min-deposit enforcement + credited_crypto sync (no phantom re-credit)")

# send_message must return an object with .message_id for the depcheck flow
class _Msg:
    message_id = 1
def _send(uid, text, **kw):
    SENT.append((uid, str(text)))
    return _Msg()
main.bot.send_message = _send

# min-deposit gate used by the watcher
main.deposit_settings['TRX']['min'] = 5.0
main.deposit_settings['USDT_ERC20']['min'] = 10.0
check("sub-min TRX rejected ($1.2 < $5)", main._meets_min_deposit('TRX', 10) is False)
check("above-min TRX ok ($12 >= $5)", main._meets_min_deposit('TRX', 100) is True)
check("sub-min USDT rejected ($5 < $10)", main._meets_min_deposit('USDT_ERC20', 5) is False)
check("above-min USDT ok ($15 >= $10)", main._meets_min_deposit('USDT_ERC20', 15) is True)

# --- Confirm path: below-min deposit is rejected, not credited ---
dep0 = main.user_db[222]['deposit']
main.check_address_for_new_deposit = lambda a, c: (True, 5.0, 'txLOW', time.time())
main.get_onchain_balance = lambda a, c: 27.0
main.handle_inline(FakeCall('cb_depcheck_USDT_ERC20', 222))
check("below-min confirm not credited", main.user_db[222]['deposit'] == dep0)
check("below-min confirm warns user", any(uid == 222 and 'below the minimum' in t for uid, t in SENT))

# --- Confirm path: valid deposit credits AND syncs the watcher's mark ---
main.check_address_for_new_deposit = lambda a, c: (True, 22.0, 'txOK', time.time())
main.get_onchain_balance = lambda a, c: 27.0   # wallet now holds 27 (22 new + 5 old)
w = main.user_db[222]['wallets']['USDT_ERC20']
dep_before = main.user_db[222]['deposit']
main.handle_inline(FakeCall('cb_depcheck_USDT_ERC20', 222))
check("confirm credits deposit", abs(main.user_db[222]['deposit'] - (dep_before + 22.0)) < 1e-9)
check("confirm syncs credited_crypto to onchain", w.get('credited_crypto') == 27.0,
      f"= {w.get('credited_crypto')}")

# --- Admin approve path: credits AND syncs ledger so watcher can't re-credit ---
w2 = main.user_db[111]['wallets']['USDT_TRC20']
w2['total_deposited'] = 0.0
w2.pop('credited_crypto', None)
main.pending_deposits['dep1'] = {'user_id': 111, 'amount': 42.0, 'currency': 'USDT_TRC20'}
main.get_onchain_balance = lambda a, c: 42.0
dep_before = main.user_db[111]['deposit']
main.handle_inline(FakeCall('cb_depapp_dep1', 999))   # uid 999 = admin
check("admin approve credits deposit", abs(main.user_db[111]['deposit'] - (dep_before + 42.0)) < 1e-9)
check("admin approve syncs total_deposited", w2.get('total_deposited') == 42.0)
check("admin approve syncs credited_crypto", w2.get('credited_crypto') == 42.0,
      f"= {w2.get('credited_crypto')}")


print("\n[9] Treasury: validation, fees, overview, gas wallet, send gating")

# --- address validation per network ---
check("EVM addr valid", main.validate_address('0x28C6c06298d514Db089934071355E5743bf21d60', 'USDT_BEP20'))
check("EVM addr invalid", not main.validate_address('0x123', 'USDT_ERC20'))
check("TRON addr valid", main.validate_address('TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs', 'USDT_TRC20'))
check("TRON addr invalid", not main.validate_address('Txyznotreal', 'USDT_TRC20'))
check("TRON addr wrong net", not main.validate_address('TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs', 'USDT_BEP20'))
check("BTC bech32 valid", main.validate_address('bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97', 'BTC'))
check("BTC invalid", not main.validate_address('1notanaddress', 'BTC'))
check("BTC legacy valid", main.validate_address('1BoatSLRHtKNngkdXEeobR76b53LETtpyT', 'BTC'))

# --- live fee estimates (public endpoints) ---
est = main.estimate_network_fee('TRX')
check("TRX fee est", est.get('fee_crypto') == 1.1 and est.get('gas_asset') == 'TRX')
est = main.estimate_network_fee('USDT_TRC20')
check("TRC20 fee est gas=TRX", est.get('gas_asset') == 'TRX' and est.get('fee_crypto', 0) > 0)
est = main.estimate_network_fee('USDT_ERC20')
check("ERC20 fee est gas=ETH", est.get('gas_asset') == 'ETH' and est.get('fee_crypto', 0) > 0,
      f"= {est.get('fee_crypto')}")
est = main.estimate_network_fee('USDT_BEP20')
check("BEP20 fee est gas=BNB", est.get('gas_asset') == 'BNB' and est.get('fee_crypto', 0) > 0)
est = main.estimate_network_fee('BTC')
check("BTC fee est", est.get('gas_asset') == 'BTC' and est.get('fee_crypto', 0) > 0,
      f"= {est.get('fee_crypto')}")

# --- TRC20 energy path (gas wallet empty -> burn path; energy helpers sane) ---
check("TRC20 energy estimate known", main._tron_energy_needed(TRON_ADDR) in (64300, 130000))
res = main._tron_account_resources(TRON_ADDR)
check("account resources readable", res is None or 'energy_limit' in res)
est = main.estimate_network_fee('USDT_TRC20', TRON_ADDR)
check("TRC20 est carries energy info", 'energy_needed' in est and 'delegated' in est,
      f"= fee {est.get('fee_crypto')} delegated={est.get('delegated')}")

# --- /api/balance_overview aggregates live balances ---
main.user_db[111]['wallets']['USDT_TRC20']['live_balance'] = 100.0
main.user_db[111]['wallets']['USDT_BEP20']['live_balance'] = 50.0
main.user_db[222]['wallets']['USDT_ERC20']['live_balance'] = 25.0
main.user_db[222]['wallets']['BTC']['live_balance'] = 0.5
main.user_db[222]['wallets']['TRX']['live_balance'] = 10.0
r = post('/api/balance_overview', {'pin': PIN})
check("balance_overview 200", r.status_code == 200)
ov = r.json()
check("overview total TRC20", ov['assets']['USDT_TRC20']['total_crypto'] == 100.0)
check("overview total BTC usd", abs(ov['assets']['BTC']['total_usd'] - 0.5 * 65000.0) < 1)
check("overview wallets listed", ov['assets']['USDT_TRC20']['wallets'][0]['uid'] == 111)
check("overview gas keys", set(ov['gas'].keys()) == {'TRX', 'BNB', 'ETH', 'BTC'})
check("overview needs pin", post('/api/balance_overview', {'pin': 'x'}).status_code == 401)

# --- /api/validate_addr endpoint ---
check("validate_addr api", post('/api/validate_addr', {'pin': PIN, 'network': 'USDT_TRC20',
      'address': 'TKHuVq1oKVruCGLvqVexFs6dawKv6fQgFs'}).json().get('valid') is True)

# --- /api/gas_wallet saves config ---
r = post('/api/gas_wallet', {'pin': PIN, 'tron_address': TRON_ADDR, 'evm_address': ERC20_ADDR})
check("gas_wallet save", r.json().get('success') is True)
check("gas_wallet persisted", main.gas_wallet.get('tron_address') == TRON_ADDR)
check("gas balances read", r.json().get('gas', {}).get('TRX') is not None,
      f"= {r.json().get('gas', {}).get('TRX')}")

# --- /api/send_asset gating (stub the executor so nothing broadcasts) ---
main.execute_treasury_send = lambda tid: send_tasks_done(tid)
def send_tasks_done(tid):
    main.send_tasks[tid].update({'status': 'done', 'txid': 'stubtx', 'txids': ['stubtx']})

# bad pin / bad address / unknown user / no wallet
check("send bad pin", post('/api/send_asset', {'pin': 'x', 'network': 'TRX', 'uid': 222,
      'to_addr': TRON_ADDR, 'amount': 1}).status_code == 401)
check("send bad addr", post('/api/send_asset', {'pin': PIN, 'network': 'TRX', 'uid': 222,
      'to_addr': 'notanaddr', 'amount': 1}).status_code == 400)
check("send unknown user", post('/api/send_asset', {'pin': PIN, 'network': 'TRX', 'uid': 777,
      'to_addr': TRON_ADDR, 'amount': 1}).status_code == 400)

# TRX: amount+fee must fit balance (live balance stubbed to 10 TRX)
main.get_onchain_balance = lambda a, c: 10.0
check("send over balance+fee rejected", post('/api/send_asset', {'pin': PIN, 'network': 'TRX',
      'uid': 222, 'to_addr': TRON_ADDR, 'amount': 9.5}).status_code == 400)
r = post('/api/send_asset', {'pin': PIN, 'network': 'TRX', 'uid': 222, 'to_addr': TRON_ADDR, 'amount': 8.0})
check("send queued", r.json().get('success') is True)
tid = r.json().get('task_id')
time.sleep(0.3)
check("send task completed (stub)", main.send_tasks[tid]['status'] == 'done')

# token send doesn't need gas at validation level
main.get_onchain_balance = lambda a, c: 100.0
r = post('/api/send_asset', {'pin': PIN, 'network': 'USDT_TRC20', 'uid': 111,
      'to_addr': TRON_ADDR, 'amount': 50})
check("token send queued", r.json().get('success') is True)

# --- seed-derived gas wallet resolution (bip_utils stubbed -> derive() = None,
#     so inject the derived cache directly) ---
check("overview reports gas_source marker",
      ov.get('gas_source') in ('seed', 'manual', 'none'), f"= {ov.get('gas_source')}")
main._gas_derived_cache = {'evm_address': '0xSEEDEVM', 'tron_address': 'TSEEDTRON',
                           'btc_address': 'bc1seedbtc',
                           'evm_key': 'kE', 'tron_key': 'kT', 'btc_key': 'kB'}
saved_manual = dict(main.gas_wallet)
main.gas_wallet.clear()
main.gas_wallet.update({'evm_address': '', 'evm_key': '', 'tron_address': '',
                        'tron_key': '', 'btc_address': '', 'btc_key': ''})
check("resolver falls back to seed addr", main.get_gas_addr('tron') == 'TSEEDTRON')
check("resolver falls back to seed key", main.get_gas_key('tron') == 'kT')
check("resolver falls back to seed evm", main.get_gas_addr('evm') == '0xSEEDEVM')
main.gas_wallet['tron_address'] = 'TMANUAL'
main.gas_wallet['tron_key'] = 'kMANUAL'
check("manual override wins over seed", main.get_gas_addr('tron') == 'TMANUAL'
      and main.get_gas_key('tron') == 'kMANUAL')
main.gas_wallet.clear()
main.gas_wallet.update(saved_manual)
main._gas_derived_cache = None

# --- GasFree: TIP-712 signature recovers the signer's tron address (offline) ---
import hashlib as _hl
from ecdsa import SigningKey, SECP256k1, util as _ecutil
from ecdsa import VerifyingKey as _VK

def _b58check_enc(payload):
    B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    raw = payload + _hl.sha256(_hl.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(raw, 'big'); s = ''
    while n:
        n, r = divmod(n, 58); s = B58[r] + s
    return '1' * (len(raw) - len(raw.lstrip(b'\x00'))) + s

def _tron_addr_of(vk):
    from Crypto.Hash import keccak as _kk
    h = _kk.new(digest_bits=256); h.update(vk.to_string())
    return _b58check_enc(b'\x41' + h.digest()[-20:])

sk = SigningKey.generate(curve=SECP256k1)
key_hex = sk.to_string().hex()
my_addr = _tron_addr_of(sk.verifying_key)
sig_hex, digest = main._tip712_sign(key_hex, main.USDT_TRC20_CONTRACT,
                                  TRON_ADDR, my_addr, TRON_ADDR, 1000000, 100000, 1999999999, 0)
check("gasfree sig is 65 bytes", len(bytes.fromhex(sig_hex)) == 65)
recid = bytes.fromhex(sig_hex)[-1] - 27
cands = _VK.from_public_key_recovery_with_digest(bytes.fromhex(sig_hex)[:64], digest,
                                                 curve=SECP256k1, sigdecode=_ecutil.sigdecode_string)
check("gasfree sig recovers signer tron address",
      _tron_addr_of(cands[recid]) == my_addr, f"= {_tron_addr_of(cands[recid])}")

# --- fee_mode validation on send_asset ---
check("usdt fee_mode rejected on BEP20", post('/api/send_asset', {'pin': PIN, 'network': 'USDT_BEP20',
      'uid': 111, 'to_addr': ERC20_ADDR, 'amount': 1, 'fee_mode': 'usdt'}).status_code == 400)
r = post('/api/send_asset', {'pin': PIN, 'network': 'USDT_TRC20', 'uid': 111,
      'to_addr': TRON_ADDR, 'amount': 1, 'fee_mode': 'bogus'})
check("bad fee_mode rejected", r.status_code == 400)
r = post('/api/send_asset', {'pin': PIN, 'network': 'USDT_TRC20', 'uid': 111,
      'to_addr': TRON_ADDR, 'amount': 1, 'fee_mode': 'usdt'})
check("usdt mode needs API keys", r.status_code == 400 and 'GASFREE' in r.json().get('error', ''),
      f"= {r.json().get('error')}")

server.shutdown()

print(f"\n==== RESULT: {PASS} passed, {FAIL} failed ====")
raise SystemExit(1 if FAIL else 0)
