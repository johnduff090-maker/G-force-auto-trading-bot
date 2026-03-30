import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import uuid
import time
import os
import threading
import requests
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from dotenv import load_dotenv
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes

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
            ADMIN_IDS.append(int(x.strip()))

print(f"👑 RECOGNIZED ADMIN IDs: {ADMIN_IDS}")
print("="*40 + "\n")

MASTER_SEED = os.getenv('MASTER_SEED_PHRASE', '')
if MASTER_SEED:
    MASTER_SEED = MASTER_SEED.replace('"', '').replace("'", "")

# API KEYS FOR BLOCKCHAIN TRACKING
TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')

# --- DYNAMIC MEMORY & STATE ---
menus = {'root': []}
menu_posts = {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]}

user_current_path = {}
user_state = {} 
user_selected_button = {} 
user_clipboard = {}        

# User Database
user_db = {}
user_action_data = {} 
btn_metadata = {}
editor_msg_ids = {}

# --- ADMIN TRACKERS ---
admin_bal_type = {}            
admin_bal_notify = {}          
admin_bal_comment_on = {}      
admin_bal_target = {}          
admin_bal_comment_text = {}    
bot_plans = {}                
user_plan_setup = {}          

# --- DEPOSIT ENGINE SETTINGS ---
pending_deposits = {}
admin_dep_setup = {}

# Expanded to include min, max, pending, and success messages
deposit_settings = {
    'USDT_TRC20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT TRC20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly `%crypto_amount%` USDT to:\n\n`%address%`\n\n_The system is monitoring the blockchain and will credit you automatically._', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.'},
    'USDT_BEP20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT BEP20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly `%crypto_amount%` USDT to:\n\n`%address%`\n\n_The system is monitoring the blockchain and will credit you automatically._', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.'},
    'USDT_ERC20': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 10.0, 'max': 10000.0, 'msg_enter': 'Enter amount of USDT ERC20 (in USD) to deposit:', 'msg_instruct': 'Please send exactly `%crypto_amount%` USDT to:\n\n`%address%`\n\n_The system is monitoring the blockchain and will credit you automatically._', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.'},
    'TRX': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 5.0, 'max': 10000.0, 'msg_enter': 'Enter amount of TRX (in USD) to deposit:', 'msg_instruct': 'Please send exactly `%crypto_amount%` TRX to:\n\n`%address%`\n\n_The system is monitoring the blockchain and will credit you automatically._', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.'},
    'BTC': {'mode': 'auto', 'address': 'Not Set', 'hd_key': 'Not Set', 'min': 50.0, 'max': 50000.0, 'msg_enter': 'Enter amount of BTC (in USD) to deposit:', 'msg_instruct': 'Please send exactly `%crypto_amount%` BTC to:\n\n`%address%`\n\n_The system is monitoring the blockchain and will credit you automatically._', 'msg_pending': '✅ Your deposit request for $%usd_amount% has been submitted to the administrators.', 'msg_success': '✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.'}
}

# --- NEW: SYSTEM PLANS INITIALIZATION ---
if not bot_plans:
    for i in range(6):
        bot_plans[f'plan{i}'] = {
            'name': f'Plan {i}', 'min': 10.0, 'max': 1000.0, 'length': 24.0, 'profit': 5.0,
            'text': f'✨ **Plan {i} Description** ✨\n\nEdit this in Admin -> Plans.',
            'photo': None, 'inline_text': '🛒 Purchase Plan'
        }

processed_txids = set() # Stores Hashes to prevent double-crediting

def get_default_metadata():
    return {
        'random_message': False,
        'admin_only': False,
        'invisible': False,
        'command': None,
        'move_by_command': False,
        'do_not_ask_address': False,
        'bonus': False,
        'withdrawal': False,
        'w_var': None,
        'w_min': None,
        'w_max': None,
        'w_msg_enter': None,
        'w_msg_addr': None,
        'w_msg_conf': None,
        'row_idx': 0,
        'assigned_plan': None # NEW: Maps a button directly to a Plan
    }

def init_user_db(message):
    user_id = message.from_user.id
    if user_id not in user_db:
        user_db[user_id] = {
            'balance': 1000.00, 'bonus': 500.00, 'deposit': 200.00, 
            'hourly': 0.00, 'plan': 0.00, 'address': 'Not Set',
            'first_name': message.from_user.first_name or 'Unknown',
            'last_name': message.from_user.last_name or '',
            'username': message.from_user.username or 'No Username',
            'active_plans': [], 
            'pending_plan': None,
            'wallets': {} # Store generated HD wallets here
        }
    else:
        user_db[user_id]['first_name'] = message.from_user.first_name or 'Unknown'
        user_db[user_id]['last_name'] = message.from_user.last_name or ''
        user_db[user_id]['username'] = message.from_user.username or 'No Username'
        if 'active_plans' not in user_db[user_id]: user_db[user_id]['active_plans'] = []
        if 'pending_plan' not in user_db[user_id]: user_db[user_id]['pending_plan'] = None
        if 'wallets' not in user_db[user_id]: user_db[user_id]['wallets'] = {}

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
        # Bulletproof fallbacks if CoinGecko blocks the IP
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
        
        # Select correct derivation path based on currency
        if currency == 'BTC':
            coin_type = Bip44Coins.BITCOIN
        elif 'TRC20' in currency or currency == 'TRX':
            coin_type = Bip44Coins.TRON
        else:
            # BEP20 and ERC20 use standard Ethereum derivation
            coin_type = Bip44Coins.ETHEREUM

        bip44_mst = Bip44.FromSeed(seed_bytes, coin_type)
        
        # We use user_id % 2147483647 to ensure the index is within the valid range for hardened derivation
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
                    
                    # --- TRACKING TRON NETWORK (TRX & USDT TRC20) ---
                    if curr in ['TRX', 'USDT_TRC20']:
                        headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
                        
                        if curr == 'USDT_TRC20':
                            # Scan for TRC20 Token Transfers
                            url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20"
                        else:
                            # Scan for raw TRX Transfers
                            url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions"
                        
                        resp = requests.get(url, headers=headers, timeout=10)
                        if resp.status_code == 200:
                            txs = resp.json().get('data', [])
                            for tx in txs:
                                txid = tx.get('transaction_id') or tx.get('txID')
                                
                                # HASH CHECK: Skip if we already credited this
                                if txid in processed_txids:
                                    continue
                                    
                                # Validate it's incoming to the user's generated address
                                is_incoming = False
                                crypto_amount = 0.0
                                
                                if curr == 'USDT_TRC20':
                                    if tx.get('token_info', {}).get('address') == USDT_TRC20_CONTRACT and tx.get('to') == addr:
                                        is_incoming = True
                                        # USDT has 6 decimals on Tron
                                        crypto_amount = float(tx.get('value', 0)) / 1_000_000
                                elif curr == 'TRX':
                                    if tx.get('raw_data', {}).get('contract', [{}])[0].get('parameter', {}).get('value', {}).get('to_address') == addr:
                                        is_incoming = True
                                        # TRX has 6 decimals
                                        crypto_amount = float(tx['raw_data']['contract'][0]['parameter']['value'].get('amount', 0)) / 1_000_000
                                
                                # AUTO APPROVAL & USD CONVERSION
                                if is_incoming and crypto_amount > 0:
                                    processed_txids.add(txid)
                                    
                                    live_price = get_crypto_price(curr) or 1.0
                                    usd_value = crypto_amount * live_price
                                    
                                    # Credit the User
                                    user_db[uid]['deposit'] += usd_value
                                    
                                    # Notifications
                                    try:
                                        conf = deposit_settings[curr]
                                        msg_success = conf.get('msg_success', "✅ **Deposit Detected!**\n\nThe blockchain confirmed a deposit of **%crypto_amount% %currency%**.\n**$%usd_amount% USD** has been automatically added to your balance!")
                                        msg_success = msg_success.replace('%usd_amount%', f"{usd_value:.2f}").replace('%crypto_amount%', f"{crypto_amount:.2f}").replace('%currency%', curr.replace('_', ' '))
                                        bot.send_message(uid, msg_success, parse_mode="Markdown")
                                    except Exception: pass
                                    
                                    admin_msg = f"🟢 **AUTO-DEPOSIT APPROVED**\nUser: `{uid}`\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {crypto_amount}\nUSD Credited: ${usd_value:.2f}\nHash (TXID): `{txid}`"
                                    for admin in ADMIN_IDS:
                                        try: bot.send_message(admin, admin_msg, parse_mode="Markdown")
                                        except Exception: pass
                                        
                                    # Trigger Auto-Buy if they were waiting for a plan
                                    check_and_trigger_auto_buy(uid)

                    # --- ADD TRACKING FOR ERC20 / BEP20 / BTC HERE LATER ---

        except Exception as e:
            pass # Suppress background errors so it doesn't interrupt the bot
        
        # Pause for 30 seconds before checking the blockchain again
        time.sleep(30)

