import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import uuid
import time
import os
import threading
import requests
import json
import html
import re
import psutil
import random
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

# DASHBOARD SECURITY PIN
ADMIN_PIN = os.getenv('ADMIN_PIN', '123456')

# --- NEW FEATURE 1: NORTHFLANK API CREDENTIALS ---
NORTHFLANK_API_KEY = os.getenv('NORTHFLANK_API_KEY', '')
NORTHFLANK_PROJECT = os.getenv('NORTHFLANK_PROJECT', '')
NORTHFLANK_VOLUME = os.getenv('NORTHFLANK_VOLUME', '')

# API KEYS FOR BLOCKCHAIN TRACKING
TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY', '')

# --- AIVEN POSTGRESQL DATABASE SYSTEM ---
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_LOADED_SUCCESSFULLY = False  # 🔒 THE NEW SAFETY LOCK

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
        print("✅ Aiven Database connected and table verified!")
    except Exception as e:
        print(f"❌ Aiven DB Init Error: {e}")

def load_database():
    global DB_LOADED_SUCCESSFULLY
    if not DATABASE_URL: return {}
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT data FROM bot_state WHERE id = 1;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        DB_LOADED_SUCCESSFULLY = True # 🔓 UNLOCKS SAVING
        print("✅ Aiven Memory successfully loaded into Bot!")
        
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
        print(f"⚠️ CRITICAL: Error loading from Aiven DB: {e}")
        # By NOT unlocking the safety lock here, we prevent the bot from wiping Aiven!
        return {}

def save_database():
    # 🛑 PREVENTS THE DEADLY OVERWRITE BUG
    if not DATABASE_URL or not DB_LOADED_SUCCESSFULLY: 
        return 
        
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
        'global_ui_settings': global_ui_settings,
        'reinvest_settings': reinvest_settings,
        'global_messages_setup': global_messages_setup,
        'processed_txids': list(processed_txids), # Convert set to list for database
        'blocked_users': list(blocked_users),     # NEW: Blocked users saving
        'block_settings': block_settings,         # NEW: Block messages saving
        'dynamic_stats': dynamic_stats,           # NEW: Dynamic Stats saving
        'invite_settings': invite_settings        # NEW: Invite settings saving
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
        # 💓 THE HEARTBEAT MONITOR:
        print(f"💾 AIVEN AUTO-SAVE: {len(user_db)} users backed up successfully!")
    except Exception as e:
        print(f"⚠️ AIVEN DB SAVE ERROR: {e}")

def auto_save_loop():
    """Runs forever in the background, saving data every 10 seconds."""
    while True:
        time.sleep(10)
        save_database()

# Initialize Neon and Load Data
init_db()
db_data = load_database()

# --- NEW: SMART DECIMAL FORMATTER ---
def fmt_amt(val):
    """Dynamically shows 2 decimals for standard numbers, or exactly infinite decimals for micro-amounts."""
    if val is None: return "0.00"
    try:
        v = float(val)
        if v == 0: return "0.00"
        if abs(v) >= 0.01:
            return "{:.2f}".format(v)
        else:
            s = f"{v:.8f}".rstrip('0')
            if s.endswith('.'): s += "00"
            return s
    except:
        return "0.00"

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
pending_auto_txids = {}
pending_withdrawals = {} # Tracker for Admin Withdrawal System

# --- PERSISTENT DATA (Loaded from Neon DB) ---
user_db = db_data.get('user_db', {})
menus = db_data.get('menus', {'root': []})
menu_posts = db_data.get('menu_posts', {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]})
btn_metadata = db_data.get('btn_metadata', {})
processed_txids = set(db_data.get('processed_txids', []))

# NEW: Blocked Users Persistent Data
blocked_users = set(db_data.get('blocked_users', []))
block_settings = db_data.get('block_settings', {
    'msg_block': '🚫 You have been blocked by the admin and cannot use this bot.',
    'msg_unblock': '✅ You have been unblocked. Welcome back!'
})

# NEW: Dynamic Stats Persistent Data
dynamic_stats = db_data.get('dynamic_stats', {
    'investments': 0.0,
    'withdrawn': 0.0,
    'users': 0,
    'last_refresh': 0.0
})

global_ui_settings = db_data.get('global_ui_settings', {'loading_bar_style': '1', 'loading_bar_time': 3.0})

# NEW: Global Messages Manager Data
global_messages_setup = db_data.get('global_messages_setup', {
    'hourly_dm': '💰You have received +{hourly_amount} USDT hourly profits.\nTime left: {time_left}',
    'expiry_dm': '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed',
    'ref_join_msg': '🎉 1 user joined via your link!',
    'ref_commission_msg': '💵 You received +{amount} USDT from your referral activity!',
    'level_up_msg': '🎉 Congratulations! You reached Referral Level {level} and earned {reward} USDT!',
    'admin_change_msg': '🔔 Admin Notice\n\nYour {btype} balance is now: <b>{new_bal}</b>'
})

# NEW: Reinvest Settings Persistent Data
reinvest_settings = db_data.get('reinvest_settings', {
    'msg_success': '✅ <b>Reinvest Successful!</b>\nYou have successfully reinvested <b>$%amount%</b> into <b>%plan_name%</b>.',
    'msg_fail': '❌ You can not invest right now: You need at least %min_amount% USDT to invest!',
    'inline_deposit_text': '🏦 Deposit Now'
})

# NEW: Invite Settings Persistent Data (UPDATED WITH DYNAMIC LINK TOGGLE)
invite_settings = db_data.get('invite_settings', {
    'levels': [{'users': 10, 'reward': 5.0}, {'users': 25, 'reward': 15.0}, {'users': 100, 'reward': 50.0}],
    'msg_template': "👥 <b>Referral Statistics</b>\n\n%levels_display%\n\n👥 My team Deposits: %team_deposits% USDT\n♾ Earnings: %affiliate_earnings% USDT",
    'use_loading_bar': True,
    'ref_commission_pct': 0.0,
    'use_dynamic_link': False
})

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
    'w_msg_conf': 'Are you sure you want to withdraw %withdraw% USDT via %network% to:\n<code>%address%</code>',
    'w_msg_processing': '♻️ Your Withdrawal of %withdraw% is processing on the blockchain...',
    'w_msg_approve': '✅ Withdrawal Completed\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: -%withdraw% USDT\n🔗 Address: <code>%address%</code>\n🌐 Network: %network%\n⚡ Type: Instant\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Successful ✔️ \n\nYour funds have been sent successfully to your wallet.',
    'w_msg_decline': '❌ Withdrawal Declined\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: %withdraw% USDT\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Failed ❌ \n\nYour withdrawal request was declined. The funds have been refunded to your balance.',
    'w_msg_ignore': '🚫 Withdrawal Ignored\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: %withdraw% USDT\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Cancelled 🚫 \n\nYour withdrawal request has been ignored.',
    'do_not_ask_address': False,
    'w_commission': 0.0,
    'w_rate_toggle': False,
    'public_report': None,
    'private_report': None,
    'addr_var': 'wallet',
    'use_ascii_receipt': False,
    'payout_btn_text': '📜 View Receipt',
    'payout_popup_msg': 'Payment Success!'
})

global_wallet_setup = db_data.get('global_wallet_setup', {
    'msg_main': '💡 Your currently set USDT Wallet Address is: <code>%wallet%</code>\n\nEmail: <code>%email%</code>\n\n💹 It will be used for all future withdrawals.\n\nNOTE🔴: Supported, USDT Network Address are: TRC20 and BEP20 Set Only one..',
    'msg_prompt': '✏️ Send now your USDT TRC 20 OR BEP 20 Address to use it in future transactions ..',
    'msg_success': '🖊 Done: Your new wallet address is <code>%wallet%</code> (%network%)',
    'inline_set': 'Set wallet', 'inline_change': 'Change wallet',
    'ask_email': True, 'msg_email_prompt': '✏️ Please enter your Email address:'
})

global_bonus_setup = db_data.get('global_bonus_setup', {
    'amount': 5.0, 'cooldown_hours': 24.0, 'min_withdraw': 50.0,
    'msg_success': '🎉 Congratulations! You have received $%bonus_amount% as a bonus.',
    'msg_fail': '⏳ You have already claimed your bonus. Please wait %time_left%.'
})

bot_plans = db_data.get('bot_plans', {})

# --- SYSTEM PLANS INITIALIZATION ---
if not bot_plans:
    for i in range(6):
        name_str = 'G-Force Free Plan' if i == 0 else f'G-Force Plan {i}'
        bot_plans[f'plan{i}'] = {
            'name': name_str, 'min': 10.0, 'max': 1000.0, 'length': 24.0, 'profit': 5.0,
            'text': f'✨ <b>{name_str} Description</b> ✨\n\nEdit this in Admin -&gt; Plans.',
            'photo': None, 'inline_text': '🛒 Purchase Plan', 'inline_active_text': '(Active ✅)', 
            'redirect_cmd': None, 'is_free': (i == 0), 'bonus_amount': 50.0 if i == 0 else 0.0
        }

# --- NEW: BACKGROUND CACHE PRELOADER ---
def preload_core_languages():
    """Background-translates and caches the bot's core strings and active menus for new users."""
    all_strings = set([
        '🏠 Home', '🔙 Back', '❌ Cancel Action', '💵 Balance', '🔐 Admin',
        'Deposit balance', 'Withdrawal balance', '✔️ Leave as Is', '➖ Set Empty'
    ])
    for menu_list in menus.values():
        all_strings.update(menu_list)
        
    langs = ['zh-CN', 'pt', 'nl', 'es', 'de', 'fr', 'ar', 'ru', 'id', 'hi']
    for lang in langs:
        for text in all_strings:
            get_tl_and_map(text, lang)
        time.sleep(0.5)

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
        'is_language': False,
        'is_reinvest': False,
        'is_stats': False,   # NEW
        'is_info': False,    # NEW
        'is_invite': False,  # NEW
        'is_deposit': False, # NEW EDITABLE DEPOSIT
        'is_live_trading': False # NEW
    }

def init_user_db(message):
    user_id = message.from_user.id
    is_new_user = False
    if user_id not in user_db:
        is_new_user = True
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
            'lang': 'en',
            'referred_by': None,           # NEW
            'team_deposits': 0.0,          # NEW
            'affiliate_earnings': 0.0,     # NEW
            'claimed_levels': [],          # NEW
            'invite_links_map': []         # NEW
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
        if 'referred_by' not in user_db[user_id]: user_db[user_id]['referred_by'] = None
        if 'team_deposits' not in user_db[user_id]: user_db[user_id]['team_deposits'] = 0.0
        if 'affiliate_earnings' not in user_db[user_id]: user_db[user_id]['affiliate_earnings'] = 0.0
        if 'claimed_levels' not in user_db[user_id]: user_db[user_id]['claimed_levels'] = []
        if 'invite_links_map' not in user_db[user_id]: user_db[user_id]['invite_links_map'] = []
    
    return is_new_user

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
        
        # BTC requires WIF Private Key, EVM/Tron uses Hex
        if currency == 'BTC':
            private_key = bip44_acc.PrivateKey().ToWif()
        else:
            private_key = bip44_acc.PrivateKey().Raw().ToHex()
        
        return public_address, private_key
    except Exception as e:
        print(f"Wallet Gen Error: {e}")
        return "GEN_ERROR", "GEN_ERROR"

# --- HELPER: REFERRAL COMMISSION ENGINE ---
def process_referral_commission(user_id, amount, is_deposit=True):
    inviter = user_db.get(user_id, {}).get('referred_by')
    if inviter and inviter in user_db:
        pct = invite_settings.get('ref_commission_pct', 0.0)
        if pct > 0:
            comm = amount * (pct / 100.0)
            user_db[inviter]['balance'] += comm
            user_db[inviter]['affiliate_earnings'] += comm
            log_tx(inviter, "Referral Commission", comm)
            try:
                lang = user_db[inviter].get('lang', 'en')
                msg = global_messages_setup.get('ref_commission_msg', '💵 You received +{amount} USDT from your referral activity!')
                msg = msg.replace('{amount}', f"{fmt_amt(comm)}")
                bot.send_message(inviter, get_tl_and_map(msg, lang), parse_mode="HTML")
            except: pass
        if is_deposit:
            user_db[inviter]['team_deposits'] += amount

# --- MASTER API SCANNER HELPER (100% AUTOMATED NETWORK SCAN) ---
def check_address_for_new_deposit(addr, curr):
    """Scans the respective blockchain for new incoming transfers and extracts timestamps."""
    crypto_amount = 0.0
    txid_found = ""
    tx_time = 0.0
    
    try:
        if curr in ['TRX', 'USDT_TRC20']:
            headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
            
            if curr == 'USDT_TRC20':
                url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20?only_to=true"
            else:
                url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions?only_to=true"
                
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('data', [])
                for tx in txs:
                    txid = tx.get('transaction_id') or tx.get('txID')
                    if txid in processed_txids: continue
                    
                    if curr == 'USDT_TRC20':
                        if tx.get('token_info', {}).get('address') == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t":
                            tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                            return True, float(tx.get('value', 0)) / 1_000_000, txid, tx_time
                            
                    elif curr == 'TRX':
                        contract = tx.get('raw_data', {}).get('contract', [{}])[0]
                        if contract.get('type') == 'TransferContract':
                            amt = contract.get('parameter', {}).get('value', {}).get('amount', 0)
                            tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                            return True, float(amt) / 1_000_000, txid, tx_time
                            
        elif curr == 'USDT_ERC20':
            url = f"https://api.etherscan.io/api?module=account&action=tokentx&address={addr}&page=1&offset=10&sort=desc&apikey={ETHERSCAN_API_KEY}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('result', [])
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('hash')
                        if txid in processed_txids: continue
                        if tx.get('contractAddress', '').lower() == "0xdac17f958d2ee523a2206206994597c13d831ec7" and tx.get('to', '').lower() == addr.lower():
                            tx_time = float(tx.get('timeStamp', time.time()))
                            return True, float(tx.get('value', 0)) / 10**6, txid, tx_time
                            
        elif curr == 'USDT_BEP20':
            url = f"https://api.bscscan.com/api?module=account&action=tokentx&address={addr}&page=1&offset=10&sort=desc&apikey={BSCSCAN_API_KEY}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('result', [])
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('hash')
                        if txid in processed_txids: continue
                        if tx.get('contractAddress', '').lower() == "0x55d398326f99059ff775485246999027b3197955" and tx.get('to', '').lower() == addr.lower():
                            tx_time = float(tx.get('timeStamp', time.time()))
                            return True, float(tx.get('value', 0)) / 10**18, txid, tx_time
                            
        elif curr == 'BTC':
            url = f"https://mempool.space/api/address/{addr}/txs"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json()
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('txid')
                        if txid in processed_txids: continue
                        for vout in tx.get('vout', []):
                            if vout.get('scriptpubkey_address') == addr:
                                tx_time = float(tx.get('status', {}).get('block_time', time.time()))
                                return True, float(vout.get('value', 0)) / 10**8, txid, tx_time
                                
    except Exception as e:
        print(f"API Scan Error ({curr}): {e}")
        pass
        
    return False, 0.0, "", 0.0

# --- 4. AUTO-DETECTION WATCHER ENGINE ---
def blockchain_watcher_loop():
    """Continuously checks the blockchain, verifying official timestamps for the 5-min delay."""
    while True:
        try:
            for uid, data in list(user_db.items()):
                for curr, w_data in list(data.get('wallets', {}).items()):
                    addr = w_data['address']
                    found, crypto_amount, txid, tx_time = check_address_for_new_deposit(addr, curr)
                    
                    # If we found a transaction and it hasn't been processed yet
                    if found and txid not in processed_txids:
                        now = time.time()
                        
                        # THE FIX: We use the blockchain's official timestamp!
                        # If the block was mined 5+ minutes ago (300 seconds), approve it instantly.
                        # Even if the server restarts, this math is perfectly stateless and robust.
                        if (now - tx_time) >= 300:
                            processed_txids.add(txid)
                            
                            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
                            usd_value = crypto_amount * live_price
                            
                            user_db[uid]['deposit'] += usd_value
                            user_db[uid]['wallets'][curr]['total_deposited'] = user_db[uid]['wallets'][curr].get('total_deposited', 0.0) + usd_value
                            log_tx(uid, f"Auto-Deposit ({curr})", usd_value)
                            
                            process_referral_commission(uid, usd_value, is_deposit=True) # NEW: Commission
                            
                            try:
                                conf = deposit_settings[curr]
                                msg_success = conf.get('msg_success', "✅ <b>Deposit Detected!</b>\n\nThe blockchain confirmed a deposit of <b>%crypto_amount% %currency%</b>.\n<b>$%usd_amount% USD</b> has been automatically added to your balance!")
                                msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(usd_value)}").replace('%crypto_amount%', f"{fmt_amt(crypto_amount)}").replace('%currency%', curr.replace('_', ' '))
                                lang = user_db.get(uid, {}).get('lang', 'en')
                                bot.send_message(uid, get_tl_and_map(msg_success, lang), parse_mode="HTML")
                            except Exception: pass
                            
                            admin_msg = f"🟢 <b>AUTO-DEPOSIT APPROVED (5-MIN TIMEOUT)</b>\nUser: <code>{uid}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}\nHash (TXID): <code>{txid}</code>"
                            for admin in ADMIN_IDS:
                                try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                                except Exception: pass
                                
                            check_and_trigger_auto_buy(uid)
                            
        except Exception as e:
            print(f"Watcher Loop Error: {e}")
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
            msg = f"🎉 <b>Auto-Purchase Successful!</b>\n\nYour deposit triggered your pending plan.\n<b>{p_data['name']}</b> is now active with an investment of <b>${fmt_amt(invest_amt)}</b>!"
            lang = user_db.get(user_id, {}).get('lang', 'en')
            bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
        except Exception: pass

