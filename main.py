import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import uuid
import time
import os
import threading
import requests
import json
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from dotenv import load_dotenv
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
import psycopg2
from psycopg2.extras import Json

# --- AUTOTRANSLATION ENGINE (deep-translator) ---
try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("⚠️ deep-translator not found. Translating will be bypassed. Please 'pip install deep-translator'")
    class GoogleTranslator:
        def __init__(self, source, target): pass
        def translate(self, text): return text

TL_CACHE = {}
REVERSE_TL_MAP = {}

def get_tl_and_map(text, target_lang):
    if not text or target_lang == 'en': return text
    cache_key = ('en', target_lang, text)
    
    if cache_key in TL_CACHE:
        tl_text = TL_CACHE[cache_key]
    else:
        try:
            tl_text = GoogleTranslator(source='en', target=target_lang).translate(text)
            TL_CACHE[cache_key] = tl_text
        except:
            tl_text = text

    if target_lang not in REVERSE_TL_MAP: REVERSE_TL_MAP[target_lang] = {}
    REVERSE_TL_MAP[target_lang][tl_text] = text
    return tl_text

# --- 1. SECURITY VAULT (Environment Variables) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Check for both possible names Windows might have used
env_file = os.path.join(BASE_DIR, '.env')
txt_env_file = os.path.join(BASE_DIR, '.env.txt')

print("\n" + "="*40)
print("🔍 SCANNING FOR SECURITY VAULT...")

if os.path.exists(env_file):
    print("✅ Found perfect '.env' file!")
    load_dotenv(dotenv_path=env_file)
elif os.path.exists(txt_env_file):
    print("⚠️ Found '.env.txt'! (Windows hid the extension). Loading it anyway...")
    load_dotenv(dotenv_path=txt_env_file)
else:
    print("❌ CRITICAL ERROR: No environment file found at all!")
    print(f"📄 Files Python actually sees in this folder: {os.listdir(BASE_DIR)}")

BOT_TOKEN = os.getenv('BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)

# BULLETPROOF ADMIN ID PARSING
raw_admins = os.getenv('ADMIN_IDS', '')
raw_admins = raw_admins.replace('"', '').replace("'", "")

ADMIN_IDS = []
if raw_admins:
    for x in raw_admins.split(','):
        if x.strip():
            try: ADMIN_IDS.append(int(x.strip()))
            except: pass

print(f"👑 RECOGNIZED ADMIN IDs: {ADMIN_IDS}")
print("="*40 + "\n")

MASTER_SEED = os.getenv('MASTER_SEED_PHRASE', '')
if MASTER_SEED:
    MASTER_SEED = MASTER_SEED.replace('"', '').replace("'", "")

# API KEYS FOR BLOCKCHAIN TRACKING
TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')

# --- NEON POSTGRESQL DATABASE SYSTEM ---
DATABASE_URL = os.getenv('DATABASE_URL', '')

def init_db():
    if not DATABASE_URL:
        print("⚠️ NO DATABASE_URL FOUND! Make sure it is in your Environment Variables.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Create a permanent table if it doesn't exist yet
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                id INT PRIMARY KEY,
                data JSONB
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Neon Database connected and table verified!")
    except Exception as e:
        print(f"❌ Neon DB Init Error: {e}")

def load_database():
    if not DATABASE_URL: return {}
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT data FROM bot_state WHERE id = 1;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result and result[0]:
            data = result[0]
            # JSON converts Python integer keys to strings. We convert User IDs back to numbers!
            if 'user_db' in data:
                parsed_user_db = {}
                for k, v in data['user_db'].items():
                    try: parsed_user_db[int(k)] = v
                    except: parsed_user_db[k] = v
                data['user_db'] = parsed_user_db
            return data
    except Exception as e:
        print(f"⚠️ Error loading from Neon DB: {e}")
    return {}

def save_database():
    if not DATABASE_URL: return
    # Bundle everything we want to save into one master dictionary
    data_to_save = {
        'user_db': user_db,
        'menus': menus,
        'menu_posts': menu_posts,
        'btn_metadata': btn_metadata,
        'bot_plans': bot_plans,
        'deposit_settings': deposit_settings,
        'global_w_setup': global_w_setup,
        'global_wallet_setup': global_wallet_setup,
        'global_bonus_setup': global_bonus_setup,
        'processed_txids': list(processed_txids) # Convert set to list for database
    }
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Securely upsert the data into row id 1
        cur.execute("""
            INSERT INTO bot_state (id, data) 
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE 
            SET data = EXCLUDED.data;
        """, [Json(data_to_save)])
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"⚠️ Neon DB Save Error: {e}")

def auto_save_loop():
    """Runs forever in the background, saving data every 10 seconds."""
    while True:
        time.sleep(10)
        save_database()

# Initialize Neon and Load Data
init_db()
db_data = load_database()

# --- DYNAMIC MEMORY & STATE ---
user_current_path = {}
user_state = {} 
user_selected_button = {} 
user_clipboard = {}        
user_action_data = {} 
editor_msg_ids = {}

# --- ADMIN TRACKERS (Don't need to be saved to DB) ---
admin_bal_type = {}            
admin_bal_notify = {}          
admin_bal_comment_on = {}      
admin_bal_target = {}          
admin_bal_comment_text = {}    
user_plan_setup = {}          
pending_deposits = {}
admin_dep_setup = {}

# --- PERSISTENT DATA (Loaded from Neon DB) ---
user_db = db_data.get('user_db', {})
menus = db_data.get('menus', {'root': []})
menu_posts = db_data.get('menu_posts', {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]})
btn_metadata = db_data.get('btn_metadata', {})
processed_txids = set(db_data.get('processed_txids', []))

deposit_settings = db_data.get('deposit_settings', {
    'USDT_TRC20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT TRC20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly <code>%crypto_amount%</code> USDT to:\n\n<code>%address%</code>\n\n<i>The system is monitoring the blockchain and will credit you automatically.</i>', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.'},
    'USDT_BEP20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT BEP20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly <code>%crypto_amount%</code> USDT to:\n\n<code>%address%</code>\n\n<i>The system is monitoring the blockchain and will credit you automatically.</i>', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.'},
    'USDT_ERC20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT ERC20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly <code>%crypto_amount%</code> USDT to:\n\n<code>%address%</code>\n\n<i>The system is monitoring the blockchain and will credit you automatically.</i>', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.'},
    'TRX': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 5.0, 'max': 10000.0, 'msg_enter': 'Enter amount of TRX (in USD) to deposit:', 'msg_instruct': 'Please send exactly <code>%crypto_amount%</code> TRX to:\n\n<code>%address%</code>\n\n<i>The system is monitoring the blockchain and will credit you automatically.</i>', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.'},
    'BTC': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 50.0, 'max': 50000.0, 'msg_enter': 'Enter amount of BTC (in USD) to deposit:', 'msg_instruct': 'Please send exactly <code>%crypto_amount%</code> BTC to:\n\n<code>%address%</code>\n\n<i>The system is monitoring the blockchain and will credit you automatically.</i>', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.'}
})

global_w_setup = db_data.get('global_w_setup', {
    'w_var': 'balance', 'w_min': 10.0, 'w_max': 10000.0,
    'w_msg_enter': 'Please enter the amount you wish to withdraw:',
    'w_msg_addr': 'Please enter your withdrawal address:',
    'w_msg_conf': 'Confirm withdrawal of %withdraw% to <code>%address%</code>?',
    'do_not_ask_address': False
})

global_wallet_setup = db_data.get('global_wallet_setup', {
    'msg_main': '💡 Your currently set USDT Wallet Address is: <code>%wallet%</code>\n\nEmail: <code>%email%</code>\n\n💹 It will be used for all future withdrawals.\n\nNOTE🔴: Supported, USDT Network Address are: TRC20 and BEP20 Set Only one..',
    'msg_prompt': '✏️ Send now your USDT TRC 20 OR BEP 20 Address to use it in future transactions ..',
    'msg_success': '🖊 Done: Your new wallet address is <code>%wallet%</code> (%network%)',
    'inline_set': 'Set wallet', 'inline_change': 'Change wallet',
    'ask_email': True, 'msg_email_prompt': '✏️ Please enter your Email address:'
})

global_bonus_setup = db_data.get('global_bonus_setup', {
    'amount': 5.0, 'cooldown_hours': 24.0,
    'msg_success': '🎉 Congratulations! You have received $%bonus_amount% as a bonus.',
    'msg_fail': '⏳ You have already claimed your bonus. Please wait %time_left%.'
})

bot_plans = db_data.get('bot_plans', {})

# --- SYSTEM PLANS INITIALIZATION ---
if not bot_plans:
    for i in range(6):
        bot_plans[f'plan{i}'] = {
            'name': f'Plan {i}', 'min': 10.0, 'max': 1000.0, 'length': 24.0, 'profit': 5.0,
            'text': f'✨ <b>Plan {i} Description</b> ✨\n\nEdit this in Admin -&gt; Plans.',
            'photo': None, 'inline_text': '🛒 Purchase Plan', 'inline_active_text': '(Active ✅)', 
            'redirect_cmd': None, 'is_free': (i == 0), 'bonus_amount': 50.0 if i == 0 else 0.0
        }

# --- TRANSACTION LEDGER LOGGER ---
def log_tx(uid, t_type, amt):
    if uid in user_db:
        date_str = time.strftime('%Y-%m-%d %H:%M', time.gmtime())
        if 'transactions' not in user_db[uid]: user_db[uid]['transactions'] = []
        user_db[uid]['transactions'].append({'date': date_str, 'type': t_type, 'amount': amt})

def get_default_metadata():
    return {
        'random_message': False,
        'admin_only': False,
        'invisible': False,
        'command': None,
        'move_by_command': False,
        'withdrawal': False, 
        'is_wallet': False,  
        'is_bonus': False,   
        'is_balance': False,
        'assigned_plan': None, 
        'is_calculator': False, 
        'is_history': False,
        'is_language': False
    }

def init_user_db(message):
    user_id = message.from_user.id
    if user_id not in user_db:
        # ALL NEW USERS START AT ZERO
        user_db[user_id] = {
            'balance': 0.00, 'bonus': 0.00, 'deposit': 0.00, 
            'hourly': 0.00, 'plan': 0.00, 'address': 'Not Set',
            'wallet': 'Not Set', 'wallet_net': 'Not Set', 'email': 'Not Set', 'last_bonus_time': 0.0, 
            'first_name': message.from_user.first_name or 'Unknown',
            'last_name': message.from_user.last_name or '',
            'username': message.from_user.username or 'No Username',
            'active_plans': [], 
            'pending_plan': None,
            'wallets': {},
            'transactions': [],
            'ref_count': 0,
            'total_withdrawn': 0.0,
            'lang': 'en'
        }
    else:
        user_db[user_id]['first_name'] = message.from_user.first_name or 'Unknown'
        user_db[user_id]['last_name'] = message.from_user.last_name or ''
        user_db[user_id]['username'] = message.from_user.username or 'No Username'
        if 'active_plans' not in user_db[user_id]: user_db[user_id]['active_plans'] = []
        if 'pending_plan' not in user_db[user_id]: user_db[user_id]['pending_plan'] = None
        if 'wallets' not in user_db[user_id]: user_db[user_id]['wallets'] = {}
        if 'transactions' not in user_db[user_id]: user_db[user_id]['transactions'] = []
        if 'wallet' not in user_db[user_id]: user_db[user_id]['wallet'] = 'Not Set'
        if 'email' not in user_db[user_id]: user_db[user_id]['email'] = 'Not Set'
        if 'last_bonus_time' not in user_db[user_id]: user_db[user_id]['last_bonus_time'] = 0.0
        if 'ref_count' not in user_db[user_id]: user_db[user_id]['ref_count'] = 0
        if 'total_withdrawn' not in user_db[user_id]: user_db[user_id]['total_withdrawn'] = 0.0
        if 'lang' not in user_db[user_id]: user_db[user_id]['lang'] = 'en'

# --- 2. LIVE PRICE ORACLE ENGINE (WITH FALLBACKS) ---
def get_crypto_price(currency_code):
    """Fetches live USD price for the requested currency from CoinGecko with hard fallbacks."""
    mapping = {
        'USDT_TRC20': 'tether', 'USDT_BEP20': 'tether', 'USDT_ERC20': 'tether',
        'TRX': 'tron', 'BTC': 'bitcoin'
    }
    coin_id = mapping.get(currency_code, 'tether')
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data[coin_id]['usd'])
    except Exception as e:
        print(f"Oracle Error or Rate Limit: {e}")
        if 'USDT' in currency_code: return 1.0
        if 'TRX' in currency_code: return 0.12
        if 'BTC' in currency_code: return 65000.0
        return 1.0

# --- 3. HD WALLET ENGINE (BIP39/44) ---
def generate_user_wallet(user_id, currency):
    """Generates a unique deterministic wallet for a user based on their Telegram ID."""
    if not MASTER_SEED:
        return "ERROR_NO_SEED", "ERROR_NO_SEED"
        
    try:
        seed_bytes = Bip39SeedGenerator(MASTER_SEED).Generate()
        
        if currency == 'BTC':
            coin_type = Bip44Coins.BITCOIN
        elif 'TRC20' in currency or currency == 'TRX':
            coin_type = Bip44Coins.TRON
        else:
            coin_type = Bip44Coins.ETHEREUM

        bip44_mst = Bip44.FromSeed(seed_bytes, coin_type)
        
        address_index = user_id % 2147483647
        bip44_acc = bip44_mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(address_index)
        
        public_address = bip44_acc.PublicKey().ToAddress()
        private_key = bip44_acc.PrivateKey().Raw().ToHex()
        
        return public_address, private_key
    except Exception as e:
        print(f"Wallet Gen Error: {e}")
        return "GEN_ERROR", "GEN_ERROR"