# --- UNIVERSAL AUTO-BUY ENGINE ---
def check_and_trigger_auto_buy(user_id):
    if not user_db[user_id].get('pending_plan'): return
    p_macro = user_db[user_id]['pending_plan']
    if p_macro in bot_plans:
        p_data = bot_plans[p_macro]
        if user_db[user_id]['deposit'] >= p_data['min']:
            invest_amt = min(user_db[user_id]['deposit'], p_data['max'])
            user_db[user_id]['deposit'] -= invest_amt
            
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
                bot.send_message(user_id, f"🎉 **Auto-Purchase Successful!**\n\nYour deposit triggered your pending plan.\n**{p_data['name']}** is now active with an investment of **${invest_amt:.2f}**!", parse_mode="Markdown")
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
    meta = btn_metadata.get(full_path, get_default_metadata())
    
    t = text.replace('%userid%', str(user_id))
    t = t.replace('%username%', bals.get('username', 'Unknown'))
    t = t.replace('%firstname%', bals.get('first_name', 'Unknown'))
    t = t.replace('%lastname%', bals.get('last_name', ''))
    t = t.replace('%balance%', f"{bals.get('balance', 0):.2f}")
    t = t.replace('%bonus%', f"{bals.get('bonus', 0):.2f}")
    t = t.replace('%deposit%', f"{bals.get('deposit', 0):.2f}")
    
    t = t.replace('%min%', str(meta.get('w_min') or 0))
    t = t.replace('%max%', str(meta.get('w_max') or 'No Limit'))
    
    if '%my_plans%' in t:
        plans_str = ""
        active = [p for p in bals.get('active_plans', []) if p['status'] == 'active']
        if not active:
            plans_str = "_(No active plans)_"
        else:
            for p in active:
                plans_str += f"🔹 **{bot_plans.get(p['macro'], {}).get('name', 'Plan')}**\n"
                plans_str += f"Invested: ${p['amount']:.2f}\nEarned: ${p['earned']:.4f}\n\n"
        t = t.replace('%my_plans%', plans_str)
        
    for p_macro, p_data in bot_plans.items():
        if p_macro in t:
            p_details = f"**{p_data['name']}**\nMin: ${p_data['min']} | Max: ${p_data['max']}\nProfit: {p_data['profit']}% / Hour"
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
    
    text = "🛠 **Inline Keyboard Editor**\n\nClick a button to Edit/Move/Delete it, or click Add New."
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

def send_path_content(chat_id, user_id, path, is_editing=False):
    if is_editing and user_id in editor_msg_ids:
        for m_id in editor_msg_ids[user_id]:
            try: bot.delete_message(chat_id, m_id)
            except Exception: pass
        editor_msg_ids[user_id] = []

    # NEW: Check if this button is assigned directly to a Plan
    meta = btn_metadata.get(path, get_default_metadata())
    assigned_plan = meta.get('assigned_plan')
    
    if assigned_plan and assigned_plan in bot_plans:
        p_data = bot_plans[assigned_plan]
        p_text = replace_macros(p_data.get('text', ''), user_id, path)
        p_photo = p_data.get('photo')
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton(p_data.get('inline_text', '🛒 Purchase Plan'), callback_data=f"cb_buyplan_{assigned_plan}"))
        
        try:
            if p_photo:
                sent = bot.send_photo(chat_id, p_photo, caption=p_text, parse_mode="Markdown", reply_markup=markup)
            else:
                sent = bot.send_message(chat_id, p_text, parse_mode="Markdown", reply_markup=markup)
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
        except Exception as e:
            sent = bot.send_message(chat_id, f"⚠️ Error rendering plan: {e}")
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

    # Standard post rendering follows...
    posts = menu_posts.get(path, [])
    if not posts and not assigned_plan:
        msg = f"📂 **{path.split('/')[-1]}**\n\n_(No messages set for this menu)_" if path != 'root' else "Welcome!"
        sent = bot.send_message(chat_id, msg, parse_mode="Markdown")
        if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
        return
        
    for p in posts:
        text = replace_macros(p['text'], user_id, path)
        
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
                    if b['mode'] == 'url':
                        row_btns.append(InlineKeyboardButton(b['text'], url=b['data']))
                    elif b['mode'] == 'popup':
                        row_btns.append(InlineKeyboardButton(b['text'], callback_data=f"cb_pop_{b['id']}"))
                    elif b['mode'] == 'command':
                        row_btns.append(InlineKeyboardButton(b['text'], callback_data=f"cb_cmd_{b['id']}"))
                    elif b['mode'] == 'buy_plan':
                        row_btns.append(InlineKeyboardButton(b['text'], callback_data=f"cb_buy_{b['id']}"))
                    elif b['mode'] == 'deposit':
                        row_btns.append(InlineKeyboardButton(b['text'], callback_data=f"cb_dep_{b['id']}"))
                if row_btns:
                    markup.row(*row_btns)
                    
        if is_editing:
            editor_markup = get_post_inline_tools(p['id'])
            for row in editor_markup.keyboard:
                markup.row(*row)
                
        if not markup.keyboard: 
            markup = None
        
        try:
            if p['type'] == 'photo':
                sent = bot.send_photo(chat_id, p['photo'], caption=text, parse_mode="Markdown", reply_markup=markup)
            else:
                sent = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
                
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
    
    markup.row(KeyboardButton(f'Random Message ({rm_text})'), KeyboardButton(f'Admin Only ({ao_text})'))
    markup.row(KeyboardButton(f'Invisible ({inv_text})'), KeyboardButton('Subscription (Join)'))
    markup.row(KeyboardButton('Assign Command'), KeyboardButton('Assign Plan')) # NEW
    markup.row(KeyboardButton('Assign Editor'), KeyboardButton('Assign Bonus'))
    markup.row(KeyboardButton('Set Fixed Exchange'), KeyboardButton('Form Settings'))
    markup.row(KeyboardButton('Assign Withdrawal'), KeyboardButton('Shop Editor'))
    markup.row(KeyboardButton('🔙 Exit Button Settings'))
    return markup

def get_withdrawal_keyboard(full_path):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    meta = btn_metadata.get(full_path, get_default_metadata())
    addr_text = "☑️ On" if meta.get('do_not_ask_address') else "⬜️ Off"
    
    markup.row(KeyboardButton('Set Withdrawal'), KeyboardButton('Delete Withdrawal'))
    markup.row(KeyboardButton('Success Message'), KeyboardButton('Fail Message'))
    markup.row(KeyboardButton('Confirm Msg.'), KeyboardButton('Decline Msg.'), KeyboardButton('Ignore Msg.'))
    markup.row(KeyboardButton('Public Group Report'), KeyboardButton('Private Group Report'))
    markup.row(KeyboardButton('Address Condition'), KeyboardButton('Address Variable'))
    markup.row(KeyboardButton(f'Do not ask for Address ({addr_text})'))
    markup.row(KeyboardButton('Commission'), KeyboardButton('Rate'))
    markup.row(KeyboardButton('🔙 Back'))
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