# --- TRUE BACKGROUND HOURLY ALERTS (FIX APPLIED HERE) ---
def process_accruals(user_id):
    u = user_db.get(user_id)
    if not u or not u.get('active_plans'): return
    
    now = time.time()
    for p in u['active_plans']:
        if p['status'] != 'active': continue
        
        elapsed_sec = now - p['last_accrual']
        full_hours = int(elapsed_sec // 3600)
        
        if full_hours > 0:
            for _ in range(full_hours):
                hourly_earned = p['amount'] * (p['profit_pct'] / 100.0)
                u['balance'] += hourly_earned
                p['earned'] += hourly_earned
                p['last_accrual'] += 3600
                
                # Calculate time left for DM
                time_left_str = "Lifetime"
                if p['length_hours'] > 0:
                    time_left_sec = (p['start_time'] + (p['length_hours'] * 3600)) - p['last_accrual']
                    if time_left_sec > 0:
                        hours, remainder = divmod(time_left_sec, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        time_left_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
                    else:
                        time_left_str = "0h 0m 0s"
                        
                try:
                    msg = global_messages_setup.get('hourly_dm', '💰You have received +{hourly_amount} USDT hourly profits.\nTime left: {time_left}')
                    msg = msg.replace('{hourly_amount}', f"{fmt_amt(hourly_earned)}").replace('{time_left}', time_left_str)
                    lang = u.get('lang', 'en')
                    bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
                except: pass
                
        if p['length_hours'] > 0:
            total_elapsed = (now - p['start_time']) / 3600.0
            if total_elapsed >= p['length_hours']:
                p['status'] = 'expired'
                try:
                    msg = global_messages_setup.get('expiry_dm', '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed')
                    msg = msg.replace('{total_profit}', f"{fmt_amt(p['earned'])}")
                    lang = u.get('lang', 'en')
                    bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
                except: pass

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

# --- NEW: DYNAMIC STATS REFRESH ENGINE ---
def refresh_dynamic_stats():
    now = time.time()
    # Initial seeding if 0
    if dynamic_stats['last_refresh'] == 0.0:
        dynamic_stats['investments'] = random.uniform(50000, 100000)
        dynamic_stats['withdrawn'] = dynamic_stats['investments'] * 3
        dynamic_stats['users'] = random.randint(5000, 10000)
        dynamic_stats['last_refresh'] = now
    elif now - dynamic_stats['last_refresh'] >= 86400:
        inv_add = random.uniform(10000, 16000)
        dynamic_stats['investments'] += inv_add
        dynamic_stats['withdrawn'] += (inv_add * 3)
        dynamic_stats['users'] += random.randint(700, 1500)
        dynamic_stats['last_refresh'] = now

def replace_macros(text, user_id, full_path, action_data=None):
    if not text: return "Not set."
    process_accruals(user_id) 
    refresh_dynamic_stats() 
    
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
    t = t.replace('%balance%', f"{fmt_amt(bals.get('balance', 0))}")
    t = t.replace('%bonus%', f"{fmt_amt(bals.get('bonus', 0))}")
    t = t.replace('%deposit%', f"{fmt_amt(bals.get('deposit', 0))}")
    t = t.replace('%lang%', bals.get('lang', 'en').upper())
    
    # NEW EXTENDED MACROS
    t = t.replace('%plan_invest%', f"{fmt_amt(plan_invest)}")
    t = t.replace('%hourly_profit%', f"{fmt_amt(hourly_profit)}")
    t = t.replace('%plan_names%', plan_names)
    t = t.replace('%ref_count%', str(ref_count))
    t = t.replace('%withdrawn%', f"{fmt_amt(total_withdrawn)}")
    t = t.replace('%team_deposits%', f"{fmt_amt(bals.get('team_deposits', 0))}")
    t = t.replace('%affiliate_earnings%', f"{fmt_amt(bals.get('affiliate_earnings', 0))}")
    
    bot_info = bot.get_me()
    t = t.replace('%ref_link%', f"https://t.me/{bot_info.username}?start={user_id}")
    
    # DYNAMIC LEVELS MACRO
    if '%levels_display%' in t:
        levels_str = ""
        for i, level in enumerate(invite_settings['levels']):
            req = level['users']
            current = min(bals.get('ref_count', 0), req)
            pct = int((current / req) * 10) if req > 0 else 10
            bar = "■" * pct + "▯" * (10 - pct)
            levels_str += f"{i+1}° Level: [{bar}] {req} users\n"
        t = t.replace('%levels_display%', levels_str)
    
    # NEW DYNAMIC STATS MACROS
    t = t.replace('%stats_invest%', f"{dynamic_stats['investments']:,.2f}")
    t = t.replace('%stats_withdrawn%', f"{dynamic_stats['withdrawn']:,.2f}")
    t = t.replace('%stats_users%', str(dynamic_stats['users']))
    
    t = t.replace('%wallet%', bals.get('wallet', 'Not Set'))
    t = t.replace('%email%', bals.get('email', 'Not Set'))
    t = t.replace('%bonus_amount%', str(global_bonus_setup['amount']))
    t = t.replace('%commission%', str(global_w_setup.get('w_commission', 0.0)))
    
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
                plans_str += f"Invested: ${fmt_amt(p['amount'])}\nEarned: ${fmt_amt(p['earned'])}\n\n"
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
        t = t.replace('%withdraw%', f"{fmt_amt(action_data.get('amount', 0))}")
        t = t.replace('%address%', action_data.get('address', bals.get('address', 'Not Set')))
        t = t.replace('%network%', action_data.get('network', bals.get('wallet_net', 'Unknown')))
    else:
        t = t.replace('%withdraw%', "0.00")
        t = t.replace('%address%', bals.get('address', 'Not Set'))
        t = t.replace('%network%', bals.get('wallet_net', 'Unknown'))
        
    # NEW EDITABLE LIVE TRADING MACROS
    if any(m in t for m in ['%trade_runtime%', '%trade_profit%', '%trade_anim_bar%', '%trade_pct%']):
        if not active:
            t = t.replace('%trade_runtime%', "00h 00m 00s")
            t = t.replace('%trade_profit%', "0.000000")
            t = t.replace('%trade_anim_bar%', "[■■■■■■■■■■]")
            t = t.replace('%trade_pct%', "100% (Completed)")
        else:
            now = time.time()
            oldest_start = min(p['start_time'] for p in active)
            elapsed_sec = now - oldest_start
            hours, remainder = divmod(int(elapsed_sec), 3600)
            minutes, seconds = divmod(remainder, 60)
            t = t.replace('%trade_runtime%', f"{hours:02d}h {minutes:02d}m {seconds:02d}s")
            
            # Real-time micro-profit summation updating every single second
            total_live_profit = sum(p['amount'] * (p['profit_pct'] / 100.0) * ((now - p['start_time']) / 3600.0) for p in active)
            t = t.replace('%trade_profit%', f"{total_live_profit:.6f}")
            
            # --- NEW SMART PRIORITY LOGIC ---
            # Separate plans with actual timers from lifetime plans
            timed_plans = [p for p in active if p['length_hours'] > 0]
            
            if timed_plans:
                # If they have ANY timed plans, track the oldest timed one
                tracked_plan = min(timed_plans, key=lambda x: x['start_time'])
                tot_sec = tracked_plan['length_hours'] * 3600
                plan_elapsed = now - tracked_plan['start_time']
                pct = min(100.0, (plan_elapsed / tot_sec) * 100)
                
                if pct >= 100.0:
                    t = t.replace('%trade_anim_bar%', "[■■■■■■■■■■]")
                    t = t.replace('%trade_pct%', "100% Completed")
                else:
                    cycle = int(now) % 3
                    bars = ["[■■■▯▯▯▯▯▯▯]", "[■■■■■■▯▯▯▯]", "[■■■■■■■■■■]"]
                    t = t.replace('%trade_anim_bar%', bars[cycle])
                    t = t.replace('%trade_pct%', f"{pct:.2f}% to Completion")
            else:
                # If ALL active plans are lifetime plans
                cycle = int(now) % 3
                bars = ["[■■■▯▯▯▯▯▯▯]", "[■■■■■■▯▯▯▯]", "[■■■■■■■■■■]"]
                t = t.replace('%trade_anim_bar%', bars[cycle])
                t = t.replace('%trade_pct%', "Lifetime Contract (Running)")

    # --- NEW FEATURE 1: ASCII RECEIPT MACRO ENGINE ---
    if '%ascii_receipt%' in t:
        if global_w_setup.get('use_ascii_receipt', False):
            tx_full = action_data.get('txid', 'N/A') if action_data else 'N/A'
            tx_short = tx_full[:11] + "..." if len(tx_full) > 11 else tx_full
            u_name = bals.get('username', 'Unknown')
            if len(u_name) > 13: u_name = u_name[:10] + "..."
            
            w_amt = fmt_amt(action_data.get('amount', 0)) if action_data else "0.00"
            n_str = action_data.get('network', bals.get('wallet_net', 'Unknown')) if action_data else bals.get('wallet_net', 'Unknown')
            if len(n_str) > 14: n_str = n_str[:11] + "..."
            
            # Using precise '<18' string padding to guarantee alignment across all screen sizes
            ascii_box = (
                "<pre>\n"
                "╔════════════════════════════╗\n"
                "║     G-FORCE PAYOUT LOG     ║\n"
                "╠════════════════════════════╣\n"
                f"║ TXID:   {tx_short:<18} ║\n"
                f"║ USER:   @{u_name:<17} ║\n"
                "║                            ║\n"
                f"║ WITHDRAWAL: ${w_amt:<13} ║\n"
                f"║ NETWORK:  {n_str:<16} ║\n"
                "║ FEE:    $0.00              ║\n"
                "╠════════════════════════════╣\n"
                "║      [ STATUS: PAID ]      ║\n"
                "╚════════════════════════════╝\n"
                "</pre>"
            )
            t = t.replace('%ascii_receipt%', ascii_box)
        else:
            # Silent clear if toggled off
            t = t.replace('%ascii_receipt%', '')
            
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

# --- THE FIX: GLOBAL MACRO: %loading_bar% ANIMATOR ---
def execute_loading_animation(chat_id, msg_id, part_a, style_opt, is_photo, total_seconds):
    """Animates a standalone loading message, then deletes it."""
    frames = {
        '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
        '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
        '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
    }
    all_bars = frames.get(str(style_opt), frames['1'])
    
    # NATIVE TELEGRAM API LIMIT FIX: Skip frames if the requested time is too short to physically render them all
    if total_seconds <= 0.5:
        bars = [all_bars[-1]] # Instantly 100%
    elif total_seconds <= 1.5:
        bars = [all_bars[0], all_bars[-1]] # 0% -> 100%
    elif total_seconds <= 2.5:
        bars = [all_bars[0], all_bars[len(all_bars)//2], all_bars[-1]] # 0% -> 50% -> 100%
    else:
        bars = all_bars # Full 6 frames

    sleep_time = total_seconds / len(bars)
    sep = "\n\n" if part_a.strip() else ""
    
    for bar in bars:
        iter_start = time.time()
        frame_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{bar}"
        try:
            if is_photo:
                bot.edit_message_caption(caption=frame_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                bot.edit_message_text(text=frame_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except:
            pass
            
        elapsed = time.time() - iter_start
        remaining = sleep_time - elapsed
        if remaining > 0:
            time.sleep(remaining)
            
    time.sleep(0.1) # Tiny buffer before deletion
    try: bot.delete_message(chat_id, msg_id)
    except: pass

def execute_live_trading_animation(chat_id, msg_id, raw_text, user_id, path, lang, markup):
    """Animates the live trading terminal in real-time for 30 seconds."""
    for _ in range(30): 
        time.sleep(1.0) # Updates screen exactly once per second
        updated_text = get_tl_and_map(replace_macros(raw_text, user_id, path), lang)
        try:
            bot.edit_message_text(text=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            if "message is not modified" in str(e).lower(): continue
            break # Exits cleanly if user leaves the menu

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
        raw_text = get_tl_and_map(replace_macros(p['text'], user_id, path), lang)
        
        has_loading_macro = False
        total_loading_time = float(global_ui_settings.get('loading_bar_time', 3.0)) # Fetch default time dynamically
        part_a = ""
        final_text = ""
        
        # THE FIX: Finds %loading_bar% OR %loading_bar_5s% custom times!
        match = re.search(r'%loading_bar(?:_(\d+(?:\.\d+)?)s)?%', raw_text)
        if match:
            has_loading_macro = True
            if match.group(1):
                total_loading_time = float(match.group(1))
            part_a = raw_text[:match.start()].strip()
            part_b = raw_text[match.end():].strip()
            final_text = part_a + ("\n\n" if part_a and part_b else "") + part_b
            
            # FIX: If we are in editing mode, make sure final_text retains the raw macro so it doesn't vanish
            if is_editing:
                final_text = raw_text
        else:
            final_text = raw_text
            
        style = global_ui_settings.get('loading_bar_style', '1')
        
        if has_loading_macro and not is_editing:
            # 1. SEND THE TEMPORARY LOADING MESSAGE FIRST
            sep = "\n\n" if part_a else ""
            bars = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "░░░░░░░░░░ 0%", "▒▒▒▒▒▒▒▒▒▒ 0%"]
            initial_bar = bars[int(style)-1] if style in ['1', '2', '3'] else bars[0]
            temp_msg_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{initial_bar}"
            
            try:
                if p['type'] == 'photo':
                    temp_msg = bot.send_photo(chat_id, p['photo'], caption=temp_msg_text, parse_mode="HTML")
                else:
                    temp_msg = bot.send_message(chat_id, temp_msg_text, parse_mode="HTML")
                # 2. PAUSE THE MENU AND ANIMATE it SYNCHRONOUSLY
                execute_loading_animation(chat_id, temp_msg.message_id, part_a, style, p['type'] == 'photo', total_loading_time)
            except: pass
            
        # 3. IF THERE IS NOTHING LEFT AFTER THE BAR DELETES ITSELF, SKIP SENDING AN EMPTY BUBBLE
        # Because we set final_text = raw_text during is_editing, it won't be completely empty,
        # so this logic naturally bypasses the 'skip' when editing!
        if has_loading_macro and not final_text and not p.get('custom_inlines') and not p.get('photo'):
            # Only skip if we aren't supposed to attach a reply keyboard here
            if not (i == len(posts) - 1 and not kb_attached and reply_keyboard):
                continue
        
        markup = InlineKeyboardMarkup()
        custom_inlines = p.get('custom_inlines', [])
        
        # APPEND NEW GEN LINK BUTTON DYNAMICALLY IF ASSIGN INVITE IS TRUE
        if meta.get('is_invite') and i == len(posts) - 1 and not is_editing:
            btn_text = get_tl_and_map("🔗 Generate Referral Link", lang)
            markup.row(InlineKeyboardButton(btn_text, callback_data='cb_gen_ref_link'))

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
                    elif b['mode'] == 'question':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_question_{b['id']}"))
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
        
        # 4. FINALLY, SEND THE REAL POST (PART B)
        try:
            if p['type'] == 'photo':
                # For photos, if text is completely empty after extraction, make sure caption is empty, not a space
                cap = final_text if final_text else None
                sent = bot.send_photo(chat_id, p['photo'], caption=cap, parse_mode="HTML", reply_markup=markup)
            else:
                # To prevent sending empty text messages which crash Telegram
                safe_text = final_text if final_text else " "
                sent = bot.send_message(chat_id, safe_text, parse_mode="HTML", reply_markup=markup)
                
                # --- NEW: TRIGGER LIVE TRADING ANIMATION ---
                if meta.get('is_live_trading') and not is_editing:
                    threading.Thread(target=execute_live_trading_animation, args=(chat_id, sent.message_id, p['text'], user_id, path, lang, markup), daemon=True).start()
                
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
                
        except Exception as e:
            # FIX: Prevent editor lockout when HTML parse fails, send error and attach the editor markup
            err_msg = f"⚠️ <b>Error rendering post:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>Fix or delete this using the buttons below!</i>"
            sent = bot.send_message(chat_id, err_msg, parse_mode="HTML", reply_markup=markup)
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

# --- NATIVE ENTITY EXTRACTOR (Safely translates Telegram Formatting to Database HTML) ---
def extract_html(message):
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    
    if not entities:
        return text
        
    encoded_text = text.encode('utf-16-le')
    
    tags = []
    for ent in entities:
        open_tag, close_tag = '', ''
        if ent.type == 'bold': open_tag, close_tag = '<b>', '</b>'
        elif ent.type == 'italic': open_tag, close_tag = '<i>', '</i>'
        elif ent.type == 'code': open_tag, close_tag = '<code>', '</code>'
        elif ent.type == 'pre': open_tag, close_tag = '<pre>', '</pre>'
        elif ent.type == 'strikethrough': open_tag, close_tag = '<s>', '</s>'
        elif ent.type == 'underline': open_tag, close_tag = '<u>', '</u>'
        elif ent.type == 'spoiler': open_tag, close_tag = '<tg-spoiler>', '</tg-spoiler>'
        elif ent.type == 'text_link': open_tag, close_tag = f'<a href="{ent.url}">', '</a>'
        
        if open_tag:
            start = ent.offset * 2
            end = (ent.offset + ent.length) * 2
            tags.append((start, open_tag, 'open', ent.length))
            tags.append((end, close_tag, 'close', ent.length))
            
    # Sort backwards to not mess up offsets.
    tags.sort(key=lambda x: (x[0], x[2] == 'open', x[3] if x[2]=='close' else -x[3]), reverse=True)
    
    for index, tag_str, _, _ in tags:
        encoded_text = encoded_text[:index] + tag_str.encode('utf-16-le') + encoded_text[index:]
        
    try:
        return encoded_text.decode('utf-16-le')
    except Exception:
        return text

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
    reinv_text = "☑️ On" if meta.get('is_reinvest') else "⬜️ Off"
    stat_text = "☑️ On" if meta.get('is_stats') else "⬜️ Off"
    info_text = "☑️ On" if meta.get('is_info') else "⬜️ Off"
    invt_text = "☑️ On" if meta.get('is_invite') else "⬜️ Off"
    dep_text = "☑️ On" if meta.get('is_deposit') else "⬜️ Off"
    live_text = "☑️ On" if meta.get('is_live_trading') else "⬜️ Off"
    
    markup.row(KeyboardButton(f'Random Message ({rm_text})'), KeyboardButton(f'Admin Only ({ao_text})'))
    markup.row(KeyboardButton(f'Invisible ({inv_text})'), KeyboardButton('Subscription (Join)'))
    markup.row(KeyboardButton('Assign Command'), KeyboardButton('Assign Plan'), KeyboardButton('Assign Language')) 
    markup.row(KeyboardButton(f'Assign Calculator ({calc_text})'), KeyboardButton(f'Assign History ({hist_text})'))
    markup.row(KeyboardButton(f'Assign Withdrawal ({w_text})'), KeyboardButton(f'Assign Deposit ({dep_text})'))
    markup.row(KeyboardButton(f'Assign Bonus ({bon_text})'), KeyboardButton(f'Assign Wallet ({wal_text})'))
    markup.row(KeyboardButton(f'Assign Balance ({bal_text})'), KeyboardButton(f'Assign Stats ({stat_text})'))
    markup.row(KeyboardButton(f'Assign Reinvest ({reinv_text})'), KeyboardButton(f'Assign Live Trading ({live_text})'))
    markup.row(KeyboardButton(f'Assign Invite ({invt_text})'), KeyboardButton(f'Assign Info ({info_text})'))
    markup.row(KeyboardButton('Form Settings'), KeyboardButton('Assign Editor'))
    markup.row(KeyboardButton('Shop Editor'), KeyboardButton('🔙 Exit Button Settings'))
    return markup

def get_global_withdrawal_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    addr_text = "☑️ On" if global_w_setup.get('do_not_ask_address') else "⬜️ Off"
    rate_text = "☑️ On" if global_w_setup.get('w_rate_toggle') else "⬜️ Off"
    comm_val = global_w_setup.get('w_commission', 0.0)
    ascii_text = "☑️ On" if global_w_setup.get('use_ascii_receipt', False) else "⬜️ Off"
    
    markup.row(KeyboardButton('Set Withdrawal Var'), KeyboardButton('Set Min/Max'))
    markup.row(KeyboardButton('Edit Enter Msg'), KeyboardButton('Edit Address Msg'))
    markup.row(KeyboardButton('Edit Confirm Msg'), KeyboardButton('Processing Message'))
    markup.row(KeyboardButton('Approve Msg'), KeyboardButton('Decline Msg.'), KeyboardButton('Ignore Msg.'))
    markup.row(KeyboardButton('Public Group Report'), KeyboardButton('Private Group Report'))
    markup.row(KeyboardButton('Address Variable'))
    markup.row(KeyboardButton(f'Do not ask for Address ({addr_text})'))
    markup.row(KeyboardButton(f'Commission ({comm_val}%)'), KeyboardButton(f'Rate ({rate_text})'))
    markup.row(KeyboardButton(f'ASCII Receipt ({ascii_text})'), KeyboardButton('Edit Payout Popup'))
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
    markup.row(KeyboardButton('💰 Min Auto-Transfer'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_reinvest_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💬 Edit Success Msg'), KeyboardButton('💬 Edit Fail Msg'))
    markup.row(KeyboardButton('🔘 Edit Deposit Inline'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_loading_bar_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('Style 1: [■■■▯▯]'), KeyboardButton('Style 2: ▓▓▓░░'))
    markup.row(KeyboardButton('Style 3: ████▒▒'), KeyboardButton('⏱ Set Default Time'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_block_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('🚫 Block'), KeyboardButton('✅ Unblock'))
    markup.row(KeyboardButton('💬 Edit Block Msg'), KeyboardButton('💬 Edit Unblock Msg'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_invite_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💬 Edit Post Message'), KeyboardButton('📊 Set Levels'))
    lb_text = "☑️ On" if invite_settings.get('use_loading_bar', True) else "⬜️ Off"
    dyn_text = "☑️ On" if invite_settings.get('use_dynamic_link', False) else "⬜️ Off"
    markup.row(KeyboardButton(f'⏳ Toggle Loading Bar ({lb_text})'), KeyboardButton(f'🔗 Toggle Dynamic Link ({dyn_text})'))
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
            markup.row(KeyboardButton('📢 Broadcast Message'), KeyboardButton('🔄 Reinvest Settings'))
            markup.row(KeyboardButton('Loading Bar Settings'), KeyboardButton('🚫 Block User System'))
            markup.row(KeyboardButton('💬 Messages'), KeyboardButton('Invite Settings'))
            # --- NEW FEATURES 7 & 8: DEDICATED ADMIN BUTTONS ---
            markup.row(KeyboardButton('📊 Bot Stats'), KeyboardButton('🧹 Data Wipe Dashboard'))
            markup.row(KeyboardButton('🔙 Back to Main'))
            return markup
            
        # --- NEW FEATURE 8: ADVANCED WIPE DASHBOARD KEYBOARD ---
        if state == 'admin_wipe_menu':
            markup.row(KeyboardButton('🧹 Targeted Wipe'), KeyboardButton('☢️ General Wipe (All Users)'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup
            
        if state == 'admin_messages_menu':
            markup.row(KeyboardButton('Edit Hourly DM'), KeyboardButton('Edit Expiry DM'))
            markup.row(KeyboardButton('Edit Ref Join Msg'), KeyboardButton('Edit Ref Comm Msg'))
            markup.row(KeyboardButton('Edit Level Up Msg'), KeyboardButton('Edit Admin Change Msg'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_broadcast_action':
            markup.row(KeyboardButton('➕ Add Inline'), KeyboardButton('✅ Proceed'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state == 'admin_broadcast_preview':
            markup.row(KeyboardButton('🚀 Send Broadcast'), KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state == 'bc_wait_mode':
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('🚀 Command'))
            markup.row(KeyboardButton('🛒 Buy Plan'), KeyboardButton('🏦 Deposit'))
            markup.row(KeyboardButton('❓ Ask Question'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        if state == 'admin_w_menu': return get_global_withdrawal_keyboard()
        if state == 'admin_wallet_menu': return get_admin_wallet_keyboard()
        if state == 'admin_bonus_menu': return get_admin_bonus_keyboard()
        if state == 'admin_reinvest_menu': return get_admin_reinvest_keyboard()
        if state == 'admin_loading_bar': return get_loading_bar_keyboard()
        if state == 'admin_block_menu': return get_admin_block_keyboard()
        if state == 'admin_invite_menu': return get_admin_invite_keyboard()

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

        # --- NEW FEATURE 2: CANCELLATION FOR WIPE WAIT STATES & POPUP STATES ---
        if state.startswith('dep_setup_') or state.startswith('wallet_setup_') or state.startswith('bonus_setup_') or state.startswith('reinvest_setup_') or state.startswith('msg_setup_') or state in ['admin_loading_time', 'wait_invite_msg', 'wait_invite_levels', 'wait_ref_bonus_pct', 'wait_support_msg', 'wait_payout_popup'] or state.startswith('wait_block_') or state.startswith('wait_edit_block') or state.startswith('wait_edit_unblock') or state in ['admin_broadcast_input', 'bc_wait_text', 'wait_wipe_id', 'wait_general_wipe_confirm']:
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
            if state == 'w_setup_proc': return get_wizard_keyboard(global_w_setup.get('w_msg_processing'), allow_empty=True)
            if state == 'w_setup_appr': return get_wizard_keyboard(global_w_setup.get('w_msg_approve'), allow_empty=True)
            if state == 'w_setup_dec': return get_wizard_keyboard(global_w_setup.get('w_msg_decline'), allow_empty=True)
            if state == 'w_setup_ign': return get_wizard_keyboard(global_w_setup.get('w_msg_ignore'), allow_empty=True)

        if state == 'button_settings': return get_settings_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_command': return get_assign_command_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_plan': return get_cancel_action_keyboard()
        
        if state in ['adding_button', 'renaming_button', 'pi_wait_text', 'pi_wait_data', 'bc_wait_data'] or state.startswith('admin_suprep_'):
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

    if state in ['buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg']:
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
    
    # --- NEW: INTERCEPT BLOCKED USERS ---
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return

    # Payload Extraction for Deep Linking
    parts = message.text.split()
    payload = parts[1] if len(parts) > 1 else None

    # --- NEW: HOMEPAGE HARDCODED LOADING BAR (Independent) ---
    frames = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"]
    try:
        loading_msg = bot.send_message(message.chat.id, f"♻️ <b>INITIALIZING SYSTEM...</b>\n{frames[0]}", parse_mode="HTML")
        for bar in frames[1:]:
            time.sleep(0.3)
            bot.edit_message_text(f"♻️ <b>INITIALIZING SYSTEM...</b>\n{bar}", chat_id=message.chat.id, message_id=loading_msg.message_id, parse_mode="HTML")
        time.sleep(0.2)
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # --- NEW: NEW USER ADMIN ALERT & PRELOAD ---
    is_new = init_user_db(message)
    inviter_id = None
    
    if payload:
        if payload.isdigit():
            inviter_id = int(payload)
        else:
            # Check dynamic invite links from memory bank
            for uid, udata in user_db.items():
                if payload in udata.get('invite_links_map', []):
                    inviter_id = uid
                    break
            # Fallback dynamic lookup
            if not inviter_id and payload.startswith('gf_'):
                potential_username = payload[3:]
                for uid, udata in user_db.items():
                    if str(uid) == potential_username or udata.get('username', '').lower() == potential_username.lower():
                        inviter_id = uid
                        break
                        
    if is_new:
        if inviter_id and inviter_id in user_db and inviter_id != user_id:
            user_db[user_id]['referred_by'] = inviter_id
            user_db[inviter_id]['ref_count'] += 1
            try:
                lang = user_db[inviter_id].get('lang', 'en')
                bot.send_message(inviter_id, get_tl_and_map(global_messages_setup['ref_join_msg'], lang))
            except: pass
            
            # Check level thresholds
            for i, level in enumerate(invite_settings['levels']):
                if user_db[inviter_id]['ref_count'] >= level['users']:
                    if i not in user_db[inviter_id].get('claimed_levels', []):
                        user_db[inviter_id]['balance'] += level['reward']
                        if 'claimed_levels' not in user_db[inviter_id]: user_db[inviter_id]['claimed_levels'] = []
                        user_db[inviter_id]['claimed_levels'].append(i)
                        log_tx(inviter_id, f"Referral Level {i+1} Reward", level['reward'])
                        try:
                            msg = global_messages_setup['level_up_msg'].replace('{level}', str(i+1)).replace('{reward}', str(level['reward']))
                            bot.send_message(inviter_id, get_tl_and_map(msg, lang))
                        except: pass

        total_bot_users = len(user_db)
        alert_msg = (
            f"🆕 New User!\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Total: [{total_bot_users}]\n"
            f"Name: {message.from_user.first_name}"
        )
        if user_db[user_id]['referred_by']:
            alert_msg += f"\nReferred by: <code>{user_db[user_id]['referred_by']}</code>"
            
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, alert_msg, parse_mode="HTML")
            except: pass
            
        # Trigger background language preload
        threading.Thread(target=preload_core_languages, daemon=True).start()

    user_current_path[user_id] = 'root'
    user_state[user_id] = 'normal'
    user_selected_button[user_id] = None
    
    send_path_content(message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))

@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    
    # --- NEW: INTERCEPT BLOCKED USERS ---
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return
    
    # --- NEW: NATIVE FORMATTING CAPTURE ---
    formatted_text = extract_html(message)

    is_admin = user_id in ADMIN_IDS
    
    # Initialize and check if new user
    is_new = init_user_db(message)
    if is_new:
        total_bot_users = len(user_db)
        alert_msg = (
            f"🆕 New User!\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Total: [{total_bot_users}]\n"
            f"Name: {message.from_user.first_name}"
        )
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, alert_msg, parse_mode="HTML")
            except: pass
        # Trigger background language preload
        threading.Thread(target=preload_core_languages, daemon=True).start()

    process_accruals(user_id) 
    
    lang = user_db.get(user_id, {}).get('lang', 'en')
    
    if text == '/setwallet info' or text == '/setwallet':
        if global_wallet_setup['ask_email'] and user_db[user_id].get('email', 'Not Set') == 'Not Set':
            user_state[user_id] = 'wallet_wait_email'
            bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_email_prompt'], lang), reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'wallet_wait_address'
            bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if user_id not in user_current_path: user_current_path[user_id] = 'root'
    if user_id not in user_state: user_state[user_id] = 'normal'
    
    # REVERSE MAP: Transparently translate incoming buttons back to English logic!
    # This loop absolutely guarantees that BACK and HOME buttons always work in any language!
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
    if not is_admin and user_state[user_id] not in ['w_action_amount', 'w_action_addr', 'dep_wait_amount', 'dep_wait_proof', 'buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg']: 
        user_state[user_id] = 'normal'
        
    current_path = user_current_path[user_id]
    state = user_state[user_id]
    selected_btn = user_selected_button.get(user_id)
    full_path = f"{current_path}/{selected_btn}" if selected_btn else None

    # --- HANDLE USER ABORTING OR NAVIGATING FIRST (BEFORE STATE LOGIC CATCHES IT) ---
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
        elif state.startswith('bal_') or state in ['adding_button', 'renaming_button', 'assign_plan', 'admin_wait_tx_id', 'assign_command', 'wait_ref_bonus_pct']:
            fallback = 'bal_menu' if state.startswith('bal_') or state == 'wait_ref_bonus_pct' else 'editing'
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
        elif state.startswith('reinvest_setup_'):
            user_state[user_id] = 'admin_reinvest_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Reinvest setting cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('msg_setup_'):
            user_state[user_id] = 'admin_messages_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state in ['wait_invite_msg', 'wait_invite_levels']:
            user_state[user_id] = 'admin_invite_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state == 'admin_loading_time':
            user_state[user_id] = 'admin_loading_bar'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('wait_block') or state.startswith('wait_edit_block') or state.startswith('wait_edit_unblock'):
            user_state[user_id] = 'admin_block_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state in ['admin_broadcast_input', 'admin_broadcast_action', 'admin_broadcast_preview', 'bc_wait_mode', 'bc_wait_text', 'bc_wait_data']:
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Broadcast cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        # --- NEW FEATURE 2: WIPE CANCELLATION & POPUP MENU ---
        elif state in ['wait_wipe_id', 'wait_general_wipe_confirm']:
            user_state[user_id] = 'admin_wipe_menu'
            bot.send_message(message.chat.id, "Wipe action cancelled.", reply_markup=get_keyboard(user_id))
            return
        elif state == 'wait_payout_popup':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state == 'wait_support_msg' or state.startswith('admin_suprep_'):
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        else:
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("❌ Action Cancelled.", lang), reply_markup=get_keyboard(user_id))
            return

    # --- INTERCEPT MENU CLICKS WHILE IN SETUP ---
    msg_menu_cmds = ['Edit Hourly DM', 'Edit Expiry DM', 'Edit Ref Join Msg', 'Edit Ref Comm Msg', 'Edit Level Up Msg', 'Edit Admin Change Msg']
    if text in msg_menu_cmds and state.startswith('msg_setup_'):
        user_state[user_id] = 'admin_messages_menu'
        state = 'admin_messages_menu'
        
    # --- SUPPORT DESK LOGIC ---
    if state == 'wait_support_msg':
        bot.send_message(message.chat.id, "Sending... ⏳")
        time.sleep(1.5)
        bot.send_message(message.chat.id, "✅ Your message has been routed securely to Support.", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('💬 Reply to User', callback_data=f'cb_suprep_{user_id}'))
        
        admin_alert = f"💬 <b>New Support Ticket</b>\n\n👤 User: <code>{user_id}</code> (@{message.from_user.username or 'No Username'})\n\n<b>Message:</b>\n{formatted_text}"
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, admin_alert, parse_mode="HTML", reply_markup=markup)
            except Exception: pass
        return
        
    if state.startswith('admin_suprep_'):
        target_uid = int(state.split('_')[2])
        target_lang = user_db.get(target_uid, {}).get('lang', 'en')
        
        reply_msg = f"👤 <b>Message from Support:</b>\n\n{formatted_text}"
        try:
            bot.send_message(target_uid, get_tl_and_map(reply_msg, target_lang), parse_mode="HTML")
            bot.send_message(message.chat.id, f"✅ Reply securely delivered to user <code>{target_uid}</code>.", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        except:
            bot.send_message(message.chat.id, "❌ Delivery failed. User may have blocked the bot.", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

    # --- ADMIN MESSAGES MANAGER ---
    if state == 'admin_menu' and text == '💬 Messages':
        user_state[user_id] = 'admin_messages_menu'
        bot.send_message(message.chat.id, "💬 <b>Messages Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_messages_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Hourly DM':
            user_state[user_id] = 'msg_setup_hourly'
            bot.send_message(message.chat.id, f"Enter the Hourly Accrual DM (Macros: {{hourly_amount}}, {{time_left}}):\n\n<b>Current:</b>\n{global_messages_setup['hourly_dm']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Expiry DM':
            user_state[user_id] = 'msg_setup_expiry'
            bot.send_message(message.chat.id, f"Enter the Plan Expiry DM (Macro: {{total_profit}}):\n\n<b>Current:</b>\n{global_messages_setup['expiry_dm']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Ref Join Msg':
            user_state[user_id] = 'msg_setup_ref_join'
            bot.send_message(message.chat.id, f"Enter the msg sent when someone uses their referral link:\n\n<b>Current:</b>\n{global_messages_setup['ref_join_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Ref Comm Msg':
            user_state[user_id] = 'msg_setup_ref_comm'
            bot.send_message(message.chat.id, f"Enter the msg sent when earning a referral commission (Macro: {{amount}}):\n\n<b>Current:</b>\n{global_messages_setup['ref_commission_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Level Up Msg':
            user_state[user_id] = 'msg_setup_lvl_up'
            bot.send_message(message.chat.id, f"Enter the msg sent when hitting a new invite level (Macros: {{level}}, {{reward}}):\n\n<b>Current:</b>\n{global_messages_setup['level_up_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Admin Change Msg':
            user_state[user_id] = 'msg_setup_adm_change'
            bot.send_message(message.chat.id, f"Enter the msg sent when Admin updates balance directly (Macros: {{btype}}, {{new_bal}}):\n\n<b>Current:</b>\n{global_messages_setup['admin_change_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('msg_setup_'):
        if state == 'msg_setup_hourly': global_messages_setup['hourly_dm'] = formatted_text
        elif state == 'msg_setup_expiry': global_messages_setup['expiry_dm'] = formatted_text
        elif state == 'msg_setup_ref_join': global_messages_setup['ref_join_msg'] = formatted_text
        elif state == 'msg_setup_ref_comm': global_messages_setup['ref_commission_msg'] = formatted_text
        elif state == 'msg_setup_lvl_up': global_messages_setup['level_up_msg'] = formatted_text
        elif state == 'msg_setup_adm_change': global_messages_setup['admin_change_msg'] = formatted_text
        
        user_state[user_id] = 'admin_messages_menu'
        bot.send_message(message.chat.id, "✅ Message updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN INVITE MENU SETTINGS ---
    if state == 'admin_menu' and text == 'Invite Settings':
        user_state[user_id] = 'admin_invite_menu'
        bot.send_message(message.chat.id, "👥 <b>Invite Settings Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_invite_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Post Message':
            user_state[user_id] = 'wait_invite_msg'
            bot.send_message(message.chat.id, f"Enter new template (Macros: %levels_display%, %team_deposits%, %affiliate_earnings%):\n\n<b>Current:</b>\n{invite_settings['msg_template']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '📊 Set Levels':
            user_state[user_id] = 'wait_invite_levels'
            curr_lvl = ", ".join([f"{l['users']}-{l['reward']}" for l in invite_settings['levels']])
            bot.send_message(message.chat.id, f"Enter comma-separated levels as Users-Reward (e.g. 10-5, 25-15, 100-50):\n\n<b>Current:</b>\n{curr_lvl}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('⏳ Toggle Loading Bar'):
            invite_settings['use_loading_bar'] = not invite_settings.get('use_loading_bar', True)
            bot.send_message(message.chat.id, "✅ Loading bar toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('🔗 Toggle Dynamic Link'):
            invite_settings['use_dynamic_link'] = not invite_settings.get('use_dynamic_link', False)
            bot.send_message(message.chat.id, "✅ Dynamic links toggled.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_invite_msg':
        invite_settings['msg_template'] = formatted_text
        user_state[user_id] = 'admin_invite_menu'
        bot.send_message(message.chat.id, "✅ Message updated.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_invite_levels':
        try:
            parts = text.split(',')
            new_lvls = []
            for p in parts:
                u, r = p.split('-')
                new_lvls.append({'users': int(u.strip()), 'reward': float(r.strip())})
            invite_settings['levels'] = new_lvls
            user_state[user_id] = 'admin_invite_menu'
            bot.send_message(message.chat.id, "✅ Levels updated.", reply_markup=get_keyboard(user_id))
        except:
            bot.send_message(message.chat.id, "⚠️ Invalid format. Use Users-Reward, separated by commas (e.g. 10-5, 25-15).")
        return

    # --- NEW: BROADCAST SYSTEM ENTRY ---
    if text == '📢 Broadcast Message' and is_admin:
        user_state[user_id] = 'admin_broadcast_input'
        user_action_data[user_id] = {'broadcast': {'text': '', 'photo': None, 'inlines': []}}
        bot.send_message(message.chat.id, "Send the text or photo for the broadcast message:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'admin_broadcast_input':
        user_action_data[user_id]['broadcast']['text'] = formatted_text
        if message.photo:
            user_action_data[user_id]['broadcast']['photo'] = message.photo[-1].file_id
        user_state[user_id] = 'admin_broadcast_action'
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row(KeyboardButton('➕ Add Inline'), KeyboardButton('✅ Proceed'))
        markup.row(KeyboardButton('❌ Cancel Action'))
        bot.send_message(message.chat.id, "Message captured. What would you like to do?", reply_markup=markup)
        return

    if state == 'admin_broadcast_action':
        if text == '➕ Add Inline':
            user_state[user_id] = 'bc_wait_mode'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('🚀 Command'))
            markup.row(KeyboardButton('🛒 Buy Plan'), KeyboardButton('🏦 Deposit'))
            markup.row(KeyboardButton('❓ Ask Question'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select action for the inline button:", reply_markup=markup)
        elif text == '✅ Proceed':
            user_state[user_id] = 'admin_broadcast_preview'
            bc_data = user_action_data[user_id]['broadcast']
            markup = InlineKeyboardMarkup()
            for b in bc_data['inlines']:
                if b['mode'] == 'url': markup.add(InlineKeyboardButton(b['text'], url=b['data']))
                elif b['mode'] == 'command': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_cmd_bc_{b['data']}"))
                elif b['mode'] == 'buy_plan': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_buy_bc_{b['data']}"))
                elif b['mode'] == 'deposit': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_dep_bc_{b['data']}"))
                elif b['mode'] == 'question': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_question_bc_{b['data']}"))
            
            rmarkup = ReplyKeyboardMarkup(resize_keyboard=True)
            rmarkup.row(KeyboardButton('🚀 Send Broadcast'), KeyboardButton('❌ Cancel Action'))
            
            bot.send_message(message.chat.id, "<b>Preview of Broadcast:</b>", parse_mode="HTML", reply_markup=rmarkup)
            if bc_data['photo']:
                bot.send_photo(message.chat.id, bc_data['photo'], caption=bc_data['text'], parse_mode="HTML", reply_markup=markup if markup.keyboard else None)
            else:
                bot.send_message(message.chat.id, bc_data['text'] or " ", parse_mode="HTML", reply_markup=markup if markup.keyboard else None)
        return

    if state == 'bc_wait_mode':
        if text not in ['🔗 URL or Share', '🚀 Command', '🛒 Buy Plan', '🏦 Deposit', '❓ Ask Question']:
            return bot.send_message(message.chat.id, "Invalid option. Select from keyboard.")
        user_action_data[user_id]['bc_mode'] = text
        user_state[user_id] = 'bc_wait_text'
        bot.send_message(message.chat.id, "Enter the TEXT for this button:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'bc_wait_text':
        user_action_data[user_id]['bc_text'] = text
        mode = user_action_data[user_id]['bc_mode']
        user_state[user_id] = 'bc_wait_data'
        if mode == '🔗 URL or Share': bot.send_message(message.chat.id, "Enter the URL (e.g. https://...):")
        elif mode == '🚀 Command': bot.send_message(message.chat.id, "Enter the exact command/button name to trigger:")
        elif mode == '❓ Ask Question':
            bot.send_message(message.chat.id, "Send an identifier or just type '0' (Admins will see standard support ticket):")
        elif mode == '🛒 Buy Plan':
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for p in bot_plans: markup.row(KeyboardButton(p))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Plan to trigger:", reply_markup=markup)
        elif mode == '🏦 Deposit':
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for c in deposit_settings: markup.row(KeyboardButton(c))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Deposit currency to trigger:", reply_markup=markup)
        return

    import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import uuid
import time
import os
import threading
import requests
import json
import html
import re
import psutil
import random
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

# DASHBOARD SECURITY PIN
ADMIN_PIN = os.getenv('ADMIN_PIN', '123456')

# --- NEW FEATURE 1: NORTHFLANK API CREDENTIALS ---
NORTHFLANK_API_KEY = os.getenv('NORTHFLANK_API_KEY', '')
NORTHFLANK_PROJECT = os.getenv('NORTHFLANK_PROJECT', '')
NORTHFLANK_VOLUME = os.getenv('NORTHFLANK_VOLUME', '')

# API KEYS FOR BLOCKCHAIN TRACKING
TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY', '')

# --- AIVEN POSTGRESQL DATABASE SYSTEM ---
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_LOADED_SUCCESSFULLY = False  # 🔒 THE NEW SAFETY LOCK

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
        print("✅ Aiven Database connected and table verified!")
    except Exception as e:
        print(f"❌ Aiven DB Init Error: {e}")

def load_database():
    global DB_LOADED_SUCCESSFULLY
    if not DATABASE_URL: return {}
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT data FROM bot_state WHERE id = 1;")
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        DB_LOADED_SUCCESSFULLY = True # 🔓 UNLOCKS SAVING
        print("✅ Aiven Memory successfully loaded into Bot!")
        
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
        print(f"⚠️ CRITICAL: Error loading from Aiven DB: {e}")
        # By NOT unlocking the safety lock here, we prevent the bot from wiping Aiven!
        return {}

def save_database():
    # 🛑 PREVENTS THE DEADLY OVERWRITE BUG
    if not DATABASE_URL or not DB_LOADED_SUCCESSFULLY: 
        return 
        
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
        'global_ui_settings': global_ui_settings,
        'reinvest_settings': reinvest_settings,
        'global_messages_setup': global_messages_setup,
        'processed_txids': list(processed_txids), # Convert set to list for database
        'blocked_users': list(blocked_users),     # NEW: Blocked users saving
        'block_settings': block_settings,         # NEW: Block messages saving
        'dynamic_stats': dynamic_stats,           # NEW: Dynamic Stats saving
        'invite_settings': invite_settings        # NEW: Invite settings saving
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
        # 💓 THE HEARTBEAT MONITOR:
        print(f"💾 AIVEN AUTO-SAVE: {len(user_db)} users backed up successfully!")
    except Exception as e:
        print(f"⚠️ AIVEN DB SAVE ERROR: {e}")

def auto_save_loop():
    """Runs forever in the background, saving data every 10 seconds."""
    while True:
        time.sleep(10)
        save_database()

# Initialize Neon and Load Data
init_db()
db_data = load_database()

# --- NEW: SMART DECIMAL FORMATTER ---
def fmt_amt(val):
    """Dynamically shows 2 decimals for standard numbers, or exactly infinite decimals for micro-amounts."""
    if val is None: return "0.00"
    try:
        v = float(val)
        if v == 0: return "0.00"
        if abs(v) >= 0.01:
            return "{:.2f}".format(v)
        else:
            s = f"{v:.8f}".rstrip('0')
            if s.endswith('.'): s += "00"
            return s
    except:
        return "0.00"

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
pending_auto_txids = {}
pending_withdrawals = {} # Tracker for Admin Withdrawal System

# --- PERSISTENT DATA (Loaded from Neon DB) ---
user_db = db_data.get('user_db', {})
menus = db_data.get('menus', {'root': []})
menu_posts = db_data.get('menu_posts', {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]})
btn_metadata = db_data.get('btn_metadata', {})
processed_txids = set(db_data.get('processed_txids', []))

# NEW: Blocked Users Persistent Data
blocked_users = set(db_data.get('blocked_users', []))
block_settings = db_data.get('block_settings', {
    'msg_block': '🚫 You have been blocked by the admin and cannot use this bot.',
    'msg_unblock': '✅ You have been unblocked. Welcome back!'
})

# NEW: Dynamic Stats Persistent Data
dynamic_stats = db_data.get('dynamic_stats', {
    'investments': 0.0,
    'withdrawn': 0.0,
    'users': 0,
    'last_refresh': 0.0
})

global_ui_settings = db_data.get('global_ui_settings', {'loading_bar_style': '1', 'loading_bar_time': 3.0})

# NEW: Global Messages Manager Data
global_messages_setup = db_data.get('global_messages_setup', {
    'hourly_dm': '💰You have received +{hourly_amount} USDT hourly profits.\nTime left: {time_left}',
    'expiry_dm': '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed',
    'ref_join_msg': '🎉 1 user joined via your link!',
    'ref_commission_msg': '💵 You received +{amount} USDT from your referral activity!',
    'level_up_msg': '🎉 Congratulations! You reached Referral Level {level} and earned {reward} USDT!',
    'admin_change_msg': '🔔 Admin Notice\n\nYour {btype} balance is now: <b>{new_bal}</b>'
})

# NEW: Reinvest Settings Persistent Data
reinvest_settings = db_data.get('reinvest_settings', {
    'msg_success': '✅ <b>Reinvest Successful!</b>\nYou have successfully reinvested <b>$%amount%</b> into <b>%plan_name%</b>.',
    'msg_fail': '❌ You can not invest right now: You need at least %min_amount% USDT to invest!',
    'inline_deposit_text': '🏦 Deposit Now'
})

# NEW: Invite Settings Persistent Data (UPDATED WITH DYNAMIC LINK TOGGLE)
invite_settings = db_data.get('invite_settings', {
    'levels': [{'users': 10, 'reward': 5.0}, {'users': 25, 'reward': 15.0}, {'users': 100, 'reward': 50.0}],
    'msg_template': "👥 <b>Referral Statistics</b>\n\n%levels_display%\n\n👥 My team Deposits: %team_deposits% USDT\n♾ Earnings: %affiliate_earnings% USDT",
    'use_loading_bar': True,
    'ref_commission_pct': 0.0,
    'use_dynamic_link': False
})

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
    'w_msg_conf': 'Are you sure you want to withdraw %withdraw% USDT via %network% to:\n<code>%address%</code>',
    'w_msg_processing': '♻️ Your Withdrawal of %withdraw% is processing on the blockchain...',
    'w_msg_approve': '✅ Withdrawal Completed\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: -%withdraw% USDT\n🔗 Address: <code>%address%</code>\n🌐 Network: %network%\n⚡ Type: Instant\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Successful ✔️ \n\nYour funds have been sent successfully to your wallet.',
    'w_msg_decline': '❌ Withdrawal Declined\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: %withdraw% USDT\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Failed ❌ \n\nYour withdrawal request was declined. The funds have been refunded to your balance.',
    'w_msg_ignore': '🚫 Withdrawal Ignored\n━━━━━━━━━━━━━━━━━━\n👤 %firstname% %lastname%\n💰 Amount: %withdraw% USDT\n━━━━━━━━━━━━━━━━━━\n                           📌 Status: Cancelled 🚫 \n\nYour withdrawal request has been ignored.',
    'do_not_ask_address': False,
    'w_commission': 0.0,
    'w_rate_toggle': False,
    'public_report': None,
    'private_report': None,
    'addr_var': 'wallet',
    'use_ascii_receipt': False,
    'payout_btn_text': '📜 View Receipt',
    'payout_popup_msg': 'Payment Success!'
})

global_wallet_setup = db_data.get('global_wallet_setup', {
    'msg_main': '💡 Your currently set USDT Wallet Address is: <code>%wallet%</code>\n\nEmail: <code>%email%</code>\n\n💹 It will be used for all future withdrawals.\n\nNOTE🔴: Supported, USDT Network Address are: TRC20 and BEP20 Set Only one..',
    'msg_prompt': '✏️ Send now your USDT TRC 20 OR BEP 20 Address to use it in future transactions ..',
    'msg_success': '🖊 Done: Your new wallet address is <code>%wallet%</code> (%network%)',
    'inline_set': 'Set wallet', 'inline_change': 'Change wallet',
    'ask_email': True, 'msg_email_prompt': '✏️ Please enter your Email address:'
})

global_bonus_setup = db_data.get('global_bonus_setup', {
    'amount': 5.0, 'cooldown_hours': 24.0, 'min_withdraw': 50.0,
    'msg_success': '🎉 Congratulations! You have received $%bonus_amount% as a bonus.',
    'msg_fail': '⏳ You have already claimed your bonus. Please wait %time_left%.'
})

bot_plans = db_data.get('bot_plans', {})

# --- SYSTEM PLANS INITIALIZATION ---
if not bot_plans:
    for i in range(6):
        name_str = 'G-Force Free Plan' if i == 0 else f'G-Force Plan {i}'
        bot_plans[f'plan{i}'] = {
            'name': name_str, 'min': 10.0, 'max': 1000.0, 'length': 24.0, 'profit': 5.0,
            'text': f'✨ <b>{name_str} Description</b> ✨\n\nEdit this in Admin -&gt; Plans.',
            'photo': None, 'inline_text': '🛒 Purchase Plan', 'inline_active_text': '(Active ✅)', 
            'redirect_cmd': None, 'is_free': (i == 0), 'bonus_amount': 50.0 if i == 0 else 0.0
        }

# --- NEW: BACKGROUND CACHE PRELOADER ---
def preload_core_languages():
    """Background-translates and caches the bot's core strings and active menus for new users."""
    all_strings = set([
        '🏠 Home', '🔙 Back', '❌ Cancel Action', '💵 Balance', '🔐 Admin',
        'Deposit balance', 'Withdrawal balance', '✔️ Leave as Is', '➖ Set Empty'
    ])
    for menu_list in menus.values():
        all_strings.update(menu_list)
        
    langs = ['zh-CN', 'pt', 'nl', 'es', 'de', 'fr', 'ar', 'ru', 'id', 'hi']
    for lang in langs:
        for text in all_strings:
            get_tl_and_map(text, lang)
        time.sleep(0.5)

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
        'is_language': False,
        'is_reinvest': False,
        'is_stats': False,   # NEW
        'is_info': False,    # NEW
        'is_invite': False,  # NEW
        'is_deposit': False, # NEW EDITABLE DEPOSIT
        'is_live_trading': False # NEW
    }

def init_user_db(message):
    user_id = message.from_user.id
    is_new_user = False
    if user_id not in user_db:
        is_new_user = True
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
            'lang': 'en',
            'referred_by': None,           # NEW
            'team_deposits': 0.0,          # NEW
            'affiliate_earnings': 0.0,     # NEW
            'claimed_levels': [],          # NEW
            'invite_links_map': []         # NEW
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
        if 'referred_by' not in user_db[user_id]: user_db[user_id]['referred_by'] = None
        if 'team_deposits' not in user_db[user_id]: user_db[user_id]['team_deposits'] = 0.0
        if 'affiliate_earnings' not in user_db[user_id]: user_db[user_id]['affiliate_earnings'] = 0.0
        if 'claimed_levels' not in user_db[user_id]: user_db[user_id]['claimed_levels'] = []
        if 'invite_links_map' not in user_db[user_id]: user_db[user_id]['invite_links_map'] = []
    
    return is_new_user

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
        
        # BTC requires WIF Private Key, EVM/Tron uses Hex
        if currency == 'BTC':
            private_key = bip44_acc.PrivateKey().ToWif()
        else:
            private_key = bip44_acc.PrivateKey().Raw().ToHex()
        
        return public_address, private_key
    except Exception as e:
        print(f"Wallet Gen Error: {e}")
        return "GEN_ERROR", "GEN_ERROR"

# --- HELPER: REFERRAL COMMISSION ENGINE ---
def process_referral_commission(user_id, amount, is_deposit=True):
    inviter = user_db.get(user_id, {}).get('referred_by')
    if inviter and inviter in user_db:
        pct = invite_settings.get('ref_commission_pct', 0.0)
        if pct > 0:
            comm = amount * (pct / 100.0)
            user_db[inviter]['balance'] += comm
            user_db[inviter]['affiliate_earnings'] += comm
            log_tx(inviter, "Referral Commission", comm)
            try:
                lang = user_db[inviter].get('lang', 'en')
                msg = global_messages_setup.get('ref_commission_msg', '💵 You received +{amount} USDT from your referral activity!')
                msg = msg.replace('{amount}', f"{fmt_amt(comm)}")
                bot.send_message(inviter, get_tl_and_map(msg, lang), parse_mode="HTML")
            except: pass
        if is_deposit:
            user_db[inviter]['team_deposits'] += amount

# --- MASTER API SCANNER HELPER (100% AUTOMATED NETWORK SCAN) ---
def check_address_for_new_deposit(addr, curr):
    """Scans the respective blockchain for new incoming transfers and extracts timestamps."""
    crypto_amount = 0.0
    txid_found = ""
    tx_time = 0.0
    
    try:
        if curr in ['TRX', 'USDT_TRC20']:
            headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
            
            if curr == 'USDT_TRC20':
                url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20?only_to=true"
            else:
                url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions?only_to=true"
                
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('data', [])
                for tx in txs:
                    txid = tx.get('transaction_id') or tx.get('txID')
                    if txid in processed_txids: continue
                    
                    if curr == 'USDT_TRC20':
                        if tx.get('token_info', {}).get('address') == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t":
                            tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                            return True, float(tx.get('value', 0)) / 1_000_000, txid, tx_time
                            
                    elif curr == 'TRX':
                        contract = tx.get('raw_data', {}).get('contract', [{}])[0]
                        if contract.get('type') == 'TransferContract':
                            amt = contract.get('parameter', {}).get('value', {}).get('amount', 0)
                            tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                            return True, float(amt) / 1_000_000, txid, tx_time
                            
        elif curr == 'USDT_ERC20':
            url = f"https://api.etherscan.io/api?module=account&action=tokentx&address={addr}&page=1&offset=10&sort=desc&apikey={ETHERSCAN_API_KEY}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('result', [])
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('hash')
                        if txid in processed_txids: continue
                        if tx.get('contractAddress', '').lower() == "0xdac17f958d2ee523a2206206994597c13d831ec7" and tx.get('to', '').lower() == addr.lower():
                            tx_time = float(tx.get('timeStamp', time.time()))
                            return True, float(tx.get('value', 0)) / 10**6, txid, tx_time
                            
        elif curr == 'USDT_BEP20':
            url = f"https://api.bscscan.com/api?module=account&action=tokentx&address={addr}&page=1&offset=10&sort=desc&apikey={BSCSCAN_API_KEY}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json().get('result', [])
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('hash')
                        if txid in processed_txids: continue
                        if tx.get('contractAddress', '').lower() == "0x55d398326f99059ff775485246999027b3197955" and tx.get('to', '').lower() == addr.lower():
                            tx_time = float(tx.get('timeStamp', time.time()))
                            return True, float(tx.get('value', 0)) / 10**18, txid, tx_time
                            
        elif curr == 'BTC':
            url = f"https://mempool.space/api/address/{addr}/txs"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                txs = resp.json()
                if isinstance(txs, list):
                    for tx in txs:
                        txid = tx.get('txid')
                        if txid in processed_txids: continue
                        for vout in tx.get('vout', []):
                            if vout.get('scriptpubkey_address') == addr:
                                tx_time = float(tx.get('status', {}).get('block_time', time.time()))
                                return True, float(vout.get('value', 0)) / 10**8, txid, tx_time
                                
    except Exception as e:
        print(f"API Scan Error ({curr}): {e}")
        pass
        
    return False, 0.0, "", 0.0

# --- 4. AUTO-DETECTION WATCHER ENGINE ---
def blockchain_watcher_loop():
    """Continuously checks the blockchain, verifying official timestamps for the 5-min delay."""
    while True:
        try:
            for uid, data in list(user_db.items()):
                for curr, w_data in list(data.get('wallets', {}).items()):
                    addr = w_data['address']
                    found, crypto_amount, txid, tx_time = check_address_for_new_deposit(addr, curr)
                    
                    # If we found a transaction and it hasn't been processed yet
                    if found and txid not in processed_txids:
                        now = time.time()
                        
                        # THE FIX: We use the blockchain's official timestamp!
                        # If the block was mined 5+ minutes ago (300 seconds), approve it instantly.
                        # Even if the server restarts, this math is perfectly stateless and robust.
                        if (now - tx_time) >= 300:
                            processed_txids.add(txid)
                            
                            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
                            usd_value = crypto_amount * live_price
                            
                            user_db[uid]['deposit'] += usd_value
                            user_db[uid]['wallets'][curr]['total_deposited'] = user_db[uid]['wallets'][curr].get('total_deposited', 0.0) + usd_value
                            log_tx(uid, f"Auto-Deposit ({curr})", usd_value)
                            
                            process_referral_commission(uid, usd_value, is_deposit=True) # NEW: Commission
                            
                            try:
                                conf = deposit_settings[curr]
                                msg_success = conf.get('msg_success', "✅ <b>Deposit Detected!</b>\n\nThe blockchain confirmed a deposit of <b>%crypto_amount% %currency%</b>.\n<b>$%usd_amount% USD</b> has been automatically added to your balance!")
                                msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(usd_value)}").replace('%crypto_amount%', f"{fmt_amt(crypto_amount)}").replace('%currency%', curr.replace('_', ' '))
                                lang = user_db.get(uid, {}).get('lang', 'en')
                                bot.send_message(uid, get_tl_and_map(msg_success, lang), parse_mode="HTML")
                            except Exception: pass
                            
                            admin_msg = f"🟢 <b>AUTO-DEPOSIT APPROVED (5-MIN TIMEOUT)</b>\nUser: <code>{uid}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}\nHash (TXID): <code>{txid}</code>"
                            for admin in ADMIN_IDS:
                                try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                                except Exception: pass
                                
                            check_and_trigger_auto_buy(uid)
                            
        except Exception as e:
            print(f"Watcher Loop Error: {e}")
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
            msg = f"🎉 <b>Auto-Purchase Successful!</b>\n\nYour deposit triggered your pending plan.\n<b>{p_data['name']}</b> is now active with an investment of <b>${fmt_amt(invest_amt)}</b>!"
            lang = user_db.get(user_id, {}).get('lang', 'en')
            bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
        except Exception: pass

# --- TRUE BACKGROUND HOURLY ALERTS (FIX APPLIED HERE) ---
def process_accruals(user_id):
    u = user_db.get(user_id)
    if not u or not u.get('active_plans'): return
    
    now = time.time()
    for p in u['active_plans']:
        if p['status'] != 'active': continue
        
        elapsed_sec = now - p['last_accrual']
        full_hours = int(elapsed_sec // 3600)
        
        if full_hours > 0:
            for _ in range(full_hours):
                hourly_earned = p['amount'] * (p['profit_pct'] / 100.0)
                u['balance'] += hourly_earned
                p['earned'] += hourly_earned
                p['last_accrual'] += 3600
                
                # Calculate time left for DM
                time_left_str = "Lifetime"
                if p['length_hours'] > 0:
                    time_left_sec = (p['start_time'] + (p['length_hours'] * 3600)) - p['last_accrual']
                    if time_left_sec > 0:
                        hours, remainder = divmod(time_left_sec, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        time_left_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
                    else:
                        time_left_str = "0h 0m 0s"
                        
                try:
                    msg = global_messages_setup.get('hourly_dm', '💰You have received +{hourly_amount} USDT hourly profits.\nTime left: {time_left}')
                    msg = msg.replace('{hourly_amount}', f"{fmt_amt(hourly_earned)}").replace('{time_left}', time_left_str)
                    lang = u.get('lang', 'en')
                    bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
                except: pass
                
        if p['length_hours'] > 0:
            total_elapsed = (now - p['start_time']) / 3600.0
            if total_elapsed >= p['length_hours']:
                p['status'] = 'expired'
                try:
                    msg = global_messages_setup.get('expiry_dm', '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed')
                    msg = msg.replace('{total_profit}', f"{fmt_amt(p['earned'])}")
                    lang = u.get('lang', 'en')
                    bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
                except: pass

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

# --- NEW: DYNAMIC STATS REFRESH ENGINE ---
def refresh_dynamic_stats():
    now = time.time()
    # Initial seeding if 0
    if dynamic_stats['last_refresh'] == 0.0:
        dynamic_stats['investments'] = random.uniform(50000, 100000)
        dynamic_stats['withdrawn'] = dynamic_stats['investments'] * 3
        dynamic_stats['users'] = random.randint(5000, 10000)
        dynamic_stats['last_refresh'] = now
    elif now - dynamic_stats['last_refresh'] >= 86400:
        inv_add = random.uniform(10000, 16000)
        dynamic_stats['investments'] += inv_add
        dynamic_stats['withdrawn'] += (inv_add * 3)
        dynamic_stats['users'] += random.randint(700, 1500)
        dynamic_stats['last_refresh'] = now

def replace_macros(text, user_id, full_path, action_data=None):
    if not text: return "Not set."
    process_accruals(user_id) 
    refresh_dynamic_stats() 
    
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
    t = t.replace('%balance%', f"{fmt_amt(bals.get('balance', 0))}")
    t = t.replace('%bonus%', f"{fmt_amt(bals.get('bonus', 0))}")
    t = t.replace('%deposit%', f"{fmt_amt(bals.get('deposit', 0))}")
    t = t.replace('%lang%', bals.get('lang', 'en').upper())
    
    # NEW EXTENDED MACROS
    t = t.replace('%plan_invest%', f"{fmt_amt(plan_invest)}")
    t = t.replace('%hourly_profit%', f"{fmt_amt(hourly_profit)}")
    t = t.replace('%plan_names%', plan_names)
    t = t.replace('%ref_count%', str(ref_count))
    t = t.replace('%withdrawn%', f"{fmt_amt(total_withdrawn)}")
    t = t.replace('%team_deposits%', f"{fmt_amt(bals.get('team_deposits', 0))}")
    t = t.replace('%affiliate_earnings%', f"{fmt_amt(bals.get('affiliate_earnings', 0))}")
    
    bot_info = bot.get_me()
    t = t.replace('%ref_link%', f"https://t.me/{bot_info.username}?start={user_id}")
    
    # DYNAMIC LEVELS MACRO
    if '%levels_display%' in t:
        levels_str = ""
        for i, level in enumerate(invite_settings['levels']):
            req = level['users']
            current = min(bals.get('ref_count', 0), req)
            pct = int((current / req) * 10) if req > 0 else 10
            bar = "■" * pct + "▯" * (10 - pct)
            levels_str += f"{i+1}° Level: [{bar}] {req} users\n"
        t = t.replace('%levels_display%', levels_str)
    
    # NEW DYNAMIC STATS MACROS
    t = t.replace('%stats_invest%', f"{dynamic_stats['investments']:,.2f}")
    t = t.replace('%stats_withdrawn%', f"{dynamic_stats['withdrawn']:,.2f}")
    t = t.replace('%stats_users%', str(dynamic_stats['users']))
    
    t = t.replace('%wallet%', bals.get('wallet', 'Not Set'))
    t = t.replace('%email%', bals.get('email', 'Not Set'))
    t = t.replace('%bonus_amount%', str(global_bonus_setup['amount']))
    t = t.replace('%commission%', str(global_w_setup.get('w_commission', 0.0)))
    
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
                plans_str += f"Invested: ${fmt_amt(p['amount'])}\nEarned: ${fmt_amt(p['earned'])}\n\n"
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
        t = t.replace('%withdraw%', f"{fmt_amt(action_data.get('amount', 0))}")
        t = t.replace('%address%', action_data.get('address', bals.get('address', 'Not Set')))
        t = t.replace('%network%', action_data.get('network', bals.get('wallet_net', 'Unknown')))
    else:
        t = t.replace('%withdraw%', "0.00")
        t = t.replace('%address%', bals.get('address', 'Not Set'))
        t = t.replace('%network%', bals.get('wallet_net', 'Unknown'))

    # NEW EDITABLE LIVE TRADING MACROS
    if any(m in t for m in ['%trade_runtime%', '%trade_profit%', '%trade_anim_bar%', '%trade_pct%']):
        if not active:
            t = t.replace('%trade_runtime%', "00h 00m 00s")
            t = t.replace('%trade_profit%', "0.000000")
            t = t.replace('%trade_anim_bar%', "[■■■■■■■■■■]")
            t = t.replace('%trade_pct%', "100% (Completed)")
        else:
            now = time.time()
            oldest_start = min(p['start_time'] for p in active)
            elapsed_sec = now - oldest_start
            hours, remainder = divmod(int(elapsed_sec), 3600)
            minutes, seconds = divmod(remainder, 60)
            t = t.replace('%trade_runtime%', f"{hours:02d}h {minutes:02d}m {seconds:02d}s")
            
            # Real-time micro-profit summation updating every single second
            total_live_profit = sum(p['amount'] * (p['profit_pct'] / 100.0) * ((now - p['start_time']) / 3600.0) for p in active)
            t = t.replace('%trade_profit%', f"{total_live_profit:.6f}")
            
            # --- NEW SMART PRIORITY LOGIC ---
            # Separate plans with actual timers from lifetime plans
            timed_plans = [p for p in active if p['length_hours'] > 0]
            
            if timed_plans:
                # If they have ANY timed plans, track the oldest timed one
                tracked_plan = min(timed_plans, key=lambda x: x['start_time'])
                tot_sec = tracked_plan['length_hours'] * 3600
                plan_elapsed = now - tracked_plan['start_time']
                pct = min(100.0, (plan_elapsed / tot_sec) * 100)
                
                if pct >= 100.0:
                    t = t.replace('%trade_anim_bar%', "[■■■■■■■■■■]")
                    t = t.replace('%trade_pct%', "100% Completed")
                else:
                    cycle = int(now) % 3
                    bars = ["[■■■▯▯▯▯▯▯▯]", "[■■■■■■▯▯▯▯]", "[■■■■■■■■■■]"]
                    t = t.replace('%trade_anim_bar%', bars[cycle])
                    t = t.replace('%trade_pct%', f"{pct:.2f}% to Completion")
            else:
                # If ALL active plans are lifetime plans
                cycle = int(now) % 3
                bars = ["[■■■▯▯▯▯▯▯▯]", "[■■■■■■▯▯▯▯]", "[■■■■■■■■■■]"]
                t = t.replace('%trade_anim_bar%', bars[cycle])
                t = t.replace('%trade_pct%', "Lifetime Contract (Running)")

    # --- NEW FEATURE 1: ASCII RECEIPT MACRO ENGINE ---
    if '%ascii_receipt%' in t:
        if global_w_setup.get('use_ascii_receipt', False):
            tx_full = action_data.get('txid', 'N/A') if action_data else 'N/A'
            tx_short = tx_full[:11] + "..." if len(tx_full) > 11 else tx_full
            u_name = bals.get('username', 'Unknown')
            if len(u_name) > 13: u_name = u_name[:10] + "..."
            
            w_amt = fmt_amt(action_data.get('amount', 0)) if action_data else "0.00"
            n_str = action_data.get('network', bals.get('wallet_net', 'Unknown')) if action_data else bals.get('wallet_net', 'Unknown')
            if len(n_str) > 14: n_str = n_str[:11] + "..."
            
            # Using precise '<18' string padding to guarantee alignment across all screen sizes
            ascii_box = (
                "<pre>\n"
                "╔════════════════════════════╗\n"
                "║     G-FORCE PAYOUT LOG     ║\n"
                "╠════════════════════════════╣\n"
                f"║ TXID:   {tx_short:<18} ║\n"
                f"║ USER:   @{u_name:<17} ║\n"
                "║                            ║\n"
                f"║ WITHDRAWAL: ${w_amt:<13} ║\n"
                f"║ NETWORK:  {n_str:<16} ║\n"
                "║ FEE:    $0.00              ║\n"
                "╠════════════════════════════╣\n"
                "║      [ STATUS: PAID ]      ║\n"
                "╚════════════════════════════╝\n"
                "</pre>"
            )
            t = t.replace('%ascii_receipt%', ascii_box)
        else:
            # Silent clear if toggled off
            t = t.replace('%ascii_receipt%', '')
            
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

# --- THE FIX: GLOBAL MACRO: %loading_bar% ANIMATOR ---
def execute_loading_animation(chat_id, msg_id, part_a, style_opt, is_photo, total_seconds):
    """Animates a standalone loading message, then deletes it."""
    frames = {
        '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
        '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
        '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
    }
    all_bars = frames.get(str(style_opt), frames['1'])
    
    # NATIVE TELEGRAM API LIMIT FIX: Skip frames if the requested time is too short to physically render them all
    if total_seconds <= 0.5:
        bars = [all_bars[-1]] # Instantly 100%
    elif total_seconds <= 1.5:
        bars = [all_bars[0], all_bars[-1]] # 0% -> 100%
    elif total_seconds <= 2.5:
        bars = [all_bars[0], all_bars[len(all_bars)//2], all_bars[-1]] # 0% -> 50% -> 100%
    else:
        bars = all_bars # Full 6 frames

    sleep_time = total_seconds / len(bars)
    sep = "\n\n" if part_a.strip() else ""
    
    for bar in bars:
        iter_start = time.time()
        frame_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{bar}"
        try:
            if is_photo:
                bot.edit_message_caption(caption=frame_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                bot.edit_message_text(text=frame_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except:
            pass
            
        elapsed = time.time() - iter_start
        remaining = sleep_time - elapsed
        if remaining > 0:
            time.sleep(remaining)
            
    time.sleep(0.1) # Tiny buffer before deletion
    try: bot.delete_message(chat_id, msg_id)
    except: pass

def execute_live_trading_animation(chat_id, msg_id, raw_text, user_id, path, lang, markup):
    """Animates the live trading terminal in real-time for 30 seconds."""
    for _ in range(30): 
        time.sleep(1.0) # Updates screen exactly once per second
        updated_text = get_tl_and_map(replace_macros(raw_text, user_id, path), lang)
        try:
            bot.edit_message_text(text=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            if "message is not modified" in str(e).lower(): continue
            break # Exits cleanly if user leaves the menu

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
        raw_text = get_tl_and_map(replace_macros(p['text'], user_id, path), lang)
        
        has_loading_macro = False
        total_loading_time = float(global_ui_settings.get('loading_bar_time', 3.0)) # Fetch default time dynamically
        part_a = ""
        final_text = ""
        
        # THE FIX: Finds %loading_bar% OR %loading_bar_5s% custom times!
        match = re.search(r'%loading_bar(?:_(\d+(?:\.\d+)?)s)?%', raw_text)
        if match:
            has_loading_macro = True
            if match.group(1):
                total_loading_time = float(match.group(1))
            part_a = raw_text[:match.start()].strip()
            part_b = raw_text[match.end():].strip()
            final_text = part_a + ("\n\n" if part_a and part_b else "") + part_b
            
            # FIX: If we are in editing mode, make sure final_text retains the raw macro so it doesn't vanish
            if is_editing:
                final_text = raw_text
        else:
            final_text = raw_text
            
        style = global_ui_settings.get('loading_bar_style', '1')
        
        if has_loading_macro and not is_editing:
            # 1. SEND THE TEMPORARY LOADING MESSAGE FIRST
            sep = "\n\n" if part_a else ""
            bars = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "░░░░░░░░░░ 0%", "▒▒▒▒▒▒▒▒▒▒ 0%"]
            initial_bar = bars[int(style)-1] if style in ['1', '2', '3'] else bars[0]
            temp_msg_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{initial_bar}"
            
            try:
                if p['type'] == 'photo':
                    temp_msg = bot.send_photo(chat_id, p['photo'], caption=temp_msg_text, parse_mode="HTML")
                else:
                    temp_msg = bot.send_message(chat_id, temp_msg_text, parse_mode="HTML")
                # 2. PAUSE THE MENU AND ANIMATE it SYNCHRONOUSLY
                execute_loading_animation(chat_id, temp_msg.message_id, part_a, style, p['type'] == 'photo', total_loading_time)
            except: pass
            
        # 3. IF THERE IS NOTHING LEFT AFTER THE BAR DELETES ITSELF, SKIP SENDING AN EMPTY BUBBLE
        # Because we set final_text = raw_text during is_editing, it won't be completely empty,
        # so this logic naturally bypasses the 'skip' when editing!
        if has_loading_macro and not final_text and not p.get('custom_inlines') and not p.get('photo'):
            # Only skip if we aren't supposed to attach a reply keyboard here
            if not (i == len(posts) - 1 and not kb_attached and reply_keyboard):
                continue
        
        markup = InlineKeyboardMarkup()
        custom_inlines = p.get('custom_inlines', [])
        
        # APPEND NEW GEN LINK BUTTON DYNAMICALLY IF ASSIGN INVITE IS TRUE
        if meta.get('is_invite') and i == len(posts) - 1 and not is_editing:
            btn_text = get_tl_and_map("🔗 Generate Referral Link", lang)
            markup.row(InlineKeyboardButton(btn_text, callback_data='cb_gen_ref_link'))

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
                    elif b['mode'] == 'question':
                        row_btns.append(InlineKeyboardButton(tl_btn_text, callback_data=f"cb_question_{b['id']}"))
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
        
        # 4. FINALLY, SEND THE REAL POST (PART B)
        try:
            if p['type'] == 'photo':
                # For photos, if text is completely empty after extraction, make sure caption is empty, not a space
                cap = final_text if final_text else None
                sent = bot.send_photo(chat_id, p['photo'], caption=cap, parse_mode="HTML", reply_markup=markup)
            else:
                # To prevent sending empty text messages which crash Telegram
                safe_text = final_text if final_text else " "
                sent = bot.send_message(chat_id, safe_text, parse_mode="HTML", reply_markup=markup)
                
                # --- NEW: TRIGGER LIVE TRADING ANIMATION ---
                if meta.get('is_live_trading') and not is_editing:
                    threading.Thread(target=execute_live_trading_animation, args=(chat_id, sent.message_id, p['text'], user_id, path, lang, markup), daemon=True).start()
                
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
                
        except Exception as e:
            # FIX: Prevent editor lockout when HTML parse fails, send error and attach the editor markup
            err_msg = f"⚠️ <b>Error rendering post:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>Fix or delete this using the buttons below!</i>"
            sent = bot.send_message(chat_id, err_msg, parse_mode="HTML", reply_markup=markup)
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

# --- NATIVE ENTITY EXTRACTOR (Safely translates Telegram Formatting to Database HTML) ---
def extract_html(message):
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    
    if not entities:
        return text
        
    encoded_text = text.encode('utf-16-le')
    
    tags = []
    for ent in entities:
        open_tag, close_tag = '', ''
        if ent.type == 'bold': open_tag, close_tag = '<b>', '</b>'
        elif ent.type == 'italic': open_tag, close_tag = '<i>', '</i>'
        elif ent.type == 'code': open_tag, close_tag = '<code>', '</code>'
        elif ent.type == 'pre': open_tag, close_tag = '<pre>', '</pre>'
        elif ent.type == 'strikethrough': open_tag, close_tag = '<s>', '</s>'
        elif ent.type == 'underline': open_tag, close_tag = '<u>', '</u>'
        elif ent.type == 'spoiler': open_tag, close_tag = '<tg-spoiler>', '</tg-spoiler>'
        elif ent.type == 'text_link': open_tag, close_tag = f'<a href="{ent.url}">', '</a>'
        
        if open_tag:
            start = ent.offset * 2
            end = (ent.offset + ent.length) * 2
            tags.append((start, open_tag, 'open', ent.length))
            tags.append((end, close_tag, 'close', ent.length))
            
    # Sort backwards to not mess up offsets.
    tags.sort(key=lambda x: (x[0], x[2] == 'open', x[3] if x[2]=='close' else -x[3]), reverse=True)
    
    for index, tag_str, _, _ in tags:
        encoded_text = encoded_text[:index] + tag_str.encode('utf-16-le') + encoded_text[index:]
        
    try:
        return encoded_text.decode('utf-16-le')
    except Exception:
        return text

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
    reinv_text = "☑️ On" if meta.get('is_reinvest') else "⬜️ Off"
    stat_text = "☑️ On" if meta.get('is_stats') else "⬜️ Off"
    info_text = "☑️ On" if meta.get('is_info') else "⬜️ Off"
    invt_text = "☑️ On" if meta.get('is_invite') else "⬜️ Off"
    dep_text = "☑️ On" if meta.get('is_deposit') else "⬜️ Off"
    live_text = "☑️ On" if meta.get('is_live_trading') else "⬜️ Off"
    
    markup.row(KeyboardButton(f'Random Message ({rm_text})'), KeyboardButton(f'Admin Only ({ao_text})'))
    markup.row(KeyboardButton(f'Invisible ({inv_text})'), KeyboardButton('Subscription (Join)'))
    markup.row(KeyboardButton('Assign Command'), KeyboardButton('Assign Plan'), KeyboardButton('Assign Language')) 
    markup.row(KeyboardButton(f'Assign Calculator ({calc_text})'), KeyboardButton(f'Assign History ({hist_text})'))
    markup.row(KeyboardButton(f'Assign Withdrawal ({w_text})'), KeyboardButton(f'Assign Deposit ({dep_text})'))
    markup.row(KeyboardButton(f'Assign Bonus ({bon_text})'), KeyboardButton(f'Assign Wallet ({wal_text})'))
    markup.row(KeyboardButton(f'Assign Balance ({bal_text})'), KeyboardButton(f'Assign Stats ({stat_text})'))
    markup.row(KeyboardButton(f'Assign Reinvest ({reinv_text})'), KeyboardButton(f'Assign Live Trading ({live_text})'))
    markup.row(KeyboardButton(f'Assign Invite ({invt_text})'), KeyboardButton(f'Assign Info ({info_text})'))
    markup.row(KeyboardButton('Form Settings'), KeyboardButton('Assign Editor'))
    markup.row(KeyboardButton('Shop Editor'), KeyboardButton('🔙 Exit Button Settings'))
    return markup

def get_global_withdrawal_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    addr_text = "☑️ On" if global_w_setup.get('do_not_ask_address') else "⬜️ Off"
    rate_text = "☑️ On" if global_w_setup.get('w_rate_toggle') else "⬜️ Off"
    comm_val = global_w_setup.get('w_commission', 0.0)
    ascii_text = "☑️ On" if global_w_setup.get('use_ascii_receipt', False) else "⬜️ Off"
    
    markup.row(KeyboardButton('Set Withdrawal Var'), KeyboardButton('Set Min/Max'))
    markup.row(KeyboardButton('Edit Enter Msg'), KeyboardButton('Edit Address Msg'))
    markup.row(KeyboardButton('Edit Confirm Msg'), KeyboardButton('Processing Message'))
    markup.row(KeyboardButton('Approve Msg'), KeyboardButton('Decline Msg.'), KeyboardButton('Ignore Msg.'))
    markup.row(KeyboardButton('Public Group Report'), KeyboardButton('Private Group Report'))
    markup.row(KeyboardButton('Address Variable'))
    markup.row(KeyboardButton(f'Do not ask for Address ({addr_text})'))
    markup.row(KeyboardButton(f'Commission ({comm_val}%)'), KeyboardButton(f'Rate ({rate_text})'))
    markup.row(KeyboardButton(f'ASCII Receipt ({ascii_text})'), KeyboardButton('Edit Payout Popup'))
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
    markup.row(KeyboardButton('💰 Min Auto-Transfer'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_reinvest_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💬 Edit Success Msg'), KeyboardButton('💬 Edit Fail Msg'))
    markup.row(KeyboardButton('🔘 Edit Deposit Inline'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_loading_bar_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('Style 1: [■■■▯▯]'), KeyboardButton('Style 2: ▓▓▓░░'))
    markup.row(KeyboardButton('Style 3: ████▒▒'), KeyboardButton('⏱ Set Default Time'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_block_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('🚫 Block'), KeyboardButton('✅ Unblock'))
    markup.row(KeyboardButton('💬 Edit Block Msg'), KeyboardButton('💬 Edit Unblock Msg'))
    markup.row(KeyboardButton('🔙 Back to Admin'))
    return markup

def get_admin_invite_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💬 Edit Post Message'), KeyboardButton('📊 Set Levels'))
    lb_text = "☑️ On" if invite_settings.get('use_loading_bar', True) else "⬜️ Off"
    dyn_text = "☑️ On" if invite_settings.get('use_dynamic_link', False) else "⬜️ Off"
    markup.row(KeyboardButton(f'⏳ Toggle Loading Bar ({lb_text})'), KeyboardButton(f'🔗 Toggle Dynamic Link ({dyn_text})'))
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
            markup.row(KeyboardButton('📢 Broadcast Message'), KeyboardButton('🔄 Reinvest Settings'))
            markup.row(KeyboardButton('Loading Bar Settings'), KeyboardButton('🚫 Block User System'))
            markup.row(KeyboardButton('💬 Messages'), KeyboardButton('Invite Settings'))
            # --- NEW FEATURES 7 & 8: DEDICATED ADMIN BUTTONS ---
            markup.row(KeyboardButton('📊 Bot Stats'), KeyboardButton('🧹 Data Wipe Dashboard'))
            markup.row(KeyboardButton('🔙 Back to Main'))
            return markup
            
        # --- NEW FEATURE 8: ADVANCED WIPE DASHBOARD KEYBOARD ---
        if state == 'admin_wipe_menu':
            markup.row(KeyboardButton('🧹 Targeted Wipe'), KeyboardButton('☢️ General Wipe (All Users)'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup
            
        if state == 'admin_messages_menu':
            markup.row(KeyboardButton('Edit Hourly DM'), KeyboardButton('Edit Expiry DM'))
            markup.row(KeyboardButton('Edit Ref Join Msg'), KeyboardButton('Edit Ref Comm Msg'))
            markup.row(KeyboardButton('Edit Level Up Msg'), KeyboardButton('Edit Admin Change Msg'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_broadcast_action':
            markup.row(KeyboardButton('➕ Add Inline'), KeyboardButton('✅ Proceed'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state == 'admin_broadcast_preview':
            markup.row(KeyboardButton('🚀 Send Broadcast'), KeyboardButton('❌ Cancel Action'))
            return markup
            
        if state == 'bc_wait_mode':
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('🚀 Command'))
            markup.row(KeyboardButton('🛒 Buy Plan'), KeyboardButton('🏦 Deposit'))
            markup.row(KeyboardButton('❓ Ask Question'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        if state == 'admin_w_menu': return get_global_withdrawal_keyboard()
        if state == 'admin_wallet_menu': return get_admin_wallet_keyboard()
        if state == 'admin_bonus_menu': return get_admin_bonus_keyboard()
        if state == 'admin_reinvest_menu': return get_admin_reinvest_keyboard()
        if state == 'admin_loading_bar': return get_loading_bar_keyboard()
        if state == 'admin_block_menu': return get_admin_block_keyboard()
        if state == 'admin_invite_menu': return get_admin_invite_keyboard()

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

        # --- NEW FEATURE 2: CANCELLATION FOR WIPE WAIT STATES & POPUP STATES ---
        if state.startswith('dep_setup_') or state.startswith('wallet_setup_') or state.startswith('bonus_setup_') or state.startswith('reinvest_setup_') or state.startswith('msg_setup_') or state in ['admin_loading_time', 'wait_invite_msg', 'wait_invite_levels', 'wait_ref_bonus_pct', 'wait_support_msg', 'wait_payout_popup'] or state.startswith('wait_block_') or state.startswith('wait_edit_block') or state.startswith('wait_edit_unblock') or state in ['admin_broadcast_input', 'bc_wait_text', 'wait_wipe_id', 'wait_general_wipe_confirm']:
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
            if state == 'w_setup_proc': return get_wizard_keyboard(global_w_setup.get('w_msg_processing'), allow_empty=True)
            if state == 'w_setup_appr': return get_wizard_keyboard(global_w_setup.get('w_msg_approve'), allow_empty=True)
            if state == 'w_setup_dec': return get_wizard_keyboard(global_w_setup.get('w_msg_decline'), allow_empty=True)
            if state == 'w_setup_ign': return get_wizard_keyboard(global_w_setup.get('w_msg_ignore'), allow_empty=True)

        if state == 'button_settings': return get_settings_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_command': return get_assign_command_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_plan': return get_cancel_action_keyboard()
        
        if state in ['adding_button', 'renaming_button', 'pi_wait_text', 'pi_wait_data', 'bc_wait_data'] or state.startswith('admin_suprep_'):
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

    if state in ['buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg']:
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
    
    # --- NEW: INTERCEPT BLOCKED USERS ---
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return

    # Payload Extraction for Deep Linking
    parts = message.text.split()
    payload = parts[1] if len(parts) > 1 else None

    # --- NEW: HOMEPAGE HARDCODED LOADING BAR (Independent) ---
    frames = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"]
    try:
        loading_msg = bot.send_message(message.chat.id, f"♻️ <b>INITIALIZING SYSTEM...</b>\n{frames[0]}", parse_mode="HTML")
        for bar in frames[1:]:
            time.sleep(0.3)
            bot.edit_message_text(f"♻️ <b>INITIALIZING SYSTEM...</b>\n{bar}", chat_id=message.chat.id, message_id=loading_msg.message_id, parse_mode="HTML")
        time.sleep(0.2)
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # --- NEW: NEW USER ADMIN ALERT & PRELOAD ---
    is_new = init_user_db(message)
    inviter_id = None
    
    if payload:
        if payload.isdigit():
            inviter_id = int(payload)
        else:
            # Check dynamic invite links from memory bank
            for uid, udata in user_db.items():
                if payload in udata.get('invite_links_map', []):
                    inviter_id = uid
                    break
            # Fallback dynamic lookup
            if not inviter_id and payload.startswith('gf_'):
                potential_username = payload[3:]
                for uid, udata in user_db.items():
                    if str(uid) == potential_username or udata.get('username', '').lower() == potential_username.lower():
                        inviter_id = uid
                        break
                        
    if is_new:
        if inviter_id and inviter_id in user_db and inviter_id != user_id:
            user_db[user_id]['referred_by'] = inviter_id
            user_db[inviter_id]['ref_count'] += 1
            try:
                lang = user_db[inviter_id].get('lang', 'en')
                bot.send_message(inviter_id, get_tl_and_map(global_messages_setup['ref_join_msg'], lang))
            except: pass
            
            # Check level thresholds
            for i, level in enumerate(invite_settings['levels']):
                if user_db[inviter_id]['ref_count'] >= level['users']:
                    if i not in user_db[inviter_id].get('claimed_levels', []):
                        user_db[inviter_id]['balance'] += level['reward']
                        if 'claimed_levels' not in user_db[inviter_id]: user_db[inviter_id]['claimed_levels'] = []
                        user_db[inviter_id]['claimed_levels'].append(i)
                        log_tx(inviter_id, f"Referral Level {i+1} Reward", level['reward'])
                        try:
                            msg = global_messages_setup['level_up_msg'].replace('{level}', str(i+1)).replace('{reward}', str(level['reward']))
                            bot.send_message(inviter_id, get_tl_and_map(msg, lang))
                        except: pass

        total_bot_users = len(user_db)
        alert_msg = (
            f"🆕 New User!\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Total: [{total_bot_users}]\n"
            f"Name: {message.from_user.first_name}"
        )
        if user_db[user_id]['referred_by']:
            alert_msg += f"\nReferred by: <code>{user_db[user_id]['referred_by']}</code>"
            
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, alert_msg, parse_mode="HTML")
            except: pass
            
        # Trigger background language preload
        threading.Thread(target=preload_core_languages, daemon=True).start()

    user_current_path[user_id] = 'root'
    user_state[user_id] = 'normal'
    user_selected_button[user_id] = None
    
    send_path_content(message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))

@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    
    # --- NEW: INTERCEPT BLOCKED USERS ---
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return
    
    # --- NEW: NATIVE FORMATTING CAPTURE ---
    formatted_text = extract_html(message)

    is_admin = user_id in ADMIN_IDS
    
    # Initialize and check if new user
    is_new = init_user_db(message)
    if is_new:
        total_bot_users = len(user_db)
        alert_msg = (
            f"🆕 New User!\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Total: [{total_bot_users}]\n"
            f"Name: {message.from_user.first_name}"
        )
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, alert_msg, parse_mode="HTML")
            except: pass
        # Trigger background language preload
        threading.Thread(target=preload_core_languages, daemon=True).start()

    process_accruals(user_id) 
    
    lang = user_db.get(user_id, {}).get('lang', 'en')
    
    if text == '/setwallet info' or text == '/setwallet':
        if global_wallet_setup['ask_email'] and user_db[user_id].get('email', 'Not Set') == 'Not Set':
            user_state[user_id] = 'wallet_wait_email'
            bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_email_prompt'], lang), reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'wallet_wait_address'
            bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if user_id not in user_current_path: user_current_path[user_id] = 'root'
    if user_id not in user_state: user_state[user_id] = 'normal'
    
    # REVERSE MAP: Transparently translate incoming buttons back to English logic!
    # This loop absolutely guarantees that BACK and HOME buttons always work in any language!
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
    if not is_admin and user_state[user_id] not in ['w_action_amount', 'w_action_addr', 'dep_wait_amount', 'dep_wait_proof', 'buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg']: 
        user_state[user_id] = 'normal'
        
    current_path = user_current_path[user_id]
    state = user_state[user_id]
    selected_btn = user_selected_button.get(user_id)
    full_path = f"{current_path}/{selected_btn}" if selected_btn else None

    # --- HANDLE USER ABORTING OR NAVIGATING FIRST (BEFORE STATE LOGIC CATCHES IT) ---
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
        elif state.startswith('bal_') or state in ['adding_button', 'renaming_button', 'assign_plan', 'admin_wait_tx_id', 'assign_command', 'wait_ref_bonus_pct']:
            fallback = 'bal_menu' if state.startswith('bal_') or state == 'wait_ref_bonus_pct' else 'editing'
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
        elif state.startswith('reinvest_setup_'):
            user_state[user_id] = 'admin_reinvest_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Reinvest setting cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('msg_setup_'):
            user_state[user_id] = 'admin_messages_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state in ['wait_invite_msg', 'wait_invite_levels']:
            user_state[user_id] = 'admin_invite_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state == 'admin_loading_time':
            user_state[user_id] = 'admin_loading_bar'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('wait_block') or state.startswith('wait_edit_block') or state.startswith('wait_edit_unblock'):
            user_state[user_id] = 'admin_block_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state in ['admin_broadcast_input', 'admin_broadcast_action', 'admin_broadcast_preview', 'bc_wait_mode', 'bc_wait_text', 'bc_wait_data']:
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Broadcast cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        # --- NEW FEATURE 2: WIPE CANCELLATION & POPUP MENU ---
        elif state in ['wait_wipe_id', 'wait_general_wipe_confirm']:
            user_state[user_id] = 'admin_wipe_menu'
            bot.send_message(message.chat.id, "Wipe action cancelled.", reply_markup=get_keyboard(user_id))
            return
        elif state == 'wait_payout_popup':
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        elif state == 'wait_support_msg' or state.startswith('admin_suprep_'):
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
            return
        else:
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("❌ Action Cancelled.", lang), reply_markup=get_keyboard(user_id))
            return

    # --- INTERCEPT MENU CLICKS WHILE IN SETUP ---
    msg_menu_cmds = ['Edit Hourly DM', 'Edit Expiry DM', 'Edit Ref Join Msg', 'Edit Ref Comm Msg', 'Edit Level Up Msg', 'Edit Admin Change Msg']
    if text in msg_menu_cmds and state.startswith('msg_setup_'):
        user_state[user_id] = 'admin_messages_menu'
        state = 'admin_messages_menu'
        
    # --- SUPPORT DESK LOGIC ---
    if state == 'wait_support_msg':
        bot.send_message(message.chat.id, "Sending... ⏳")
        time.sleep(1.5)
        bot.send_message(message.chat.id, "✅ Your message has been routed securely to Support.", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('💬 Reply to User', callback_data=f'cb_suprep_{user_id}'))
        
        admin_alert = f"💬 <b>New Support Ticket</b>\n\n👤 User: <code>{user_id}</code> (@{message.from_user.username or 'No Username'})\n\n<b>Message:</b>\n{formatted_text}"
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, admin_alert, parse_mode="HTML", reply_markup=markup)
            except Exception: pass
        return
        
    if state.startswith('admin_suprep_'):
        target_uid = int(state.split('_')[2])
        target_lang = user_db.get(target_uid, {}).get('lang', 'en')
        
        reply_msg = f"👤 <b>Message from Support:</b>\n\n{formatted_text}"
        try:
            bot.send_message(target_uid, get_tl_and_map(reply_msg, target_lang), parse_mode="HTML")
            bot.send_message(message.chat.id, f"✅ Reply securely delivered to user <code>{target_uid}</code>.", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        except:
            bot.send_message(message.chat.id, "❌ Delivery failed. User may have blocked the bot.", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

    # --- ADMIN MESSAGES MANAGER ---
    if state == 'admin_menu' and text == '💬 Messages':
        user_state[user_id] = 'admin_messages_menu'
        bot.send_message(message.chat.id, "💬 <b>Messages Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_messages_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Hourly DM':
            user_state[user_id] = 'msg_setup_hourly'
            bot.send_message(message.chat.id, f"Enter the Hourly Accrual DM (Macros: {{hourly_amount}}, {{time_left}}):\n\n<b>Current:</b>\n{global_messages_setup['hourly_dm']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Expiry DM':
            user_state[user_id] = 'msg_setup_expiry'
            bot.send_message(message.chat.id, f"Enter the Plan Expiry DM (Macro: {{total_profit}}):\n\n<b>Current:</b>\n{global_messages_setup['expiry_dm']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Ref Join Msg':
            user_state[user_id] = 'msg_setup_ref_join'
            bot.send_message(message.chat.id, f"Enter the msg sent when someone uses their referral link:\n\n<b>Current:</b>\n{global_messages_setup['ref_join_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Ref Comm Msg':
            user_state[user_id] = 'msg_setup_ref_comm'
            bot.send_message(message.chat.id, f"Enter the msg sent when earning a referral commission (Macro: {{amount}}):\n\n<b>Current:</b>\n{global_messages_setup['ref_commission_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Level Up Msg':
            user_state[user_id] = 'msg_setup_lvl_up'
            bot.send_message(message.chat.id, f"Enter the msg sent when hitting a new invite level (Macros: {{level}}, {{reward}}):\n\n<b>Current:</b>\n{global_messages_setup['level_up_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Admin Change Msg':
            user_state[user_id] = 'msg_setup_adm_change'
            bot.send_message(message.chat.id, f"Enter the msg sent when Admin updates balance directly (Macros: {{btype}}, {{new_bal}}):\n\n<b>Current:</b>\n{global_messages_setup['admin_change_msg']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('msg_setup_'):
        if state == 'msg_setup_hourly': global_messages_setup['hourly_dm'] = formatted_text
        elif state == 'msg_setup_expiry': global_messages_setup['expiry_dm'] = formatted_text
        elif state == 'msg_setup_ref_join': global_messages_setup['ref_join_msg'] = formatted_text
        elif state == 'msg_setup_ref_comm': global_messages_setup['ref_commission_msg'] = formatted_text
        elif state == 'msg_setup_lvl_up': global_messages_setup['level_up_msg'] = formatted_text
        elif state == 'msg_setup_adm_change': global_messages_setup['admin_change_msg'] = formatted_text
        
        user_state[user_id] = 'admin_messages_menu'
        bot.send_message(message.chat.id, "✅ Message updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN INVITE MENU SETTINGS ---
    if state == 'admin_menu' and text == 'Invite Settings':
        user_state[user_id] = 'admin_invite_menu'
        bot.send_message(message.chat.id, "👥 <b>Invite Settings Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_invite_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Post Message':
            user_state[user_id] = 'wait_invite_msg'
            bot.send_message(message.chat.id, f"Enter new template (Macros: %levels_display%, %team_deposits%, %affiliate_earnings%):\n\n<b>Current:</b>\n{invite_settings['msg_template']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '📊 Set Levels':
            user_state[user_id] = 'wait_invite_levels'
            curr_lvl = ", ".join([f"{l['users']}-{l['reward']}" for l in invite_settings['levels']])
            bot.send_message(message.chat.id, f"Enter comma-separated levels as Users-Reward (e.g. 10-5, 25-15, 100-50):\n\n<b>Current:</b>\n{curr_lvl}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('⏳ Toggle Loading Bar'):
            invite_settings['use_loading_bar'] = not invite_settings.get('use_loading_bar', True)
            bot.send_message(message.chat.id, "✅ Loading bar toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('🔗 Toggle Dynamic Link'):
            invite_settings['use_dynamic_link'] = not invite_settings.get('use_dynamic_link', False)
            bot.send_message(message.chat.id, "✅ Dynamic links toggled.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_invite_msg':
        invite_settings['msg_template'] = formatted_text
        user_state[user_id] = 'admin_invite_menu'
        bot.send_message(message.chat.id, "✅ Message updated.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_invite_levels':
        try:
            parts = text.split(',')
            new_lvls = []
            for p in parts:
                u, r = p.split('-')
                new_lvls.append({'users': int(u.strip()), 'reward': float(r.strip())})
            invite_settings['levels'] = new_lvls
            user_state[user_id] = 'admin_invite_menu'
            bot.send_message(message.chat.id, "✅ Levels updated.", reply_markup=get_keyboard(user_id))
        except:
            bot.send_message(message.chat.id, "⚠️ Invalid format. Use Users-Reward, separated by commas (e.g. 10-5, 25-15).")
        return

    # --- NEW: BROADCAST SYSTEM ENTRY ---
    if text == '📢 Broadcast Message' and is_admin:
        user_state[user_id] = 'admin_broadcast_input'
        user_action_data[user_id] = {'broadcast': {'text': '', 'photo': None, 'inlines': []}}
        bot.send_message(message.chat.id, "Send the text or photo for the broadcast message:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'admin_broadcast_input':
        user_action_data[user_id]['broadcast']['text'] = formatted_text
        if message.photo:
            user_action_data[user_id]['broadcast']['photo'] = message.photo[-1].file_id
        user_state[user_id] = 'admin_broadcast_action'
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row(KeyboardButton('➕ Add Inline'), KeyboardButton('✅ Proceed'))
        markup.row(KeyboardButton('❌ Cancel Action'))
        bot.send_message(message.chat.id, "Message captured. What would you like to do?", reply_markup=markup)
        return

    if state == 'admin_broadcast_action':
        if text == '➕ Add Inline':
            user_state[user_id] = 'bc_wait_mode'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('🔗 URL or Share'), KeyboardButton('🚀 Command'))
            markup.row(KeyboardButton('🛒 Buy Plan'), KeyboardButton('🏦 Deposit'))
            markup.row(KeyboardButton('❓ Ask Question'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select action for the inline button:", reply_markup=markup)
        elif text == '✅ Proceed':
            user_state[user_id] = 'admin_broadcast_preview'
            bc_data = user_action_data[user_id]['broadcast']
            markup = InlineKeyboardMarkup()
            for b in bc_data['inlines']:
                if b['mode'] == 'url': markup.add(InlineKeyboardButton(b['text'], url=b['data']))
                elif b['mode'] == 'command': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_cmd_bc_{b['data']}"))
                elif b['mode'] == 'buy_plan': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_buy_bc_{b['data']}"))
                elif b['mode'] == 'deposit': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_dep_bc_{b['data']}"))
                elif b['mode'] == 'question': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_question_bc_{b['data']}"))
            
            rmarkup = ReplyKeyboardMarkup(resize_keyboard=True)
            rmarkup.row(KeyboardButton('🚀 Send Broadcast'), KeyboardButton('❌ Cancel Action'))
            
            bot.send_message(message.chat.id, "<b>Preview of Broadcast:</b>", parse_mode="HTML", reply_markup=rmarkup)
            if bc_data['photo']:
                bot.send_photo(message.chat.id, bc_data['photo'], caption=bc_data['text'], parse_mode="HTML", reply_markup=markup if markup.keyboard else None)
            else:
                bot.send_message(message.chat.id, bc_data['text'] or " ", parse_mode="HTML", reply_markup=markup if markup.keyboard else None)
        return

    if state == 'bc_wait_mode':
        if text not in ['🔗 URL or Share', '🚀 Command', '🛒 Buy Plan', '🏦 Deposit', '❓ Ask Question']:
            return bot.send_message(message.chat.id, "Invalid option. Select from keyboard.")
        user_action_data[user_id]['bc_mode'] = text
        user_state[user_id] = 'bc_wait_text'
        bot.send_message(message.chat.id, "Enter the TEXT for this button:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'bc_wait_text':
        user_action_data[user_id]['bc_text'] = text
        mode = user_action_data[user_id]['bc_mode']
        user_state[user_id] = 'bc_wait_data'
        if mode == '🔗 URL or Share': bot.send_message(message.chat.id, "Enter the URL (e.g. https://...):")
        elif mode == '🚀 Command': bot.send_message(message.chat.id, "Enter the exact command/button name to trigger:")
        elif mode == '❓ Ask Question':
            bot.send_message(message.chat.id, "Send an identifier or just type '0' (Admins will see standard support ticket):")
        elif mode == '🛒 Buy Plan':
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for p in bot_plans: markup.row(KeyboardButton(p))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Plan to trigger:", reply_markup=markup)
        elif mode == '🏦 Deposit':
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            for c in deposit_settings: markup.row(KeyboardButton(c))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select the Deposit currency to trigger:", reply_markup=markup)
        return

    if state == 'bc_wait_data':
        mode_map = {'🔗 URL or Share': 'url', '🚀 Command': 'command', '🛒 Buy Plan': 'buy_plan', '🏦 Deposit': 'deposit', '❓ Ask Question': 'question'}
        b_mode = mode_map[user_action_data[user_id]['bc_mode']]
        user_action_data[user_id]['broadcast']['inlines'].append({
            'text': user_action_data[user_id]['bc_text'],
            'mode': b_mode,
            'data': text
        })
        user_state[user_id] = 'admin_broadcast_action'
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row(KeyboardButton('➕ Add Inline'), KeyboardButton('✅ Proceed'))
        markup.row(KeyboardButton('❌ Cancel Action'))
        bot.send_message(message.chat.id, "✅ Button added! What next?", reply_markup=markup)
        return

    if state == 'admin_broadcast_preview' and text == '🚀 Send Broadcast':
        bc_data = user_action_data[user_id]['broadcast']
        # Prepare inline markup
        markup = InlineKeyboardMarkup()
        for b in bc_data['inlines']:
            if b['mode'] == 'url': markup.add(InlineKeyboardButton(b['text'], url=b['data']))
            elif b['mode'] == 'command': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_cmd_bc_{b['data']}"))
            elif b['mode'] == 'buy_plan': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_buy_bc_{b['data']}"))
            elif b['mode'] == 'deposit': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_dep_bc_{b['data']}"))
            elif b['mode'] == 'question': markup.add(InlineKeyboardButton(b['text'], callback_data=f"cb_question_bc_{b['data']}"))
        if not markup.keyboard: markup = None
        
        bot.send_message(message.chat.id, "🚀 Broadcast is sending in the background...", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'admin_menu'
        
        def send_bc():
            sent_count = 0
            fail_count = 0
            dead_users = []

            for uid in list(user_db.keys()):
                try:
                    lang = user_db.get(uid, {}).get('lang', 'en')
                    tl_text = get_tl_and_map(replace_macros(bc_data['text'], uid, 'root'), lang) if bc_data['text'] else None
                    
                    tl_markup = None
                    if markup:
                        tl_markup = InlineKeyboardMarkup()
                        for row in markup.keyboard:
                            tl_row = []
                            for btn in row:
                                tl_btn_text = get_tl_and_map(btn.text, lang)
                                if btn.url: tl_row.append(InlineKeyboardButton(tl_btn_text, url=btn.url))
                                else: tl_row.append(InlineKeyboardButton(tl_btn_text, callback_data=btn.callback_data))
                            tl_markup.row(*tl_row)

                    if bc_data['photo']:
                        bot.send_photo(uid, bc_data['photo'], caption=tl_text, parse_mode="HTML", reply_markup=tl_markup)
                    else:
                        bot.send_message(uid, tl_text or " ", parse_mode="HTML", reply_markup=tl_markup)
                    sent_count += 1
                except telebot.apihelper.ApiTelegramException as e:
                    if 'Forbidden' in str(e) or 'chat not found' in str(e) or 'deactivated' in str(e):
                        fail_count += 1
                        dead_users.append(uid)
                except Exception:
                    fail_count += 1
                time.sleep(0.05) # Prevent flood wait
                
            for d in dead_users:
                user_db.pop(d, None)
                if d in blocked_users: blocked_users.remove(d)
                
            bot.send_message(message.chat.id, f"<b>Broadcast Complete.</b>\n✅ Delivered: {sent_count} | ❌ Failed (Blocked/Deleted): {fail_count}", parse_mode="HTML")
            
        threading.Thread(target=send_bc, daemon=True).start()
        return

    # --- FEATURE 2: ADVANCED STATS & WIPE SYSTEM HANDLERS ---
    if state == 'admin_menu' and text == '📊 Bot Stats':
        bot_info = bot.get_me()
        total_users = len(user_db)
        btn_count = len(btn_metadata)
        msg_count = sum(len(v) for v in menu_posts.values())
        
        stats_msg = (
            f"📊 <b>BOT STATISTICS</b>\n"
            f"#statistics\n\n"
            f"@{bot_info.username}\n"
            f"▪️Created: [Auto]\n\n"
            f"▪️Users: {total_users}\n"
            f"▫️Active: {total_users}\n"
            f"▫️Deleted: 0\n"
            f"▪️Admins: {len(ADMIN_IDS)}\n\n"
            f"▪️Bot structure:\n"
            f"▫️Buttons: {btn_count} / 200\n"
            f"▫️Messages: {msg_count} / 400"
        )
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('🔍 Scan', callback_data='cb_scan_users'))
        
        bot.send_message(message.chat.id, stats_msg, parse_mode="HTML", reply_markup=markup)
        return

    # --- NEW: REFERRAL LINK GENERATION INLINE ---
    if call.data == 'cb_gen_ref_link':
        bot.answer_callback_query(call.id)
        bot_info = bot.get_me()
        
        # FEATURE 3: DYNAMIC INVITE LINKS TOGGLE
        if invite_settings.get('use_dynamic_link', False):
            username_clean = call.from_user.username
            if username_clean:
                ref_id = f"gf_{username_clean}"
            else:
                ref_id = f"gf_{user_id}_{str(uuid.uuid4())[:4]}"
                
            # Save to memory bank so old links stay active forever
            if ref_id not in user_db[user_id].get('invite_links_map', []):
                if 'invite_links_map' not in user_db[user_id]: user_db[user_id]['invite_links_map'] = []
                user_db[user_id]['invite_links_map'].append(ref_id)
        else:
            ref_id = str(user_id)
            
        ref_link = f"https://t.me/{bot_info.username}?start={ref_id}"
        
        if invite_settings.get('use_loading_bar', True):
            style_opt = global_ui_settings.get('loading_bar_style', '1')
            frames = {
                '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
                '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
                '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
            }
            bars = frames.get(str(style_opt), frames['1'])
            
            loading_msg = bot.send_message(call.message.chat.id, get_tl_and_map(f"⏳ <b>Generating Unique Link...</b>\n{bars[0]}", lang), parse_mode="HTML")
            for bar in bars[1:]:
                time.sleep(0.4)
                try: bot.edit_message_text(get_tl_and_map(f"⏳ <b>Generating Unique Link...</b>\n{bar}", lang), call.message.chat.id, loading_msg.message_id, parse_mode="HTML")
                except: pass
                
            try: bot.delete_message(call.message.chat.id, loading_msg.message_id)
            except: pass
            
        bot.send_message(call.message.chat.id, get_tl_and_map(f"✅ <b>Your Unique Referral Link:</b>\n\n{ref_link}", lang), parse_mode="HTML")
        return

    # --- NEW: SUPPORT QUESTION INLINE BUTTON ---
    if call.data.startswith('cb_question_'):
        bot.answer_callback_query(call.id)
        user_state[user_id] = 'wait_support_msg'
        bot.send_message(call.message.chat.id, get_tl_and_map("💬 <b>Support Desk</b>\n\nPlease type your message below. An administrator will reply as soon as possible.", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    # --- ADMIN SUPPORT REPLY BUTTON ---
    if call.data.startswith('cb_suprep_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        target_uid = call.data.replace('cb_suprep_', '')
        user_state[user_id] = f'admin_suprep_{target_uid}'
        bot.send_message(call.message.chat.id, f"Type your reply to User <code>{target_uid}</code>. It will be sent anonymously as 'Support'.", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return bot.answer_callback_query(call.id)

    # --- NEW: TRANSACTION PAGINATION INLINE ---
    if call.data.startswith('cb_txpage_'):
        page = int(call.data.replace('cb_txpage_', ''))
        txs = user_db.get(user_id, {}).get('transactions', [])
        if not txs:
            return bot.answer_callback_query(call.id, get_tl_and_map("No transactions found.", lang), show_alert=True)
        
        txs_reversed = txs[::-1]
        limit = 7
        start_idx = page * limit
        end_idx = start_idx + limit
        current_txs = txs_reversed[start_idx:end_idx]
        
        msg = f"📜 <b>Your Transaction History (Page {page + 1}):</b>\n\n"
        for tx in current_txs:
            msg += f"🗓 <code>{tx['date']}</code>\n🔹 <b>{tx['type']}</b> | <b>${tx['amount']:.2f}</b>\n\n"
        
        markup = InlineKeyboardMarkup()
        btns = []
        if page > 0:
            btns.append(InlineKeyboardButton(get_tl_and_map('⬅️ Previous', lang), callback_data=f'cb_txpage_{page - 1}'))
        if end_idx < len(txs_reversed):
            btns.append(InlineKeyboardButton(get_tl_and_map('Next ➡️', lang), callback_data=f'cb_txpage_{page + 1}'))
        
        if btns:
            markup.row(*btns)
        
        try:
            bot.edit_message_text(get_tl_and_map(msg, lang), call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup if btns else None)
        except Exception:
            pass
        return bot.answer_callback_query(call.id)

    # --- NEW: ADMIN BROADCAST INLINE COMMANDS ---
    if call.data.startswith('cb_cmd_bc_'):
        cmd = call.data.replace('cb_cmd_bc_', '')
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        msg = call.message
        msg.from_user = call.from_user
        msg.text = cmd
        handle_messages(msg)
        return bot.answer_callback_query(call.id)
        
    elif call.data.startswith('cb_buy_bc_'):
        plan = call.data.replace('cb_buy_bc_', '')
        if plan in bot_plans:
            execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan)
        return bot.answer_callback_query(call.id)
        
    elif call.data.startswith('cb_dep_bc_'):
        curr = call.data.replace('cb_dep_bc_', '')
        if curr in deposit_settings:
            user_action_data[user_id] = {'currency': curr}
            user_state[user_id] = 'dep_wait_amount'
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception: pass
            bot.send_message(call.message.chat.id, get_tl_and_map(deposit_settings[curr]['msg_enter'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return bot.answer_callback_query(call.id)
        
    elif call.data.startswith('cb_question_bc_'):
        bot.answer_callback_query(call.id)
        user_state[user_id] = 'wait_support_msg'
        bot.send_message(call.message.chat.id, get_tl_and_map("💬 <b>Support Desk</b>\n\nPlease type your message below. An administrator will reply as soon as possible.", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return
        
    elif call.data == 'cb_reinv_dep_menu':
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        dep_markup = InlineKeyboardMarkup()
        for c in deposit_settings:
            dep_markup.add(InlineKeyboardButton(c.replace('_', ' '), callback_data=f"cb_dep_{c}"))
        bot.send_message(call.message.chat.id, get_tl_and_map("Select a currency to deposit:", lang), reply_markup=dep_markup)
        bot.answer_callback_query(call.id)
        return

    # --- NEW: UNBLOCK USER INLINE BUTTON ---
    if call.data.startswith('cb_unblock_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        target_id = int(call.data.replace('cb_unblock_', ''))
        
        if target_id in blocked_users:
            blocked_users.remove(target_id)
            bot.answer_callback_query(call.id, f"✅ User {target_id} successfully unblocked.", show_alert=True)
            
            # Notify the unblocked user
            target_lang = user_db.get(target_id, {}).get('lang', 'en')
            try: bot.send_message(target_id, get_tl_and_map(block_settings['msg_unblock'], target_lang), parse_mode="HTML")
            except: pass
            
            # Refresh the inline menu list
            if not blocked_users:
                bot.edit_message_text("All users are now unblocked.", call.message.chat.id, call.message.message_id)
            else:
                markup = InlineKeyboardMarkup()
                for buid in blocked_users:
                    uname = user_db.get(buid, {}).get('first_name', 'Unknown')
                    markup.row(InlineKeyboardButton(f"✅ Unblock {uname} ({buid})", callback_data=f"cb_unblock_{buid}"))
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, "User is not currently blocked.", show_alert=True)
        return

    # --- NEW: ADMIN WITHDRAWAL NOTIFICATION INLINES ---
    if call.data.startswith('cb_wad_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        parts = call.data.split('_')
        action = parts[2] # 'app', 'dec', 'ign'
        mode = parts[3] # 's' (silent), 'm' (message)
        w_id = parts[4]
        
        if 'pending_withdrawals' not in globals() or w_id not in pending_withdrawals:
            return bot.answer_callback_query(call.id, "Withdrawal no longer pending or expired.", show_alert=True)
            
        w_data = pending_withdrawals.pop(w_id)
        target = w_data['user_id']
        amt = w_data['amount']
        w_var = w_data['currency_var']
        target_lang = user_db.get(target, {}).get('lang', 'en')
        
        if action == 'app':
            log_tx(target, "Withdrawal Approved", 0) 
            bot.edit_message_text(f"{call.message.text}\n\n✅ <b>APPROVED ({'Silent' if mode=='s' else 'Msg sent'})</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            
            if mode == 'm':
                msg_template = global_w_setup.get('w_msg_approve')
                if msg_template:
                    
                    # --- FIX: HARD OVERRIDE OLD DB MESSAGE IF ASCII TOGGLE IS ON ---
                    if global_w_setup.get('use_ascii_receipt', False):
                        msg_template = "%ascii_receipt%"
                        
                    msg = replace_macros(msg_template, target, w_data['path'], w_data)
                    
                    # FEATURE 2: Attach Native Telegram Popup Button
                    payout_markup = InlineKeyboardMarkup()
                    btn_text = global_w_setup.get('payout_btn_text', '📜 View Receipt')
                    payout_markup.row(InlineKeyboardButton(get_tl_and_map(btn_text, target_lang), callback_data='cb_payout_popup_alert'))
                    
                    try: bot.send_message(target, get_tl_and_map(msg, target_lang), parse_mode="HTML", reply_markup=payout_markup)
                    except: pass
            
            pub_chat = global_w_setup.get('public_report')
            if pub_chat:
                try:
                    pub_msg = f"💸 <b>SUCCESSFUL WITHDRAWAL</b> 💸\n\n👤 User: {user_db.get(target, {}).get('first_name', 'Unknown')}\n💰 Amount: {fmt_amt(amt)}\n🌐 Network: {w_data['network']}\n🔗 Address: {w_data['address'][:6]}...{w_data['address'][-4:]}"
                    bot.send_message(pub_chat, pub_msg, parse_mode="HTML")
                except: pass

        elif action == 'dec':
            if target in user_db:
                user_db[target][w_var] = user_db[target].get(w_var, 0) + amt
                user_db[target]['total_withdrawn'] = max(0, user_db[target].get('total_withdrawn', 0.0) - amt)
                log_tx(target, "Withdrawal Refunded", amt)
                
            bot.edit_message_text(f"{call.message.text}\n\n❌ <b>DECLINED (Refunded to user)</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            
            if mode == 'm':
                msg_template = global_w_setup.get('w_msg_decline')
                if msg_template:
                    msg = replace_macros(msg_template, target, w_data['path'], w_data)
                    try: bot.send_message(target, get_tl_and_map(msg, target_lang), parse_mode="HTML")
                    except: pass

        elif action == 'ign':
            bot.edit_message_text(f"{call.message.text}\n\n🚫 <b>IGNORED (No Refund)</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            if mode == 'm':
                msg_template = global_w_setup.get('w_msg_ignore')
                if msg_template:
                    msg = replace_macros(msg_template, target, w_data['path'], w_data)
                    try: bot.send_message(target, get_tl_and_map(msg, target_lang), parse_mode="HTML")
                    except: pass
        
        return bot.answer_callback_query(call.id, "Action executed successfully.")


    # --- ON-DEMAND DEPOSIT BLOCKCHAIN SCAN ---
    if call.data.startswith('cb_depcheck_'):
        try: bot.answer_callback_query(call.id, get_tl_and_map("Checking the blockchain network...", lang))
        except: pass
        
        curr = call.data.replace('cb_depcheck_', '')
        addr = user_db[user_id].get('wallets', {}).get(curr, {}).get('address')
        
        if not addr:
            return bot.send_message(call.message.chat.id, get_tl_and_map("⚠️ Wallet not found.", lang))
            
        style_opt = global_ui_settings.get('loading_bar_style', '1')
        
        frames = {
            '1': ["[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■■■] 100%"],
            '2': ["▓▓░░░░░░░░ 20%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
            '3': ["██▒▒▒▒▒▒▒▒ 20%", "██████▒▒▒▒ 60%", "██████████ 100%"]
        }
        bar_styles = frames.get(str(style_opt), frames['1'])
        
        scan_msg = bot.send_message(call.message.chat.id, get_tl_and_map(f"⏳ <b>Checking Blockchain...</b>\n[▯▯▯▯▯▯▯▯▯▯] 0%", lang), parse_mode="HTML")
        
        for bar in bar_styles:
            time.sleep(0.4) 
            try: bot.edit_message_text(get_tl_and_map(f"⏳ <b>Checking Blockchain...</b>\n{bar}", lang), call.message.chat.id, scan_msg.message_id, parse_mode="HTML")
            except: pass

        found_deposit, crypto_amount, txid_found, _ = check_address_for_new_deposit(addr, curr)
        
        if found_deposit:
            processed_txids.add(txid_found)
            pending_auto_txids.pop(txid_found, None) # NEW: Stop the auto-timer if they manually clicked!
            
            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
            usd_value = crypto_amount * live_price
            
            user_db[user_id]['deposit'] += usd_value
            user_db[user_id]['wallets'][curr]['total_deposited'] = user_db[user_id]['wallets'][curr].get('total_deposited', 0.0) + usd_value
            log_tx(user_id, f"Deposit ({curr})", usd_value)
            
            process_referral_commission(user_id, usd_value, is_deposit=True) # NEW: Referral Commission
            
            admin_msg = f"🟢 <b>DEPOSIT CONFIRMED (MANUAL)</b>\nUser: <code>{user_id}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}\nHash (TXID): <code>{txid_found}</code>"
            for admin in ADMIN_IDS:
                try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                except Exception: pass
                
            check_and_trigger_auto_buy(user_id)
            
            try: bot.send_message(call.message.chat.id, get_tl_and_map(f"✅ <b>Deposit Successful!</b>\nAmount: {fmt_amt(crypto_amount)} {curr.split('_')[0]}\nCredited: ${fmt_amt(usd_value)}", lang), parse_mode="HTML")
            except: pass
            
        else:
            try: bot.send_message(call.message.chat.id, get_tl_and_map(f"⏳ <b>Pending:</b> Your transaction is still waiting for blockchain confirmation. Please wait a moment and click Confirm again.", lang), parse_mode="HTML")
            except: pass
            
        try: bot.delete_message(call.message.chat.id, scan_msg.message_id)
        except: pass
        return

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
            bot.answer_callback_query(call.id, get_tl_and_map(f"⚠️ Insufficient balance. You need at least ${fmt_amt(p_data['min'])}.", lang), show_alert=True)
            
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
        bot.send_message(call.message.chat.id, get_tl_and_map(f"📈 <b>{p_data['name']}</b>\nMin: ${fmt_amt(p_data['min'])} | Max: ${fmt_amt(p_data['max'])}\n\nAvailable Balance: ${fmt_amt(total_avail)}\n\nEnter the amount you wish to invest:", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
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
            
            process_referral_commission(target, amt, is_deposit=True) # NEW: Referral Commission
            
            msg_success = conf.get('msg_success', "✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.")
            msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(amt)}").replace('%crypto_amount%', '')
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
            bot.send_message(target, get_tl_and_map(f"❌ <b>Deposit Rejected</b>\nYour deposit request for <b>${fmt_amt(dep['amount'])}</b> could not be verified.", target_lang), parse_mode="HTML")
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
            bot.send_message(call.message.chat.id, f"Send the new text (image will be kept):\n\nℹ️ <b>Current Text:</b>\n\n{curr_txt}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif action == 'repall':
            user_state[user_id] = 'posts_rep_all'
            user_action_data[user_id] = {'post_id': post_id}
            post = next((p for p in menu_posts.get(current_path, []) if p['id'] == post_id), None)
            curr_txt = post['text'] if post else ""
            bot.send_message(call.message.chat.id, f"Send the new message (text or photo):\n\nℹ️ <b>Current Text:</b>\n\n{curr_txt}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
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
            markup.row(KeyboardButton('❓ Ask Question'))
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
            markup.row(KeyboardButton('❓ Ask Question'))
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
            
            amount = data['amount']
            w_var = global_w_setup.get('w_var', 'balance')
            
            # Deduct balance
            user_db[user_id][w_var] -= amount
            user_db[user_id]['total_withdrawn'] = user_db[user_id].get('total_withdrawn', 0.0) + amount
            log_tx(user_id, "Withdrawal Pending", -amount)
            
            # Delete confirm inline msg FIRST
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass

            # Send Processing message (Now with %loading_bar% support!)
            proc_msg = global_w_setup.get('w_msg_processing', '♻️ Your Withdrawal of %withdraw% is processing on the blockchain...')
            raw_text = get_tl_and_map(replace_macros(proc_msg, user_id, data['path'], data), lang)
            
            match = re.search(r'%loading_bar(?:_(\d+(?:\.\d+)?)s)?%', raw_text)
            if match:
                total_loading_time = float(match.group(1)) if match.group(1) else float(global_ui_settings.get('loading_bar_time', 3.0))
                part_a = raw_text[:match.start()].strip()
                part_b = raw_text[match.end():].strip()
                
                style = global_ui_settings.get('loading_bar_style', '1')
                bars = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "░░░░░░░░░░ 0%", "▒▒▒▒▒▒▒▒▒▒ 0%"]
                initial_bar = bars[int(style)-1] if style in ['1', '2', '3'] else bars[0]
                
                sep = "\n\n" if part_a else ""
                temp_msg_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{initial_bar}"
                
                temp_msg = bot.send_message(call.message.chat.id, temp_msg_text, parse_mode="HTML")
                execute_loading_animation(call.message.chat.id, temp_msg.message_id, part_a, style, False, total_loading_time)
                
                final_text = part_a + ("\n\n" if part_a and part_b else "") + part_b
                if final_text:
                    bot.send_message(call.message.chat.id, final_text, parse_mode="HTML", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(call.message.chat.id, raw_text, parse_mode="HTML", reply_markup=get_keyboard(user_id))
            
            user_state[user_id] = 'normal'
            
            # Add to pending global dictionary
            w_id = str(uuid.uuid4())[:8]
            
            if 'pending_withdrawals' not in globals():
                pending_withdrawals = {}
            
            # Retrieve the correct address/network depending on if it was manual or pre-set
            addr = data.get('address', user_db[user_id].get('wallet', 'Unknown'))
            net = data.get('network', user_db[user_id].get('wallet_net', 'Unknown'))
            comm_pct = global_w_setup.get('w_commission', 0.0)
            final_amt = amount - (amount * (comm_pct / 100.0))
            
            pending_withdrawals[w_id] = {
                'user_id': user_id, 'amount': amount, 'final_amt': final_amt,
                'address': addr, 'network': net, 'currency_var': w_var,
                'path': data['path']
            }
            
            # Build Admin Inline Keyboard
            adm_markup = InlineKeyboardMarkup()
            adm_markup.row(
                InlineKeyboardButton('Approve ✅', callback_data=f'cb_wad_app_s_{w_id}'),
                InlineKeyboardButton('Decline', callback_data=f'cb_wad_dec_s_{w_id}'),
                InlineKeyboardButton('Ignore', callback_data=f'cb_wad_ign_s_{w_id}')
            )
            adm_markup.row(
                InlineKeyboardButton('Approve 🗒️', callback_data=f'cb_wad_app_m_{w_id}'),
                InlineKeyboardButton('Decline 🗒️', callback_data=f'cb_wad_dec_m_{w_id}'),
                InlineKeyboardButton('Ignore 🗒️', callback_data=f'cb_wad_ign_m_{w_id}')
            )
            
            admin_alert = (
                f"🚨 <b>NEW WITHDRAWAL REQUEST</b> 🚨\n\n"
                f"👤 User: <code>{user_id}</code> (@{call.from_user.username or 'None'})\n"
                f"💰 Requested: <b>{fmt_amt(amount)}</b>\n"
                f"💸 Final (after {comm_pct}% comm): <b>{fmt_amt(final_amt)}</b>\n"
                f"🔗 Address: <code>{addr}</code>\n"
                f"🌐 Network: {net}\n"
                f"🗃 Variable: {w_var}"
            )
            
            for admin in ADMIN_IDS:
                try: bot.send_message(admin, admin_alert, parse_mode="HTML", reply_markup=adm_markup)
                except: pass
                
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
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b""
        
        try:
            data = json.loads(post_data)
        except:
            data = {}
            
        pin = data.get('pin', '')

        if parsed_path.path == '/api/verify_pin':
            if pin == ADMIN_PIN:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            else:
                self.send_response(401)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Invalid PIN'}).encode())
                
        elif parsed_path.path == '/api/get_wallets':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            wallets_list = []
            total_usd = 0.0
            
            for uid, udata in user_db.items():
                for curr, wdata in udata.get('wallets', {}).items():
                    deposited = wdata.get('total_deposited', 0.0)
                    swept = wdata.get('admin_swept_total', 0.0)
                    pending = deposited - swept
                    
                    if pending > 0:
                        username = udata.get('username', str(uid))
                        if username == 'No Username': username = str(uid)
                        
                        wallets_list.append({
                            'uid': uid,
                            'username': username,
                            'network': curr.replace('_', ' '),
                            'address': wdata.get('address', ''),
                            'amount': f"{fmt_amt(pending)} {curr.split('_')[0]}",
                            'time': "Active"
                        })
                        
                        live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
                        total_usd += (pending * live_price)
                        
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'wallets': wallets_list, 'total_usd': total_usd}).encode())

        elif parsed_path.path == '/api/get_private_key':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            uid = int(data.get('uid'))
            network = data.get('network').replace(' ', '_')
            
            pk = user_db.get(uid, {}).get('wallets', {}).get(network, {}).get('private_key', 'Not Found')
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'private_key': pk}).encode())

        elif parsed_path.path == '/api/mark_swept':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            uid = int(data.get('uid'))
            network = data.get('network').replace(' ', '_')
            
            if uid in user_db and network in user_db[uid].get('wallets', {}):
                wdata = user_db[uid]['wallets'][network]
                wdata['admin_swept_total'] = wdata.get('total_deposited', 0.0)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            else:
                self.send_response(400)
                self.end_headers()

        elif parsed_path.path == '/api/get_admins':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'admins': ADMIN_IDS}).encode())

        elif parsed_path.path == '/api/add_admin':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
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
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
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

        # --- NEW FEATURE 1: WALLET REGISTRY API ---
        elif parsed_path.path == '/api/wallet_registry':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            registry = []
            for uid, udata in user_db.items():
                username = udata.get('username', str(uid))
                first_name = udata.get('first_name', 'Unknown')
                display_name = f"{first_name} (@{username})" if username != 'No Username' else first_name
                
                w_addr = udata.get('wallet', 'Not Set')
                w_net = udata.get('wallet_net', 'Not Set')
                
                if w_addr != 'Not Set':
                    registry.append({
                        'uid': uid,
                        'name': display_name,
                        'network': w_net,
                        'address': w_addr
                    })
                    
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'registry': registry}).encode())

        # --- UPDATED: 3-POINT RESOURCE METRICS (CPU, RAM, DISK) ---
        elif parsed_path.path == '/api/server_stats':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            stats = {
                'aiven_storage': {'used_mb': 0, 'total_mb': 1024}, # Your 1GB Aiven Disk
                'bot_ram': {'used_mb': 0, 'total_mb': 1024},       # Your 1GB Northflank RAM
                'bot_cpu': {'percent': 0}                         # Your 1 CPU Core
            }
            
            # 1. Measure Aiven Storage (Disk)
            if DATABASE_URL:
                try:
                    conn = psycopg2.connect(DATABASE_URL)
                    cur = conn.cursor()
                    cur.execute("SELECT pg_database_size(current_database());")
                    size_bytes = cur.fetchone()[0]
                    cur.close()
                    conn.close()
                    stats['aiven_storage']['used_mb'] = round(size_bytes / (1024 * 1024), 2)
                except: pass

            # 2. Measure Bot RAM (Memory)
            try:
                # Direct read from Northflank/Linux container memory
                with open('/sys/fs/cgroup/memory.current', 'r') as f:
                    ram_bytes = int(f.read().strip())
                stats['bot_ram']['used_mb'] = round(ram_bytes / (1024 * 1024), 2)
            except:
                # Fallback for local testing
                stats['bot_ram']['used_mb'] = round(psutil.virtual_memory().used / (1024 * 1024), 2)

            # 3. Measure Bot CPU (Brain Power)
            stats['bot_cpu']['percent'] = psutil.cpu_percent(interval=None)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'stats': stats}).encode())

            # 2. Fetch Northflank RAM Usage
            if NORTHFLANK_API_KEY and NORTHFLANK_PROJECT:
                try:
                    headers = {"Authorization": f"Bearer {NORTHFLANK_API_KEY}"}
                    url = f"https://api.northflank.com/v1/projects/{NORTHFLANK_PROJECT}/services"
                    resp = requests.get(url, headers=headers, timeout=5)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        services = data.get('data', {}).get('services', [])
                        
                        if services:
                            # 🧠 THE FIX: Read the exact RAM directly from the Linux server!
                            try:
                                # Standard Northflank / Docker container memory (cgroup v2)
                                with open('/sys/fs/cgroup/memory.current', 'r') as f:
                                    ram_bytes = int(f.read().strip())
                            except FileNotFoundError:
                                try:
                                    # Fallback for older Linux containers (cgroup v1)
                                    with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                                        ram_bytes = int(f.read().strip())
                                except FileNotFoundError:
                                    ram_bytes = 0 # Safety net if testing on Windows
                                    
                            stats['northflank']['used_mb'] = round(ram_bytes / (1024 * 1024), 2)
                            stats['northflank']['total_mb'] = 512.00 # Standard Northflank free tier limit
                            stats['northflank']['status'] = 'Active'
                        else:
                            stats['northflank']['status'] = 'No Services Found'
                    else:
                        print(f"❌ Northflank API Error: {resp.status_code} - {resp.text}")
                        stats['northflank']['status'] = f"API Error {resp.status_code}"
                except Exception as e:
                    print(f"❌ Northflank Connection Error: {e}")
                    stats['northflank']['status'] = 'Connection Error'
            else:
                stats['northflank']['status'] = 'Missing API Keys'

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'stats': stats}).encode())

        # --- Catch-all 404 (MUST BE AT THE VERY BOTTOM OF do_POST) ---
        else:
            self.send_response(404)
            self.end_headers()

def run_web_server():
    """Runs the HTTP server silently in the background."""
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), AdminDashboardHandler)
    print(f"🌐 Web server running on port {port} for UptimeRobot & Admin Dashboard.")
    server.serve_forever()

# --- TRUE BACKGROUND HOURLY ALERTS (FIX APPLIED HERE) ---
def background_accruals_loop():
    """Runs continuously in the background to send hourly alerts exactly when due, even if user is AFK."""
    while True:
        try:
            for uid in list(user_db.keys()):
                process_accruals(uid)
        except Exception as e:
            print(f"Background Accrual Error: {e}")
        time.sleep(60) # Scans every 60 seconds independently

if __name__ == '__main__':
    # Start the Background Accruals Engine (True Hourly Alerts)
    print("🕒 Starting background accruals and alert thread...")
    threading.Thread(target=background_accruals_loop, daemon=True).start()

    # Start the Web Server (Required for Render and Dashboard)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Start the Blockchain Scanner (Now with 5-minute patience!)
    print("👀 Starting background watcher thread...")
    threading.Thread(target=blockchain_watcher_loop, daemon=True).start()

    # Start the Auto-Save Database Thread
    print("💾 Starting JSON database auto-save thread...")
    threading.Thread(target=auto_save_loop, daemon=True).start()
    
    # Start the Telegram Bot
    print("🚀 Bot is running fast! Press Ctrl+C to stop.")
    bot.infinity_polling(skip_pending=True)