# --- 4. AUTO-DETECTION WATCHER ENGINE ---
def blockchain_watcher_loop():
    """Continuously checks the blockchain for new deposits to generated wallets."""
    USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    
    while True:
        try:
            for uid, data in user_db.items():
                for curr, w_data in data.get('wallets', {}).items():
                    addr = w_data['address']
                    
                    if curr in ['TRX', 'USDT_TRC20']:
                        headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
                        
                        if curr == 'USDT_TRC20':
                            url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20"
                        else:
                            url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions"
                        
                        resp = requests.get(url, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            txs = resp.json().get('data', [])
                            for tx in txs:
                                txid = tx.get('transaction_id') or tx.get('txID')
                                
                                if txid in processed_txids:
                                    continue
                                    
                                is_incoming = False
                                crypto_amount = 0.0
                                
                                if curr == 'USDT_TRC20':
                                    if tx.get('token_info', {}).get('address') == USDT_TRC20_CONTRACT and tx.get('to') == addr:
                                        is_incoming = True
                                        crypto_amount = float(tx.get('value', 0)) / 1_000_000
                                elif curr == 'TRX':
                                    if tx.get('raw_data', {}).get('contract', [{}])[0].get('parameter', {}).get('value', {}).get('to_address') == addr:
                                        is_incoming = True
                                        crypto_amount = float(tx['raw_data']['contract'][0]['parameter']['value'].get('amount', 0)) / 1_000_000
                                
                                if is_incoming and crypto_amount > 0:
                                    processed_txids.add(txid)
                                    
                                    live_price = get_crypto_price(curr) or 1.0
                                    usd_value = crypto_amount * live_price
                                    
                                    user_db[uid]['deposit'] += usd_value
                                    log_tx(uid, f"Auto-Deposit ({curr})", usd_value)
                                    
                                    try:
                                        conf = deposit_settings[curr]
                                        msg_success = conf.get('msg_success', "✅ <b>Deposit Detected!</b>\n\nThe blockchain confirmed a deposit of <b>%crypto_amount% %currency%</b>.\n<b>$%usd_amount% USD</b> has been automatically added to your balance!")
                                        msg_success = msg_success.replace('%usd_amount%', f"{usd_value:.2f}").replace('%crypto_amount%', f"{crypto_amount:.2f}").replace('%currency%', curr.replace('_', ' '))
                                        # Auto-translate before sending
                                        lang = user_db.get(uid, {}).get('lang', 'en')
                                        bot.send_message(uid, get_tl_and_map(msg_success, lang), parse_mode="HTML")
                                    except Exception: pass
                                    
                                    admin_msg = f"🟢 <b>AUTO-DEPOSIT APPROVED</b>\nUser: <code>{uid}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {crypto_amount}\nUSD Credited: ${usd_value:.2f}\nHash (TXID): <code>{txid}</code>"
                                    for admin in ADMIN_IDS:
                                        try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                                        except Exception: pass
                                        
                                    check_and_trigger_auto_buy(uid)

        except Exception as e:
            pass
        time.sleep(30)

# --- UNIVERSAL AUTO-BUY ENGINE ---
def check_and_trigger_auto_buy(user_id):
    if not user_db[user_id].get('pending_plan'): return
    p_macro = user_db[user_id]['pending_plan']
    if p_macro in bot_plans:
        p_data = bot_plans[p_macro]
        
        if p_macro == 'plan0':
            invest_amt = p_data.get('bonus_amount', 50.0)
            user_db[user_id]['pending_plan'] = None
            # Free plan activation bypasses balance reduction
        else:
            if user_db[user_id]['deposit'] >= p_data['min']:
                invest_amt = min(user_db[user_id]['deposit'], p_data['max'])
                user_db[user_id]['deposit'] -= invest_amt
                log_tx(user_id, f"Bought {p_data['name']}", -invest_amt)
            else:
                return

        new_plan = {
            'id': str(uuid.uuid4())[:8],
            'macro': p_macro,
            'amount': invest_amt,
            'profit_pct': p_data['profit'],
            'length_hours': p_data.get('length', 0),
            'start_time': time.time(),
            'last_accrual': time.time(),
            'earned': 0.0,
            'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        user_db[user_id]['pending_plan'] = None
        
        try:
            msg = f"🎉 <b>Auto-Purchase Successful!</b>\n\nYour deposit triggered your pending plan.\n<b>{p_data['name']}</b> is now active with an investment of <b>${invest_amt:.2f}</b>!"
            lang = user_db.get(user_id, {}).get('lang', 'en')
            bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
        except Exception: pass

def process_accruals(user_id):
    u = user_db.get(user_id)
    if not u or not u.get('active_plans'): return
    
    now = time.time()
    for p in u['active_plans']:
        if p['status'] != 'active': continue
        
        elapsed_sec = now - p['last_accrual']
        elapsed_hours = elapsed_sec / 3600.0
        
        if elapsed_hours > 0:
            earned = p['amount'] * (p['profit_pct'] / 100.0) * elapsed_hours
            u['balance'] += earned  
            p['last_accrual'] = now
            p['earned'] += earned
            
        if p['length_hours'] > 0:
            total_elapsed = (now - p['start_time']) / 3600.0
            if total_elapsed >= p['length_hours']:
                p['status'] = 'expired'

def change_menu_paths(old_base, new_base):
    for k in list(menus.keys()):
        if k == old_base or k.startswith(old_base + '/'):
            new_k = k.replace(old_base, new_base, 1)
            menus[new_k] = menus.pop(k)
            
    for mk in list(btn_metadata.keys()):
        if mk == old_base or mk.startswith(old_base + '/'):
            new_mk = mk.replace(old_base, new_base, 1)
            btn_metadata[new_mk] = btn_metadata.pop(mk)
            
    for pk in list(menu_posts.keys()):
        if pk == old_base or pk.startswith(old_base + '/'):
            new_pk = pk.replace(old_base, new_base, 1)
            menu_posts[new_pk] = menu_posts.pop(pk)

def replace_macros(text, user_id, full_path, action_data=None):
    if not text: return "Not set."
    process_accruals(user_id) 
    
    bals = user_db.get(user_id, {})
    
    # CALCULATE NEW BALANCE MACROS
    active = [p for p in bals.get('active_plans', []) if p['status'] == 'active']
    plan_invest = sum(p['amount'] for p in active)
    hourly_profit = sum(p['amount'] * (p['profit_pct'] / 100.0) for p in active)
    plan_names = ", ".join(bot_plans.get(p['macro'], {}).get('name', 'Plan') for p in active) if active else "None"
    ref_count = bals.get('ref_count', 0)
    total_withdrawn = bals.get('total_withdrawn', 0.0)

    t = text.replace('%userid%', str(user_id))
    t = t.replace('%username%', bals.get('username', 'Unknown'))
    t = t.replace('%firstname%', bals.get('first_name', 'Unknown'))
    t = t.replace('%lastname%', bals.get('last_name', ''))
    t = t.replace('%balance%', f"{bals.get('balance', 0):.2f}")
    t = t.replace('%bonus%', f"{bals.get('bonus', 0):.2f}")
    t = t.replace('%deposit%', f"{bals.get('deposit', 0):.2f}")
    t = t.replace('%lang%', bals.get('lang', 'en').upper())
    
    # NEW EXTENDED MACROS
    t = t.replace('%plan_invest%', f"{plan_invest:.2f}")
    t = t.replace('%hourly_profit%', f"{hourly_profit:.2f}")
    t = t.replace('%plan_names%', plan_names)
    t = t.replace('%ref_count%', str(ref_count))
    t = t.replace('%withdrawn%', f"{total_withdrawn:.2f}")
    
    t = t.replace('%wallet%', bals.get('wallet', 'Not Set'))
    t = t.replace('%email%', bals.get('email', 'Not Set'))
    t = t.replace('%bonus_amount%', str(global_bonus_setup['amount']))
    
    # Use GLOBAL withdrawal settings for macros
    t = t.replace('%min%', str(global_w_setup.get('w_min') or 0))
    t = t.replace('%max%', str(global_w_setup.get('w_max') or 'No Limit'))
    
    if '%my_plans%' in t or '%activeplan%' in t:
        plans_str = ""
        if not active:
            plans_str = "<i>(No active plans)</i>"
        else:
            for p in active:
                p_name = bot_plans.get(p['macro'], {}).get('name', 'Plan')
                plans_str += f"🔹 <b>{p_name}</b>\n"
                plans_str += f"Invested: ${p['amount']:.2f}\nEarned: ${p['earned']:.4f}\n\n"
        t = t.replace('%my_plans%', plans_str)
        t = t.replace('%activeplan%', plans_str)
        
    for p_macro, p_data in bot_plans.items():
        if p_macro in t:
            if p_macro == 'plan0':
                p_details = f"<b>{p_data['name']}</b>\nBonus Capital: ${p_data.get('bonus_amount', 50.0)}\nProfit: {p_data['profit']}% / Hour"
            else:
                p_details = f"<b>{p_data['name']}</b>\nMin: ${p_data['min']} | Max: ${p_data['max']}\nProfit: {p_data['profit']}% / Hour"
            
            if p_data.get('length') and p_data['length'] > 0:
                p_details += f"\nContract: {p_data['length']} Hours"
            else:
                p_details += "\nContract: Lifetime"
            t = t.replace(p_macro, p_details)
    
    if action_data:
        t = t.replace('%withdraw%', f"{action_data.get('amount', 0):.2f}")
        t = t.replace('%address%', action_data.get('address', bals.get('address', 'Not Set')))
    else:
        t = t.replace('%withdraw%', "0.00")
        t = t.replace('%address%', bals.get('address', 'Not Set'))
        
    return t

# --- POSTS ENGINE ---
def get_post_inline_tools(post_id):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton('⬆️', callback_data=f'cb_p_up_{post_id}'),
        InlineKeyboardButton('✳️', callback_data=f'cb_p_star_{post_id}'),
        InlineKeyboardButton('🔠 Rep...', callback_data=f'cb_p_reptext_{post_id}'),
        InlineKeyboardButton('⬇️', callback_data=f'cb_p_down_{post_id}')
    )
    markup.row(
        InlineKeyboardButton('➗ Replace', callback_data=f'cb_p_repall_{post_id}'),
        InlineKeyboardButton('✖️ Delete', callback_data=f'cb_p_del_{post_id}'),
        InlineKeyboardButton('➕ Add', callback_data=f'cb_p_add_{post_id}')
    )
    return markup

def render_pi_manager(chat_id, post, message_id=None):
    markup = InlineKeyboardMarkup()
    custom_inlines = post.get('custom_inlines', [])
    rows_dict = {}
    for b in custom_inlines:
        r = b.get('row_idx', 0)
        rows_dict.setdefault(r, []).append(b)
        
    for r_idx in sorted(rows_dict.keys()):
        row_btns = []
        for b in rows_dict[r_idx]:
            row_btns.append(InlineKeyboardButton(b['text'], callback_data=f"cb_pis_{b['id']}"))
        if row_btns:
            markup.row(*row_btns)
            
    markup.row(InlineKeyboardButton('➕ Add New Inline', callback_data='cb_pi_add'))
    markup.row(InlineKeyboardButton('🔙 Done', callback_data='cb_pi_done'))
    
    text = "🛠 <b>Inline Keyboard Editor</b>\n\nClick a button to Edit/Move/Delete it, or click Add New."
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

def send_path_content(chat_id, user_id, path, is_editing=False, reply_keyboard=None):
    if is_editing and user_id in editor_msg_ids:
        for m_id in editor_msg_ids[user_id]:
            try: bot.delete_message(chat_id, m_id)
            except Exception: pass
        editor_msg_ids[user_id] = []

    lang = user_db.get(user_id, {}).get('lang', 'en')
    meta = btn_metadata.get(path, get_default_metadata())
    assigned_plan = meta.get('assigned_plan')
    
    kb_attached = False
    
    if assigned_plan and assigned_plan in bot_plans:
        p_data = bot_plans[assigned_plan]
        p_text = get_tl_and_map(replace_macros(p_data.get('text', ''), user_id, path), lang)
        p_photo = p_data.get('photo')
        
        has_active = any(p['macro'] == assigned_plan and p['status'] == 'active' for p in user_db.get(user_id, {}).get('active_plans', []))
        btn_text_raw = p_data.get('inline_active_text', '(Active ✅)') if has_active else p_data.get('inline_text', '🛒 Purchase Plan')
        btn_text = get_tl_and_map(btn_text_raw, lang)
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton(btn_text, callback_data=f"cb_buyplan_{assigned_plan}"))
        
        try:
            if p_photo:
                sent = bot.send_photo(chat_id, p_photo, caption=p_text, parse_mode="HTML", reply_markup=markup)
            else:
                sent = bot.send_message(chat_id, p_text, parse_mode="HTML", reply_markup=markup)
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
        except Exception as e:
            sent = bot.send_message(chat_id, f"⚠️ Error rendering plan: {e}")
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

    posts = menu_posts.get(path, [])
    if not posts and not assigned_plan:
        msg_raw = f"📂 <b>{path.split('/')[-1]}</b>\n\n<i>(No messages set for this menu)</i>" if path != 'root' else "Welcome!"
        sent = bot.send_message(chat_id, get_tl_and_map(msg_raw, lang), parse_mode="HTML", reply_markup=reply_keyboard)
        if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
        return
        
    for i, p in enumerate(posts):
        text = get_tl_and_map(replace_macros(p['text'], user_id, path), lang)
        
        markup = InlineKeyboardMarkup()
        custom_inlines = p.get('custom_inlines', [])
        
        if custom_inlines:
            rows_dict = {}
            for b in custom_inlines:
                r = b.get('row_idx', 0)
                rows_dict.setdefault(r, []).append(b)
                
            for r_idx in sorted(rows_dict.keys()):
                row_btns = []
                for b in rows_dict[r_idx]:
                    # Bypass translating Language indicator buttons so the flags and native names stay perfect
                    if b['mode'] == 'set_lang':
                        tl_btn_text = b['text']
                    else:
                        tl_btn_text = get_tl_and_map(b['text'], lang)
                        
                    if b['mode'] == 'url':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, url=b['data']))
                    elif b['mode'] == 'popup':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_pop_{b['id']}"))
                    elif b['mode'] == 'command':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_cmd_{b['id']}"))
                    elif b['mode'] == 'buy_plan':
                        plan_macro = b['data'].split('\n')[0].strip()
                        p_data = bot_plans.get(plan_macro, {})
                        has_active = any(bp['macro'] == plan_macro and bp['status'] == 'active' for bp in user_db.get(user_id, {}).get('active_plans', []))
                        btn_text_raw = p_data.get('inline_active_text', '(Active ✅)') if has_active else b['text']
                        row_btns.append(InlineKeyboardButton(get_tl_and_map(btn_text_raw, lang), callback_data=f"cb_buy_{b['id']}"))
                    elif b['mode'] == 'deposit':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_dep_{b['id']}"))
                    elif b['mode'] == 'set_lang':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_lang_{b['id']}"))
                if row_btns:
                    markup.row(*row_btns)
                    
        if is_editing:
            editor_markup = get_post_inline_tools(p['id'])
            for row in editor_markup.keyboard:
                markup.row(*row)
                
        if not markup.keyboard: 
            markup = None
            
        # INTELLIGENT KEYBOARD INJECTION: Try to hide the reply keyboard inside the last normal post to avoid empty bubbles
        if i == len(posts) - 1 and not markup and not kb_attached and reply_keyboard:
            markup = reply_keyboard
            kb_attached = True
        
        try:
            if p['type'] == 'photo':
                sent = bot.send_photo(chat_id, p['photo'], caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                sent = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)
                
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
        except Exception as e:
            sent = bot.send_message(chat_id, f"⚠️ Error rendering post: {e}")
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