def get_keyboard(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    current_path = user_current_path.get(user_id, 'root')
    state = user_state.get(user_id, 'normal')
    is_admin = user_id in ADMIN_IDS
    
    if is_admin:
        # POSTS EDITOR STATES
        if state == 'posts_editing':
            markup.row(KeyboardButton('➕ Add Message'))
            markup.row(KeyboardButton('Pagination in Editor (10)'))
            markup.row(KeyboardButton('🎛️ Buttons Editor'), KeyboardButton('🛑 Stop Editor'))
            return markup

        if state in ['posts_adding', 'posts_insert_after', 'posts_rep_text', 'posts_rep_all']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        # ADMIN SYSTEM STATES
        if state == 'admin_menu':
            markup.row(KeyboardButton('📜 Macros'), KeyboardButton('📊 Plans'))
            markup.row(KeyboardButton('🏦 Deposit Settings'))
            markup.row(KeyboardButton('🔙 Back to Main'))
            return markup

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

        if state.startswith('dep_setup_'):
            return get_cancel_action_keyboard()

        # --- NEW: ADMIN PLANS MANAGER ---
        if state == 'admin_plans':
            markup.row(KeyboardButton('Plan 0'), KeyboardButton('Plan 1'))
            markup.row(KeyboardButton('Plan 2'), KeyboardButton('Plan 3'))
            markup.row(KeyboardButton('Plan 4'), KeyboardButton('Plan 5'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_plan_settings':
            markup.row(KeyboardButton('💰 Set Min Deposit'), KeyboardButton('💰 Set Max Deposit'))
            markup.row(KeyboardButton('⏱ Contract Length'), KeyboardButton('📈 Plan Percentage'))
            markup.row(KeyboardButton('🖼 Plan Display'), KeyboardButton('💬 Set Inline Text'))
            markup.row(KeyboardButton('🔙 Back to Plans List'))
            return markup

        if state.startswith('plan_setup_'):
            return get_cancel_action_keyboard()

        # BALANCE STATES
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
        if state in ['bal_change_id', 'bal_set_id']:
            c_txt = "▶️ On" if admin_bal_comment_on.get(user_id, False) else "⏸ Off"
            markup.row(KeyboardButton(f'With Comment ({c_txt})'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
        if state in ['bal_get_id', 'bal_change_amount', 'bal_set_amount']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup
        if state in ['bal_change_comment', 'bal_set_comment']:
            markup.row(KeyboardButton('➖ Set Empty'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

        # WIZARD / SETTINGS STATES
        if state.startswith('w_setup_'):
            selected_btn = user_selected_button.get(user_id)
            meta = btn_metadata.get(f"{current_path}/{selected_btn}", get_default_metadata())
            if state == 'w_setup_var': return get_wizard_keyboard(meta.get('w_var'), ['balance', 'bonus', 'deposit', 'hourly', 'plan'])
            if state == 'w_setup_min': return get_wizard_keyboard(meta.get('w_min'), allow_empty=True)
            if state == 'w_setup_max': return get_wizard_keyboard(meta.get('w_max'), allow_empty=True)
            if state == 'w_setup_enter': return get_wizard_keyboard(meta.get('w_msg_enter'), allow_empty=True)
            if state == 'w_setup_addr': return get_wizard_keyboard(meta.get('w_msg_addr'), allow_empty=True)
            if state == 'w_setup_conf': return get_wizard_keyboard(meta.get('w_msg_conf'), allow_empty=True)

        if state == 'button_settings': return get_settings_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'withdrawal_settings': return get_withdrawal_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        if state == 'assign_command': return get_assign_command_keyboard(f"{current_path}/{user_selected_button.get(user_id)}")
        
        if state in ['adding_button', 'renaming_button']:
            markup.row(KeyboardButton('❌ Cancel Action'))
            return markup

    if state == 'buyplan_wait_amount':
        return get_cancel_action_keyboard()

    # CUSTOM BUTTONS (Visible to all)
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
            for i in range(0, len(row_btns), 2):
                if i + 1 < len(row_btns): markup.row(row_btns[i], row_btns[i+1])
                else: markup.row(row_btns[i])

    if current_path != 'root' and state in ['normal', 'editing', 'posts_editing', 'dep_wait_amount', 'dep_wait_proof']:
        markup.row(KeyboardButton('🔙 Back'), KeyboardButton('🏠 Home'))

    if not is_admin: return markup

    # NORMAL / EDITING ADMIN MENUS
    if state == 'editing':
        markup.row(KeyboardButton('➕ Add Button'))
        if user_clipboard.get(user_id):
            markup.row(KeyboardButton(f'📋 Paste "{user_clipboard[user_id]["name"]}"'))
        markup.row(KeyboardButton('🛑 Stop Editor'), KeyboardButton('📝 Posts Editor'))
    elif state == 'normal' and current_path == 'root':
        markup.row(KeyboardButton('🎛️ Buttons Editor'), KeyboardButton('📝 Posts Editor'))
        markup.row(KeyboardButton('💵 Balance'), KeyboardButton('🔐 Admin'))
        
    return markup

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

def get_withdrawal_conf_inline():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton('✅ Confirm', callback_data='cb_w_yes'), InlineKeyboardButton('🚫 Cancel', callback_data='cb_w_no'))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    init_user_db(message)
    user_current_path[user_id] = 'root'
    user_state[user_id] = 'normal'
    user_selected_button[user_id] = None
    
    send_path_content(message.chat.id, user_id, 'root', is_editing=False)
    bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))

@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    is_admin = user_id in ADMIN_IDS
    
    init_user_db(message)
    process_accruals(user_id) 
    
    if user_id not in user_current_path: user_current_path[user_id] = 'root'
    if user_id not in user_state: user_state[user_id] = 'normal'
    if not is_admin and user_state[user_id] not in ['w_action_amount', 'w_action_addr', 'dep_wait_amount', 'dep_wait_proof', 'buyplan_wait_amount']: 
        user_state[user_id] = 'normal'
        
    current_path = user_current_path[user_id]
    state = user_state[user_id]
    selected_btn = user_selected_button.get(user_id)
    full_path = f"{current_path}/{selected_btn}" if selected_btn else None

    # --- HANDLE USER ABORTING ANY LIVE ACTION ---
    if text in ['❌ Cancel Action', '❌ Cancel', '🚫 Cancel Action']:
        if state in ['posts_adding', 'posts_insert_after', 'posts_rep_text', 'posts_rep_all']:
            user_state[user_id] = 'posts_editing'
            bot.send_message(message.chat.id, "Action cancelled.", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
            return
        elif state in ['pi_wait_mode', 'pi_wait_dep_curr', 'pi_wait_text']:
            user_state[user_id] = 'posts_editing'
            bot.send_message(message.chat.id, "Inline editor action cancelled.", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
            return
        elif state.startswith('bal_') or state in ['adding_button', 'renaming_button', 'assign_plan']:
            fallback = 'bal_menu' if state.startswith('bal_') else 'editing'
            user_state[user_id] = fallback
            bot.send_message(message.chat.id, "Action cancelled.", reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('dep_setup_'):
            user_state[user_id] = 'admin_dep_settings'
            bot.send_message(message.chat.id, "Deposit setting cancelled.", reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('plan_setup_'):
            user_state[user_id] = 'admin_plan_settings'
            bot.send_message(message.chat.id, "Plan setting cancelled.", reply_markup=get_keyboard(user_id))
            return
        else:
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "❌ Action Cancelled.", reply_markup=get_keyboard(user_id))
            return

    # --- ENHANCED PLAN BUYING ENGINE ---
    if state == 'buyplan_wait_amount':
        try: invest_amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        
        p_id = user_action_data[user_id].get('buy_plan_id')
        p_data = bot_plans[p_id]
        
        if invest_amount < p_data['min'] or invest_amount > p_data['max']:
            return bot.send_message(message.chat.id, f"⚠️ Amount must be between **${p_data['min']}** and **${p_data['max']}**.", parse_mode="Markdown")
            
        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        
        if invest_amount > (u_dep + u_bal):
            return bot.send_message(message.chat.id, "⚠️ Insufficient funds.")
            
        # Deduct from deposit first, then balance
        if u_dep >= invest_amount:
            user_db[user_id]['deposit'] -= invest_amount
        else:
            rem = invest_amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem
            
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
        bot.send_message(message.chat.id, f"🎉 **Success!**\nYou invested **${invest_amount:.2f}** into **{p_data['name']}**!\nYour profit is accruing automatically.", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- ENHANCED USER DEPOSIT FLOW ENGINE (WITH ORACLE & HD WALLETS) ---
    if state == 'dep_wait_amount':
        try: usd_amount = float(text)
        except ValueError:
            return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only (e.g., 100).")
            
        if user_id not in user_action_data or 'currency' not in user_action_data.get(user_id, {}):
            user_state[user_id] = 'normal'
            return bot.send_message(message.chat.id, "⚠️ Session expired. Please click the deposit button again.", reply_markup=get_keyboard(user_id))
        
        curr = user_action_data[user_id]['currency']
        conf = deposit_settings[curr]
        
        # NEW ENFORCEMENT: Check Min/Max Limits
        c_min = conf.get('min', 0.0)
        c_max = conf.get('max', float('inf'))
        if usd_amount < c_min: return bot.send_message(message.chat.id, f"⚠️ Minimum deposit is **${c_min:.2f} USD**.", parse_mode="Markdown")
        if usd_amount > c_max: return bot.send_message(message.chat.id, f"⚠️ Maximum deposit is **${c_max:.2f} USD**.", parse_mode="Markdown")

        user_action_data[user_id]['usd_amount'] = usd_amount
        
        if conf['mode'] == 'manual':
            # Old Manual Flow
            msg = conf['msg_instruct'].replace('%amount%', str(usd_amount)).replace('%address%', conf['address'])
            user_state[user_id] = 'dep_wait_proof'
            bot.send_message(message.chat.id, msg, parse_mode='Markdown', reply_markup=get_cancel_action_keyboard())
        else:
            # --- NEW AUTO / HD WALLET / LIVE PRICE FLOW ---
            bot.send_message(message.chat.id, f"🔄 Fetching live exchange rate for {curr.replace('_', ' ')}...", reply_markup=get_cancel_action_keyboard())
            
            # Fetch Price
            live_price = get_crypto_price(curr)
            if not live_price:
                user_state[user_id] = 'normal'
                return bot.send_message(message.chat.id, "⚠️ Error connecting to price oracle. Please try again later.", reply_markup=get_keyboard(user_id))
            
            crypto_amount = round(usd_amount / live_price, 6)
            
            # Retrieve or Generate HD Wallet
            if curr not in user_db[user_id]['wallets']:
                bot.send_message(message.chat.id, "🔐 Generating your secure deterministic wallet...", reply_markup=get_cancel_action_keyboard())
                
                address, private_key = generate_user_wallet(user_id, curr)
                if address == "ERROR_NO_SEED":
                    return bot.send_message(message.chat.id, "⚠️ Admin has not configured the Master Seed Phrase. Deposits offline.")
                
                user_db[user_id]['wallets'][curr] = {'address': address, 'private_key': private_key}
                
                # SECURE ALERT TO ADMIN
                admin_alert = f"🚨 **NEW WALLET GENERATED** 🚨\n\n👤 User: `{user_id}` (@{message.from_user.username})\n🪙 Currency: {curr.replace('_', ' ')}\n\n📫 Public Address:\n`{address}`\n\n🔑 **PRIVATE KEY** (KEEP SECRET):\n`{private_key}`"
                for admin in ADMIN_IDS:
                    try: bot.send_message(admin, admin_alert, parse_mode="Markdown")
                    except Exception: pass
            else:
                address = user_db[user_id]['wallets'][curr]['address']
            
            # Instruct User
            msg = conf['msg_instruct'].replace('%crypto_amount%', str(crypto_amount)).replace('%address%', address)
            msg = f"*(Live Rate: 1 {curr.split('_')[0]} = ${live_price:.2f})*\n\n{msg}"
            
            bot.send_message(message.chat.id, msg, parse_mode='Markdown')
            
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
        return

    if state == 'dep_wait_proof':
        if user_id not in user_action_data or 'currency' not in user_action_data.get(user_id, {}):
            user_state[user_id] = 'normal'
            return bot.send_message(message.chat.id, "⚠️ Session expired. Please click the deposit button again.", reply_markup=get_keyboard(user_id))
            
        dep_id = str(uuid.uuid4())[:8]
        curr = user_action_data[user_id]['currency']
        amt = user_action_data[user_id]['usd_amount']
        pending_deposits[dep_id] = {'user_id': user_id, 'amount': amt, 'currency': curr}
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('✅ Approve', callback_data=f'cb_depapp_{dep_id}'),
                   InlineKeyboardButton('❌ Reject', callback_data=f'cb_deprej_{dep_id}'))
        
        admin_msg = f"📥 **New Deposit Request**\nUser ID: `{user_id}`\nUsername: @{message.from_user.username or 'None'}\nAmount: **${amt} (USD Equivalent)**"
        
        for admin in ADMIN_IDS:
            try:
                if message.photo:
                    bot.send_photo(admin, message.photo[-1].file_id, caption=admin_msg, parse_mode="Markdown", reply_markup=markup)
                else:
                    bot.send_message(admin, admin_msg + f"\n\n**Proof Data:**\n{text}", parse_mode="Markdown", reply_markup=markup)
            except Exception: pass
        
        user_state[user_id] = 'normal'
        
        # DYNAMIC PENDING MESSAGE (Manual Mode)
        conf = deposit_settings[curr]
        msg_pending = conf.get('msg_pending', "✅ Your deposit request has been submitted to the administrators.")
        msg_pending = msg_pending.replace('%usd_amount%', str(amt))
        bot.send_message(message.chat.id, msg_pending, parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN DEPOSIT MENU CONTROLS ---
    if state == 'admin_dep_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 **Admin Panel**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        else:
            curr_key = text.strip().upper().replace(' ', '_')
            if curr_key in deposit_settings:
                admin_dep_setup[user_id] = curr_key
                user_state[user_id] = 'admin_dep_settings'
                clean_name = curr_key.replace('_', ' ')
                bot.send_message(message.chat.id, f"🏦 **Editing Settings for {clean_name}**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_dep_settings':
        curr = admin_dep_setup.get(user_id)
        if text == '🔙 Back to Deposit Menu':
            user_state[user_id] = 'admin_dep_menu'
            bot.send_message(message.chat.id, "🏦 **Deposit Menu**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text.startswith('🔄 Mode:'):
            deposit_settings[curr]['mode'] = 'auto' if deposit_settings[curr]['mode'] == 'manual' else 'manual'
            bot.send_message(message.chat.id, f"Mode switched to **{deposit_settings[curr]['mode'].upper()}**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == '📍 Set Static Address':
            user_state[user_id] = 'dep_setup_addr'
            bot.send_message(message.chat.id, f"Send the Static Receiving Address for **{curr.replace('_', ' ')}**:\n\nℹ️ Current: `{deposit_settings[curr]['address']}`", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '🔑 Set HD Wallet Key':
            user_state[user_id] = 'dep_setup_key'
            bot.send_message(message.chat.id, f"Send the Master HD Key/Seed for **{curr.replace('_', ' ')}** (Auto Mode):\n\nℹ️ Current: `{deposit_settings[curr]['hd_key']}`", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Enter Msg':
            user_state[user_id] = 'dep_setup_enter'
            bot.send_message(message.chat.id, f"Send the prompt message asking user for amount:\n\nℹ️ Current: `{deposit_settings[curr]['msg_enter']}`", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Instruct Msg':
            user_state[user_id] = 'dep_setup_instruct'
            bot.send_message(message.chat.id, f"Send instructions containing `%crypto_amount%` and `%address%` macros:\n\nℹ️ Current:\n{deposit_settings[curr]['msg_instruct']}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        
        elif text == '💰 Set Min Deposit':
            user_state[user_id] = 'dep_setup_min'
            bot.send_message(message.chat.id, f"Enter Minimum Deposit Amount in USD for **{curr.replace('_', ' ')}**:\n\nℹ️ Current: {deposit_settings[curr].get('min', 10.0)}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💰 Set Max Deposit':
            user_state[user_id] = 'dep_setup_max'
            bot.send_message(message.chat.id, f"Enter Maximum Deposit Amount in USD for **{curr.replace('_', ' ')}**:\n\nℹ️ Current: {deposit_settings[curr].get('max', 10000.0)}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Pending Msg':
            user_state[user_id] = 'dep_setup_pending'
            bot.send_message(message.chat.id, f"Send the message shown when a user submits deposit proof (Manual Mode). Use macro `%usd_amount%`:\n\nℹ️ Current:\n{deposit_settings[curr].get('msg_pending', '')}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'dep_setup_success'
            bot.send_message(message.chat.id, f"Send the success message when a deposit is approved. Use macros `%usd_amount%` and `%crypto_amount%`:\n\nℹ️ Current:\n{deposit_settings[curr].get('msg_success', '')}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
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

    # --- NEW: ADMIN PLANS MANAGER ---
    if state == 'admin_plans':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 **Admin Panel**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text.startswith('Plan '):
            p_id = text.replace('Plan ', 'plan').lower()
            if p_id in bot_plans:
                if user_id not in user_action_data: user_action_data[user_id] = {}
                user_action_data[user_id]['edit_plan'] = p_id
                user_state[user_id] = 'admin_plan_settings'
                bot.send_message(message.chat.id, f"⚙️ **Editing {text}**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_plan_settings':
        p_id = user_action_data[user_id].get('edit_plan')
        if text == '🔙 Back to Plans List':
            user_state[user_id] = 'admin_plans'
            bot.send_message(message.chat.id, "📊 **Plans Manager**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == '💰 Set Min Deposit':
            user_state[user_id] = 'plan_setup_min'
            bot.send_message(message.chat.id, f"Enter Minimum Deposit for **{bot_plans[p_id]['name']}**:\n\nℹ️ Current: ${bot_plans[p_id]['min']}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💰 Set Max Deposit':
            user_state[user_id] = 'plan_setup_max'
            bot.send_message(message.chat.id, f"Enter Maximum Deposit for **{bot_plans[p_id]['name']}**:\n\nℹ️ Current: ${bot_plans[p_id]['max']}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '⏱ Contract Length':
            user_state[user_id] = 'plan_setup_length'
            bot.send_message(message.chat.id, f"Enter Contract Length (in hours) for **{bot_plans[p_id]['name']}**:\n\nℹ️ Current: {bot_plans[p_id]['length']} hours", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '📈 Plan Percentage':
            user_state[user_id] = 'plan_setup_profit'
            bot.send_message(message.chat.id, f"Enter Profit Percentage for **{bot_plans[p_id]['name']}**:\n\nℹ️ Current: {bot_plans[p_id]['profit']}%", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '🖼 Plan Display':
            user_state[user_id] = 'plan_setup_display'
            bot.send_message(message.chat.id, f"Send an Image with a Caption (or just text) to set as the display for **{bot_plans[p_id]['name']}**:", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Set Inline Text':
            user_state[user_id] = 'plan_setup_inline'
            bot.send_message(message.chat.id, f"Enter the text for the inline purchase button (e.g. 'Buy Now'):\n\nℹ️ Current: {bot_plans[p_id].get('inline_text', 'Buy Now')}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('plan_setup_'):
        p_id = user_action_data[user_id].get('edit_plan')
        if state == 'plan_setup_min':
            try: bot_plans[p_id]['min'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_max':
            try: bot_plans[p_id]['max'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_length':
            try: bot_plans[p_id]['length'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_profit':
            try: bot_plans[p_id]['profit'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Numbers only.")
        elif state == 'plan_setup_display':
            bot_plans[p_id]['photo'] = message.photo[-1].file_id if message.photo else None
            bot_plans[p_id]['text'] = message.caption if message.photo else text
        elif state == 'plan_setup_inline':
            bot_plans[p_id]['inline_text'] = text
            
        user_state[user_id] = 'admin_plan_settings'
        bot.send_message(message.chat.id, "✅ Plan updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- HANDLE INLINE BUTTONS EDITOR WORKFLOW ---
    if state == 'pi_wait_mode':
        mode_map = {'🔗 URL or Share': 'url', '💬 Popup Window': 'popup', '🚀 Command': 'command', '🛒 Buy Plan': 'buy_plan', '🏦 Deposit': 'deposit'}
        if text in mode_map:
            if user_id not in user_action_data: user_action_data[user_id] = {}
            user_action_data[user_id]['mode'] = mode_map[text]
            
            if mode_map[text] == 'deposit':
                user_state[user_id] = 'pi_wait_dep_curr'
                markup = ReplyKeyboardMarkup(resize_keyboard=True)
                for c in deposit_settings.keys():
                    markup.row(KeyboardButton(c.replace('_', ' '))) 
                markup.row(KeyboardButton('❌ Cancel Action'))
                bot.send_message(message.chat.id, "🏦 Select the deposit method for this button:", reply_markup=markup)
                return

            user_state[user_id] = 'pi_wait_text'
            
            prev_text = ""
            if 'btn_id' in user_action_data[user_id]:
                post_id = user_action_data[user_id]['post_id']
                btn_id = user_action_data[user_id]['btn_id']
                post = next((p for p in menu_posts[current_path] if p['id'] == post_id), None)
                if post:
                    b = next((x for x in post.get('custom_inlines', []) if x['id'] == btn_id), None)
                    if b: prev_text = f"\n\nℹ️ **Current Config:**\nTitle: `{b['text']}`\nData: `{b['data']}`"
            
            if mode_map[text] == 'buy_plan':
                inst = "Send the **Title** on line 1.\nOn line 2, put the **Plan Macro** (e.g. `%plan0%`).\nOn line 3 (Optional), put the **Deposit Command** to trigger if they don't have enough balance."
            else:
                inst = "Send the **Title** on line 1, and **Data/URL** on line 2.\n_(Press Enter to jump to the second line)_"
                
            bot.send_message(message.chat.id, f"{inst}{prev_text}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        else:
            bot.send_message(message.chat.id, "Please use the keyboard to select a valid category.")
        return

    if state == 'pi_wait_dep_curr':
        curr_key = text.strip().upper().replace(" ", "_") 
        if curr_key not in deposit_settings:
            return bot.send_message(message.chat.id, "⚠️ Invalid method. Please select directly from the keyboard buttons.")
        user_action_data[user_id]['dep_curr'] = curr_key
        user_state[user_id] = 'pi_wait_text'
        
        prev_text = ""
        if 'btn_id' in user_action_data[user_id]:
            post_id = user_action_data[user_id]['post_id']
            btn_id = user_action_data[user_id]['btn_id']
            post = next((p for p in menu_posts[current_path] if p['id'] == post_id), None)
            if post:
                b = next((x for x in post.get('custom_inlines', []) if x['id'] == btn_id), None)
                if b: prev_text = f"\n\nℹ️ **Current Title:** `{b['text']}`"
                
        clean_curr = curr_key.replace('_', ' ')
        bot.send_message(message.chat.id, f"Enter the **Display Title** for this button (e.g., Deposit {clean_curr}):{prev_text}", parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'pi_wait_text':
        mode = user_action_data[user_id]['mode']
        
        if mode == 'deposit':
            title = text.strip()
            data = user_action_data[user_id]['dep_curr']
        else:
            lines = text.split('\n', 1)
            if len(lines) < 2 and mode not in ['buy_plan']:
                bot.send_message(message.chat.id, "⚠️ You must send both Title and Data separated by a new line. Try again.")
                return
            title = lines[0].strip()
            data = lines[1].strip() if len(lines) > 1 else ""

        post_id = user_action_data[user_id]['post_id']
        post = next((p for p in menu_posts[current_path] if p['id'] == post_id), None)
        
        if post:
            if 'custom_inlines' not in post: post['custom_inlines'] = []
            
            if 'btn_id' in user_action_data[user_id]:
                btn_id = user_action_data[user_id]['btn_id']
                b = next((x for x in post['custom_inlines'] if x['id'] == btn_id), None)
                if b:
                    b['text'], b['data'], b['mode'] = title, data, mode
            else:
                max_r = max([x.get('row_idx', 0) for x in post['custom_inlines']] + [0]) if post['custom_inlines'] else 0
                new_r = max_r + 1 if post['custom_inlines'] else 0
                post['custom_inlines'].append({'id': str(uuid.uuid4())[:8], 'text': title, 'mode': mode, 'data': data, 'row_idx': new_r})
                
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, "✅ Inline Button Saved!", reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    # --- HANDLE POSTS EDITING WORKFLOW ---
    if state in ['posts_adding', 'posts_insert_after', 'posts_rep_text', 'posts_rep_all']:
        post_type = 'photo' if message.photo else 'text'
        photo_id = message.photo[-1].file_id if message.photo else None
        
        if current_path not in menu_posts: menu_posts[current_path] = []
        posts_list = menu_posts[current_path]
        
        if state == 'posts_adding':
            posts_list.append({'id': str(uuid.uuid4())[:8], 'type': post_type, 'text': text, 'photo': photo_id})
            
        elif state == 'posts_insert_after':
            target_id = user_action_data[user_id]['post_id']
            for i, p in enumerate(posts_list):
                if p['id'] == target_id:
                    posts_list.insert(i + 1, {'id': str(uuid.uuid4())[:8], 'type': post_type, 'text': text, 'photo': photo_id})
                    break
                    
        elif state == 'posts_rep_text':
            target_id = user_action_data[user_id]['post_id']
            for p in posts_list:
                if p['id'] == target_id:
                    p['text'] = text
                    break
                    
        elif state == 'posts_rep_all':
            target_id = user_action_data[user_id]['post_id']
            for p in posts_list:
                if p['id'] == target_id:
                    p['type'] = post_type
                    p['text'] = text
                    p['photo'] = photo_id
                    break

        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, "✅ Menu Updated!", reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    # --- BLOCK UNAUTHORIZED ADMIN COMMANDS ---
    admin_commands = ['🎛️ Buttons Editor', '📝 Posts Editor', '💵 Balance', '🔐 Admin', '➕ Add Button', '🛑 Stop Editor', '🔙 Exit Button Settings', '✅ Confirm', '🚫 Cancel', '✖️ Delete', 'Deposit balance', 'Withdrawal balance', '🔙 Exit Balance', '📜 Macros', '📊 Plans', '🔙 Back to Main', '🔙 Back to Admin', '➕ Add Plan', '➕ Add Message', 'Pagination in Editor (10)', '🏦 Deposit Settings', '🔙 Back to Deposit Menu', '📍 Set Static Address', '🔑 Set HD Wallet Key', '💬 Edit Enter Msg', '💬 Edit Instruct Msg', '💰 Set Min Deposit', '💰 Set Max Deposit', '💬 Edit Pending Msg', '💬 Edit Success Msg']
    if not is_admin and (text in admin_commands or text.startswith('📋 Paste "') or text == '✔️ Leave as Is' or text == '➖ Set Empty' or text.startswith('⚙️ Edit ')):
        bot.send_message(message.chat.id, "Unrecognized command.", reply_markup=get_keyboard(user_id))
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
            bot.send_message(message.chat.id, "📝 **Posts Editor Activated**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, True)
        elif current_path in menus and text in menus[current_path]:
            if user_selected_button.get(user_id) == text:
                user_selected_button[user_id] = None
                new_path = f"{current_path}/{text}"
                user_current_path[user_id] = new_path
                if new_path not in menus: menus[new_path] = []
                send_path_content(message.chat.id, user_id, new_path, False)
                bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
            else:
                user_selected_button[user_id] = text
                bot.send_message(message.chat.id, f"🛠 Selected: **{text}**\nChoose an action:", parse_mode="Markdown", reply_markup=get_edit_inline_tools())
        return

    if state == 'posts_editing':
        if text == '🛑 Stop Editor':
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "🛑 Posts Editor stopped.", reply_markup=get_keyboard(user_id))
            send_path_content(message.chat.id, user_id, current_path, False)
            bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
            return
        elif text == '🎛️ Buttons Editor':
            user_state[user_id] = 'editing'
            bot.send_message(message.chat.id, "🎛 **Buttons Editor Activated**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
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
            bot.send_message(message.chat.id, "🏦 **Deposit Architecture Menu**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == '📜 Macros':
            macros_msg = (
                "📝 **Available Macros List**\n"
                "(Tap on any macro to copy it)\n\n"
                "`%balance%` - Withdrawal balance (profits)\n"
                "`%deposit%` - Deposit balance\n"
                "`%my_plans%` - Shows user their active plans\n"
                "`%userid%` - Telegram numeric ID\n"
                "`%username%` - Telegram @username\n"
                "`%firstname%` - User's first name\n"
                "`%lastname%` - User's last name\n\n"
                "`%usd_amount%` - USD amount of deposit\n"
                "`%crypto_amount%` - Crypto amount of deposit\n"
                "`%address%` - Wallet address\n\n"
                "`%plan0%` ... `%plan5%` - Plan details\n"
            )
            bot.send_message(message.chat.id, macros_msg, parse_mode="Markdown")
        elif text == '📊 Plans':
            user_state[user_id] = 'admin_plans'
            bot.send_message(message.chat.id, "📊 **Plans Manager**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN BALANCE MANAGEMENT ENGINE ---
    if state == 'normal' and text == '💵 Balance':
        if is_admin:
            user_state[user_id] = 'bal_select'
            bot.send_message(message.chat.id, "Select the balance to manage:", reply_markup=get_keyboard(user_id))
        else:
            bal = user_db[user_id]['balance']
            bot.send_message(message.chat.id, f"Balance: ${bal:.2f}")
        return

    if state == 'bal_select':
        if text in ['Deposit balance', 'Withdrawal balance']:
            admin_bal_type[user_id] = 'deposit' if text == 'Deposit balance' else 'balance'
            user_state[user_id] = 'bal_menu'
            bot.send_message(message.chat.id, f"🗃 **Managing {text}**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == '🔙 Exit Balance':
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, "Exited balance management.", reply_markup=get_keyboard(user_id))
        return

    if state == 'bal_menu':
        if text == '🔙 Exit Balance':
            user_state[user_id] = 'bal_select'
            bot.send_message(message.chat.id, "Select balance type:", reply_markup=get_keyboard(user_id))
        elif text.startswith('Notify User'):
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
                bot.send_message(message.chat.id, f"👤 **User Info**\nID: `{target}`\nName: {u['first_name']}\nUsername: @{u['username']}\n\n💰 **{btype.title()}:** {u[btype]:.2f}", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
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
                
                info_msg = f"👤 **User Found**\nID: `{target}`\nName: {u['first_name']}\nUsername: @{u['username']}\n💰 Current {btype.title()}: **{u[btype]:.2f}**\n\n"
                
                if admin_bal_comment_on.get(user_id, False):
                    user_state[user_id] = state.replace('_id', '_comment')
                    bot.send_message(message.chat.id, info_msg + "Enter the **comment** for the balance change:", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
                else:
                    admin_bal_comment_text[user_id] = ""
                    user_state[user_id] = state.replace('_id', '_amount')
                    bot.send_message(message.chat.id, info_msg + "Enter the **numeric value** (+/- allowed for change):", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "❌ User not found. Try again or Cancel.")
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid ID. Must be a number.")
        return

    if state in ['bal_change_comment', 'bal_set_comment']:
        if text == '➖ Set Empty': admin_bal_comment_text[user_id] = ""
        else: admin_bal_comment_text[user_id] = text
            
        user_state[user_id] = state.replace('_comment', '_amount')
        bot.send_message(message.chat.id, "Enter the **numeric value** (+/- allowed for change):", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
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
            bot.send_message(message.chat.id, f"✅ **Success!**\nNew {btype.title()} balance for `{target}` is **{new_bal:.2f}**.", parse_mode="Markdown")
            
            if admin_bal_notify.get(user_id, True) and comment:
                try:
                    bot.send_message(target, f"🔔 **Admin Notice**\n{comment}\n\nYour {btype.title()} is now: **{new_bal:.2f}**", parse_mode="Markdown")
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
        meta = btn_metadata.get(target_path, get_default_metadata())
        
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
            
        w_min = float(meta['w_min']) if meta.get('w_min') else 0
        w_max = float(meta['w_max']) if meta.get('w_max') else float('inf')
        
        if amount < w_min: return bot.send_message(message.chat.id, f"⚠️ Minimum withdrawal is {w_min}.")
        if amount > w_max: return bot.send_message(message.chat.id, f"⚠️ Maximum withdrawal is {w_max}.")
            
        w_var = meta.get('w_var')
        user_bal = user_db[user_id].get(w_var, 0)
        if amount > user_bal: return bot.send_message(message.chat.id, f"❌ Insufficient funds. Your {w_var} balance is {user_bal:.2f}.")
            
        user_action_data[user_id]['amount'] = amount
        
        if not meta.get('do_not_ask_address'):
            user_state[user_id] = 'w_action_addr'
            msg = meta.get('w_msg_addr') or "Please enter your withdrawal address:"
            bot.send_message(message.chat.id, replace_macros(msg, user_id, target_path, user_action_data[user_id]), parse_mode="Markdown")
        else:
            user_state[user_id] = 'w_action_conf'
            msg = meta.get('w_msg_conf') or f"Confirm withdrawal of {amount}?"
            bot.send_message(message.chat.id, replace_macros(msg, user_id, target_path, user_action_data[user_id]), parse_mode="Markdown", reply_markup=get_withdrawal_conf_inline())
        return

    if state == 'w_action_addr':
        target_path = user_action_data[user_id]['path']
        meta = btn_metadata.get(target_path, get_default_metadata())
        user_action_data[user_id]['address'] = text
        
        user_state[user_id] = 'w_action_conf'
        msg = meta.get('w_msg_conf') or f"Confirm withdrawal of {user_action_data[user_id]['amount']} to `{text}`?"
        bot.send_message(message.chat.id, replace_macros(msg, user_id, target_path, user_action_data[user_id]), parse_mode="Markdown", reply_markup=get_withdrawal_conf_inline())
        return

    # --- GLOBAL FEATURE: Move by Command ---
    if state in ['normal', 'posts_editing']:
        for path, meta in btn_metadata.items():
            if meta.get('move_by_command') and meta.get('command') == text:
                if meta.get('admin_only') and not is_admin:
                    return bot.send_message(message.chat.id, "⛔️ You do not have permission to use this button.")
                user_current_path[user_id] = path
                if path not in menus: menus[path] = []
                
                send_path_content(message.chat.id, user_id, path, is_editing=(state == 'posts_editing'))
                bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
                return

    # --- WITHDRAWAL WIZARD SETUP (Admin) ---
    if state.startswith('w_setup_'):
        if text == '🚫 Cancel':
            user_state[user_id] = 'withdrawal_settings'
            bot.send_message(message.chat.id, "Setup Cancelled.", reply_markup=get_keyboard(user_id))
            return
            
        val = None if text == '➖ Set Empty' else text
        if text != '✔️ Leave as Is':
            if state == 'w_setup_var': btn_metadata[full_path]['w_var'] = val
            elif state == 'w_setup_min': btn_metadata[full_path]['w_min'] = val
            elif state == 'w_setup_max': btn_metadata[full_path]['w_max'] = val
            elif state == 'w_setup_enter': btn_metadata[full_path]['w_msg_enter'] = val
            elif state == 'w_setup_addr': btn_metadata[full_path]['w_msg_addr'] = val
            elif state == 'w_setup_conf': btn_metadata[full_path]['w_msg_conf'] = val

        if state == 'w_setup_var':
            user_state[user_id] = 'w_setup_min'
            curr = btn_metadata[full_path].get('w_min')
            bot.send_message(message.chat.id, f"✨ Enter the MINIMAL sum for withdrawal.\n\nLeave empty if there is no minimal sum.\n\nℹ️ Current minimal sum:\n{curr}", reply_markup=get_keyboard(user_id))
            
        elif state == 'w_setup_min':
            user_state[user_id] = 'w_setup_max'
            curr = btn_metadata[full_path].get('w_max')
            bot.send_message(message.chat.id, f"✨ Enter the MAXIMAL sum for withdrawal.\n\nLeave empty if there is no maximal sum.\n\nℹ️ Current maximal sum:\n{curr}", reply_markup=get_keyboard(user_id))
            
        elif state == 'w_setup_max':
            user_state[user_id] = 'w_setup_enter'
            curr = btn_metadata[full_path].get('w_msg_enter')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown UPON ENTRANCE into the Withdraw button.\n\n❗️ Use macros like %balance%, %min%, %max%, etc.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
            
        elif state == 'w_setup_enter':
            user_state[user_id] = 'w_setup_addr'
            curr = btn_metadata[full_path].get('w_msg_addr')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown when ASK ADDRESS/PHONE to withdraw.\n\n❗️ Use macros like %firstname%, %address%.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
            
        elif state == 'w_setup_addr':
            user_state[user_id] = 'w_setup_conf'
            curr = btn_metadata[full_path].get('w_msg_conf')
            bot.send_message(message.chat.id, f"✨ Enter the MESSAGE shown BEFORE the operation commit.\n\n❗️ Ask User to CONFIRM withdraw operation.\n\nℹ️ Current message:\n{curr}", reply_markup=get_keyboard(user_id))
            
        elif state == 'w_setup_conf':
            user_state[user_id] = 'withdrawal_settings'
            bot.send_message(message.chat.id, "✅ Withdrawal setup complete!", reply_markup=get_keyboard(user_id))
        return

    # --- NEW: ASSIGN PLAN TO BUTTON MENU ---
    if state == 'assign_plan':
        if text == '➖ Remove Plan':
            btn_metadata[full_path]['assigned_plan'] = None
            bot.send_message(message.chat.id, "Plan removed from button.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Plan '):
            p_id = text.replace('Plan ', 'plan').lower()
            btn_metadata[full_path]['assigned_plan'] = p_id
            bot.send_message(message.chat.id, f"✅ Button assigned to **{bot_plans[p_id]['name']}**!", parse_mode="Markdown")
        
        user_state[user_id] = 'button_settings'
        bot.send_message(message.chat.id, "Menu:", reply_markup=get_keyboard(user_id))
        return

    # --- STATE: ASSIGN COMMAND MENU ---
    if state == 'assign_command':
        if text == '🚫 Cancel':
            user_state[user_id] = 'button_settings'
            bot.send_message(message.chat.id, "Cancelled command assignment.", reply_markup=get_keyboard(user_id))
        elif text == '✖️ Delete':
            btn_metadata[full_path]['command'] = None
            user_state[user_id] = 'button_settings'
            bot.send_message(message.chat.id, "Command deleted.", reply_markup=get_keyboard(user_id))
        elif text == '✅ Confirm':
            user_state[user_id] = 'button_settings'
            curr_cmd = btn_metadata[full_path].get('command', 'None')
            bot.send_message(message.chat.id, f"Command confirmed as: `{curr_cmd}`", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text.startswith('Move by Command'):
            btn_metadata[full_path]['move_by_command'] = not btn_metadata[full_path].get('move_by_command')
            bot.send_message(message.chat.id, "Move by Command toggled.", reply_markup=get_keyboard(user_id))
        else:
            btn_metadata[full_path]['command'] = text
            bot.send_message(message.chat.id, f"Stored: `{text}`\nNow press ✅ Confirm to save.", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- STATE: WITHDRAWAL SETTINGS MENU ---
    if state == 'withdrawal_settings':
        if text == '🔙 Back':
            user_state[user_id] = 'button_settings'
            bot.send_message(message.chat.id, "Back to Button Settings.", reply_markup=get_keyboard(user_id))
        elif text == 'Set Withdrawal':
            user_state[user_id] = 'w_setup_var'
            curr = btn_metadata[full_path].get('w_var')
            bot.send_message(message.chat.id, f"✨ Select variable for withdrawal (deduction).\n\n❗️ User will specify the amount deducted from this variable.\n\nℹ️ Current variable:\n{curr}", reply_markup=get_keyboard(user_id))
        elif text.startswith('Do not ask for Address'):
            btn_metadata[full_path]['do_not_ask_address'] = not btn_metadata[full_path].get('do_not_ask_address')
            bot.send_message(message.chat.id, "Address setting toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Delete Withdrawal':
            btn_metadata[full_path]['w_var'] = None
            bot.send_message(message.chat.id, "🗑 Withdrawal properties deleted from this button.", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, f"🛠 **{text}** selected.\nReady to program this logic!", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- STATE: BUTTON SETTINGS MENU ---
    if state == 'button_settings':
        if full_path not in btn_metadata: btn_metadata[full_path] = get_default_metadata()
            
        if text == '🔙 Exit Button Settings':
            user_state[user_id] = 'editing'
            bot.send_message(message.chat.id, f"Exited settings for **{selected_btn}**.", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == 'Assign Command':
            user_state[user_id] = 'assign_command'
            curr = btn_metadata[full_path].get('command', 'None assigned yet')
            bot.send_message(message.chat.id, f"Send the command for this button (Current: `{curr}`)", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == 'Assign Plan':
            user_state[user_id] = 'assign_plan'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('Plan 0'), KeyboardButton('Plan 1'), KeyboardButton('Plan 2'))
            markup.row(KeyboardButton('Plan 3'), KeyboardButton('Plan 4'), KeyboardButton('Plan 5'))
            markup.row(KeyboardButton('➖ Remove Plan'), KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select a Plan to assign directly to this button:", reply_markup=markup)
        elif text == 'Assign Withdrawal':
            user_state[user_id] = 'withdrawal_settings'
            bot.send_message(message.chat.id, f"Withdrawal settings for: {selected_btn}", reply_markup=get_keyboard(user_id))
        elif text.startswith('Random Message'):
            btn_metadata[full_path]['random_message'] = not btn_metadata[full_path]['random_message']
            bot.send_message(message.chat.id, "Random Message toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Admin Only'):
            btn_metadata[full_path]['admin_only'] = not btn_metadata[full_path]['admin_only']
            bot.send_message(message.chat.id, "Admin Only toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Invisible'):
            btn_metadata[full_path]['invisible'] = not btn_metadata[full_path]['invisible']
            bot.send_message(message.chat.id, "Invisible toggled.", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, f"🛠 **{text}** selected.\nReady for logic!", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        return

    # --- HANDLE BUTTONS EDITOR ADD / RENAME ---
    if state == 'adding_button':
        if current_path not in menus: menus[current_path] = []
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

    # --- NAVIGATION COMMANDS (Back & Home) ---
    if state in ['normal', 'posts_editing', 'editing']:
        if text == '🏠 Home':
            user_current_path[user_id] = 'root'
            user_selected_button[user_id] = None
            send_path_content(message.chat.id, user_id, 'root', is_editing=(state == 'posts_editing'))
            bot.send_message(message.chat.id, "📍 Returned to Main Menu:", reply_markup=get_keyboard(user_id))
            return
            
        elif text == '🔙 Back' and current_path != 'root':
            parts = current_path.split('/')[:-1]
            new_path = '/'.join(parts) if len(parts) > 1 else 'root'
            user_current_path[user_id] = new_path
            user_selected_button[user_id] = None
            send_path_content(message.chat.id, user_id, new_path, is_editing=(state == 'posts_editing'))
            bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
            return

    # --- HANDLE NORMAL / POSTS EDITING TRAVERSAL ---
    if state == 'normal' or state == 'posts_editing':
        if text == '🎛️ Buttons Editor':
            if is_admin:
                user_state[user_id] = 'editing'
                bot.send_message(message.chat.id, "🎛 **Buttons Editor Activated**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
        elif text == '📝 Posts Editor':
            if is_admin:
                user_state[user_id] = 'posts_editing'
                bot.send_message(message.chat.id, "📝 **Posts Editor Activated**", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
                send_path_content(message.chat.id, user_id, current_path, True)
        elif text == '🔐 Admin':
            if is_admin:
                user_state[user_id] = 'admin_menu'
                bot.send_message(message.chat.id, "🔐 **Admin Panel**\nChoose an option:", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "Unrecognized command.", reply_markup=get_keyboard(user_id))
            
        elif current_path in menus and text in menus[current_path]:
            custom_btn_path = f"{current_path}/{text}"
            meta = btn_metadata.get(custom_btn_path, get_default_metadata())
            
            if meta.get('admin_only') and not is_admin:
                return bot.send_message(message.chat.id, "⛔️ You do not have permission to use this button.")

            if meta.get('w_var') and state != 'posts_editing':
                user_state[user_id] = 'w_action_amount'
                user_action_data[user_id] = {'path': custom_btn_path}
                msg = meta.get('w_msg_enter') or "Please enter the amount you wish to withdraw:"
                bot.send_message(message.chat.id, replace_macros(msg, user_id, custom_btn_path), parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
                return

            new_path = custom_btn_path
            user_current_path[user_id] = new_path
            if new_path not in menus: menus[new_path] = []
            
            send_path_content(message.chat.id, user_id, new_path, is_editing=(state == 'posts_editing'))
            bot.send_message(message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, "Unrecognized command.", reply_markup=get_keyboard(user_id))


# --- INLINE BUTTON LOGIC ---
@bot.callback_query_handler(func=lambda call: True)
def handle_inline(call):
    user_id = call.from_user.id
    current_path = user_current_path.get(user_id, 'root')
    target_btn = user_selected_button.get(user_id)
    is_admin = user_id in ADMIN_IDS

    # --- ENHANCED DYNAMIC PLAN BUYER INLINE ACTION ---
    if call.data.startswith('cb_buyplan_'):
        plan_id = call.data.split('_')[2]
        if plan_id not in bot_plans:
            return bot.answer_callback_query(call.id, "Plan not found.", show_alert=True)
            
        p_data = bot_plans[plan_id]
        
        # Check Total Available Funds (Deposit + Withdrawal Balance)
        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        total_avail = u_dep + u_bal
        
        # Insufficient Funds -> Redirect to Deposit Engine
        if total_avail < p_data['min']:
            user_db[user_id]['pending_plan'] = plan_id
            bot.answer_callback_query(call.id, "Insufficient balance. Redirecting to Deposit...", show_alert=True)
            
            markup = InlineKeyboardMarkup()
            for c in deposit_settings.keys():
                markup.row(InlineKeyboardButton(c.replace('_', ' '), callback_data=f"cb_dep_{c}"))
            bot.send_message(call.message.chat.id, "💰 **Insufficient Funds!**\nPlease select a deposit method below to fund your account and automatically activate your plan:", parse_mode="Markdown", reply_markup=markup)
            return
            
        # Funds OK -> Move to Amount Entry State
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['buy_plan_id'] = plan_id
        user_state[user_id] = 'buyplan_wait_amount'
        bot.send_message(call.message.chat.id, f"📈 **{p_data['name']}**\nMin: ${p_data['min']} | Max: ${p_data['max']}\n\nAvailable Balance: ${total_avail:.2f}\n\nEnter the amount you wish to invest:", reply_markup=get_cancel_action_keyboard())
        bot.answer_callback_query(call.id)
        return

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
            
            # DYNAMIC SUCCESS MESSAGE (Manual Mode)
            msg_success = conf.get('msg_success', "✅ **Deposit Approved!**\n**$%usd_amount%** has been successfully added to your deposit balance.")
            msg_success = msg_success.replace('%usd_amount%', f"{amt:.2f}").replace('%crypto_amount%', '')
            bot.send_message(target, msg_success, parse_mode="Markdown")
            
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
            bot.send_message(target, f"❌ **Deposit Rejected**\nYour deposit request for **${dep['amount']}** could not be verified.", parse_mode="Markdown")
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
                        return bot.answer_callback_query(call.id, b['data'], show_alert=True)
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
        # Allow checking if it was generated directly from the Buy Plan redirect
        if len(call.data.split('_')) > 2 and call.data.split('_')[2] in deposit_settings:
             curr = call.data.replace('cb_dep_', '')
        else:
            for path, posts in menu_posts.items():
                for p in posts:
                    for b in p.get('custom_inlines', []):
                        if b['id'] == btn_id:
                            curr = b['data'].strip().upper().replace(" ", "_")
        
        if curr not in deposit_settings:
            return bot.answer_callback_query(call.id, "Error: Currency not configured.", show_alert=True)
            
        bot.answer_callback_query(call.id)
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['currency'] = curr
        user_state[user_id] = 'dep_wait_amount'
        
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass
        
        bot.send_message(call.message.chat.id, deposit_settings[curr]['msg_enter'], parse_mode="Markdown", reply_markup=get_cancel_action_keyboard())
        return
        
    elif call.data.startswith('cb_buy_'):
        btn_id = call.data.split('_')[2]
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        bot.answer_callback_query(call.id, "Processing request...")
                        lines = b['data'].split('\n')
                        plan_macro = lines[0].strip()
                        dep_cmd = lines[1].strip() if len(lines) > 1 else None
                        
                        if plan_macro not in bot_plans:
                            return bot.send_message(call.message.chat.id, "⚠️ Error: This plan no longer exists in the system.")
                            
                        p_data = bot_plans[plan_macro]
                        u_dep = user_db[user_id]['deposit']
                        
                        if u_dep < p_data['min']:
                            user_db[user_id]['pending_plan'] = plan_macro
                            bot.send_message(call.message.chat.id, f"⚠️ Insufficient deposit balance (Min: ${p_data['min']}). Redirecting to Deposit...", parse_mode="Markdown")
                            if dep_cmd:
                                try: bot.delete_message(call.message.chat.id, call.message.message_id)
                                except Exception: pass
                                msg = call.message
                                msg.from_user = call.from_user
                                msg.text = dep_cmd
                                handle_messages(msg)
                            return
                            
                        invest_amt = min(u_dep, p_data['max'])
                        user_db[user_id]['deposit'] -= invest_amt
                        
                        new_plan = {
                            'id': str(uuid.uuid4())[:8],
                            'macro': plan_macro,
                            'amount': invest_amt,
                            'profit_pct': p_data['profit'],
                            'length_hours': p_data.get('length', 0),
                            'start_time': time.time(),
                            'last_accrual': time.time(),
                            'earned': 0.0,
                            'status': 'active'
                        }
                        user_db[user_id]['active_plans'].append(new_plan)
                        bot.send_message(call.message.chat.id, f"🎉 **Success!**\n\nYou successfully invested **${invest_amt:.2f}** into **{p_data['name']}**!\nYour profit is accruing automatically.", parse_mode="Markdown")
                        return
        return bot.answer_callback_query(call.id)

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
            bot.send_message(call.message.chat.id, "Send the new text (image will be kept):", reply_markup=get_cancel_action_keyboard())
            
        elif action == 'repall':
            user_state[user_id] = 'posts_rep_all'
            user_action_data[user_id] = {'post_id': post_id}
            bot.send_message(call.message.chat.id, "Send the new message (text or photo):", reply_markup=get_cancel_action_keyboard())
            
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
            markup.row(KeyboardButton('🏦 Deposit'), KeyboardButton('❌ Cancel Action'))
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
        
        bot.edit_message_text(f"🛠 **Managing:** `{btn_text}`", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
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
            markup.row(KeyboardButton('🏦 Deposit'), KeyboardButton('❌ Cancel Action'))
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
            w_var = meta.get('w_var')
            
            user_db[user_id][w_var] -= data['amount']
            user_state[user_id] = 'normal'
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "✅ Withdrawal request processed successfully!", reply_markup=get_keyboard(user_id))
        return
        
    elif call.data == 'cb_w_no':
        if user_state.get(user_id) == 'w_action_conf':
            user_state[user_id] = 'normal'
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "❌ Withdrawal cancelled.", reply_markup=get_keyboard(user_id))
        return
    
    if call.data == 'go_back':
        if current_path != 'root':
            parts = current_path.split('/')[:-1]
            new_path = '/'.join(parts) if len(parts) > 1 else 'root'
            user_current_path[user_id] = new_path
            bot.delete_message(call.message.chat.id, call.message.message_id)
            send_path_content(call.message.chat.id, user_id, new_path, is_editing=(user_state.get(user_id) == 'posts_editing'))
            bot.send_message(call.message.chat.id, "📍 Navigation Controls:", reply_markup=get_keyboard(user_id))
        bot.answer_callback_query(call.id)
        return

    if not is_admin:
        return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)

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
        bot.send_message(call.message.chat.id, f"⚙️ **Settings for:** `{target_btn}`", parse_mode="Markdown", reply_markup=get_keyboard(user_id))

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
        bot.edit_message_text(f"🛠 Selected: **{target_btn}**\nChoose an action:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=get_edit_inline_tools())

    bot.answer_callback_query(call.id)

# --- NEW: LIGHTWEIGHT WEB SERVER FOR ADMIN DASHBOARD & UPTIMEROBOT ---
class AdminDashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        # This is strictly for UptimeRobot so it gets a successful ping!
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/':
            try:
                # Serve the index.html file
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
            # Send current admin list to dashboard
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
    
    # Start the Telegram Bot
    print("🚀 Bot is running fast! Press Ctrl+C to stop.")
    bot.infinity_polling(skip_pending=True)