# --- KEYBOARD BUILDERS ---
def get_wizard_keyboard(current_val, options=None, allow_empty=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    row1 = []
    if current_val is not None: row1.append(KeyboardButton('✔️ Leave as Is'))
    if allow_empty: row1.append(KeyboardButton('➖ Set Empty'))
    if row1: markup.row(*row1)

    if options:
        for o in options: markup.row(KeyboardButton(o))

    markup.row(KeyboardButton('🚫 Cancel Action'))
    return markup

def get_settings_keyboard(full_path):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    meta = btn_metadata.get(full_path, get_default_metadata())
    
    rm_text = "☑️ On" if meta.get('random_message') else "⬜️ Off"
    ao_text = "☑️ On" if meta.get('admin_only') else "⬜️ Off"
    inv_text = "☑️ On" if meta.get('invisible') else "⬜️ Off"
    calc_text = "☑️ On" if meta.get('is_calculator') else "⬜️ Off"
    hist_text = "☑️ On" if meta.get('is_history') else "⬜️ Off"
    w_text = "☑️ On" if meta.get('withdrawal') else "⬜️ Off"
    wal_text = "☑️ On" if meta.get('is_wallet') else "⬜️ Off"
    bon_text = "☑️ On" if meta.get('is_bonus') else "⬜️ Off"
    bal_text = "☑️ On" if meta.get('is_balance') else "⬜️ Off"
    
    markup.row(KeyboardButton(f'Random Message ({rm_text})'), KeyboardButton(f'Admin Only ({ao_text})'))
    markup.row(KeyboardButton(f'Invisible ({inv_text})'), KeyboardButton('Subscription (Join)'))
    markup.row(KeyboardButton('Assign Command'), KeyboardButton('Assign Plan'), KeyboardButton('Assign Language')) 
    markup.row(KeyboardButton(f'Assign Calculator ({calc_text})'), KeyboardButton(f'Assign History ({hist_text})'))
    markup.row(KeyboardButton(f'Assign Withdrawal ({w_text})'), KeyboardButton(f'Assign Wallet ({wal_text})'))
    markup.row(KeyboardButton(f'Assign Bonus ({bon_text})'), KeyboardButton(f'Assign Balance ({bal_text})'))
    markup.row(KeyboardButton('Assign Editor'), KeyboardButton('Form Settings'), KeyboardButton('Shop Editor'))
    markup.row(KeyboardButton('🔙 Exit Button Settings'))
    return markup

def get_global_withdrawal_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    addr_text = "☑️ On" if global_w_setup.get('do_not_ask_address') else "⬜️ Off"
    
    markup.row(KeyboardButton('Set Withdrawal Var'), KeyboardButton('Set Min/Max'))
    markup.row(KeyboardButton('Edit Enter Msg'), KeyboardButton('Edit Address Msg'))
    markup.row(KeyboardButton('Edit Confirm Msg'), KeyboardButton('Success Message'))
    markup.row(KeyboardButton('Fail Message'), KeyboardButton('Decline Msg.'), KeyboardButton('Ignore Msg.'))
    markup.row(KeyboardButton('Public Group Report'), KeyboardButton('Private Group Report'))
    markup.row(KeyboardButton('Address Condition'), KeyboardButton('Address Variable'))
    markup.row(KeyboardButton(f'Do not ask for Address ({addr_text})'))
    markup.row(KeyboardButton('Commission'), KeyboardButton('Rate'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_wallet_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    email_text = "☑️ On" if global_wallet_setup.get('ask_email') else "⬜️ Off"
    markup.row(KeyboardButton('💬 Edit Main Msg'), KeyboardButton('💬 Edit Prompt Msg'))
    markup.row(KeyboardButton('💬 Edit Success Msg'), KeyboardButton('💬 Edit Email Prompt'))
    markup.row(KeyboardButton('🔘 Edit Inline (Set)'), KeyboardButton('🔘 Edit Inline (Change)'))
    markup.row(KeyboardButton(f'📧 Toggle Email ({email_text})'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_bonus_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💰 Set Amount'), KeyboardButton('⏱ Set Cooldown (hrs)'))
    markup.row(KeyboardButton('💬 Edit Success Msg'), KeyboardButton('💬 Edit Fail Msg'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_assign_command_keyboard(full_path):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    meta = btn_metadata.get(full_path, get_default_metadata())
    cmd_text = "▶️ On" if meta.get('move_by_command') else "⏸ Off"
    
    markup.row(KeyboardButton('✖️ Delete'))
    markup.row(KeyboardButton(f'Move by Command ({cmd_text})'))
    markup.row(KeyboardButton('✅ Confirm'), KeyboardButton('🚫 Cancel Action'))
    return markup

def get_cancel_action_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('❌ Cancel Action'))
    return markup

def get_keyboard_raw(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    current_path = user_current_path.get(user_id, 'root')
    state = user_state.get(user_id, 'normal')
    is_admin = user_id in ADMIN_IDS
    
    if is_admin:
        if state == 'posts_editing':
            markup.row(KeyboardButton('➕ Add Message'))
            markup.row(KeyboardButton('Pagination in Editor (10)'))
            markup.row(KeyboardButton('🎛️ Buttons Editor'), KeyboardButton('🛑 Stop Editor'))
            return markup

        if state in ['posts_adding', 'posts_insert_after', 'posts_rep_text', 'posts_rep_all']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        if state == 'admin_menu':
            markup.row(KeyboardButton('User Macro'), KeyboardButton('📊 Plans'))
            markup.row(KeyboardButton('🏦 Deposit Settings'), KeyboardButton('Withdrawal Settings')) 
            markup.row(KeyboardButton('💳 Wallet Settings'), KeyboardButton('🎁 Bonus Settings')) 
            markup.row(KeyboardButton('🧮 Calculator'), KeyboardButton('📜 Transactions'))
            markup.row(KeyboardButton('🔙 Back to Main'))
            return markup

        if state == 'admin_w_menu': return get_global_withdrawal_keyboard()
        if state == 'admin_wallet_menu': return get_admin_wallet_keyboard()
        if state == 'admin_bonus_menu': return get_admin_bonus_keyboard()

        if state == 'admin_dep_menu':
            for c in deposit_settings.keys():
                markup.row(KeyboardButton(c.replace('_', ' '))) 
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_dep_settings':
            c = admin_dep_setup.get(user_id)
            if not c or c not in deposit_settings:
                markup.row(KeyboardButton('🔙 Back to Deposit Menu'))
                return markup
                
            c_mode = deposit_settings[c]['mode'].upper()
            markup.row(KeyboardButton(f"🔄 Mode: {c_mode}"))
            markup.row(KeyboardButton('💰 Set Min Deposit'), KeyboardButton('💰 Set Max Deposit'))
            markup.row(KeyboardButton('💬 Edit Enter Msg'), KeyboardButton('💬 Edit Instruct Msg'))
            markup.row(KeyboardButton('💬 Edit Pending Msg'), KeyboardButton('💬 Edit Success Msg'))
            markup.row(KeyboardButton('📍 Set Static Address'), KeyboardButton('🔑 Set HD Wallet Key'))
            markup.row(KeyboardButton('🔙 Back to Deposit Menu'))
            return markup

        if state.startswith('dep_setup_') or state.startswith('wallet_setup_') or state.startswith('bonus_setup_'):
            return get_cancel_action_keyboard()

        if state == 'admin_plans':
            markup.row(KeyboardButton('Plan 0'), KeyboardButton('Plan 1'))
            markup.row(KeyboardButton('Plan 2'), KeyboardButton('Plan 3'))
            markup.row(KeyboardButton('Plan 4'), KeyboardButton('Plan 5'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_plan_settings':
            p_id = user_action_data.get(user_id, {}).get('edit_plan')
            is_free = bot_plans.get(p_id, {}).get('is_free', False)
            free_txt = "☑️ On" if is_free else "⬜️ Off"
            
            if p_id == 'plan0':
                markup.row(KeyboardButton('💰 Set Bonus Amount'))
            else:
                markup.row(KeyboardButton('💰 Set Min Deposit'), KeyboardButton('💰 Set Max Deposit'))
                
            markup.row(KeyboardButton('⏱ Contract Length'), KeyboardButton('📈 Plan Percentage'))
            markup.row(KeyboardButton('🖼 Plan Display'), KeyboardButton('💬 Set Inline Text'))
            markup.row(KeyboardButton('💬 Set Active Inline Text'), KeyboardButton(f'🆓 Toggle Free Plan ({free_txt})'))
            markup.row(KeyboardButton('🔗 Set Redirect Cmd'), KeyboardButton('🔙 Back to Plans List')) 
            return markup

        if state.startswith('plan_setup_'):
            p_id = user_action_data.get(user_id, {}).get('edit_plan')
            if state == 'plan_setup_redirect':
                return get_wizard_keyboard(bot_plans.get(p_id, {}).get('redirect_cmd'), allow_empty=True)
            return get_cancel_action_keyboard()

        if state == 'bal_select':
            markup.row(KeyboardButton('Deposit balance'), KeyboardButton('Withdrawal balance'))
            markup.row(KeyboardButton('🔙 Exit Balance'))
            return markup
            
        if state == 'bal_menu':
            markup.row(KeyboardButton('💵 Get'), KeyboardButton('💵 Change'), KeyboardButton('💵 Set'))
            n_txt = "▶️ On" if admin_bal_notify.get(user_id, True) else "⏸ Off"
            markup.row(KeyboardButton(f'Notify User ({n_txt})'), KeyboardButton('Referral Bonus'))
            markup.row(KeyboardButton('🔙 Exit Balance'))
            return markup
            
        if state in ['bal_change_id', 'bal_set_id', 'admin_wait_tx_id']:
            c_txt = "▶️ On" if admin_bal_comment_on.get(user_id, False) else "⏸ Off"
            if state != 'admin_wait_tx_id': markup.row(KeyboardButton(f'With Comment ({c_txt})'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state in ['bal_get_id', 'bal_change_amount', 'bal_set_amount']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state in ['bal_change_comment', 'bal_set_comment']:
            markup.row(KeyboardButton('➖ Set Empty'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        if state.startswith('w_setup_'):
            if state == 'w_setup_var': return get_wizard_keyboard(global_w_setup.get('w_var'), ['balance', 'bonus', 'deposit', 'hourly', 'plan'])
            if state == 'w_setup_min': return get_wizard_keyboard(global_w_setup.get('w_min'), allow_empty=True)
            if state == 'w_setup_max': return get_wizard_keyboard(global_w_setup.get('w_max'), allow_empty=True)
            if state == 'w_setup_enter': return get_wizard_keyboard(global_w_setup.get('w_msg_enter'), allow_empty=True)
            if state == 'w_setup_addr': return get_wizard_keyboard(global_w_setup.get('w_msg_addr'), allow_empty=True)
            if state == 'w_setup_conf': return get_wizard_keyboard(global_w_setup.get('w_msg_conf'), allow_empty=True)

        if state == 'button_settings': return get_settings_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_command': return get_assign_command_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_plan': return get_cancel_action_keyboard()
        
        if state in ['adding_button', 'renaming_button', 'pi_wait_text', 'pi_wait_data']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

    if state in ['buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address']:
        return get_cancel_action_keyboard()

    if current_path in menus and menus[current_path]:
        rows_dict = {}
        for name in menus[current_path]:
            btn_full_path = f"{current_path}/{name}"
            meta = btn_metadata.get(btn_full_path, get_default_metadata())
            
            if meta.get('invisible') and not (is_admin and state in ['editing', 'posts_editing']):
                continue
                
            r_idx = meta.get('row_idx', 0)
            if r_idx not in rows_dict:
                rows_dict[r_idx] = []
            rows_dict[r_idx].append(KeyboardButton(name))

        for r_idx in sorted(rows_dict.keys()):
            row_btns = rows_dict[r_idx]
            if row_btns:
                markup.row(*row_btns)

    if current_path != 'root' and state in ['normal', 'editing', 'posts_editing', 'dep_wait_amount', 'dep_wait_proof']:
        markup.row(KeyboardButton('🔙 Back'), KeyboardButton('🏠 Home'))

    if not is_admin: return markup

    if state == 'editing':
        markup.row(KeyboardButton('➕ Add Button'))
        if user_clipboard.get(user_id):
            markup.row(KeyboardButton(f'📋 Paste "{user_clipboard[user_id]["name"]}"'))
        markup.row(KeyboardButton('🛑 Stop Editor'), KeyboardButton('📝 Posts Editor'))
    elif state == 'normal':
        markup.row(KeyboardButton('🎛️ Buttons Editor'), KeyboardButton('📝 Posts Editor'))
        if current_path == 'root':
            markup.row(KeyboardButton('💵 Balance'), KeyboardButton('🔐 Admin'))
        
    return markup

def get_keyboard(user_id):
    """Intercepts and translates Reply Keyboard outputs transparently."""
    markup = get_keyboard_raw(user_id)
    lang = user_db.get(user_id, {}).get('lang', 'en')
    if lang == 'en' or not markup: return markup

    new_markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in markup.keyboard:
        new_row = []
        for btn in row:
            tl_text = get_tl_and_map(btn['text'], lang)
            new_row.append(KeyboardButton(tl_text))
        new_markup.row(*new_row)
    return new_markup

def get_edit_inline_tools():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton('⬅️', callback_data='cb_move_left'),
        InlineKeyboardButton('⬆️', callback_data='cb_move_up'),
        InlineKeyboardButton('⬇️', callback_data='cb_move_down'),
        InlineKeyboardButton('➡️', callback_data='cb_move_right'),
        InlineKeyboardButton('✳️', callback_data='cb_settings') 
    )
    markup.row(
        InlineKeyboardButton('➗ Edit', callback_data='cb_rename'),
        InlineKeyboardButton('✖️ Delete', callback_data='cb_delete'),
        InlineKeyboardButton('✂️ Cut', callback_data='cb_cut')
    )
    return markup

def get_back_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('🔙 Go Back to Previous Menu', callback_data='go_back'))
    return markup

def get_withdrawal_conf_inline(lang='en'):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(get_tl_and_map('✅ Confirm', lang), callback_data='cb_w_yes'), 
               InlineKeyboardButton(get_tl_and_map('🚫 Cancel', lang), callback_data='cb_w_no'))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    init_user_db(message)
    user_current_path[user_id] = 'root'
    user_state[user_id] = 'normal'
    user_selected_button[user_id] = None
    
    send_path_content(message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))

@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    is_admin = user_id in ADMIN_IDS
    
    init_user_db(message)
    process_accruals(user_id) 
    
    if user_id not in user_current_path: user_current_path[user_id] = 'root'
    if user_id not in user_state: user_state[user_id] = 'normal'
    
    # REVERSE MAP: Transparently translate incoming buttons back to English logic!
    # This loop absolutely guarantees that BACK and HOME buttons always work in any language!
    lang = user_db.get(user_id, {}).get('lang', 'en')
    if lang != 'en':
        if text in REVERSE_TL_MAP.get(lang, {}):
            text = REVERSE_TL_MAP[lang][text]
        else:
            # Bulletproof Fallback check for core navigation (fixes bot reboot translation amnesia)
            core_commands = ['🏠 Home', '🔙 Back', '❌ Cancel Action', '🔙 Exit Button Settings', '🔙 Exit Balance', '🔙 Back to Main', '🔙 Back to Admin', '🎛️ Buttons Editor', '📝 Posts Editor', '💵 Balance', '🔐 Admin']
            for cmd in core_commands:
                if text == get_tl_and_map(cmd, lang):
                    text = cmd
                    break
            if text not in core_commands:
                for btn_name in menus.get(user_current_path.get(user_id, 'root'), []):
                    if text == get_tl_and_map(btn_name, lang):
                        text = btn_name
                        break

    # Reset normal users if stuck in certain states
    if not is_admin and user_state[user_id] not in ['w_action_amount', 'w_action_addr', 'dep_wait_amount', 'dep_wait_proof', 'buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address']: 
        user_state[user_id] = 'normal'
        
    current_path = user_current_path[user_id]
    state = user_state[user_id]
    selected_btn = user_selected_button.get(user_id)
    full_path = f"{current_path}/{selected_btn}" if selected_btn else None

    # --- UPDATED MACRO LIST LOGIC (BULLETPROOF PARSE CATCHER + LIST STYLE) ---
    if text in ['User Macro', 'User Macros', '📜 Macros'] and is_admin:
        macros_msg = (
            "📝 <b>Available Macros List</b>\n"
            "<i>HTML Tags allowed: <b>bold</b>, <i>italic</i>, <code>monospace</code>, <u>underline</u>, <s>strikethrough</s></i>\n"
            "(Tap on any macro to copy it)\n\n"
            "• <code>%balance%</code> - Withdrawal balance (profits)\n"
            "• <code>%deposit%</code> - Deposit balance\n"
            "• <code>%my_plans%</code> - Shows user their active plans\n"
            "• <code>%activeplan%</code> - Exact same as %my_plans%\n"
            "• <code>%userid%</code> - Telegram numeric ID\n"
            "• <code>%username%</code> - Telegram @username\n"
            "• <code>%firstname%</code> - User's first name\n"
            "• <code>%lastname%</code> - User's last name\n\n"
            "• <code>%usd_amount%</code> - USD amount of deposit\n"
            "• <code>%crypto_amount%</code> - Crypto amount of deposit\n"
            "• <code>%address%</code> - Withdraw Wallet address\n\n"
            "• <code>%wallet%</code> - User's USDT Wallet address\n"
            "• <code>%email%</code> - User's Email address\n"
            "• <code>%bonus_amount%</code> - The defined bonus amount\n"
            "• <code>%time_left%</code> - Used dynamically in Bonus fail msg\n\n"
            "• <code>%plan0%</code> ... <code>%plan5%</code> - Plan details\n"
            "• <code>%lang%</code> - User's current language\n\n"
            "<b>NEW BALANCE MACROS:</b>\n"
            "• <code>%plan_invest%</code> - Total active investment\n"
            "• <code>%hourly_profit%</code> - Total hourly profit\n"
            "• <code>%plan_names%</code> - Names of active plans\n"
            "• <code>%ref_count%</code> - Number of referrals\n"
            "• <code>%withdrawn%</code> - Total amount withdrawn\n"
        )
        try:
            bot.send_message(message.chat.id, macros_msg, parse_mode="HTML", reply_markup=get_keyboard(user_id))
        except Exception as e:
            bot.send_message(message.chat.id, "Error rendering Macros.", reply_markup=get_keyboard(user_id))
        return

    # --- HANDLE USER ABORTING OR NAVIGATING ---
    if text in ['❌ Cancel Action', '❌ Cancel', '🚫 Cancel Action']:
        if state in ['posts_adding', 'posts_insert_after', 'posts_rep_text', 'posts_rep_all']:
            user_state[user_id] = 'posts_editing'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
            return
        elif state in ['pi_wait_mode', 'pi_wait_text', 'pi_wait_data', 'pi_wait_buy_plan', 'pi_wait_deposit']:
            user_state[user_id] = 'posts_editing'
            bot.send_message(message.chat.id, get_tl_and_map("Inline editor action cancelled.", lang), reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
            return
        elif state.startswith('bal_') or state in ['adding_button', 'renaming_button', 'assign_plan', 'admin_wait_tx_id', 'assign_command']:
            fallback = 'bal_menu' if state.startswith('bal_') else 'editing'
            user_state[user_id] = fallback
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('dep_setup_'):
            user_state[user_id] = 'admin_dep_settings'
            bot.send_message(message.chat.id, get_tl_and_map("Deposit setting cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('plan_setup_'):
            user_state[user_id] = 'admin_plan_settings'
            bot.send_message(message.chat.id, get_tl_and_map("Plan setting cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('w_setup_'):
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Withdrawal setup cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('wallet_setup_'):
            user_state[user_id] = 'admin_wallet_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Wallet setup cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('bonus_setup_'):
            user_state[user_id] = 'admin_bonus_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Bonus setup cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        else:
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("❌ Action Cancelled.", lang), reply_markup=get_keyboard(user_id))
            return

    # --- FIX 1: NAVIGATION BUTTONS (HOME, BACK, EXITS) ---
    if text == '🏠 Home':
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal' if not is_admin else state # Maintain editing states if admin
        if state in ['posts_adding', 'w_action_amount', 'w_action_addr', 'buyplan_wait_amount', 'dep_wait_amount', 'dep_wait_proof', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address']:
            user_state[user_id] = 'normal'
        send_path_content(message.chat.id, user_id, 'root', is_editing=(user_state[user_id] == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
        return

    if text == '🔙 Back':
        if current_path != 'root':
            parts = current_path.split('/')[:-1]
            new_path = '/'.join(parts) if len(parts) > 1 else 'root'
            user_current_path[user_id] = new_path
            if state in ['w_action_amount', 'w_action_addr', 'buyplan_wait_amount', 'dep_wait_amount', 'dep_wait_proof', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address']:
                user_state[user_id] = 'normal'
            send_path_content(message.chat.id, user_id, new_path, is_editing=(user_state[user_id] == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
        return

    if text == '🔙 Exit Button Settings':
        user_state[user_id] = 'editing'
        user_selected_button[user_id] = None
        bot.send_message(message.chat.id, get_tl_and_map("Exited settings.", lang), reply_markup=get_keyboard(user_id))
        return

    if text == '🔙 Exit Balance':
        user_state[user_id] = 'normal'
        bot.send_message(message.chat.id, get_tl_and_map("Exited balance management.", lang), reply_markup=get_keyboard(user_id))
        return

    # --- FIX: POSTS ADDING / EDITING PROCESSORS ---
    if state == 'posts_adding':
        if current_path not in menu_posts: menu_posts[current_path] = []
        new_post = {
            'id': str(uuid.uuid4())[:8],
            'type': 'photo' if message.photo else 'text',
            'text': message.caption if message.photo else text,
            'photo': message.photo[-1].file_id if message.photo else None,
            'custom_inlines': []
        }
        menu_posts[current_path].append(new_post)
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Message added successfully!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    if state == 'posts_rep_text':
        p_id = user_action_data[user_id]['post_id']
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == p_id), None)
        if post:
            post['text'] = text
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Text updated successfully!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return
        
    if state == 'posts_rep_all':
        p_id = user_action_data[user_id]['post_id']
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == p_id), None)
        if post:
            post['type'] = 'photo' if message.photo else 'text'
            post['text'] = message.caption if message.photo else text
            post['photo'] = message.photo[-1].file_id if message.photo else None
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Message completely replaced!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    if state == 'posts_insert_after':
        p_id = user_action_data[user_id]['post_id']
        posts_list = menu_posts.get(current_path, [])
        idx = next((i for i, p in enumerate(posts_list) if p['id'] == p_id), -1)
        
        new_post = {
            'id': str(uuid.uuid4())[:8],
            'type': 'photo' if message.photo else 'text',
            'text': message.caption if message.photo else text,
            'photo': message.photo[-1].file_id if message.photo else None,
            'custom_inlines': []
        }
        if idx != -1:
            posts_list.insert(idx + 1, new_post)
        else:
            posts_list.append(new_post)
            
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Message inserted successfully!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    # --- FIX 2: BUTTON ASSIGNMENTS HANDLER ---
    if state == 'button_settings':
        btn_path = f"{current_path}/{user_selected_button.get(user_id)}"
        meta = btn_metadata.get(btn_path, get_default_metadata())
        
        if text == 'Assign Command':
            user_state[user_id] = 'assign_command'
            bot.send_message(message.chat.id, "Enter the command (e.g. /deposit) to bind to this button:", reply_markup=get_cancel_action_keyboard())
        elif text == 'Assign Plan':
            user_state[user_id] = 'assign_plan'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for p in bot_plans: markup.row(KeyboardButton(p))
            markup.row(KeyboardButton('➖ Set Empty'), KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select a plan to assign:", reply_markup=markup)
        elif text == 'Assign Language':
            meta['is_language'] = True
            btn_metadata[btn_path] = meta
            # Pre-populate menu_posts if empty with a language keyboard matrix
            if not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': 'Current Language: <b>%lang%</b>\nSelect Language to change it',
                    'photo': None,
                    'custom_inlines': []
                }
                # Add default buttons dynamically from requirement. Chinese forced to zh-CN so deep-translator never fails.
                langs = [
                    ('🇬🇧 English', 'en'), ('🇨🇳 Chinese', 'zh-CN'), ('🇵🇹 Portuguese', 'pt'),
                    ('🇳🇱 Dutch', 'nl'), ('🇪🇸 Spanish', 'es'), ('🇩🇪 German', 'de'),
                    ('🇫🇷 French', 'fr'), ('🇸🇦 Arabic', 'ar'), ('🇷🇺 Russian', 'ru'),
                    ('🇮🇩 Indonesian', 'id'), ('🇮🇳 Hindi', 'hi')
                ]
                r_idx = 0
                for i, (l_name, l_code) in enumerate(langs):
                    if i > 0 and i % 2 == 0: r_idx += 1
                    new_post['custom_inlines'].append({
                        'id': str(uuid.uuid4())[:6],
                        'text': l_name,
                        'mode': 'set_lang',
                        'data': l_code,
                        'row_idx': r_idx
                    })
                menu_posts[btn_path] = [new_post]
            user_state[user_id] = 'button_settings'
            bot.send_message(message.chat.id, "✅ Language Menu assigned!\n\nThe post and inline buttons have been generated for you. You can edit their layout or remove languages directly in the Posts Editor.", reply_markup=get_keyboard(user_id))
            return
        elif text.startswith('Assign Calculator'):
            meta['is_calculator'] = not meta.get('is_calculator', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Calculator toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign History'):
            meta['is_history'] = not meta.get('is_history', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "History toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Withdrawal'):
            meta['withdrawal'] = not meta.get('withdrawal', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Withdrawal toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Wallet'):
            meta['is_wallet'] = not meta.get('is_wallet', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Wallet toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Bonus'):
            meta['is_bonus'] = not meta.get('is_bonus', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Bonus toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Balance'):
            meta['is_balance'] = not meta.get('is_balance', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_balance'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "━━━━━━━━━━━━━━━━━━\n📊 <b>G-Force Auto Trading Bot</b>\n━━━━━━━━━━━━━━━━━━\n💵 Balance: <b>%balance% USDT</b>\n💼 Active Investment: <b>%plan_invest% USDT</b>\n━━━━━━━━━━━━━━━━━━\n🎁 Bonus: <b>%bonus% USDT</b>\n⏱ Hourly Profit: <b>%hourly_profit% USDT</b>\n━━━━━━━━━━━━━━━━━━\n⚙️ Plan: <b>%plan_names%</b>\n👥 Referrals: <b>%ref_count% Users</b>\n💳 Payouts: <b>%withdrawn% USDT</b>\n━━━━━━━━━━━━━━━━━━",
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Balance page assigned and pre-populated.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Random Message'):
            meta['random_message'] = not meta.get('random_message', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Random Message toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Admin Only'):
            meta['admin_only'] = not meta.get('admin_only', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Admin Only toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Invisible'):
            meta['invisible'] = not meta.get('invisible', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Invisible toggled.", reply_markup=get_keyboard(user_id))
        return

    if state == 'assign_command':
        btn_path = f"{current_path}/{user_selected_button.get(user_id)}"
        meta = btn_metadata.get(btn_path, get_default_metadata())
        meta['move_by_command'] = True
        meta['command'] = text
        btn_metadata[btn_path] = meta
        user_state[user_id] = 'button_settings'
        bot.send_message(message.chat.id, f"✅ Command <code>{text}</code> assigned to this button!", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'assign_plan':
        btn_path = f"{current_path}/{user_selected_button.get(user_id)}"
        meta = btn_metadata.get(btn_path, get_default_metadata())
        if text == '➖ Set Empty':
            meta['assigned_plan'] = None
        else:
            if text not in bot_plans: return bot.send_message(message.chat.id, "⚠️ Invalid plan selected.")
            meta['assigned_plan'] = text
        btn_metadata[btn_path] = meta
        user_state[user_id] = 'button_settings'
        bot.send_message(message.chat.id, f"✅ Plan assigned!", reply_markup=get_keyboard(user_id))
        return

    # --- INLINE POST EDITOR LOGIC FIX ---
    if state == 'pi_wait_mode':
        if text not in ['🔗 URL or Share', '💬 Popup Window', '🚀 Command', '🛒 Buy Plan', '🏦 Deposit', '🌐 Set Language']:
            return bot.send_message(message.chat.id, "Invalid option. Select from keyboard.")
        
        user_action_data[user_id]['pi_mode'] = text
        user_state[user_id] = 'pi_wait_text'
        bot.send_message(message.chat.id, "Enter the TEXT for this button:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'pi_wait_text':
        user_action_data[user_id]['pi_text'] = text
        mode = user_action_data[user_id]['pi_mode']
        
        if mode == '🔗 URL or Share':
            user_state[user_id] = 'pi_wait_data'
            bot.send_message(message.chat.id, "Enter the URL (e.g. https://...):")
        elif mode == '💬 Popup Window':
            user_state[user_id] = 'pi_wait_data'
            bot.send_message(message.chat.id, "Enter the text to show in the popup:")
        elif mode == '🚀 Command':
            user_state[user_id] = 'pi_wait_data'
            bot.send_message(message.chat.id, "Enter the exact command/button name to trigger:")
        elif mode == '🌐 Set Language':
            user_state[user_id] = 'pi_wait_data'
            bot.send_message(message.chat.id, "Enter the language code (e.g. 'en', 'es', 'fr', 'zh-CN'):")
        elif mode == '🛒 Buy Plan':
            user_state[user_id] = 'pi_wait_data'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for p in bot_plans: markup.row(KeyboardButton(p))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Plan to trigger:", reply_markup=markup)
        elif mode == '🏦 Deposit':
            user_state[user_id] = 'pi_wait_data'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for c in deposit_settings: markup.row(KeyboardButton(c))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Deposit currency to trigger:", reply_markup=markup)
        return

    if state == 'pi_wait_data':
        data_val = text
        btn_text = user_action_data[user_id]['pi_text']
        raw_mode = user_action_data[user_id]['pi_mode']
        
        mode_map = {
            '🔗 URL or Share': 'url',
            '💬 Popup Window': 'popup',
            '🚀 Command': 'command',
            '🛒 Buy Plan': 'buy_plan',
            '🏦 Deposit': 'deposit',
            '🌐 Set Language': 'set_lang'
        }
        final_mode = mode_map[raw_mode]
        
        if final_mode == 'buy_plan':
            if data_val not in bot_plans: return bot.send_message(message.chat.id, "Invalid plan.")
        elif final_mode == 'deposit':
            if data_val not in deposit_settings: return bot.send_message(message.chat.id, "Invalid deposit.")
            
        post_id = user_action_data[user_id]['post_id']
        btn_id = user_action_data[user_id].get('btn_id')
        
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
        if post:
            if 'custom_inlines' not in post: post['custom_inlines'] = []
            
            if btn_id: 
                for b in post['custom_inlines']:
                    if b['id'] == btn_id:
                        b['text'] = btn_text
                        b['mode'] = final_mode
                        b['data'] = data_val
                        break
            else: 
                max_r = 0
                if post['custom_inlines']:
                    max_r = max(b.get('row_idx', 0) for b in post['custom_inlines']) + 1
                post['custom_inlines'].append({
                    'id': str(uuid.uuid4())[:6],
                    'text': btn_text,
                    'mode': final_mode,
                    'data': data_val,
                    'row_idx': max_r
                })
                
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, "✅ Inline button saved!", reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    # --- WALLET FLOW USER ---
    if state == 'wallet_wait_email':
        user_db[user_id]['email'] = text
        user_state[user_id] = 'wallet_wait_address'
        bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML")
        return

    if state == 'wallet_wait_address':
        addr = text.strip()
        net = ""
        if addr.startswith('T') and len(addr) >= 33:
            net = "TRC20"
        elif addr.startswith('0x') and len(addr) == 42:
            net = "BEP20"
        else:
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid Address. Supported networks are USDT TRC20 (starts with T) and BEP20 (starts with 0x). Try again or Cancel.", lang))

        user_db[user_id]['wallet'] = addr
        user_db[user_id]['wallet_net'] = net
        user_state[user_id] = 'normal'
        
        msg = global_wallet_setup['msg_success'].replace('%wallet%', addr).replace('%network%', net)
        bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, current_path), lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN WALLET SETTINGS ---
    if state == 'admin_wallet_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Main Msg':
            user_state[user_id] = 'wallet_setup_main'
            bot.send_message(message.chat.id, f"Enter the main wallet page message (macros: %wallet%, %email%):\n\nCurrent:\n{global_wallet_setup['msg_main']}", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Prompt Msg':
            user_state[user_id] = 'wallet_setup_prompt'
            bot.send_message(message.chat.id, f"Enter the message asking for address:\n\nCurrent:\n{global_wallet_setup['msg_prompt']}", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'wallet_setup_success'
            bot.send_message(message.chat.id, f"Enter the success message:\n\nCurrent:\n{global_wallet_setup['msg_success']}", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Email Prompt':
            user_state[user_id] = 'wallet_setup_email_prompt'
            bot.send_message(message.chat.id, f"Enter the message asking for email:\n\nCurrent:\n{global_wallet_setup['msg_email_prompt']}", reply_markup=get_cancel_action_keyboard())
        elif text == '🔘 Edit Inline (Set)':
            user_state[user_id] = 'wallet_setup_inline_set'
            bot.send_message(message.chat.id, f"Enter the button text for first time setup:\n\nCurrent: {global_wallet_setup['inline_set']}", reply_markup=get_cancel_action_keyboard())
        elif text == '🔘 Edit Inline (Change)':
            user_state[user_id] = 'wallet_setup_inline_change'
            bot.send_message(message.chat.id, f"Enter the button text for changing wallet:\n\nCurrent: {global_wallet_setup['inline_change']}", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('📧 Toggle Email'):
            global_wallet_setup['ask_email'] = not global_wallet_setup['ask_email']
            bot.send_message(message.chat.id, f"Email requirement toggled.", reply_markup=get_keyboard(user_id))
        return

    if state.startswith('wallet_setup_'):
        if state == 'wallet_setup_main': global_wallet_setup['msg_main'] = text
        elif state == 'wallet_setup_prompt': global_wallet_setup['msg_prompt'] = text
        elif state == 'wallet_setup_success': global_wallet_setup['msg_success'] = text
        elif state == 'wallet_setup_email_prompt': global_wallet_setup['msg_email_prompt'] = text
        elif state == 'wallet_setup_inline_set': global_wallet_setup['inline_set'] = text
        elif state == 'wallet_setup_inline_change': global_wallet_setup['inline_change'] = text
        
        user_state[user_id] = 'admin_wallet_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN BONUS SETTINGS ---
    if state == 'admin_bonus_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💰 Set Amount':
            user_state[user_id] = 'bonus_setup_amount'
            bot.send_message(message.chat.id, f"Enter the bonus amount:\n\nCurrent: ${global_bonus_setup['amount']}", reply_markup=get_cancel_action_keyboard())
        elif text == '⏱ Set Cooldown (hrs)':
            user_state[user_id] = 'bonus_setup_cooldown'
            bot.send_message(message.chat.id, f"Enter cooldown time in hours (e.g. 12 or 24):\n\nCurrent: {global_bonus_setup['cooldown_hours']}h", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'bonus_setup_success'
            bot.send_message(message.chat.id, f"Enter success msg (macro: %bonus_amount%):\n\nCurrent:\n{global_bonus_setup['msg_success']}", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Fail Msg':
            user_state[user_id] = 'bonus_setup_fail'
            bot.send_message(message.chat.id, f"Enter fail msg (macro: %time_left%):\n\nCurrent:\n{global_bonus_setup['msg_fail']}", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('bonus_setup_'):
        if state == 'bonus_setup_amount':
            try: global_bonus_setup['amount'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_cooldown':
            try: global_bonus_setup['cooldown_hours'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_success': global_bonus_setup['msg_success'] = text
        elif state == 'bonus_setup_fail': global_bonus_setup['msg_fail'] = text
        
        user_state[user_id] = 'admin_bonus_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- PROFIT CALCULATOR ENGINE ---
    if state == 'wait_calc_amount':
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))
        
        msg = f"🧮 <b>Calculator Results for ${amount:.2f}</b>\n\n"
        found = False
        markup = InlineKeyboardMarkup()
        for p_id, p_data in bot_plans.items():
            if p_id == 'plan0': continue 
            if p_data['min'] <= amount <= p_data['max']:
                found = True
                hourly = amount * (p_data['profit'] / 100.0)
                daily = hourly * 24
                msg += f"🔹 <b>{p_data['name']}</b>\n"
                msg += f"Hourly Profit: ${hourly:.2f}\nDaily Profit: ${daily:.2f}\n"
                if p_data['length'] > 0:
                    total = hourly * p_data['length']
                    msg += f"Total Return ({p_data['length']}h): ${total:.2f}\n\n"
                else:
                    msg += f"Total Return: Lifetime\n\n"
                
                markup.row(InlineKeyboardButton(get_tl_and_map(f"🛒 Buy {p_data['name']}", lang), callback_data=f"cb_calcbuy_{p_id}_{amount}"))
                
        if not found:
            msg += "No plans available for this exact amount."
            
        bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=markup if found else get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

    # --- PLAN BUYING ENGINE (Wait Amount Fallback) ---
    if state == 'buyplan_wait_amount':
        try: invest_amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))
        
        p_id = user_action_data[user_id].get('buy_plan_id')
        p_data = bot_plans[p_id]
        
        if invest_amount < p_data['min'] or invest_amount > p_data['max']:
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Amount must be between <b>${p_data['min']}</b> and <b>${p_data['max']}</b>.", lang), parse_mode="HTML")
            
        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        
        if invest_amount > (u_dep + u_bal):
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Insufficient funds.", lang))
            
        if u_dep >= invest_amount:
            user_db[user_id]['deposit'] -= invest_amount
        else:
            rem = invest_amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem
            
        log_tx(user_id, f"Bought {p_data['name']}", -invest_amount)
            
        new_plan = {
            'id': str(uuid.uuid4())[:8],
            'macro': p_id,
            'amount': invest_amount,
            'profit_pct': p_data['profit'],
            'length_hours': p_data.get('length', 0),
            'start_time': time.time(),
            'last_accrual': time.time(),
            'earned': 0.0,
            'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        
        user_state[user_id] = 'normal'
        msg = f"🎉 <b>Success!</b>\nYou invested <b>${invest_amount:.2f}</b> into <b>{p_data['name']}</b>!\nYour profit is accruing automatically."
        bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- ENHANCED USER DEPOSIT FLOW ENGINE (WITH ORACLE & HD WALLETS) ---
    if state == 'dep_wait_amount':
        try: usd_amount = float(text)
        except ValueError:
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Please enter numbers only (e.g., 100).", lang))
            
        if user_id not in user_action_data or 'currency' not in user_action_data.get(user_id, {}):
            user_state[user_id] = 'normal'
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Session expired. Please click the deposit button again.", lang), reply_markup=get_keyboard(user_id))
        
        curr = user_action_data[user_id]['currency']
        conf = deposit_settings[curr]
        
        c_min = conf.get('min', 0.0)
        c_max = conf.get('max', float('inf'))
        if usd_amount < c_min: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Minimum deposit is <b>${c_min:.2f} USD</b>.", lang), parse_mode="HTML")
        if usd_amount > c_max: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Maximum deposit is <b>${c_max:.2f} USD</b>.", lang), parse_mode="HTML")

        user_action_data[user_id]['usd_amount'] = usd_amount
        
        if conf['mode'] == 'manual':
            msg = conf['msg_instruct'].replace('%amount%', str(usd_amount)).replace('%address%', conf['address'])
            user_state[user_id] = 'dep_wait_proof'
            bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode='HTML', reply_markup=get_cancel_action_keyboard())
        else:
            bot.send_message(message.chat.id, get_tl_and_map(f"🔄 Fetching live exchange rate for {curr.replace('_', ' ')}...", lang), reply_markup=get_cancel_action_keyboard())
            
            live_price = get_crypto_price(curr)
            if not live_price:
                user_state[user_id] = 'normal'
                return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Error connecting to price oracle. Please try again later.", lang), reply_markup=get_keyboard(user_id))
            
            crypto_amount = round(usd_amount / live_price, 6)
            
            if curr not in user_db[user_id]['wallets']:
                bot.send_message(message.chat.id, get_tl_and_map("🔐 Generating your secure deterministic wallet...", lang), reply_markup=get_cancel_action_keyboard())
                
                address, private_key = generate_user_wallet(user_id, curr)
                if address == "ERROR_NO_SEED":
                    return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Admin has not configured the Master Seed Phrase. Deposits offline.", lang))
                
                user_db[user_id]['wallets'][curr] = {'address': address, 'private_key': private_key}
                
                admin_alert = f"🚨 <b>NEW WALLET GENERATED</b> 🚨\n\n👤 User: <code>{user_id}</code> (@{message.from_user.username})\n🪙 Currency: {curr.replace('_', ' ')}\n\n📫 Public Address:\n<code>{address}</code>\n\n🔑 <b>PRIVATE KEY</b> (KEEP SECRET):\n<code>{private_key}</code>"
                for admin in ADMIN_IDS:
                    try: bot.send_message(admin, admin_alert, parse_mode="HTML")
                    except Exception: pass
            else:
                address = user_db[user_id]['wallets'][curr]['address']
            
            msg = conf['msg_instruct'].replace('%crypto_amount%', str(crypto_amount)).replace('%address%', address)
            msg = f"<i>(Live Rate: 1 {curr.split('_')[0]} = ${live_price:.2f})</i>\n\n{msg}"
            
            bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode='HTML', reply_markup=get_keyboard(user_id))
            
            user_state[user_id] = 'normal'
        return

    if state == 'dep_wait_proof':
        if user_id not in user_action_data or 'currency' not in user_action_data.get(user_id, {}):
            user_state[user_id] = 'normal'
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Session expired. Please click the deposit button again.", lang), reply_markup=get_keyboard(user_id))
            
        dep_id = str(uuid.uuid4())[:8]
        curr = user_action_data[user_id]['currency']
        amt = user_action_data[user_id]['usd_amount']
        pending_deposits[dep_id] = {'user_id': user_id, 'amount': amt, 'currency': curr}
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('✅ Approve', callback_data=f'cb_depapp_{dep_id}'),
                   InlineKeyboardButton('❌ Reject', callback_data=f'cb_deprej_{dep_id}'))
        
        admin_msg = f"📥 <b>New Deposit Request</b>\nUser ID: <code>{user_id}</code>\nUsername: @{message.from_user.username or 'None'}\nAmount: <b>${amt} (USD Equivalent)</b>"
        
        for admin in ADMIN_IDS:
            try:
                if message.photo:
                    bot.send_photo(admin, message.photo[-1].file_id, caption=admin_msg, parse_mode="HTML", reply_markup=markup)
                else:
                    bot.send_message(admin, admin_msg + f"\n\n**Proof Data:**\n{text}", parse_mode="HTML", reply_markup=markup)
            except Exception: pass
        
        user_state[user_id] = 'normal'
        
        conf = deposit_settings[curr]
        msg_pending = conf.get('msg_pending', "✅ Your deposit request has been submitted to the administrators.")
        msg_pending = msg_pending.replace('%usd_amount%', str(amt))
        bot.send_message(message.chat.id, get_tl_and_map(msg_pending, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN DEPOSIT MENU CONTROLS ---
    if state == 'admin_dep_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        else:
            curr_key = text.strip().upper().replace(' ', '_')
            if curr_key in deposit_settings:
                admin_dep_setup[user_id] = curr_key
                user_state[user_id] = 'admin_dep_settings'
                clean_name = curr_key.replace('_', ' ')
                bot.send_message(message.chat.id, f"🏦 <b>Editing Settings for {clean_name}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_dep_settings':
        curr = admin_dep_setup.get(user_id)
        if text == '🔙 Back to Deposit Menu':
            user_state[user_id] = 'admin_dep_menu'
            bot.send_message(message.chat.id, "🏦 <b>Deposit Menu</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text.startswith('🔄 Mode:'):
            deposit_settings[curr]['mode'] = 'auto' if deposit_settings[curr]['mode'] == 'manual' else 'manual'
            bot.send_message(message.chat.id, f"Mode switched to <b>{deposit_settings[curr]['mode'].upper()}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📍 Set Static Address':
            user_state[user_id] = 'dep_setup_addr'
            bot.send_message(message.chat.id, f"Send the Static Receiving Address for <b>{curr.replace('_', ' ')}</b>:\n\nℹ️ Current: <code>{deposit_settings[curr]['address']}</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '🔑 Set HD Wallet Key':
            user_state[user_id] = 'dep_setup_key'
            bot.send_message(message.chat.id, f"Send the Master HD Key/Seed for <b>{curr.replace('_', ' ')}</b> (Auto Mode):\n\nℹ️ Current: <code>{deposit_settings[curr]['hd_key']}</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Enter Msg':
            user_state[user_id] = 'dep_setup_enter'
            bot.send_message(message.chat.id, f"Send the prompt message asking user for amount:\n\nℹ️ Current: <code>{deposit_settings[curr]['msg_enter']}</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Instruct Msg':
            user_state[user_id] = 'dep_setup_instruct'
            bot.send_message(message.chat.id, f"Send instructions containing `%crypto_amount%` and `%address%` macros:\n\nℹ️ Current:\n{deposit_settings[curr]['msg_instruct']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        
        elif text == '💰 Set Min Deposit':
            user_state[user_id] = 'dep_setup_min'
            bot.send_message(message.chat.id, f"Enter Minimum Deposit Amount in USD for <b>{curr.replace('_', ' ')}</b>:\n\nℹ️ Current: {deposit_settings[curr].get('min', 10.0)}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💰 Set Max Deposit':
            user_state[user_id] = 'dep_setup_max'
            bot.send_message(message.chat.id, f"Enter Maximum Deposit Amount in USD for <b>{curr.replace('_', ' ')}</b>:\n\nℹ️ Current: {deposit_settings[curr].get('max', 10000.0)}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Pending Msg':
            user_state[user_id] = 'dep_setup_pending'
            bot.send_message(message.chat.id, f"Send the message shown when a user submits deposit proof (Manual Mode). Use macro `%usd_amount%`:\n\nℹ️ Current:\n{deposit_settings[curr].get('msg_pending', '')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'dep_setup_success'
            bot.send_message(message.chat.id, f"Send the success message when a deposit is approved. Use macros `%usd_amount%` and `%crypto_amount%`:\n\nℹ️ Current:\n{deposit_settings[curr].get('msg_success', '')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return
        
    if state.startswith('dep_setup_'):
        curr = admin_dep_setup.get(user_id)
        if state == 'dep_setup_addr': deposit_settings[curr]['address'] = text
        elif state == 'dep_setup_key': deposit_settings[curr]['hd_key'] = text
        elif state == 'dep_setup_enter': deposit_settings[curr]['msg_enter'] = text
        elif state == 'dep_setup_instruct': deposit_settings[curr]['msg_instruct'] = text
        elif state == 'dep_setup_pending': deposit_settings[curr]['msg_pending'] = text
        elif state == 'dep_setup_success': deposit_settings[curr]['msg_success'] = text
        elif state == 'dep_setup_min':
            try: deposit_settings[curr]['min'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
        elif state == 'dep_setup_max':
            try: deposit_settings[curr]['max'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
        
        user_state[user_id] = 'admin_dep_settings'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- GLOBAL WITHDRAWAL SETTINGS ---
    if state == 'admin_w_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Set Withdrawal Var':
            user_state[user_id] = 'w_setup_var'
            curr = global_w_setup.get('w_var', 'balance')
            bot.send_message(message.chat.id, f"✨ Select variable for withdrawal (deduction).\n\n❗️ User will specify the amount deducted from this variable.\n\nℹ️ Current variable:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text == 'Set Min/Max':
            user_state[user_id] = 'w_setup_min'
            curr = global_w_setup.get('w_min')
            bot.send_message(message.chat.id, f"✨ Enter the MINIMAL sum for withdrawal.\n\nLeave empty if there is no minimal sum.\n\nℹ️ Current minimal sum:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Enter Msg':
            user_state[user_id] = 'w_setup_enter'
            curr = global_w_setup.get('w_msg_enter')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown UPON ENTRANCE into the Withdraw button.\n\n❗️ Use macros like %balance%, %min%, %max%, etc.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Address Msg':
            user_state[user_id] = 'w_setup_addr'
            curr = global_w_setup.get('w_msg_addr')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown when ASK ADDRESS/PHONE to withdraw.\n\n❗️ Use macros like %firstname%, %address%.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Confirm Msg':
            user_state[user_id] = 'w_setup_conf'
            curr = global_w_setup.get('w_msg_conf')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown BEFORE the operation commit.\n\n❗️ Ask User to CONFIRM withdraw operation.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text.startswith('Do not ask for Address'):
            global_w_setup['do_not_ask_address'] = not global_w_setup.get('do_not_ask_address', False)
            bot.send_message(message.chat.id, "Address setting toggled.", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, f"🛠 <b>{text}</b> is acknowledged. Setup feature coming soon!", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state.startswith('w_setup_'):
        val = None if text == '➖ Set Empty' else text
        if text != '✔️ Leave as Is':
            if state == 'w_setup_var': global_w_setup['w_var'] = val
            elif state == 'w_setup_min': global_w_setup['w_min'] = val
            elif state == 'w_setup_max': global_w_setup['w_max'] = val
            elif state == 'w_setup_enter': global_w_setup['w_msg_enter'] = val
            elif state == 'w_setup_addr': global_w_setup['w_msg_addr'] = val
            elif state == 'w_setup_conf': global_w_setup['w_msg_conf'] = val

        if state == 'w_setup_var':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "✅ Withdrawal setup saved!", reply_markup=get_keyboard(user_id))
        elif state == 'w_setup_min':
            user_state[user_id] = 'w_setup_max'
            curr = global_w_setup.get('w_max')
            bot.send_message(message.chat.id, f"✨ Enter the MAXIMAL sum for withdrawal.\n\nLeave empty if there is no maximal sum.\n\nℹ️ Current maximal sum:\n{curr}", reply_markup=get_keyboard(user_id))
        elif state == 'w_setup_max':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "✅ Limits saved!", reply_markup=get_keyboard(user_id))
        elif state == 'w_setup_enter' or state == 'w_setup_addr' or state == 'w_setup_conf':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "✅ Messages updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN PLANS MANAGER ---
    if state == 'admin_plans':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text.startswith('Plan '):
            p_id = text.replace('Plan ', 'plan').lower()
            if p_id in bot_plans:
                if user_id not in user_action_data: user_action_data[user_id] = {}
                user_action_data[user_id]['edit_plan'] = p_id
                user_state[user_id] = 'admin_plan_settings'
                bot.send_message(message.chat.id, f"⚙️ <b>Editing {text}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_plan_settings':
        p_id = user_action_data[user_id].get('edit_plan')
        if text == '🔙 Back to Plans List':
            user_state[user_id] = 'admin_plans'
            bot.send_message(message.chat.id, "📊 <b>Plans Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        
        # FIX: Plan 0 custom logic
        elif text == '💰 Set Bonus Amount' and p_id == 'plan0':
            user_state[user_id] = 'plan_setup_bonus'
            bot.send_message(message.chat.id, f"Enter free bonus capital amount for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id].get('bonus_amount', 50.0)}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif text == '💰 Set Min Deposit' and p_id != 'plan0':
            user_state[user_id] = 'plan_setup_min'
            bot.send_message(message.chat.id, f"Enter Minimum Deposit for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id]['min']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💰 Set Max Deposit' and p_id != 'plan0':
            user_state[user_id] = 'plan_setup_max'
            bot.send_message(message.chat.id, f"Enter Maximum Deposit for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id]['max']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '⏱ Contract Length':
            user_state[user_id] = 'plan_setup_length'
            msg_instruct = f"Enter Contract Length for <b>{bot_plans[p_id]['name']}</b>:\n\n"
            msg_instruct += "• <b>For Days:</b> Enter 1, 2, 3 etc.\n"
            msg_instruct += "• <b>For Hours:</b> Enter 0.1 for 10h, 0.24 for 24h etc.\n"
            msg_instruct += "• Enter 0 for Lifetime.\n\n"
            msg_instruct += f"ℹ️ Current: {bot_plans[p_id]['length']} hours"
            bot.send_message(message.chat.id, msg_instruct, parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '📈 Plan Percentage':
            user_state[user_id] = 'plan_setup_profit'
            bot.send_message(message.chat.id, f"Enter Profit Percentage for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: {bot_plans[p_id]['profit']}%", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '🖼 Plan Display':
            user_state[user_id] = 'plan_setup_display'
            bot.send_message(message.chat.id, f"Send an Image with a Caption (or just text) to set as the display for <b>{bot_plans[p_id]['name']}</b>:", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Set Inline Text':
            user_state[user_id] = 'plan_setup_inline'
            bot.send_message(message.chat.id, f"Enter the text for the inline purchase button (e.g. 'Buy Now'):\n\nℹ️ Current: {bot_plans[p_id].get('inline_text', 'Buy Now')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Set Active Inline Text':
            user_state[user_id] = 'plan_setup_active_inline'
            bot.send_message(message.chat.id, f"Enter the text for when a user already owns this plan:\n\nℹ️ Current: {bot_plans[p_id].get('inline_active_text', '(Active ✅)')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('🆓 Toggle Free Plan'):
            bot_plans[p_id]['is_free'] = not bot_plans[p_id].get('is_free', False)
            bot.send_message(message.chat.id, f"✅ Free Plan mode toggled.", reply_markup=get_keyboard(user_id))
        elif text == '🔗 Set Redirect Cmd':
            user_state[user_id] = 'plan_setup_redirect'
            bot.send_message(message.chat.id, f"Enter the command or text to redirect users to when they lack funds (e.g. /deposit or a menu button name). Send '➖ Set Empty' to use the default deposit menu:\n\nℹ️ Current: <code>{bot_plans[p_id].get('redirect_cmd', 'Default Deposit Menu')}</code>", parse_mode="HTML", reply_markup=get_wizard_keyboard(bot_plans[p_id].get('redirect_cmd'), allow_empty=True))
        return

    if state.startswith('plan_setup_'):
        p_id = user_action_data[user_id].get('edit_plan')
        if state == 'plan_setup_bonus':
            try: bot_plans[p_id]['bonus_amount'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_min':
            try: bot_plans[p_id]['min'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_max':
            try: bot_plans[p_id]['max'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_length':
            try: 
                raw_val = float(text)
                if raw_val > 0 and raw_val < 1:
                    bot_plans[p_id]['length'] = round(raw_val * 100) 
                elif raw_val >= 1:
                    bot_plans[p_id]['length'] = raw_val * 24 
                else:
                    bot_plans[p_id]['length'] = 0.0 
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_profit':
            try: bot_plans[p_id]['profit'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_display':
            bot_plans[p_id]['photo'] = message.photo[-1].file_id if message.photo else None
            bot_plans[p_id]['text'] = message.caption if message.photo else text
        elif state == 'plan_setup_inline':
            bot_plans[p_id]['inline_text'] = text
        elif state == 'plan_setup_active_inline':
            bot_plans[p_id]['inline_active_text'] = text
        elif state == 'plan_setup_redirect':
            bot_plans[p_id]['redirect_cmd'] = None if text == '➖ Set Empty' else text
            
        user_state[user_id] = 'admin_plan_settings'
        bot.send_message(message.chat.id, "✅ Plan updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- BLOCK UNAUTHORIZED ADMIN COMMANDS ---
    admin_commands = ['🎛️ Buttons Editor', '📝 Posts Editor', '💵 Balance', '🔐 Admin', '➕ Add Button', '🛑 Stop Editor', '✅ Confirm', '🚫 Cancel', '✖️ Delete', 'Deposit balance', 'Withdrawal balance', 'User Macro', 'User Macros', '📜 Macros', '📊 Plans', '🔙 Back to Main', '🔙 Back to Admin', '➕ Add Plan', '➕ Add Message', 'Pagination in Editor (10)', '🏦 Deposit Settings', 'Withdrawal Settings', '🔙 Back to Deposit Menu', '📍 Set Static Address', '🔑 Set HD Wallet Key', '💬 Edit Enter Msg', '💬 Edit Instruct Msg', '💰 Set Min Deposit', '💰 Set Max Deposit', '💬 Edit Pending Msg', '💬 Edit Success Msg', '🧮 Calculator', '📜 Transactions', '💳 Wallet Settings', '🎁 Bonus Settings']
    if not is_admin and (text in admin_commands or text.startswith('📋 Paste "') or text == '✔️ Leave as Is' or text == '➖ Set Empty' or text.startswith('⚙️ Edit ')):
        bot.send_message(message.chat.id, get_tl_and_map("Unrecognized command.", lang), reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN POSTS EDITOR CONTROLS ---
    if state == 'editing':
        if text == '🛑 Stop Editor':
            user_state[user_id] = 'normal'
            user_selected_button[user_id] = None
            bot.send_message(message.chat.id, "Editor stopped.", reply_markup=get_keyboard(user_id))
        elif text == '➕ Add Button':
            user_state[user_id] = 'adding_button'
            bot.send_message(message.chat.id, "Send the name for the new button:", reply_markup=get_cancel_action_keyboard())
        elif text == '📝 Posts Editor':
            user_state[user_id] = 'posts_editing'
            bot.send_message(message.chat.id, "📝 <b>Posts Editor Activated</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
        elif current_path in menus and text in menus[current_path]:
            if user_selected_button.get(user_id) == text:
                user_selected_button[user_id] = None
                new_path = f"{current_path}/{text}"
                user_current_path[user_id] = new_path
                if new_path not in menus: menus[new_path] = []
                send_path_content(message.chat.id, user_id, new_path, False, reply_keyboard=get_keyboard(user_id))
            else:
                user_selected_button[user_id] = text
                bot.send_message(message.chat.id, f"🛠 Selected: <b>{text}</b>\nChoose an action:", parse_mode="HTML", reply_markup=get_edit_inline_tools())
        return

    if state == 'posts_editing':
        if text == '🛑 Stop Editor':
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "🛑 Posts Editor stopped.", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, False, reply_keyboard=get_keyboard(user_id))
            return
        elif text == '🎛️ Buttons Editor':
            user_state[user_id] = 'editing'
            bot.send_message(message.chat.id, "🎛 <b>Buttons Editor Activated</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            return
        elif text == '➕ Add Message':
            user_state[user_id] = 'posts_adding'
            bot.send_message(message.chat.id, "Send the text or photo for the new message:", reply_markup=get_cancel_action_keyboard())
            return
        elif text.startswith('Pagination'):
            bot.send_message(message.chat.id, "Pagination settings acknowledged. (Logic pending).", reply_markup=get_keyboard(user_id))
            return

    # --- ADMIN PANEL & PLANS ENGINE ---
    if state == 'admin_menu':
        if text == '🔙 Back to Main':
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "Returned to Main Menu.", reply_markup=get_keyboard(user_id))
        elif text == '🏦 Deposit Settings':
            user_state[user_id] = 'admin_dep_menu'
            bot.send_message(message.chat.id, "🏦 <b>Deposit Architecture Menu</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Withdrawal Settings':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "⚙️ <b>Global Withdrawal Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💳 Wallet Settings':
            user_state[user_id] = 'admin_wallet_menu'
            bot.send_message(message.chat.id, "💳 <b>Global Wallet Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '🎁 Bonus Settings':
            user_state[user_id] = 'admin_bonus_menu'
            bot.send_message(message.chat.id, "🎁 <b>Bonus Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📊 Plans':
            user_state[user_id] = 'admin_plans'
            bot.send_message(message.chat.id, "📊 <b>Plans Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '🧮 Calculator':
            user_state[user_id] = 'wait_calc_amount'
            bot.send_message(message.chat.id, "Enter amount to test calculator:", reply_markup=get_cancel_action_keyboard())
        elif text == '📜 Transactions':
            user_state[user_id] = 'admin_wait_tx_id'
            bot.send_message(message.chat.id, "Enter User ID to view history:", reply_markup=get_cancel_action_keyboard())
        return

    # --- ADMIN BALANCE MANAGEMENT ENGINE ---
    if state == 'normal' and text == '💵 Balance':
        if is_admin:
            user_state[user_id] = 'bal_select'
            bot.send_message(message.chat.id, "Select the balance to manage:", reply_markup=get_keyboard(user_id))
        else:
            bal = user_db[user_id]['balance']
            bot.send_message(message.chat.id, get_tl_and_map(f"Balance: ${bal:.2f}", lang))
        return

    if state == 'bal_select':
        if text in ['Deposit balance', 'Withdrawal balance']:
            admin_bal_type[user_id] = 'deposit' if text == 'Deposit balance' else 'balance'
            user_state[user_id] = 'bal_menu'
            bot.send_message(message.chat.id, f"🗃 <b>Managing {text}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'bal_menu':
        if text.startswith('Notify User'):
            admin_bal_notify[user_id] = not admin_bal_notify.get(user_id, True)
            bot.send_message(message.chat.id, "Notification setting toggled.", reply_markup=get_keyboard(user_id))
        elif text == '💵 Get':
            user_state[user_id] = 'bal_get_id'
            bot.send_message(message.chat.id, "Enter the User ID:", reply_markup=get_keyboard(user_id))
        elif text == '💵 Change':
            user_state[user_id] = 'bal_change_id'
            bot.send_message(message.chat.id, "Enter the User ID to CHANGE balance:", reply_markup=get_keyboard(user_id))
        elif text == '💵 Set':
            user_state[user_id] = 'bal_set_id'
            bot.send_message(message.chat.id, "Enter the User ID to SET balance:", reply_markup=get_keyboard(user_id))
        elif text == 'Referral Bonus':
            bot.send_message(message.chat.id, "Referral Bonus settings... (Ready for logic)", reply_markup=get_keyboard(user_id))
        return

    if state == 'bal_get_id':
        try:
            target = int(text)
            if target in user_db:
                process_accruals(target)
                u = user_db[target]
                btype = admin_bal_type[user_id]
                bot.send_message(message.chat.id, f"👤 <b>User Info</b>\nID: <code>{target}</code>\nName: {u['first_name']}\nUsername: @{u['username']}\n\n💰 <b>{btype.title()}:</b> {u[btype]:.2f}", parse_mode="HTML", reply_markup=get_keyboard(user_id))
                user_state[user_id] = 'bal_menu'
                bot.send_message(message.chat.id, "Menu:", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "❌ User not found in DB. Try again or Cancel.")
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid ID. Must be a number.")
        return

    if state in ['bal_change_id', 'bal_set_id']:
        if text.startswith('With Comment'):
            admin_bal_comment_on[user_id] = not admin_bal_comment_on.get(user_id, False)
            bot.send_message(message.chat.id, "Comment toggle updated.", reply_markup=get_keyboard(user_id))
            return
            
        try:
            target = int(text)
            if target in user_db:
                admin_bal_target[user_id] = target
                process_accruals(target)
                u = user_db[target]
                btype = admin_bal_type[user_id]
                
                info_msg = f"👤 <b>User Found</b>\nID: <code>{target}</code>\nName: {u['first_name']}\nUsername: @{u['username']}\n💰 Current {btype.title()}: <b>{u[btype]:.2f}</b>\n\n"
                
                if admin_bal_comment_on.get(user_id, False):
                    user_state[user_id] = state.replace('_id', '_comment')
                    bot.send_message(message.chat.id, info_msg + "Enter the <b>comment</b> for the balance change:", parse_mode="HTML", reply_markup=get_keyboard(user_id))
                else:
                    admin_bal_comment_text[user_id] = ""
                    user_state[user_id] = state.replace('_id', '_amount')
                    bot.send_message(message.chat.id, info_msg + "Enter the <b>numeric value</b> (+/- allowed for change):", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "❌ User not found. Try again or Cancel.")
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid ID. Must be a number.")
        return

    if state in ['bal_change_comment', 'bal_set_comment']:
        if text == '➖ Set Empty': admin_bal_comment_text[user_id] = ""
        else: admin_bal_comment_text[user_id] = text
            
        user_state[user_id] = state.replace('_comment', '_amount')
        bot.send_message(message.chat.id, "Enter the <b>numeric value</b> (+/- allowed for change):", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state in ['bal_change_amount', 'bal_set_amount']:
        try:
            val = float(text)
            target = admin_bal_target[user_id]
            btype = admin_bal_type[user_id]
            comment = admin_bal_comment_text.get(user_id, "")
            
            if 'change' in state: user_db[target][btype] += val
            else: user_db[target][btype] = val
                
            new_bal = user_db[target][btype]
            
            action_type = "Admin Add" if 'change' in state else "Admin Set"
            log_tx(target, f"{action_type} ({btype.title()})", val)
            
            bot.send_message(message.chat.id, f"✅ <b>Success!</b>\nNew {btype.title()} balance for <code>{target}</code> is <b>{new_bal:.2f}</b>.", parse_mode="HTML")
            
            if admin_bal_notify.get(user_id, True) and comment:
                try:
                    target_lang = user_db.get(target, {}).get('lang', 'en')
                    msg = f"🔔 <b>Admin Notice</b>\n{comment}\n\nYour {btype.title()} is now: <b>{new_bal:.2f}</b>"
                    bot.send_message(target, get_tl_and_map(msg, target_lang), parse_mode="HTML")
                    bot.send_message(message.chat.id, f"✅ Notification securely sent to user {target}.")
                except Exception:
                    bot.send_message(message.chat.id, f"⚠️ Could not notify user {target} (they may have blocked the bot).")

            if btype == 'deposit':
                check_and_trigger_auto_buy(target)

            user_state[user_id] = 'bal_menu'
            bot.send_message(message.chat.id, "Menu:", reply_markup=get_keyboard(user_id))
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
        return

    # --- LIVE WITHDRAWAL ENGINE FLOW ---
    if state == 'w_action_amount':
        target_path = user_action_data[user_id]['path']
        
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Please enter numbers only.", lang))
            
        w_min = float(global_w_setup.get('w_min') or 0)
        w_max = float(global_w_setup.get('w_max') or float('inf'))
        
        if amount < w_min: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Minimum withdrawal is {w_min}.", lang))
        if amount > w_max: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Maximum withdrawal is {w_max}.", lang))
            
        w_var = global_w_setup.get('w_var', 'balance')
        user_bal = user_db[user_id].get(w_var, 0)
        if amount > user_bal: return bot.send_message(message.chat.id, get_tl_and_map(f"❌ Insufficient funds. Your {w_var} balance is {user_bal:.2f}.", lang))
            
        user_action_data[user_id]['amount'] = amount
        
        if not global_w_setup.get('do_not_ask_address'):
            user_state[user_id] = 'w_action_addr'
            msg = global_w_setup.get('w_msg_addr') or "Please enter your withdrawal address:"
            bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, target_path, user_action_data[user_id]), lang), parse_mode="HTML")
        else:
            user_state[user_id] = 'w_action_conf'
            msg = global_w_setup.get('w_msg_conf') or f"Confirm withdrawal of {amount}?"
            bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, target_path, user_action_data[user_id]), lang), parse_mode="HTML", reply_markup=get_withdrawal_conf_inline(lang))
        return

    if state == 'w_action_addr':
        target_path = user_action_data[user_id]['path']
        user_action_data[user_id]['address'] = text
        
        user_state[user_id] = 'w_action_conf'
        msg = global_w_setup.get('w_msg_conf') or f"Confirm withdrawal of {user_action_data[user_id]['amount']} to <code>{text}</code>?"
        bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, target_path, user_action_data[user_id]), lang), parse_mode="HTML", reply_markup=get_withdrawal_conf_inline(lang))
        return

    # --- GLOBAL FEATURE: Move by Command ---
    if state in ['normal', 'posts_editing']:
        for path, meta in btn_metadata.items():
            if meta.get('move_by_command') and meta.get('command') == text:
                if meta.get('admin_only') and not is_admin:
                    return bot.send_message(message.chat.id, get_tl_and_map("⛔️ You do not have permission to use this button.", lang))
                user_current_path[user_id] = path
                if path not in menus: menus[path] = []
                
                send_path_content(message.chat.id, user_id, path, is_editing=(state == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
                return

    # --- HANDLE BUTTONS EDITOR ADD / RENAME ---
    if state == 'adding_button':
        if current_path not in menus: menus[current_path] = []
        
        forbidden_names = ['🏠 Home', '🔙 Back'] + admin_commands
        if text in forbidden_names:
            bot.send_message(message.chat.id, "⚠️ You cannot use a system command as a button name. Please type a unique name, or click '❌ Cancel Action'.", reply_markup=get_cancel_action_keyboard())
            return
            
        if text not in menus[current_path]:
            max_r_idx = 0
            for b_name in menus[current_path]:
                r = btn_metadata.get(f"{current_path}/{b_name}", {}).get('row_idx', 0)
                if r > max_r_idx: max_r_idx = r
                
            menus[current_path].append(text)
            new_meta = get_default_metadata()
            new_meta['row_idx'] = max_r_idx
            btn_metadata[f"{current_path}/{text}"] = new_meta
            
            user_state[user_id] = 'editing'
            bot.send_message(message.chat.id, f"✅ Added '{text}'!", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, "⚠️ Name exists. Try another, or Cancel.", reply_markup=get_keyboard(user_id))
        return

    if state == 'renaming_button':
        old_name = user_selected_button.get(user_id)
        
        forbidden_names = ['🏠 Home', '🔙 Back'] + admin_commands
        if text in forbidden_names:
            bot.send_message(message.chat.id, "⚠️ You cannot use a system command as a button name. Please type a unique name, or click '❌ Cancel Action'.", reply_markup=get_cancel_action_keyboard())
            return
            
        if not old_name or text in menus[current_path]:
            bot.send_message(message.chat.id, "⚠️ Invalid or duplicate name. Try another, or Cancel.", reply_markup=get_keyboard(user_id))
            return
            
        idx = menus[current_path].index(old_name)
        menus[current_path][idx] = text
        change_menu_paths(f"{current_path}/{old_name}", f"{current_path}/{text}")
        user_state[user_id] = 'editing'
        user_selected_button[user_id] = None
        bot.send_message(message.chat.id, f"✅ Renamed to '{text}'!", reply_markup=get_keyboard(user_id))
        return

    # --- HANDLE NORMAL / POSTS EDITING TRAVERSAL ---
    if state == 'normal' or state == 'posts_editing':
        if text == '🎛️ Buttons Editor':
            if is_admin:
                user_state[user_id] = 'editing'
                bot.send_message(message.chat.id, "🎛 <b>Buttons Editor Activated</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📝 Posts Editor':
            if is_admin:
                user_state[user_id] = 'posts_editing'
                bot.send_message(message.chat.id, "📝 <b>Posts Editor Activated</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
                send_path_content(message.chat.id, user_id, current_path, True)
        elif text == '🔐 Admin':
            if is_admin:
                user_state[user_id] = 'admin_menu'
                bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>\nChoose an option:", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, get_tl_and_map("Unrecognized command.", lang), reply_markup=get_keyboard(user_id))
            
        elif current_path in menus and text in menus[current_path]:
            custom_btn_path = f"{current_path}/{text}"
            meta = btn_metadata.get(custom_btn_path, get_default_metadata())
            
            if meta.get('admin_only') and not is_admin:
                return bot.send_message(message.chat.id, get_tl_and_map("⛔️ You do not have permission to use this button.", lang))

            if meta.get('withdrawal') and state != 'posts_editing':
                user_state[user_id] = 'w_action_amount'
                user_action_data[user_id] = {'path': custom_btn_path}
                msg = global_w_setup.get('w_msg_enter') or "Please enter the amount you wish to withdraw:"
                bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, custom_btn_path), lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                return

            if meta.get('is_wallet') and state != 'posts_editing':
                msg = get_tl_and_map(replace_macros(global_wallet_setup['msg_main'], user_id, custom_btn_path), lang)
                w_status = user_db[user_id].get('wallet', 'Not Set')
                btn_text = get_tl_and_map(global_wallet_setup['inline_change'] if w_status != 'Not Set' else global_wallet_setup['inline_set'], lang)
                
                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton(btn_text, callback_data='cb_wallet_start'))
                bot.send_message(message.chat.id, msg, reply_markup=markup, parse_mode='HTML')
                return

            if meta.get('is_bonus') and state != 'posts_editing':
                now = time.time()
                last_time = user_db[user_id].get('last_bonus_time', 0)
                cooldown = global_bonus_setup['cooldown_hours'] * 3600
                
                if now - last_time >= cooldown:
                    user_db[user_id]['balance'] += global_bonus_setup['amount']
                    user_db[user_id]['last_bonus_time'] = now
                    log_tx(user_id, "Bonus Received", global_bonus_setup['amount'])
                    
                    msg = global_bonus_setup['msg_success'].replace('%bonus_amount%', str(global_bonus_setup['amount']))
                    bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, custom_btn_path), lang), parse_mode="HTML")
                else:
                    time_left_sec = int(cooldown - (now - last_time))
                    hours, remainder = divmod(time_left_sec, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    time_str = f"{hours}h {minutes}m {seconds}s"
                    
                    msg = global_bonus_setup['msg_fail'].replace('%time_left%', time_str)
                    bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, custom_btn_path), lang), parse_mode="HTML")
                return

            if meta.get('is_calculator') and state != 'posts_editing':
                user_state[user_id] = 'wait_calc_amount'
                bot.send_message(message.chat.id, get_tl_and_map("🧮 <b>Profit Calculator</b>\n\nEnter the amount you want to invest (USD):", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                return

            if meta.get('is_history') and state != 'posts_editing':
                txs = user_db[user_id].get('transactions', [])
                if not txs:
                    bot.send_message(message.chat.id, get_tl_and_map("📜 You have no transaction history yet.", lang), reply_markup=get_keyboard(user_id))
                else:
                    msg = "📜 <b>Your Transaction History:</b>\n\n"
                    for tx in txs[-20:]:
                        msg += f"🗓 <code>{tx['date']}</code>\n🔹 <b>{tx['type']}</b> | <b>${tx['amount']:.2f}</b>\n\n"
                    bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
                return

            # Both is_language and is_balance now completely act as regular sub-folders automatically!
            new_path = custom_btn_path
            user_current_path[user_id] = new_path
            if new_path not in menus: menus[new_path] = []
            
            send_path_content(message.chat.id, user_id, new_path, is_editing=(state == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, get_tl_and_map("Unrecognized command.", lang), reply_markup=get_keyboard(user_id))

# --- HELPER: MASTER PLAN BUYING ENGINE WITH POPUPS & REDIRECTS ---
def execute_plan_purchase_via_popup(user_id, chat_id, message_id, call_id, plan_id, invest_amount=None):
    if plan_id not in bot_plans:
        return bot.answer_callback_query(call_id, "⚠️ Plan not found.", show_alert=True)
        
    p_data = bot_plans[plan_id]
    
    if plan_id == 'plan0':
        invest_amount = p_data.get('bonus_amount', 50.0)
    elif invest_amount is None:
        invest_amount = p_data['min']

    lang = user_db.get(user_id, {}).get('lang', 'en')

    # Handle Free / Bonus Plans
    if p_data.get('is_free', False) or plan_id == 'plan0':
        if any(p['macro'] == plan_id and p['status'] == 'active' for p in user_db[user_id].get('active_plans', [])):
            return bot.answer_callback_query(call_id, get_tl_and_map(f"❌ You already have {p_data['name']} active!", lang), show_alert=True)
            
        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': plan_id, 'amount': invest_amount,
            'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        log_tx(user_id, f"Activated Free {p_data['name']}", invest_amount)
        bot.answer_callback_query(call_id, get_tl_and_map(f"🎉 Success! Activated {p_data['name']} with ${invest_amount:.2f} virtual capital!", lang), show_alert=True)
        
        # Optionally Return home
        user_current_path[user_id] = 'root'
        send_path_content(chat_id, user_id, 'root', False)
        return
        
    # Handle Standard Paid Plans
    u_dep = user_db[user_id].get('deposit', 0)
    u_bal = user_db[user_id].get('balance', 0)
    total_avail = u_dep + u_bal
    
    if total_avail < invest_amount:
        user_db[user_id]['pending_plan'] = plan_id
        bot.answer_callback_query(call_id, get_tl_and_map(f"⚠️ Insufficient funds! You need ${invest_amount:.2f}.", lang), show_alert=True)
        
        redirect_cmd = p_data.get('redirect_cmd') or '/deposit'
        try: bot.delete_message(chat_id, message_id)
        except Exception: pass
        
        # Trigger redirect command securely
        msg = telebot.types.Message(message_id, None, None, None, redirect_cmd, [], None)
        msg.from_user = telebot.types.User(user_id, False, user_db[user_id]['first_name'])
        msg.chat = telebot.types.Chat(chat_id, 'private')
        msg.text = redirect_cmd
        handle_messages(msg)
        return
        
    if u_dep >= invest_amount:
        user_db[user_id]['deposit'] -= invest_amount
    else:
        rem = invest_amount - u_dep
        user_db[user_id]['deposit'] = 0
        user_db[user_id]['balance'] -= rem
        
    log_tx(user_id, f"Bought {p_data['name']}", -invest_amount)
    
    new_plan = {
        'id': str(uuid.uuid4())[:8], 'macro': plan_id, 'amount': invest_amount,
        'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
        'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
    }
    user_db[user_id]['active_plans'].append(new_plan)
    
    bot.answer_callback_query(call_id, get_tl_and_map(f"🎉 Success! You invested ${invest_amount:.2f} into {p_data['name']}! Profit is accruing automatically.", lang), show_alert=True)
    try: bot.delete_message(chat_id, message_id)
    except Exception: pass
    
    user_current_path[user_id] = 'root'
    send_path_content(chat_id, user_id, 'root', False)


# --- INLINE BUTTON LOGIC ---
@bot.callback_query_handler(func=lambda call: True)
def handle_inline(call):
    user_id = call.from_user.id
    current_path = user_current_path.get(user_id, 'root')
    target_btn = user_selected_button.get(user_id)
    is_admin = user_id in ADMIN_IDS
    lang = user_db.get(user_id, {}).get('lang', 'en')

    # --- WALLET SETUP NATIVE INLINE ---
    if call.data == 'cb_wallet_start':
        bot.answer_callback_query(call.id)
        if global_wallet_setup['ask_email'] and user_db[user_id].get('email', 'Not Set') == 'Not Set':
            user_state[user_id] = 'wallet_wait_email'
            bot.send_message(call.message.chat.id, get_tl_and_map(global_wallet_setup['msg_email_prompt'], lang), reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'wallet_wait_address'
            bot.send_message(call.message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    # --- LANGUAGE TRANSLATOR SELECTOR ENGINE ---
    if call.data.startswith('cb_lang_'):
        btn_id = call.data.split('_')[2]
        target_lang = 'en'
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        target_lang = b['data'].strip()
        
        # Fallback handling for deep-translator target naming convention
        if target_lang.lower() == 'zh-cn': target_lang = 'zh-CN'
        else: target_lang = target_lang.lower()

        user_db[user_id]['lang'] = target_lang
        bot.answer_callback_query(call.id, get_tl_and_map("Language updated!", target_lang), show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        
        # REFRESH MAIN MENU IMMEDIATELY
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal'
        send_path_content(call.message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))
        return

    # --- CALCULATOR DYNAMIC BUY NOW (POPUP ENGINE) ---
    if call.data.startswith('cb_calcbuy_'):
        parts = call.data.split('_')
        plan_id = parts[2]
        amount = float(parts[3])
        execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_id, amount)
        return

    # --- ENHANCED DYNAMIC PLAN BUYER INLINE ACTION ---
    if call.data.startswith('cb_buyplan_'):
        plan_id = call.data.split('_')[2]
        if plan_id not in bot_plans:
            return bot.answer_callback_query(call.id, get_tl_and_map("Plan not found.", lang), show_alert=True)
            
        p_data = bot_plans[plan_id]
        
        # If Plan is free, or Min == Max, execute instantly with Popup engine
        if p_data.get('is_free', False) or plan_id == 'plan0' or p_data['min'] == p_data['max']:
            execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_id, p_data['min'] if plan_id != 'plan0' else None)
            return
            
        # Else check total available funds before starting Wizard
        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        total_avail = u_dep + u_bal
        
        if total_avail < p_data['min']:
            user_db[user_id]['pending_plan'] = plan_id
            bot.answer_callback_query(call.id, get_tl_and_map(f"⚠️ Insufficient balance. You need at least ${p_data['min']}.", lang), show_alert=True)
            
            redirect_cmd = p_data.get('redirect_cmd') or '/deposit'
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception: pass
            
            msg = call.message
            msg.from_user = call.from_user
            msg.text = redirect_cmd
            handle_messages(msg)
            return
            
        # Funds OK -> Move to Amount Entry State (Popup impossible for text input)
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['buy_plan_id'] = plan_id
            
        user_state[user_id] = 'buyplan_wait_amount'
        bot.send_message(call.message.chat.id, get_tl_and_map(f"📈 <b>{p_data['name']}</b>\nMin: ${p_data['min']} | Max: ${p_data['max']}\n\nAvailable Balance: ${total_avail:.2f}\n\nEnter the amount you wish to invest:", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        bot.answer_callback_query(call.id)
        return

    # --- CUSTOM INLINE 'BUY' BUTTON TRIGGER (POPUP ENGINE) ---
    if call.data.startswith('cb_buy_'):
        btn_id = call.data.split('_')[2]
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        lines = b['data'].split('\n')
                        plan_macro = lines[0].strip()
                        
                        if plan_macro not in bot_plans:
                            return bot.answer_callback_query(call.id, get_tl_and_map("⚠️ Error: This plan no longer exists.", lang), show_alert=True)
                            
                        # Instant buy behavior if triggered via custom inline
                        execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_macro)
                        return
        return bot.answer_callback_query(call.id)

    # --- ADMIN MANUAL DEPOSIT APPROVAL RECEIPTS ---
    if call.data.startswith('cb_depapp_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        dep_id = call.data.split('_')[2]
        if dep_id not in pending_deposits: return bot.answer_callback_query(call.id, "Already processed.", show_alert=True)
        
        dep = pending_deposits.pop(dep_id)
        target = dep['user_id']
        amt = dep['amount']
        curr = dep['currency']
        conf = deposit_settings[curr]
        
        if target in user_db:
            user_db[target]['deposit'] += amt
            log_tx(target, f"Deposit ({curr.replace('_', ' ')})", amt)
            
            msg_success = conf.get('msg_success', "✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.")
            msg_success = msg_success.replace('%usd_amount%', f"{amt:.2f}").replace('%crypto_amount%', '')
            target_lang = user_db.get(target, {}).get('lang', 'en')
            bot.send_message(target, get_tl_and_map(msg_success, target_lang), parse_mode="HTML")
            
            try:
                if call.message.photo: bot.edit_message_caption(f"{call.message.caption}\n\n✅ **APPROVED**", call.message.chat.id, call.message.message_id, reply_markup=None)
                else: bot.edit_message_text(f"{call.message.text}\n\n✅ **APPROVED**", call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception: pass
            
            check_and_trigger_auto_buy(target) 
            
        return bot.answer_callback_query(call.id, "Approved successfully.")

    elif call.data.startswith('cb_deprej_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        dep_id = call.data.split('_')[2]
        if dep_id not in pending_deposits: return bot.answer_callback_query(call.id, "Already processed.", show_alert=True)
        
        dep = pending_deposits.pop(dep_id)
        target = dep['user_id']
        
        try:
            target_lang = user_db.get(target, {}).get('lang', 'en')
            bot.send_message(target, get_tl_and_map(f"❌ <b>Deposit Rejected</b>\nYour deposit request for <b>${dep['amount']}</b> could not be verified.", target_lang), parse_mode="HTML")
            if call.message.photo: bot.edit_message_caption(f"{call.message.caption}\n\n❌ **REJECTED**", call.message.chat.id, call.message.message_id, reply_markup=None)
            else: bot.edit_message_text(f"{call.message.text}\n\n❌ **REJECTED**", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception: pass
        return bot.answer_callback_query(call.id, "Rejected successfully.")

    # --- NATIVE INLINE ACTIONS FOR ALL USERS ---
    if call.data.startswith('cb_pop_'):
        btn_id = call.data.split('_')[2]
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        return bot.answer_callback_query(call.id, get_tl_and_map(b['data'], lang), show_alert=True)
        return bot.answer_callback_query(call.id)
        
    elif call.data.startswith('cb_cmd_'):
        btn_id = call.data.split('_')[2]
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        try: bot.delete_message(call.message.chat.id, call.message.message_id)
                        except Exception: pass
                        msg = call.message
                        msg.from_user = call.from_user
                        msg.text = b['data']
                        handle_messages(msg)
                        return bot.answer_callback_query(call.id)
        return bot.answer_callback_query(call.id)
        
    elif call.data.startswith('cb_dep_'):
        btn_id = call.data.split('_')[2]
        if len(call.data.split('_')) > 2 and call.data.split('_')[2] in deposit_settings:
             curr = call.data.replace('cb_dep_', '')
        else:
            for path, posts in menu_posts.items():
                for p in posts:
                    for b in p.get('custom_inlines', []):
                        if b['id'] == btn_id:
                            curr = b['data'].strip().upper().replace(" ", "_")
        
        if curr not in deposit_settings:
            return bot.answer_callback_query(call.id, get_tl_and_map("Error: Currency not configured.", lang), show_alert=True)
            
        bot.answer_callback_query(call.id)
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['currency'] = curr
        user_state[user_id] = 'dep_wait_amount'
        
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        
        bot.send_message(call.message.chat.id, get_tl_and_map(deposit_settings[curr]['msg_enter'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    # --- ADMIN POSTS INLINE TOOLS ---
    if call.data.startswith('cb_p_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        parts = call.data.split('_')
        action = parts[2]
        post_id = parts[3]
        
        posts_list = menu_posts.get(current_path, [])
        idx = next((i for i, p in enumerate(posts_list) if p['id'] == post_id), -1)
        
        if idx == -1: return bot.answer_callback_query(call.id, "Post not found.", show_alert=True)

        if action == 'up' and idx > 0:
            posts_list[idx], posts_list[idx-1] = posts_list[idx-1], posts_list[idx]
            send_path_content(call.message.chat.id, user_id, current_path, True)
            
        elif action == 'down' and idx < len(posts_list) - 1:
            posts_list[idx], posts_list[idx+1] = posts_list[idx+1], posts_list[idx]
            send_path_content(call.message.chat.id, user_id, current_path, True)
            
        elif action == 'reptext':
            user_state[user_id] = 'posts_rep_text'
            user_action_data[user_id] = {'post_id': post_id}
            post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
            curr_txt = post['text'] if post else ""
            safe_txt = html.escape(curr_txt)
            bot.send_message(call.message.chat.id, f"Send the new text (image will be kept):\n\nℹ️ <b>Current Text (Copy this to preserve macros):</b>\n<code>{safe_txt}</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif action == 'repall':
            user_state[user_id] = 'posts_rep_all'
            user_action_data[user_id] = {'post_id': post_id}
            post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
            curr_txt = post['text'] if post else ""
            safe_txt = html.escape(curr_txt)
            bot.send_message(call.message.chat.id, f"Send the new message (text or photo):\n\nℹ️ <b>Current Text (Copy this to preserve macros):</b>\n<code>{safe_txt}</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif action == 'add':
            user_state[user_id] = 'posts_insert_after'
            user_action_data[user_id] = {'post_id': post_id}
            bot.send_message(call.message.chat.id, "Send the message to add below this one:", reply_markup=get_cancel_action_keyboard())
            
        elif action == 'del':
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton('✅ Yes, Delete Post', callback_data=f'cb_p_delyes_{post_id}'), InlineKeyboardButton('❌ Cancel', callback_data=f'cb_p_delno_{post_id}'))
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            
        elif action == 'delyes':
            menu_posts[current_path].pop(idx)
            send_path_content(call.message.chat.id, user_id, current_path, True)
            
        elif action == 'delno':
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_post_inline_tools(post_id))
            
        elif action == 'star':
            user_state[user_id] = 'pi_manage'
            user_action_data[user_id] = {'post_id': post_id}
            post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
            if post: render_pi_manager(call.message.chat.id, post)
            
        bot.answer_callback_query(call.id)
        return

    # --- CUSTOM INLINE BUTTONS MANAGER ---
    if call.data.startswith('cb_pi_'):
        action = call.data.replace('cb_pi_', '')
        if action == 'add':
            user_state[user_id] = 'pi_wait_mode'
            if user_id not in user_action_data: user_action_data[user_id] = {}
            user_action_data[user_id].pop('btn_id', None)
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('💬 Popup Window'))
            markup.row(KeyboardButton('🚀 Command'), KeyboardButton('🛒 Buy Plan'))
            markup.row(KeyboardButton('🏦 Deposit'), KeyboardButton('🌐 Set Language'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(call.message.chat.id, "Select category for new inline button:", reply_markup=markup)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        elif action == 'done':
            bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return
        
    elif call.data.startswith('cb_pis_'):
        btn_id = call.data.replace('cb_pis_', '')
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['btn_id'] = btn_id
        
        post_id = user_action_data[user_id]['post_id']
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
        b = next((x for x in post.get('custom_inlines', []) if x['id'] == btn_id), None) if post else None
        btn_text = b['text'] if b else "Unknown"
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('⬅️', callback_data='cb_pim_left'),
                   InlineKeyboardButton('⬆️', callback_data='cb_pim_up'),
                   InlineKeyboardButton('⬇️', callback_data='cb_pim_down'),
                   InlineKeyboardButton('➡️', callback_data='cb_pim_right'))
        markup.row(InlineKeyboardButton('✏️ Edit', callback_data='cb_pim_edit'),
                   InlineKeyboardButton('✖️ Delete', callback_data='cb_pim_del'))
        markup.row(InlineKeyboardButton('🔙 Back to List', callback_data='cb_pim_back'))
        
        bot.edit_message_text(f"🛠 <b>Managing:</b> <code>{btn_text}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
        
    elif call.data.startswith('cb_pim_'):
        action = call.data.replace('cb_pim_', '')
        post_id = user_action_data[user_id]['post_id']
        btn_id = user_action_data[user_id].get('btn_id')
        
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
        inlines = post.get('custom_inlines', []) if post else []
        idx = next((i for i, b in enumerate(inlines) if b['id'] == btn_id), -1)
        
        if action == 'back' or idx == -1:
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
        elif action == 'edit':
            user_state[user_id] = 'pi_wait_mode'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('💬 Popup Window'))
            markup.row(KeyboardButton('🚀 Command'), KeyboardButton('🛒 Buy Plan'))
            markup.row(KeyboardButton('🏦 Deposit'), KeyboardButton('🌐 Set Language'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(call.message.chat.id, "Select new category for this button:", reply_markup=markup)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        elif action == 'del':
            inlines.pop(idx)
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
        elif action == 'up':
            inlines[idx]['row_idx'] -= 1
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
        elif action == 'down':
            inlines[idx]['row_idx'] += 1
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
        elif action == 'left' and idx > 0:
            inlines[idx], inlines[idx-1] = inlines[idx-1], inlines[idx]
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
        elif action == 'right' and idx < len(inlines) - 1:
            inlines[idx], inlines[idx+1] = inlines[idx+1], inlines[idx]
            render_pi_manager(call.message.chat.id, post, call.message.message_id)
            
        bot.answer_callback_query(call.id)
        return

    # --- LIVE WITHDRAWAL CONFIRMATION ---
    if call.data == 'cb_w_yes':
        if user_state.get(user_id) == 'w_action_conf':
            data = user_action_data[user_id]
            meta = btn_metadata.get(data['path'], get_default_metadata())
            
            w_var = global_w_setup.get('w_var', 'balance')
            user_db[user_id][w_var] -= data['amount']
            user_db[user_id]['total_withdrawn'] = user_db[user_id].get('total_withdrawn', 0.0) + data['amount']
            log_tx(user_id, "Withdrawal", -data['amount'])
            
            user_state[user_id] = 'normal'
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, get_tl_and_map("✅ Withdrawal request processed successfully!", lang), reply_markup=get_keyboard(user_id))
        return
        
    elif call.data == 'cb_w_no':
        if user_state.get(user_id) == 'w_action_conf':
            user_state[user_id] = 'normal'
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, get_tl_and_map("❌ Withdrawal cancelled.", lang), reply_markup=get_keyboard(user_id))
        return
    
    if call.data == 'go_back':
        if current_path != 'root':
            parts = current_path.split('/')[:-1]
            new_path = '/'.join(parts) if len(parts) > 1 else 'root'
            user_current_path[user_id] = new_path
            bot.delete_message(call.message.chat.id, call.message.message_id)
            send_path_content(call.message.chat.id, user_id, new_path, is_editing=(user_state.get(user_id) == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
        bot.answer_callback_query(call.id)
        return

    if not is_admin:
        return bot.answer_callback_query(call.id, get_tl_and_map("Action not permitted.", lang), show_alert=True)

    if not target_btn or target_btn not in menus.get(current_path, []):
        bot.answer_callback_query(call.id, "Action expired or button missing.", show_alert=True)
        return bot.delete_message(call.message.chat.id, call.message.message_id)

    # --- BUTTON INLINE TOOLS ---
    current_list = menus[current_path]
    idx = current_list.index(target_btn)

    if call.data == 'cb_move_left' and idx > 0:
        current_list[idx], current_list[idx-1] = current_list[idx-1], current_list[idx]
        bot.send_message(call.message.chat.id, "Moved left.", reply_markup=get_keyboard(user_id))
        
    elif call.data == 'cb_move_right' and idx < len(current_list) - 1:
        current_list[idx], current_list[idx+1] = current_list[idx+1], current_list[idx]
        bot.send_message(call.message.chat.id, "Moved right.", reply_markup=get_keyboard(user_id))
        
    elif call.data == 'cb_move_up':
        btn_path = f"{current_path}/{target_btn}"
        meta = btn_metadata.get(btn_path, get_default_metadata())
        meta['row_idx'] = meta.get('row_idx', 0) - 1
        btn_metadata[btn_path] = meta 
        bot.send_message(call.message.chat.id, f"Moved '{target_btn}' up.", reply_markup=get_keyboard(user_id))
        
    elif call.data == 'cb_move_down':
        btn_path = f"{current_path}/{target_btn}"
        meta = btn_metadata.get(btn_path, get_default_metadata())
        meta['row_idx'] = meta.get('row_idx', 0) + 1
        btn_metadata[btn_path] = meta 
        bot.send_message(call.message.chat.id, f"Moved '{target_btn}' down.", reply_markup=get_keyboard(user_id))
    
    elif call.data == 'cb_settings':
        user_state[user_id] = 'button_settings'
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"⚙️ <b>Settings for:</b> <code>{target_btn}</code>", parse_mode="HTML", reply_markup=get_keyboard(user_id))

    elif call.data == 'cb_rename':
        user_state[user_id] = 'renaming_button'
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"Send new name for '{target_btn}':", reply_markup=get_cancel_action_keyboard())

    elif call.data == 'cb_cut':
        full_path = f"{current_path}/{target_btn}"
        user_clipboard[user_id] = {'name': target_btn, 'full_path': full_path}
        menus[current_path].remove(target_btn) 
        user_selected_button[user_id] = None
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"✂️ Cut '{target_btn}'. Go to a new folder and press Paste.", reply_markup=get_keyboard(user_id))

    elif call.data == 'cb_delete':
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('✅ Yes, Delete', callback_data='cb_del_yes'), InlineKeyboardButton('❌ Cancel', callback_data='cb_del_no'))
        bot.edit_message_text(f"Are you sure you want to delete '{target_btn}' and all folders inside it?", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == 'cb_del_yes':
        menus[current_path].remove(target_btn)
        full_path_to_del = f"{current_path}/{target_btn}"
        for k in [k for k in menus.keys() if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del menus[k]
        for k in [k for k in btn_metadata.keys() if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del btn_metadata[k]
        for k in [k for k in menu_posts.keys() if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del menu_posts[k]
        
        user_selected_button[user_id] = None
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, f"🗑 Deleted '{target_btn}'.", reply_markup=get_keyboard(user_id))

    elif call.data == 'cb_del_no':
        bot.edit_message_text(f"🛠 Selected: <b>{target_btn}</b>\nChoose an action:", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=get_edit_inline_tools())

    bot.answer_callback_query(call.id)

# --- NEW: LIGHTWEIGHT WEB SERVER FOR ADMIN DASHBOARD & UPTIMEROBOT ---
class AdminDashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/':
            try:
                with open(os.path.join(BASE_DIR, 'index.html'), 'rb') as f:
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html not found. Make sure it is in the root directory.")
                
        elif parsed_path.path == '/api/get_admins':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'admins': ADMIN_IDS}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""

        if parsed_path.path == '/api/add_admin':
            try:
                data = json.loads(post_data)
                new_admin = int(data.get('admin_id'))
                if new_admin not in ADMIN_IDS:
                    ADMIN_IDS.append(new_admin)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': True}).encode())
                    print(f"👑 Dashboard Action: Added Admin ID {new_admin}")
                else:
                    self.send_response(400)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Admin already exists'}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        
        elif parsed_path.path == '/api/remove_admin':
            try:
                data = json.loads(post_data)
                remove_admin = int(data.get('admin_id'))
                if remove_admin in ADMIN_IDS:
                    ADMIN_IDS.remove(remove_admin)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': True}).encode())
                    print(f"👑 Dashboard Action: Removed Admin ID {remove_admin}")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Admin not found'}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_web_server():
    """Runs the HTTP server silently in the background."""
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), AdminDashboardHandler)
    print(f"🌐 Web server running on port {port} for UptimeRobot & Admin Dashboard.")
    server.serve_forever()

if __name__ == '__main__':
    # Start the Web Server (Required for Render and Dashboard)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Start the Blockchain Scanner
    print("👀 Starting background watcher thread...")
    threading.Thread(target=blockchain_watcher_loop, daemon=True).start()

    # Start the Auto-Save Database Thread
    print("💾 Starting JSON database auto-save thread...")
    threading.Thread(target=auto_save_loop, daemon=True).start()
    
    # Start the Telegram Bot
    print("🚀 Bot is running fast! Press Ctrl+C to stop.")
    bot.infinity_polling(skip_pending=True)
