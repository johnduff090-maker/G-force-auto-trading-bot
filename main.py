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

# --- NEW GMAIL IMPORTS ---
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

ADMIN_PIN = os.getenv('ADMIN_PIN', '123456')

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', SMTP_USER)

NORTHFLANK_API_KEY = os.getenv('NORTHFLANK_API_KEY', '')
NORTHFLANK_PROJECT = os.getenv('NORTHFLANK_PROJECT', '')
NORTHFLANK_VOLUME = os.getenv('NORTHFLANK_VOLUME', '')

TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY', '')

def _send_email_thread(to_email, subject, html_content):
    if not SMTP_USER or not SMTP_PASS or to_email == 'Not Set':
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = f"G-Force Trading <{SENDER_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['X-Priority'] = '1 (Highest)'
        msg['X-MSMail-Priority'] = 'High'
        msg['Importance'] = 'High'
        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        print(f"📧 BACKGROUND EMAIL SENT: {to_email} | Subject: {subject}")
    except Exception as e:
        print(f"❌ BACKGROUND EMAIL FAILED: {to_email} | Error: {e}")

def send_email_async(to_email, subject, html_content):
    threading.Thread(target=_send_email_thread, args=(to_email, subject, html_content), daemon=True).start()

# --- AIVEN POSTGRESQL DATABASE SYSTEM ---
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_LOADED_SUCCESSFULLY = False

def init_db():
    if not DATABASE_URL:
        print("⚠️ NO DATABASE_URL FOUND! Make sure it is in your Environment Variables.")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
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
        
        DB_LOADED_SUCCESSFULLY = True
        print("✅ Aiven Memory successfully loaded into Bot!")
        
        if result and result[0]:
            data = result[0]
            if 'user_db' in data:
                parsed_user_db = {}
                for k, v in data['user_db'].items():
                    try: parsed_user_db[int(k)] = v
                    except: parsed_user_db[k] = v
                data['user_db'] = parsed_user_db
            return data
    except Exception as e:
        print(f"⚠️ CRITICAL: Error loading from Aiven DB: {e}")
        return {}

def save_database():
    if not DATABASE_URL or not DB_LOADED_SUCCESSFULLY: 
        return 
        
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
        'processed_txids': list(processed_txids),
        'blocked_users': list(blocked_users),
        'block_settings': block_settings,
        'dynamic_stats': dynamic_stats,
        'invite_settings': invite_settings,
        # --- NEW ARCHITECTURE: SAVE MASTER GATEWAY CONFIGS ---
        'subscription_settings': subscription_settings,
        'homepage_bonus_settings': homepage_bonus_settings,
        'deposit_broadcast_settings': deposit_broadcast_settings # <--- ADD THIS LINE
    }
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_state (id, data) 
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE 
            SET data = EXCLUDED.data;
        """, [Json(data_to_save)])
        conn.commit()
        cur.close()
        conn.close()
        print(f"💾 AIVEN AUTO-SAVE: {len(user_db)} users backed up successfully!")
    except Exception as e:
        print(f"⚠️ AIVEN DB SAVE ERROR: {e}")

def auto_save_loop():
    while True:
        time.sleep(10)
        save_database()

init_db()
db_data = load_database()

def fmt_amt(val):
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

user_current_path = {}
user_state = {} 
user_selected_button = {} 
user_clipboard = {}        
user_action_data = {} 
editor_msg_ids = {}

admin_bal_type = {}            
admin_bal_notify = {}          
admin_bal_comment_on = {}      
admin_bal_target = {}          
admin_bal_comment_text = {}    
user_plan_setup = {}          
pending_deposits = {}
admin_dep_setup = {}
pending_auto_txids = {}
pending_withdrawals = {}

user_db = db_data.get('user_db', {})
menus = db_data.get('menus', {'root': []})
menu_posts = db_data.get('menu_posts', {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]})
btn_metadata = db_data.get('btn_metadata', {})
processed_txids = set(db_data.get('processed_txids', []))

blocked_users = set(db_data.get('blocked_users', []))
block_settings = db_data.get('block_settings', {
    'msg_block': '🚫 You have been blocked by the admin and cannot use this bot.',
    'msg_unblock': '✅ You have been unblocked. Welcome back!'
})

dynamic_stats = db_data.get('dynamic_stats', {
    'investments': 0.0,
    'withdrawn': 0.0,
    'users': 0,
    'last_refresh': 0.0
})

global_ui_settings = db_data.get('global_ui_settings', {'loading_bar_style': '1', 'loading_bar_time': 3.0})

global_messages_setup = db_data.get('global_messages_setup', {
    'hourly_dm': '💰You have received +{hourly_amount} USDT hourly profits.\nTime left: {time_left}',
    'expiry_dm': '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed',
    'ref_join_msg': '🎉 1 user joined via your link!',
    'ref_commission_msg': '💵 You received +{amount} USDT from your referral activity!',
    'level_up_msg': '🎉 Congratulations! You reached Referral Level {level} and earned {reward} USDT!',
    'admin_change_msg': 'Your {btype} balance is now: <b>{new_bal}</b>'
})

reinvest_settings = db_data.get('reinvest_settings', {
    'msg_success': '✅ <b>Reinvest Successful!</b>\nYou have successfully reinvested <b>$%amount%</b> into <b>%plan_name%</b>.',
    'msg_fail': '❌ You can not invest right now: You need at least %min_amount% USDT to invest!',
    'inline_deposit_text': '🏦 Deposit Now'
})

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
    'msg_fail': '⏳ You have already claimed your bonus. Please wait %time_left%.',
    'require_email': True,
    'msg_email_req': '⚠️ <b>Email Required</b>\n\nTo claim your free bonus, you must safely link an email address to your account. Please reply with your email address now:'
})

bot_plans = db_data.get('bot_plans', {})

if not bot_plans:
    for i in range(6):
        name_str = 'G-Force Free Plan' if i == 0 else f'G-Force Plan {i}'
        bot_plans[f'plan{i}'] = {
            'name': name_str, 'min': 10.0, 'max': 1000.0, 'length': 24.0, 'profit': 5.0,
            'text': f'✨ <b>{name_str} Description</b> ✨\n\nEdit this in Admin -&gt; Plans.',
            'photo': None, 'inline_text': '🛒 Purchase Plan', 'inline_active_text': '(Active ✅)', 
            'redirect_cmd': None, 'is_free': (i == 0), 'bonus_amount': 50.0 if i == 0 else 0.0
        }

# --- NEW ARCHITECTURE: FORCED SUBSCRIPTION & HOMEPAGE CONFIGS ---
subscription_settings = db_data.get('subscription_settings', {
    'enabled': False,
    'target_mode': 'all', # 'new', 'all', 'referrals'
    'channels': [], # Format: [{'name': 'Group 1', 'url': 'https...', 'chat_id': '-100...'}]
    'check_time_hours': 24.0,
    'msg_wall': '🚨 <b>Mandatory Subscription Required</b>\n\nTo use this bot, you must join our official community channels.',
    'msg_fail': '❌ You have not joined all required channels. Please join them and try again.',
    'btn_check': '✅ I have joined, check now'
})

homepage_bonus_settings = db_data.get('homepage_bonus_settings', {
    'enabled': False,
    'btn_text': '🎁 Claim Free Capital'
})

# --- NEW: LIVE CHANNEL BROADCAST SETTINGS ---
deposit_broadcast_settings = db_data.get('deposit_broadcast_settings', {
    'enabled': False,
    'channel_id': None,
    'template': "<b>🟢 NEW DEPOSIT DETECTED 🟢</b>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>User ID:</b> <code>{user_id}</code>\n🌐 <b>Network:</b> {network}\n💵 <b>Amount:</b> ${amount}\n💎 <b>Status:</b> Confirmed & Active\n🔗 <b>Hash/Ref:</b>\n<code>{short_hash}</code>\n━━━━━━━━━━━━━━━━━━━\n<i>🚀 Capital successfully added to trading pool.</i>"
})

def preload_core_languages():
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

# --- ADMIN DEPOSIT MENU CONTROLS ---
    if state == 'admin_dep_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📣 Live Deposit Channel':
            user_state[user_id] = 'admin_live_channel'
            bot.send_message(message.chat.id, "⚙️ <b>Live Deposit Broadcaster Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        else:
            curr_key = text.strip().upper().replace(' ', '_')
            if curr_key in deposit_settings:
                admin_dep_setup[user_id] = curr_key
                user_state[user_id] = 'admin_dep_settings'
                clean_name = curr_key.replace('_', ' ')
                bot.send_message(message.chat.id, f"🏦 <b>Editing Settings for {clean_name}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- NEW: LIVE CHANNEL BROADCAST ROUTING ---
    if state == 'admin_live_channel':
        if text == '🔙 Back to Deposit Menu':
            user_state[user_id] = 'admin_dep_menu'
            bot.send_message(message.chat.id, "🏦 <b>Deposit Architecture Menu</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text.startswith('Toggle Broadcast'):
            deposit_broadcast_settings['enabled'] = not deposit_broadcast_settings.get('enabled', False)
            bot.send_message(message.chat.id, "✅ Deposit Broadcaster toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Set Target Channel':
            user_state[user_id] = 'wait_live_channel_id'
            bot.send_message(message.chat.id, "Enter the Telegram Channel ID (e.g., -1001234567890):", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Receipt Text':
            user_state[user_id] = 'wait_live_receipt_msg'
            current_msg = deposit_broadcast_settings.get('template')
            bot.send_message(message.chat.id, f"Enter your new receipt template.\n\n<b>Available Tags:</b>\n{{user_id}}\n{{network}}\n{{amount}}\n{{short_hash}}\n\n<b>Current Template:</b>\n{current_msg}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return
        
    if state == 'wait_live_channel_id':
        deposit_broadcast_settings['channel_id'] = text.strip()
        user_state[user_id] = 'admin_live_channel'
        bot.send_message(message.chat.id, "✅ Channel ID successfully updated. Ensure the bot is an Admin in that channel!", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_live_receipt_msg':
        deposit_broadcast_settings['template'] = formatted_text
        user_state[user_id] = 'admin_live_channel'
        bot.send_message(message.chat.id, "✅ Custom receipt template updated.", reply_markup=get_keyboard(user_id))
        return

    # --- REGULAR DEPOSIT SETTINGS ROUTING ---
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
        elif state == 'dep_setup_enter': deposit_settings[curr]['msg_enter'] = formatted_text
        elif state == 'dep_setup_instruct': deposit_settings[curr]['msg_instruct'] = formatted_text
        elif state == 'dep_setup_pending': deposit_settings[curr]['msg_pending'] = formatted_text
        elif state == 'dep_setup_success': deposit_settings[curr]['msg_success'] = formatted_text
        elif state == 'dep_setup_min':
            try: deposit_settings[curr]['min'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
        elif state == 'dep_setup_max':
            try: deposit_settings[curr]['max'] = float(text)
            except ValueError: return bot.send_message(message.chat.id, "⚠️ Invalid amount. Please enter numbers only.")
        
        user_state[user_id] = 'admin_dep_settings'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

def get_default_metadata():
    return {
        'random_message': False, 'admin_only': False, 'invisible': False,
        'command': None, 'move_by_command': False, 'withdrawal': False, 
        'is_wallet': False, 'is_bonus': False, 'is_balance': False,
        'assigned_plan': None, 'is_calculator': False, 'is_history': False,
        'is_language': False, 'is_reinvest': False, 'is_stats': False,
        'is_info': False, 'is_invite': False, 'is_deposit': False, 'is_live_trading': False
    }

def init_user_db(message):
    user_id = message.from_user.id
    is_new_user = False
    if user_id not in user_db:
        is_new_user = True
        user_db[user_id] = {
            'balance': 0.00, 'bonus': 0.00, 'deposit': 0.00, 
            'hourly': 0.00, 'plan': 0.00, 'address': 'Not Set',
            'wallet': 'Not Set', 'wallet_net': 'Not Set', 'email': 'Not Set', 'last_bonus_time': 0.0, 
            'first_name': message.from_user.first_name or 'Unknown',
            'last_name': message.from_user.last_name or '',
            'username': message.from_user.username or 'No Username',
            'active_plans': [], 'pending_plan': None, 'wallets': {},
            'transactions': [], 'ref_count': 0, 'total_withdrawn': 0.0,
            'lang': 'en', 'referred_by': None, 'team_deposits': 0.0,
            'affiliate_earnings': 0.0, 'claimed_levels': [], 'invite_links_map': [],
            # --- NEW ARCHITECTURE: HIDDEN MARKERS ---
            'sub_verified': False, 'last_sub_check': 0.0, 'has_seen_homepage': False, 'is_referral': False, 'has_claimed_free_plan': False,
            'is_fully_registered': False, 'pending_inviter': None
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
        
        if 'sub_verified' not in user_db[user_id]: user_db[user_id]['sub_verified'] = False
        if 'last_sub_check' not in user_db[user_id]: user_db[user_id]['last_sub_check'] = 0.0
        if 'has_seen_homepage' not in user_db[user_id]: user_db[user_id]['has_seen_homepage'] = False
        if 'is_referral' not in user_db[user_id]: user_db[user_id]['is_referral'] = False
        if 'has_claimed_free_plan' not in user_db[user_id]: user_db[user_id]['has_claimed_free_plan'] = False
        if 'is_fully_registered' not in user_db[user_id]: user_db[user_id]['is_fully_registered'] = False
        if 'pending_inviter' not in user_db[user_id]: user_db[user_id]['pending_inviter'] = None
    
    return is_new_user

# --- NEW ARCHITECTURE: THE ENFORCER (BACKGROUND SUBSCRIPTION RETENTION) ---
def subscription_enforcer_loop():
    """Silently revokes access from users who join to pass the wall, then leave 10 minutes later."""
    while True:
        time.sleep(3600) # Runs every hour silently
        if not subscription_settings.get('enabled', False) or subscription_settings.get('check_time_hours', 0) == 0:
            continue
        
        cooldown_sec = subscription_settings['check_time_hours'] * 3600
        now = time.time()
        
        for uid, udata in list(user_db.items()):
            if uid in ADMIN_IDS: continue
            if udata.get('sub_verified', False):
                if (now - udata.get('last_sub_check', 0.0)) >= cooldown_sec:
                    all_joined = True
                    for ch in subscription_settings.get('channels', []):
                        try:
                            member = bot.get_chat_member(ch['chat_id'], uid)
                            if member.status in ['left', 'kicked']:
                                all_joined = False
                                break
                        except Exception:
                            pass # Failsafe against API limits or bot lacking admin rights
                    
                    if not all_joined:
                        user_db[uid]['sub_verified'] = False # The Silent Trap
                    else:
                        user_db[uid]['last_sub_check'] = now

threading.Thread(target=subscription_enforcer_loop, daemon=True).start()

# --- NEW ARCHITECTURE: THE INTERCEPTOR LOGIC ---
def requires_subscription_wall(user_id, is_new_user):
    """The Master Gateway check. Evaluates Target Modes to determine who hits the wall."""
    if not subscription_settings.get('enabled', False): return False
    
    # THE FIX: If the admin turned the wall ON but forgot to add channels, bypass it.
    if not subscription_settings.get('channels', []): return False 
    
    # THE FIX: Admins automatically bypass the wall! (If you tested with an admin account, it lets you in).
    if user_id in ADMIN_IDS: return False
    
    udata = user_db.get(user_id, {})
    if udata.get('sub_verified', False): return False
        
    mode = subscription_settings.get('target_mode', 'all')
    
    is_effectively_new = is_new_user or not udata.get('is_fully_registered', False)
    
    if mode == 'new' and not is_effectively_new:
        return False
    if mode == 'referrals' and not udata.get('is_referral', False):
        return False
        
    return True

def deploy_subscription_wall(chat_id, user_id):
    """Deploys the un-bypassable Multi-Channel UI wall."""
    udata = user_db.get(user_id, {})
    lang = udata.get('lang', 'en')
    markup = InlineKeyboardMarkup()
    
    for ch in subscription_settings.get('channels', []):
        markup.row(InlineKeyboardButton(ch['name'], url=ch['url']))
        
    btn_text = get_tl_and_map(subscription_settings.get('btn_check', '✅ I have joined, check now'), lang)
    markup.row(InlineKeyboardButton(btn_text, callback_data="cb_verify_sub"))
    
    msg_text = get_tl_and_map(subscription_settings.get('msg_wall'), lang)
    bot.send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=markup)

# --- NEW ARCHITECTURE: HOMEPAGE BONUS ROUTING ---
def check_homepage_bonus(chat_id, user_id):
    """The frictionless, one-time popup bridge."""
    if not homepage_bonus_settings.get('enabled', False): return False
    udata = user_db.get(user_id, {})
    if udata.get('has_seen_homepage', False): return False
    
    p_data = bot_plans.get('plan0', {})
    if not p_data: return False
    
    lang = udata.get('lang', 'en')
    
    # --- THE FIX: Pull the exact Plan 0 text and process all macros ---
    raw_msg = p_data.get('text', f"✨ <b>{p_data['name']}</b> ✨\n\nProfit: {p_data['profit']}%\nBonus Capital: ${p_data.get('bonus_amount', 50.0)}\nContract: Lifetime")
    msg = replace_macros(raw_msg, user_id, 'root')
    
    btn_text = get_tl_and_map(homepage_bonus_settings.get('btn_text', '🎁 Claim Free Capital'), lang)
    
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(btn_text, callback_data="cb_claim_homepage"))
    
    # Send it WITH their custom photo if they uploaded one in Admin -> Plans!
    try:
        if p_data.get('photo'):
            bot.send_photo(chat_id, p_data['photo'], caption=get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(chat_id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        print(f"Homepage Bonus Render Error: {e}")
        bot.send_message(chat_id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=markup)
        
    return True

def get_crypto_price(currency_code):
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

def generate_user_wallet(user_id, currency):
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
        
        if currency == 'BTC':
            private_key = bip44_acc.PrivateKey().ToWif()
        else:
            private_key = bip44_acc.PrivateKey().Raw().ToHex()
        
        return public_address, private_key
    except Exception as e:
        print(f"Wallet Gen Error: {e}")
        return "GEN_ERROR", "GEN_ERROR"

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

def check_address_for_new_deposit(addr, curr):
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

def blockchain_watcher_loop():
    while True:
        try:
            for uid, data in list(user_db.items()):
                for curr, w_data in list(data.get('wallets', {}).items()):
                    addr = w_data['address']
                    found, crypto_amount, txid, tx_time = check_address_for_new_deposit(addr, curr)
                    
                    if found and txid not in processed_txids:
                        now = time.time()
                        
                        if (now - tx_time) >= 300:
                            processed_txids.add(txid)
                            
                            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
                            usd_value = crypto_amount * live_price
                            
                            user_db[uid]['deposit'] += usd_value
                            user_db[uid]['wallets'][curr]['total_deposited'] = user_db[uid]['wallets'][curr].get('total_deposited', 0.0) + usd_value
                            log_tx(uid, f"Auto-Deposit ({curr})", usd_value)
                            
                            process_referral_commission(uid, usd_value, is_deposit=True)
                            
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
                            
                            # --- LIVE CHANNEL HOOK ---
                            broadcast_real_deposit(uid, usd_value, curr.replace('_', ' '), txid)

                            user_email = user_db.get(uid, {}).get('email', 'Not Set')
                            if user_email != 'Not Set':
                                dep_subject = "Deposit Confirmed - G-Force"
                                dep_html = f"""
                                <div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
                                    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
                                        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
                                    </div>
                                    <div style="padding: 30px;">
                                        <h3 style="margin-top: 0; color: #ffffff;">Deposit Confirmed</h3>
                                        <p>Your deposit has been successfully credited to your account.</p>
                                        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
                                            <p style="margin: 5px 0; color: #848e9c;">Asset: <span style="color: #ffffff; float: right; font-weight: bold;">{curr.replace('_', ' ')}</span></p>
                                            <p style="margin: 5px 0; color: #848e9c;">Amount: <span style="color: #0ecb81; float: right; font-weight: bold;">+{fmt_amt(crypto_amount)}</span></p>
                                            <p style="margin: 5px 0; color: #848e9c;">USD Value: <span style="color: #ffffff; float: right; font-weight: bold;">${fmt_amt(usd_value)}</span></p>
                                        </div>
                                        <p style="color: #848e9c; font-size: 12px; word-break: break-all;">TXID: {txid}</p>
                                    </div>
                                </div>
                                """
                                send_email_async(user_email, dep_subject, dep_html)
                            
        except Exception as e:
            print(f"Watcher Loop Error: {e}")
            pass
        time.sleep(30)

def check_and_trigger_auto_buy(user_id):
    if not user_db[user_id].get('pending_plan'): return
    p_macro = user_db[user_id]['pending_plan']
    if p_macro in bot_plans:
        p_data = bot_plans[p_macro]
        
        if p_data.get('is_free', False) or p_macro == 'plan0':
            # --- FREE PLAN LOOPHOLE FIX ---
            if user_db[user_id].get('has_claimed_free_plan', False) or any(p['macro'] == p_macro for p in user_db[user_id].get('active_plans', [])):
                user_db[user_id]['has_claimed_free_plan'] = True
                user_db[user_id]['pending_plan'] = None
                return
            invest_amt = p_data.get('bonus_amount', 50.0) if p_macro == 'plan0' else p_data.get('min', 0.0)
            user_db[user_id]['pending_plan'] = None
            user_db[user_id]['has_claimed_free_plan'] = True
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

                user_email = u.get('email', 'Not Set')
                if user_email != 'Not Set':
                    exp_subject = "Trading Plan Completed - G-Force"
                    p_name = bot_plans.get(p['macro'], {}).get('name', 'Plan')
                    exp_html = f"""
                    <div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
                        <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
                            <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
                        </div>
                        <div style="padding: 30px;">
                            <h3 style="margin-top: 0; color: #ffffff;">Trading Completed</h3>
                            <p>Your investment in <b>{p_name}</b> has successfully finished its cycle.</p>
                            <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
                                <p style="margin: 5px 0; color: #848e9c;">Initial Capital: <span style="color: #ffffff; float: right; font-weight: bold;">${fmt_amt(p['amount'])}</span></p>
                                <p style="margin: 5px 0; color: #848e9c;">Total Profit Earned: <span style="color: #0ecb81; float: right; font-weight: bold;">+${fmt_amt(p['earned'])}</span></p>
                            </div>
                            <p style="color: #848e9c; font-size: 14px;">Your funds are now available in your withdrawal balance.</p>
                        </div>
                    </div>
                    """
                    send_email_async(user_email, exp_subject, exp_html)

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

def refresh_dynamic_stats():
    now = time.time()
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
    
    t = t.replace('%plan_invest%', f"{fmt_amt(plan_invest)}")
    t = t.replace('%hourly_profit%', f"{fmt_amt(hourly_profit)}")
    t = t.replace('%plan_names%', plan_names)
    t = t.replace('%ref_count%', str(ref_count))
    t = t.replace('%withdrawn%', f"{fmt_amt(total_withdrawn)}")
    t = t.replace('%team_deposits%', f"{fmt_amt(bals.get('team_deposits', 0))}")
    t = t.replace('%affiliate_earnings%', f"{fmt_amt(bals.get('affiliate_earnings', 0))}")
    
    if '%trade_runtime%' in t or '%trade_profit%' in t or '%trade_anim_bar%' in t or '%trade_pct%' in t:
        if active:
            oldest_plan = min(active, key=lambda x: x['start_time'])
            elapsed = time.time() - oldest_plan['start_time']
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            runtime_str = f"{int(h):02d}h {int(m):02d}m {int(s):02d}s"

            live_profit = 0.0
            for p in active:
                profit_per_sec = (p['amount'] * (p['profit_pct'] / 100.0)) / 3600.0
                plan_elapsed = time.time() - p['start_time']
                live_profit += plan_elapsed * profit_per_sec

            bar_states = ["[■■■■■■▯▯▯▯]", "[▯■■■■■■▯▯▯]", "[▯▯■■■■■■▯▯]"]
            bar_anim = bar_states[int(time.time()) % 3]

            if oldest_plan['length_hours'] > 0:
                total_sec = oldest_plan['length_hours'] * 3600
                pct = min((elapsed / total_sec) * 100, 100.0)
                pct_str = f"{pct:.2f}% to Completion"
            else:
                pct_str = "Lifetime Contract (Running)"
        else:
            runtime_str = "00h 00m 00s"
            live_profit = 0.0
            bar_anim = "[▯▯▯▯▯▯▯▯▯▯]"
            pct_str = "No Active Plans"

        t = t.replace('%trade_runtime%', runtime_str)
        t = t.replace('%trade_profit%', f"+{live_profit:.6f} USDT")
        t = t.replace('%trade_anim_bar%', bar_anim)
        t = t.replace('%trade_pct%', pct_str)
    
    bot_info = bot.get_me()
    t = t.replace('%ref_link%', f"https://t.me/{bot_info.username}?start={user_id}")
    
    if '%levels_display%' in t:
        levels_str = ""
        for i, level in enumerate(invite_settings['levels']):
            req = level['users']
            current = min(bals.get('ref_count', 0), req)
            pct = int((current / req) * 10) if req > 0 else 10
            bar = "■" * pct + "▯" * (10 - pct)
            levels_str += f"{i+1}° Level: [{bar}] {req} users\n"
        t = t.replace('%levels_display%', levels_str)
    
    t = t.replace('%stats_invest%', f"{dynamic_stats['investments']:,.2f}")
    t = t.replace('%stats_withdrawn%', f"{dynamic_stats['withdrawn']:,.2f}")
    t = t.replace('%stats_users%', str(dynamic_stats['users']))
    
    t = t.replace('%wallet%', bals.get('wallet', 'Not Set'))
    t = t.replace('%email%', bals.get('email', 'Not Set'))
    t = t.replace('%bonus_amount%', str(global_bonus_setup['amount']))
    t = t.replace('%commission%', str(global_w_setup.get('w_commission', 0.0)))
    
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
        
    if '%ascii_receipt%' in t:
        if global_w_setup.get('use_ascii_receipt', False):
            tx_full = action_data.get('txid', 'N/A') if action_data else 'N/A'
            tx_short = tx_full[:11] + "..." if len(tx_full) > 11 else tx_full
            u_name = bals.get('username', 'Unknown')
            if len(u_name) > 13: u_name = u_name[:10] + "..."
            
            w_amt = fmt_amt(action_data.get('amount', 0)) if action_data else "0.00"
            n_str = action_data.get('network', bals.get('wallet_net', 'Unknown')) if action_data else bals.get('wallet_net', 'Unknown')
            if len(n_str) > 14: n_str = n_str[:11] + "..."
            
            ascii_box = (
                "<pre>\n"
                "╔════════════════════════════╗\n"
                "║    G-FORCE PAYOUT LOG      ║\n"
                "╠════════════════════════════╣\n"
                f"║ TXID:   {tx_short:<18} ║\n"
                f"║ USER:   @{u_name:<17} ║\n"
                "║                            ║\n"
                f"║ WITHDRAWAL: ${w_amt:<13} ║\n"
                f"║ NETWORK:  {n_str:<16} ║\n"
                "║ FEE:    $0.00              ║\n"
                "╠════════════════════════════╣\n"
                "║       [ STATUS: PAID ]     ║\n"
                "╚════════════════════════════╝\n"
                "</pre>"
            )
            t = t.replace('%ascii_receipt%', ascii_box)
        else:
            t = t.replace('%ascii_receipt%', '')
            
    return t

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

def execute_loading_animation(chat_id, msg_id, part_a, style_opt, is_photo, total_seconds):
    frames = {
        '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
        '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
        '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
    }
    all_bars = frames.get(str(style_opt), frames['1'])
    
    if total_seconds <= 0.5:
        bars = [all_bars[-1]]
    elif total_seconds <= 1.5:
        bars = [all_bars[0], all_bars[-1]]
    elif total_seconds <= 2.5:
        bars = [all_bars[0], all_bars[len(all_bars)//2], all_bars[-1]]
    else:
        bars = all_bars

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
            
    time.sleep(0.1)
    try: bot.delete_message(chat_id, msg_id)
    except: pass

def execute_live_trading_animation(chat_id, msg_id, user_id, base_text, full_path, is_photo=False):
    for _ in range(30):
        time.sleep(1.0)
        try:
            lang = user_db.get(user_id, {}).get('lang', 'en')
            updated_text = get_tl_and_map(replace_macros(base_text, user_id, full_path), lang)
            if is_photo:
                bot.edit_message_caption(caption=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                bot.edit_message_text(text=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "deleted" in err_str:
                break
            pass

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
        total_loading_time = float(global_ui_settings.get('loading_bar_time', 3.0))
        part_a = ""
        final_text = ""
        
        match = re.search(r'%loading_bar(?:_(\d+(?:\.\d+)?)s)?%', raw_text)
        if match:
            has_loading_macro = True
            if match.group(1):
                total_loading_time = float(match.group(1))
            part_a = raw_text[:match.start()].strip()
            part_b = raw_text[match.end():].strip()
            final_text = part_a + ("\n\n" if part_a and part_b else "") + part_b
            
            if is_editing:
                final_text = raw_text
        else:
            final_text = raw_text
            
        style = global_ui_settings.get('loading_bar_style', '1')
        
        if has_loading_macro and not is_editing:
            sep = "\n\n" if part_a else ""
            bars = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "░░░░░░░░░░ 0%", "▒▒▒▒▒▒▒▒▒▒ 0%"]
            initial_bar = bars[int(style)-1] if style in ['1', '2', '3'] else bars[0]
            temp_msg_text = f"{part_a}{sep}♻️ <b>LOADING...</b>\n{initial_bar}"
            
            try:
                if p['type'] == 'photo':
                    temp_msg = bot.send_photo(chat_id, p['photo'], caption=temp_msg_text, parse_mode="HTML")
                else:
                    temp_msg = bot.send_message(chat_id, temp_msg_text, parse_mode="HTML")
                execute_loading_animation(chat_id, temp_msg.message_id, part_a, style, p['type'] == 'photo', total_loading_time)
            except: pass
            
        if has_loading_macro and not final_text and not p.get('custom_inlines') and not p.get('photo'):
            if not (i == len(posts) - 1 and not kb_attached and reply_keyboard):
                continue
        
        markup = InlineKeyboardMarkup()
        custom_inlines = p.get('custom_inlines', [])
        
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
            
        if i == len(posts) - 1 and not markup and not kb_attached and reply_keyboard:
            markup = reply_keyboard
            kb_attached = True
        
        try:
            if p['type'] == 'photo':
                cap = final_text if final_text else None
                sent = bot.send_photo(chat_id, p['photo'], caption=cap, parse_mode="HTML", reply_markup=markup)
                if meta.get('is_live_trading') and not is_editing:
                    threading.Thread(target=execute_live_trading_animation, args=(chat_id, sent.message_id, user_id, p['text'], path, True), daemon=True).start()
            else:
                safe_text = final_text if final_text else " "
                sent = bot.send_message(chat_id, safe_text, parse_mode="HTML", reply_markup=markup)
                if meta.get('is_live_trading') and not is_editing:
                    threading.Thread(target=execute_live_trading_animation, args=(chat_id, sent.message_id, user_id, p['text'], path, False), daemon=True).start()
                
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)
                
        except Exception as e:
            err_msg = f"⚠️ <b>Error rendering post:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>Fix or delete this using the buttons below!</i>"
            sent = bot.send_message(chat_id, err_msg, parse_mode="HTML", reply_markup=markup)
            if is_editing: editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

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
    livet_text = "☑️ On" if meta.get('is_live_trading') else "⬜️ Off"
    
    markup.row(KeyboardButton(f'Random Message ({rm_text})'), KeyboardButton(f'Admin Only ({ao_text})'))
    markup.row(KeyboardButton(f'Invisible ({inv_text})'))
    markup.row(KeyboardButton('Assign Command'), KeyboardButton('Assign Plan'), KeyboardButton('Assign Language')) 
    markup.row(KeyboardButton(f'Assign Calculator ({calc_text})'), KeyboardButton(f'Assign History ({hist_text})'))
    markup.row(KeyboardButton(f'Assign Withdrawal ({w_text})'), KeyboardButton(f'Assign Deposit ({dep_text})'))
    markup.row(KeyboardButton(f'Assign Bonus ({bon_text})'), KeyboardButton(f'Assign Wallet ({wal_text})'))
    markup.row(KeyboardButton(f'Assign Balance ({bal_text})'), KeyboardButton(f'Assign Stats ({stat_text})'))
    markup.row(KeyboardButton(f'Assign Reinvest ({reinv_text})'), KeyboardButton(f'Assign Invite ({invt_text})'))
    markup.row(KeyboardButton(f'Assign Info ({info_text})'), KeyboardButton(f'Assign Live Trading ({livet_text})'))
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
    email_req = "☑️ On" if global_bonus_setup.get('require_email', True) else "⬜️ Off"
    markup.row(KeyboardButton('💰 Set Amount'), KeyboardButton('⏱ Set Cooldown (hrs)'))
    markup.row(KeyboardButton('💬 Edit Success Msg'), KeyboardButton('💬 Edit Fail Msg'))
    markup.row(KeyboardButton('💰 Min Auto-Transfer'), KeyboardButton(f'📧 Toggle Email ({email_req})'))
    markup.row(KeyboardButton('💬 Edit Email Req Text'), KeyboardButton('🔙 Back to Admin'))
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
            # --- NEW ARCHITECTURE: MASTER GATEWAYS ADDED TO ADMIN UI ---
            markup.row(KeyboardButton('🧱 Forced Sub Wall'), KeyboardButton('🎁 Homepage Pop-Up'))
            markup.row(KeyboardButton('📊 Bot Stats'), KeyboardButton('🧹 Data Wipe Dashboard'))
            markup.row(KeyboardButton('🔙 Back to Main'))
            return markup
            
        # --- NEW ARCHITECTURE: ADMIN UI BUILDERS ---
        if state == 'admin_sub_wall':
            wall_status = "☑️ On" if subscription_settings.get('enabled') else "⬜️ Off"
            markup.row(KeyboardButton(f'Toggle Wall ({wall_status})'), KeyboardButton('Set Target Mode'))
            markup.row(KeyboardButton('Add Required Channel'), KeyboardButton('Remove Channel'))
            markup.row(KeyboardButton('📋 View Channels'))
            markup.row(KeyboardButton('Edit Wall Message'), KeyboardButton('Edit Fail Msg'))
            markup.row(KeyboardButton('Edit Button Text'), KeyboardButton('Set Cooldown Check'))
            markup.row(KeyboardButton('👀 Check User API Sweep'), KeyboardButton('🔙 Back to Admin'))
            return markup
            
        if state == 'admin_homepage_bonus':
            markup.row(KeyboardButton('Toggle Pop-Up On/Off'), KeyboardButton('Edit Button Text'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup
            
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
            markup.row(KeyboardButton('📣 Live Deposit Channel'))
            markup.row(KeyboardButton('🔙 Back to Admin'))
            return markup

        if state == 'admin_live_channel':
            status = "☑️ On" if deposit_broadcast_settings.get('enabled') else "⬜️ Off"
            markup.row(KeyboardButton(f'Toggle Broadcast ({status})'))
            markup.row(KeyboardButton('Set Target Channel'), KeyboardButton('Edit Receipt Text'))
            markup.row(KeyboardButton('🔙 Back to Deposit Menu'))
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

        # Add Gateway states to cancellation bypasses
        if state.startswith('dep_setup_') or state.startswith('wallet_setup_') or state.startswith('bonus_setup_') or state.startswith('reinvest_setup_') or state.startswith('msg_setup_') or state in ['admin_loading_time', 'wait_invite_msg', 'wait_invite_levels', 'wait_ref_bonus_pct', 'wait_support_msg', 'wait_payout_popup'] or state.startswith('wait_block_') or state.startswith('wait_edit_block') or state.startswith('wait_edit_unblock') or state in ['admin_broadcast_input', 'bc_wait_text', 'wait_wipe_id', 'wait_general_wipe_confirm'] or state.startswith('wait_sub_') or state.startswith('wait_home_'):
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
                
            markup.row(KeyboardButton('✏️ Rename Plan'))
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

    if state in ['buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg', 'bonus_wait_email']:
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

def finalize_user_registration(user_id):
    """The master engine that triggers only when a user successfully enters the bot."""
    udata = user_db.get(user_id)
    if not udata or udata.get('is_fully_registered', False): return
    
    udata['is_fully_registered'] = True
    inviter_id = udata.get('pending_inviter')
    
    # Process Referral Pay & Notifications NOW
    if inviter_id and inviter_id in user_db and inviter_id != user_id:
        udata['referred_by'] = inviter_id
        user_db[inviter_id]['ref_count'] += 1
        try:
            lang = user_db[inviter_id].get('lang', 'en')
            bot.send_message(inviter_id, get_tl_and_map(global_messages_setup['ref_join_msg'], lang))
        except: pass
        
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

    # Alert the Admin NOW
    total_verified_users = len([u for u, d in user_db.items() if d.get('is_fully_registered', False)])
    alert_msg = (
        f"🆕 New User Fully Verified!\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Total Verified: [{total_verified_users}]\n"
        f"Name: {udata.get('first_name', 'Unknown')}"
    )
    if udata.get('referred_by'):
        alert_msg += f"\nReferred by: <code>{udata['referred_by']}</code>"
        
    for admin in ADMIN_IDS:
        try: bot.send_message(admin, alert_msg, parse_mode="HTML")
        except: pass
        
    threading.Thread(target=preload_core_languages, daemon=True).start()

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return

    parts = message.text.split()
    payload = parts[1] if len(parts) > 1 else None

    frames = ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"]
    try:
        loading_msg = bot.send_message(message.chat.id, "♻️ <b>INITIALIZING SYSTEM...</b>\n[▯▯▯▯▯▯▯▯▯▯] 0%", parse_mode="HTML")
        time.sleep(0.4) # Reduced sleep to free up bot threads
        bot.edit_message_text("♻️ <b>INITIALIZING SYSTEM...</b>\n[■■■■■■■■■■] 100%", chat_id=message.chat.id, message_id=loading_msg.message_id, parse_mode="HTML")
        time.sleep(0.2)
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    is_new = init_user_db(message)
    inviter_id = None
    
    if payload:
        if payload.isdigit():
            inviter_id = int(payload)
        else:
            for uid, udata in user_db.items():
                if payload in udata.get('invite_links_map', []):
                    inviter_id = uid
                    break
            if not inviter_id and payload.startswith('gf_'):
                potential_username = payload[3:]
                for uid, udata in user_db.items():
                    if str(uid) == potential_username or udata.get('username', '').lower() == potential_username.lower():
                        inviter_id = uid
                        break
                        
    if is_new and inviter_id:
        user_db[user_id]['pending_inviter'] = inviter_id
        user_db[user_id]['is_referral'] = True # Critical for "Referrals Only" gateway mode

    # --- NEW ARCHITECTURE: MASTER INTERCEPTOR (TRAPS USER AT SUB WALL) ---
    if requires_subscription_wall(user_id, is_new):
        deploy_subscription_wall(message.chat.id, user_id)
        return

    # --- NEW ARCHITECTURE: HOMEPAGE POPUP BRIDGE (TRAPS USER AT BONUS) ---
    if check_homepage_bonus(message.chat.id, user_id):
        return

    # IF BOTH WALLS ARE OFF, FINALIZE REGISTRATION IMMEDIATELY
    finalize_user_registration(user_id)

    user_current_path[user_id] = 'root'
    user_state[user_id] = 'normal'
    user_selected_button[user_id] = None
    
    send_path_content(message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))


@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    
    if user_id in blocked_users:
        lang = user_db.get(user_id, {}).get('lang', 'en')
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return
    
    formatted_text = extract_html(message)
    is_admin = user_id in ADMIN_IDS
    
    is_new = init_user_db(message)

    # --- NEW ARCHITECTURE: MASTER INTERCEPTOR (ENFORCES GATEWAY ON ALL TEXT COMMANDS) ---
    if requires_subscription_wall(user_id, is_new):
        try: bot.delete_message(message.chat.id, message.message_id) # Erase what they tried to do
        except: pass
        deploy_subscription_wall(message.chat.id, user_id)
        return

    # --- NEW ARCHITECTURE: HOMEPAGE POPUP BRIDGE (ENFORCES CLAIM ON ALL TEXT COMMANDS) ---
    if check_homepage_bonus(message.chat.id, user_id):
        try: bot.delete_message(message.chat.id, message.message_id) # Erase what they tried to do
        except: pass
        return

    # IF THEY PASS BOTH GATES (OR BOTH ARE OFF), ENSURE THEY ARE FINALIZED
    finalize_user_registration(user_id)

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
    
    if lang != 'en':
        if text in REVERSE_TL_MAP.get(lang, {}):
            text = REVERSE_TL_MAP[lang][text]
        else:
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

    if not is_admin and user_state[user_id] not in ['w_action_amount', 'w_action_addr', 'dep_wait_amount', 'dep_wait_proof', 'buyplan_wait_amount', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount', 'wait_support_msg', 'bonus_wait_email']: 
        user_state[user_id] = 'normal'
        
    current_path = user_current_path[user_id]
    state = user_state[user_id]
    selected_btn = user_selected_button.get(user_id)
    full_path = f"{current_path}/{selected_btn}" if selected_btn else None

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
        elif state == 'bonus_wait_email':
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("Action cancelled.", lang), reply_markup=get_keyboard(user_id))
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
        # --- NEW ARCHITECTURE: ADMIN GATEWAY SETTINGS CANCEL ROUTES ---
        elif state.startswith('wait_sub_'):
            user_state[user_id] = 'admin_sub_wall'
            bot.send_message(message.chat.id, "Gateway action cancelled.", reply_markup=get_keyboard(user_id))
            return
        elif state.startswith('wait_home_') or state.startswith('wait_live_'):
            user_state[user_id] = 'admin_homepage_bonus' if state.startswith('wait_home_') else 'admin_live_channel'
            bot.send_message(message.chat.id, "Action cancelled.", reply_markup=get_keyboard(user_id))
            return
        else:
            user_state[user_id] = 'normal'
            bot.send_message(message.chat.id, get_tl_and_map("❌ Action Cancelled.", lang), reply_markup=get_keyboard(user_id))
            return

    msg_menu_cmds = ['Edit Hourly DM', 'Edit Expiry DM', 'Edit Ref Join Msg', 'Edit Ref Comm Msg', 'Edit Level Up Msg', 'Edit Admin Change Msg']
    if text in msg_menu_cmds and state.startswith('msg_setup_'):
        user_state[user_id] = 'admin_messages_menu'
        state = 'admin_messages_menu'
        
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
                time.sleep(0.05)
                
            for d in dead_users:
                user_db.pop(d, None)
                if d in blocked_users: blocked_users.remove(d)
                
            bot.send_message(message.chat.id, f"<b>Broadcast Complete.</b>\n✅ Delivered: {sent_count} | ❌ Failed (Blocked/Deleted): {fail_count}", parse_mode="HTML")
            
        threading.Thread(target=send_bc, daemon=True).start()
        return

    if state == 'admin_menu' and text == '📊 Bot Stats':
        bot_info = bot.get_me()
        total_users = len(user_db)
        btn_count = len(btn_metadata)
        msg_count = sum(len(v) for v in menu_posts.values())
        
        stats_msg = f"""📊 <b>BOT STATISTICS</b>
#statistics

@{bot_info.username}
▪️Created: [Auto]

▪️Users: {total_users}
▫️Active: {total_users}
▫️Deleted: 0
▪️Admins: {len(ADMIN_IDS)}

▪️Bot structure:
▫️Buttons: {btn_count} / 200
▫️Messages: {msg_count} / 400"""
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('🔍 Scan', callback_data='cb_scan_users'))
        
        bot.send_message(message.chat.id, stats_msg, parse_mode="HTML", reply_markup=markup)
        return

    if state == 'admin_menu' and text == '🧹 Data Wipe Dashboard':
        user_state[user_id] = 'admin_wipe_menu'
        bot.send_message(message.chat.id, "🧹 <b>Data Wipe Dashboard</b>\n\nChoose an option below:", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_wipe_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            
        elif text == '🧹 Targeted Wipe':
            user_state[user_id] = 'wait_wipe_id'
            bot.send_message(message.chat.id, "Enter the <b>User ID</b> you want to wipe.\n\n<i>Note: This will safely reset their balance, deposits, profits, and plans to 0 while keeping their HD Wallets and settings completely intact.</i>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif text == '☢️ General Wipe (All Users)':
            user_state[user_id] = 'wait_general_wipe_confirm'
            bot.send_message(message.chat.id, "⚠️ <b>NUCLEAR OPTION ACTIVATED</b> ⚠️\n\nThis will reset EVERY user's financial balance (deposits, bonuses, active plans) to 0 across the entire database. HD Wallets, Menus, and API keys will NOT be harmed.\n\nTo proceed, type exactly:\n<code>CONFIRM WIPE</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return
        
    if state == 'wait_wipe_id':
        try:
            target = int(text)
            if target in user_db:
                user_db[target]['balance'] = 0.0
                user_db[target]['deposit'] = 0.0
                user_db[target]['bonus'] = 0.0
                user_db[target]['hourly'] = 0.0
                user_db[target]['active_plans'] = []
                user_db[target]['total_withdrawn'] = 0.0
                user_db[target]['team_deposits'] = 0.0
                user_db[target]['affiliate_earnings'] = 0.0
                
                user_state[user_id] = 'admin_wipe_menu'
                bot.send_message(message.chat.id, f"✅ <b>Targeted Wipe Successful!</b>\nUser <code>{target}</code> balances have been reset to 0.", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "❌ User not found in database. Try again or Cancel.")
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid ID format. Must be numbers only.")
        return
        
    if state == 'wait_general_wipe_confirm':
        if text == 'CONFIRM WIPE':
            for uid in user_db:
                user_db[uid]['balance'] = 0.0
                user_db[uid]['deposit'] = 0.0
                user_db[uid]['bonus'] = 0.0
                user_db[uid]['hourly'] = 0.0
                user_db[uid]['active_plans'] = []
                user_db[uid]['total_withdrawn'] = 0.0
                user_db[uid]['team_deposits'] = 0.0
                user_db[uid]['affiliate_earnings'] = 0.0
                
            user_state[user_id] = 'admin_wipe_menu'
            bot.send_message(message.chat.id, "☢️ <b>GENERAL WIPE COMPLETE</b> ☢️\nEvery single user in the database has had their balances and active plans reset to 0. Infrastructure remains fully operational.", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        else:
            user_state[user_id] = 'admin_wipe_menu'
            bot.send_message(message.chat.id, "❌ Confirmation failed. General Wipe aborted.", reply_markup=get_keyboard(user_id))
        return

    # --- NEW ARCHITECTURE: MASTER ADMIN GATEWAY SETTINGS ---
    if state == 'admin_menu' and text == '🧱 Forced Sub Wall':
        user_state[user_id] = 'admin_sub_wall'
        status = "🟢 Enabled" if subscription_settings.get('enabled') else "🔴 Disabled"
        mode = subscription_settings.get('target_mode', 'all').upper()
        ch_count = len(subscription_settings.get('channels', []))
        bot.send_message(message.chat.id, f"🧱 <b>Forced Subscription Gateway</b>\n\nStatus: {status}\nTarget Mode: {mode}\nRequired Channels: {ch_count}\nBackground Check Cooldown: {subscription_settings.get('check_time_hours')} hrs", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_menu' and text == '🎁 Homepage Pop-Up':
        user_state[user_id] = 'admin_homepage_bonus'
        status = "🟢 Enabled" if homepage_bonus_settings.get('enabled') else "🔴 Disabled"
        btn_txt = homepage_bonus_settings.get('btn_text', 'Claim Bonus')
        bot.send_message(message.chat.id, f"🎁 <b>Homepage Welcome Bonus</b>\n\nStatus: {status}\nButton Text: {btn_txt}\n\n<i>Note: This bridges the gap between /start and the Main Menu perfectly.</i>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_sub_wall':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text.startswith('Toggle Wall'):
            subscription_settings['enabled'] = not subscription_settings.get('enabled', False)
            bot.send_message(message.chat.id, "✅ Wall Status Toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Set Target Mode':
            user_state[user_id] = 'wait_sub_mode'
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton('new'), KeyboardButton('all'), KeyboardButton('referrals'))
            markup.row(KeyboardButton('❌ Cancel Action'))
            bot.send_message(message.chat.id, "Select who this wall applies to:\n\n<b>New:</b> Only fresh /start users\n<b>All:</b> Everyone hits the wall\n<b>Referrals:</b> Only users joining via invite links", parse_mode="HTML", reply_markup=markup)
        elif text == 'Add Required Channel':
            user_state[user_id] = 'wait_sub_channel'
            bot.send_message(message.chat.id, "Send the channel details separated by a pipe (|).\n\nFormat: <code>Button Name | Telegram URL | Chat ID</code>\nExample: <code>Official Channel | https://t.me/example | -100123456789</code>", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Remove Channel':
            subscription_settings['channels'] = []
            bot.send_message(message.chat.id, "🗑 All configured channels have been removed.", reply_markup=get_keyboard(user_id))
        elif text == '📋 View Channels':
            channels = subscription_settings.get('channels', [])
            if not channels:
                bot.send_message(message.chat.id, "No channels are currently required.", reply_markup=get_keyboard(user_id))
            else:
                msg = "📋 <b>Currently Required Channels:</b>\n\n"
                for i, ch in enumerate(channels, 1):
                    msg += f"{i}. <b>{ch['name']}</b>\n   URL: {ch['url']}\n   Chat ID: <code>{ch['chat_id']}</code>\n\n"
                msg += "<i>Note: Ensure the bot is an Admin in all listed channels so it can securely verify members!</i>"
                bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Set Cooldown Check':
            user_state[user_id] = 'wait_sub_time'
            bot.send_message(message.chat.id, "Enter the background retention cooldown in hours (e.g., 24). Enter 0 to disable background sweeps.", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Wall Message':
            user_state[user_id] = 'wait_sub_msg'
            bot.send_message(message.chat.id, f"Enter the new text for the subscription wall:\n\nCurrent:\n{subscription_settings.get('msg_wall')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Fail Msg':
            user_state[user_id] = 'wait_sub_fail'
            bot.send_message(message.chat.id, f"Enter the text shown when verification fails:\n\nCurrent:\n{subscription_settings.get('msg_fail', '❌ You have not joined all channels.')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Button Text':
            user_state[user_id] = 'wait_sub_btn'
            bot.send_message(message.chat.id, f"Enter the text for the Verify inline button:\n\nCurrent: {subscription_settings.get('btn_check', '✅ I have joined')}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '👀 Check User API Sweep':
            user_state[user_id] = 'wait_sub_check_user'
            bot.send_message(message.chat.id, "Enter the Telegram ID of the user you want to manually sweep through the verification logic.", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'wait_sub_mode':
        if text in ['new', 'all', 'referrals']:
            subscription_settings['target_mode'] = text
            user_state[user_id] = 'admin_sub_wall'
            bot.send_message(message.chat.id, f"✅ Target Mode set to: {text}", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, "Invalid mode.")
        return
        
    if state == 'wait_sub_channel':
        try:
            parts = text.split('|')
            if len(parts) == 3:
                subscription_settings['channels'].append({
                    'name': parts[0].strip(),
                    'url': parts[1].strip(),
                    'chat_id': parts[2].strip()
                })
                user_state[user_id] = 'admin_sub_wall'
                bot.send_message(message.chat.id, "✅ Channel successfully appended to the Wall list.", reply_markup=get_keyboard(user_id))
            else:
                bot.send_message(message.chat.id, "⚠️ Invalid format. Must use two pipe (|) characters.")
        except Exception:
            bot.send_message(message.chat.id, "Error processing string.")
        return
        
    if state == 'wait_sub_time':
        try:
            subscription_settings['check_time_hours'] = float(text)
            user_state[user_id] = 'admin_sub_wall'
            bot.send_message(message.chat.id, "✅ Background retention timer updated.", reply_markup=get_keyboard(user_id))
        except ValueError:
            bot.send_message(message.chat.id, "Invalid number.")
        return
        
    if state == 'wait_sub_msg':
        subscription_settings['msg_wall'] = formatted_text
        user_state[user_id] = 'admin_sub_wall'
        bot.send_message(message.chat.id, "✅ Wall message updated.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_sub_fail':
        subscription_settings['msg_fail'] = formatted_text
        user_state[user_id] = 'admin_sub_wall'
        bot.send_message(message.chat.id, "✅ Fail message updated.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_sub_btn':
        subscription_settings['btn_check'] = text
        user_state[user_id] = 'admin_sub_wall'
        bot.send_message(message.chat.id, "✅ Button text updated.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_sub_check_user':
        try:
            target_uid = int(text)
            bot.send_message(message.chat.id, f"🔍 <b>Performing Manual Diagnostics on {target_uid}...</b>", parse_mode="HTML")
            
            sweep_results = ""
            all_passed = True
            for ch in subscription_settings.get('channels', []):
                try:
                    member = bot.get_chat_member(ch['chat_id'], target_uid)
                    if member.status in ['left', 'kicked']:
                        all_passed = False
                        sweep_results += f"❌ Missing: {ch['name']}\n"
                    else:
                        sweep_results += f"✅ Joined: {ch['name']}\n"
                except Exception as e:
                    sweep_results += f"⚠️ API Error on {ch['name']}: {e}\n"
                    all_passed = False
            
            if target_uid in user_db:
                user_db[target_uid]['sub_verified'] = all_passed
                
            bot.send_message(message.chat.id, f"<b>Sweep Results:</b>\n{sweep_results}\n\nFinal Verified Status: {all_passed}", parse_mode="HTML", reply_markup=get_keyboard(user_id))
            user_state[user_id] = 'admin_sub_wall'
        except ValueError:
            bot.send_message(message.chat.id, "Invalid User ID format.")
        return

    if state == 'admin_homepage_bonus':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == 'Toggle Pop-Up On/Off':
            homepage_bonus_settings['enabled'] = not homepage_bonus_settings.get('enabled', False)
            bot.send_message(message.chat.id, "✅ Homepage Pop-Up Toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Button Text':
            user_state[user_id] = 'wait_home_btn'
            bot.send_message(message.chat.id, f"Enter the new Call to Action button text:\n\nCurrent: {homepage_bonus_settings.get('btn_text')}", reply_markup=get_cancel_action_keyboard())
        return
        
    if state == 'wait_home_btn':
        homepage_bonus_settings['btn_text'] = text
        user_state[user_id] = 'admin_homepage_bonus'
        bot.send_message(message.chat.id, "✅ Button text updated.", reply_markup=get_keyboard(user_id))
        return

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
            "• <code>%address%</code> - Withdraw Wallet address\n"
            "• <code>%withdraw%</code> - The withdrawal amount\n\n"
            "• <code>%wallet%</code> - User's USDT Wallet address\n"
            "• <code>%email%</code> - User's Email address\n"
            "• <code>%bonus_amount%</code> - The defined bonus amount\n"
            "• <code>%time_left%</code> - Used dynamically in Bonus fail msg\n"
            "• <code>%loading_bar%</code> - Animates a loading bar globally\n"
            "• <code>%loading_bar_5s%</code> - Custom time loading bar (e.g. 5s)\n\n"
            "• <code>%plan0%</code> ... <code>%plan5%</code> - Plan details\n"
            "• <code>%lang%</code> - User's current language\n\n"
            "<b>NEW BALANCE MACROS:</b>\n"
            "• <code>%plan_invest%</code> - Total active investment\n"
            "• <code>%hourly_profit%</code> - Total hourly profit\n"
            "• <code>%plan_names%</code> - Names of active plans\n"
            "• <code>%ref_count%</code> - Number of referrals\n"
            "• <code>%withdrawn%</code> - Total amount withdrawn\n"
            "• <code>%network%</code> - User's Withdrawal Network\n"
            "• <code>%commission%</code> - Configured withdrawal commission %\n\n"
            "<b>NEW DYNAMIC STATS MACROS:</b>\n"
            "• <code>%stats_invest%</code> - Dynamic total investments\n"
            "• <code>%stats_withdrawn%</code> - Dynamic total withdrawn\n"
            "• <code>%stats_users%</code> - Dynamic total users\n\n"
            "<b>NEW REFERRAL MACROS:</b>\n"
            "• <code>%levels_display%</code> - Visual loading bars for levels\n"
            "• <code>%team_deposits%</code> - Total team deposited amount\n"
            "• <code>%affiliate_earnings%</code> - Total affiliate earned amount\n"
            "• <code>%ref_link%</code> - Generates pure text referral link"
        )
        try:
            bot.send_message(message.chat.id, macros_msg, parse_mode="HTML", reply_markup=get_keyboard(user_id))
        except Exception as e:
            bot.send_message(message.chat.id, "Error rendering Macros.", reply_markup=get_keyboard(user_id))
        return

    if text == '🏠 Home':
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal' if not is_admin else state 
        if state in ['posts_adding', 'w_action_amount', 'w_action_addr', 'buyplan_wait_amount', 'dep_wait_amount', 'dep_wait_proof', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount']:
            user_state[user_id] = 'normal'
        send_path_content(message.chat.id, user_id, 'root', is_editing=(user_state[user_id] == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
        return

    if text == '🔙 Back':
        if current_path != 'root':
            parts = current_path.split('/')[:-1]
            new_path = '/join'.join(parts) if len(parts) > 1 else 'root'
            user_current_path[user_id] = new_path
            if state in ['w_action_amount', 'w_action_addr', 'buyplan_wait_amount', 'dep_wait_amount', 'dep_wait_proof', 'wait_calc_amount', 'wallet_wait_email', 'wallet_wait_address', 'wait_reinvest_amount']:
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

    if state == 'posts_adding':
        if current_path not in menu_posts: menu_posts[current_path] = []
        new_post = {
            'id': str(uuid.uuid4())[:8],
            'type': 'photo' if message.photo else 'text',
            'text': formatted_text,
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
            post['text'] = formatted_text
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Text updated successfully!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return
        
    if state == 'posts_rep_all':
        p_id = user_action_data[user_id]['post_id']
        post = next((p for p in menu_posts.get(current_path, []) if p['id'] == p_id), None)
        if post:
            post['type'] = 'photo' if message.photo else 'text'
            post['text'] = formatted_text
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
            'text': formatted_text,
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
            if not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': 'Current Language: %lang%\nSelect Language to change it',
                    'photo': None,
                    'custom_inlines': []
                }
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
        elif text.startswith('Assign Reinvest'):
            meta['is_reinvest'] = not meta.get('is_reinvest', False)
            btn_metadata[btn_path] = meta
            bot.send_message(message.chat.id, "Reinvest toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Deposit'):
            meta['is_deposit'] = not meta.get('is_deposit', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_deposit'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "🏦 <b>Deposit Menu</b>\n\nPlease select the currency you wish to deposit:",
                    'photo': None,
                    'custom_inlines': []
                }
                r_idx = 0
                for c in deposit_settings:
                    new_post['custom_inlines'].append({
                        'id': str(uuid.uuid4())[:6],
                        'text': c.replace('_', ' '),
                        'mode': 'deposit',
                        'data': c,
                        'row_idx': r_idx
                    })
                    r_idx += 1
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Deposit page assigned and generated dynamically. You can edit the text and layout inside the Posts Editor.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Assign Balance'):
            meta['is_balance'] = not meta.get('is_balance', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_balance'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "━━━━━━━━━━━━━━━━━━\n📊 G-Force Auto Trading Bot\n━━━━━━━━━━━━━━━━━━\n💵 Balance: %balance% USDT\n💼 Active Investment: %plan_invest% USDT\n━━━━━━━━━━━━━━━━━━\n🎁 Bonus: %bonus% USDT\n⏱ Hourly Profit: %hourly_profit% USDT\n━━━━━━━━━━━━━━━━━━\n⚙️ Plan: %plan_names%\n👥 Referrals: %ref_count% Users\n💳 Payouts: %withdrawn% USDT\n━━━━━━━━━━━━━━━━━━",
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Balance page assigned and generated dynamically. You can edit the text and layout inside the Posts Editor.", reply_markup=get_keyboard(user_id))
            
        elif text.startswith('Assign Stats'):
            meta['is_stats'] = not meta.get('is_stats', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_stats'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "📈 T͟o͟t͟a͟l͟ I͟n͟v͟e͟s͟t͟m͟e͟n͟t͟s͟ (USD)\n$%stats_invest% USD deposited\n📉 Total Withdrawn (USD)\nTotal User: %stats_users%\n$%stats_withdrawn% USD withdrawn\nGet started today, Every 24 hours Refresh",
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Stats page assigned and pre-populated.", reply_markup=get_keyboard(user_id))

        elif text.startswith('Assign Info'):
            meta['is_info'] = not meta.get('is_info', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_info'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "Userid: %userid%\nEmail: %email%\nWallet address: %wallet%\nName: %firstname% %lastname%\nClick /setwallet info to change your info",
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Info page assigned and pre-populated.", reply_markup=get_keyboard(user_id))
            
        elif text.startswith('Assign Invite'):
            meta['is_invite'] = not meta.get('is_invite', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_invite'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': invite_settings['msg_template'],
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Invite page assigned and pre-populated.", reply_markup=get_keyboard(user_id))

        elif text.startswith('Assign Live Trading'):
            meta['is_live_trading'] = not meta.get('is_live_trading', False)
            btn_metadata[btn_path] = meta
            
            if meta['is_live_trading'] and not menu_posts.get(btn_path):
                post_id = str(uuid.uuid4())[:8]
                new_post = {
                    'id': post_id,
                    'type': 'text',
                    'text': "📊 <b>LIVE TRADING TERMINAL</b> 📊\n════════════════════\n📈 Active Plan: %plan_names%\n💼 Invested: $%plan_invest%\n⏱ Runtime: %trade_runtime%\n\n🟢 Live Profit: %trade_profit%\n%trade_anim_bar% %trade_pct%\n════════════════════",
                    'photo': None,
                    'custom_inlines': []
                }
                menu_posts[btn_path] = [new_post]
            bot.send_message(message.chat.id, "✅ Live Trading Terminal assigned and pre-populated.", reply_markup=get_keyboard(user_id))

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

    if state == 'pi_wait_mode':
        if text not in ['🔗 URL or Share', '💬 Popup Window', '🚀 Command', '🛒 Buy Plan', '🏦 Deposit', '🌐 Set Language', '❓ Ask Question']:
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
        elif mode == '❓ Ask Question':
            user_state[user_id] = 'pi_wait_data'
            bot.send_message(message.chat.id, "Send an identifier or just type '0' (Admins will see standard support ticket):")
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
            '🌐 Set Language': 'set_lang',
            '❓ Ask Question': 'question'
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
            if 'custom_inlines' not in post: 
                post['custom_inlines'] = []
            
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

    if state.startswith('wallet_setup_'):
        if state == 'wallet_setup_main': global_wallet_setup['msg_main'] = formatted_text
        elif state == 'wallet_setup_prompt': global_wallet_setup['msg_prompt'] = formatted_text
        elif state == 'wallet_setup_success': global_wallet_setup['msg_success'] = formatted_text
        elif state == 'wallet_setup_email_prompt': global_wallet_setup['msg_email_prompt'] = formatted_text
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
        elif text == '💰 Min Auto-Transfer':
            user_state[user_id] = 'bonus_setup_min_withdraw'
            bot.send_message(message.chat.id, f"Enter the minimum bonus balance required before it auto-transfers to Withdrawable Balance:\n\nCurrent: ${global_bonus_setup.get('min_withdraw', 50.0)}", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('📧 Toggle Email'):
            global_bonus_setup['require_email'] = not global_bonus_setup.get('require_email', True)
            bot.send_message(message.chat.id, f"Email requirement toggled.", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Email Req Text':
            user_state[user_id] = 'bonus_setup_email_req'
            bot.send_message(message.chat.id, f"Enter the message shown when asking a user to link their email for the bonus:\n\nCurrent:\n{global_bonus_setup.get('msg_email_req', '⚠️ Email Required')}", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('bonus_setup_'):
        if state == 'bonus_setup_amount':
            try: global_bonus_setup['amount'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_cooldown':
            try: global_bonus_setup['cooldown_hours'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_min_withdraw':
            try: global_bonus_setup['min_withdraw'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_success': global_bonus_setup['msg_success'] = formatted_text
        elif state == 'bonus_setup_fail': global_bonus_setup['msg_fail'] = formatted_text
        elif state == 'bonus_setup_email_req': global_bonus_setup['msg_email_req'] = formatted_text
        
        user_state[user_id] = 'admin_bonus_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN REINVEST SETTINGS ---
    if state == 'admin_reinvest_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'reinvest_setup_success'
            bot.send_message(message.chat.id, f"Enter Reinvest Success Message (macros: %amount%, %plan_name%):\n\nCurrent:\n{reinvest_settings['msg_success']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Fail Msg':
            user_state[user_id] = 'reinvest_setup_fail'
            bot.send_message(message.chat.id, f"Enter Reinvest Fail Message (macro: %min_amount%):\n\nCurrent:\n{reinvest_settings['msg_fail']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '🔘 Edit Deposit Inline':
            user_state[user_id] = 'reinvest_setup_inline'
            bot.send_message(message.chat.id, f"Enter the text for the fallback deposit button:\n\nCurrent: {reinvest_settings['inline_deposit_text']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('reinvest_setup_'):
        if state == 'reinvest_setup_success': reinvest_settings['msg_success'] = formatted_text
        elif state == 'reinvest_setup_fail': reinvest_settings['msg_fail'] = formatted_text
        elif state == 'reinvest_setup_inline': reinvest_settings['inline_deposit_text'] = text
        
        user_state[user_id] = 'admin_reinvest_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- REINVEST SYSTEM AMOUNT INPUT HANDLER ---
    if state == 'wait_reinvest_amount':
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))

        valid_plans = {pid: p for pid, p in bot_plans.items() if pid != 'plan0'}
        if not valid_plans: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ No valid plans available.", lang))

        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        total_avail = u_dep + u_bal

        if amount > total_avail:
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Insufficient funds. You only have ${fmt_amt(total_avail)} available.", lang))

        matched_plan_id = None
        matched_plan_data = None
        for pid, p in valid_plans.items():
            if p['min'] <= amount <= p['max']:
                matched_plan_id = pid
                matched_plan_data = p
                break

        if not matched_plan_id:
            min_plan_amount = min(p['min'] for p in valid_plans.values())
            max_plan_amount = max(p['max'] for p in valid_plans.values())
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Amount does not match any plan. Please enter an amount between ${fmt_amt(min_plan_amount)} and ${fmt_amt(max_plan_amount)}.", lang))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)

        succ_msg = reinvest_settings['msg_success'].replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, get_tl_and_map(replace_macros(succ_msg, user_id, user_current_path[user_id]), lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

        if not matched_plan_id:
            min_plan_amount = min(p['min'] for p in valid_plans.values())
            max_plan_amount = max(p['max'] for p in valid_plans.values())
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Amount does not match any plan. Please enter an amount between ${fmt_amt(min_plan_amount)} and ${fmt_amt(max_plan_amount)}.", lang))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)

        succ_msg = reinvest_settings['msg_success'].replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, get_tl_and_map(replace_macros(succ_msg, user_id, user_current_path[user_id]), lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

    # --- ADMIN LOADING BAR SETTINGS ---
    if state == 'admin_loading_bar':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '⏱ Set Default Time':
            user_state[user_id] = 'admin_loading_time'
            current_time = global_ui_settings.get('loading_bar_time', 3.0)
            bot.send_message(message.chat.id, f"Enter default loading time in seconds (e.g. 3, 5, 2.5):\n\nCurrent: {current_time}s", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('Style 1'):
            global_ui_settings['loading_bar_style'] = '1'
            bot.send_message(message.chat.id, "✅ Loading Bar style changed to Style 1.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Style 2'):
            global_ui_settings['loading_bar_style'] = '2'
            bot.send_message(message.chat.id, "✅ Loading Bar style changed to Style 2.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Style 3'):
            global_ui_settings['loading_bar_style'] = '3'
            bot.send_message(message.chat.id, "✅ Loading Bar style changed to Style 3.", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'admin_loading_time':
        try:
            new_time = float(text)
            if new_time <= 0: raise ValueError
            global_ui_settings['loading_bar_time'] = new_time
            user_state[user_id] = 'admin_loading_bar'
            bot.send_message(message.chat.id, f"✅ Default loading time set to {new_time}s.", reply_markup=get_keyboard(user_id))
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid time. Please enter a positive number (e.g. 3 or 5.5).")
        return

    # --- PROFIT CALCULATOR ENGINE ---
    if state == 'wait_calc_amount':
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))
        
        msg = f"🧮 <b>Calculator Results for ${fmt_amt(amount)}</b>\n\n"
        found = False
        markup = InlineKeyboardMarkup()
        for p_id, p_data in bot_plans.items():
            if p_id == 'plan0': continue 
            if p_data['min'] <= amount <= p_data['max']:
                found = True
                hourly = amount * (p_data['profit'] / 100.0)
                daily = hourly * 24
                msg += f"🔹 <b>{p_data['name']}</b>\n"
                msg += f"Hourly Profit: ${fmt_amt(hourly)}\nDaily Profit: ${fmt_amt(daily)}\n"
                if p_data['length'] > 0:
                    total = hourly * p_data['length']
                    msg += f"Total Return ({p_data['length']}h): ${fmt_amt(total)}\n\n"
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
        msg = f"🎉 <b>Success!</b>\nYou invested <b>${fmt_amt(invest_amount)}</b> into <b>{p_data['name']}</b>!\nYour profit is accruing automatically."
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
        if usd_amount < c_min: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Minimum deposit is <b>${fmt_amt(c_min)} USD</b>.", lang), parse_mode="HTML")
        if usd_amount > c_max: return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Maximum deposit is <b>${fmt_amt(c_max)} USD</b>.", lang), parse_mode="HTML")

        user_action_data[user_id]['usd_amount'] = usd_amount
        
        if conf['mode'] == 'manual':
            msg = conf['msg_instruct'].replace('%amount%', str(usd_amount)).replace('%address%', conf['address'])
            user_state[user_id] = 'dep_wait_proof'
            bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode='HTML', reply_markup=get_cancel_action_keyboard())
        else:
            # LOADING BAR ANIMATION
            style_opt = global_ui_settings.get('loading_bar_style', '1')
            frames = {
                '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
                '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
                '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
            }
            bars = frames.get(str(style_opt), frames['1'])
            
            loading_msg = bot.send_message(message.chat.id, get_tl_and_map(f"🔄 <b>Initializing Secure Connection...</b>\n{bars[0]}", lang), parse_mode="HTML")
            for bar in bars[1:]:
                time.sleep(0.5)
                try: bot.edit_message_text(get_tl_and_map(f"🔄 <b>Generating Wallet...</b>\n{bar}", lang), message.chat.id, loading_msg.message_id, parse_mode="HTML")
                except: pass

            if 'USDT' in curr:
                live_price = 1.0
            else:
                live_price = get_crypto_price(curr)
                if not live_price:
                    user_state[user_id] = 'normal'
                    return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Error connecting to price oracle. Please try again later.", lang), reply_markup=get_keyboard(user_id))
            
            crypto_amount = round(usd_amount / live_price, 6)
            
            if curr not in user_db[user_id]['wallets']:
                address, private_key = generate_user_wallet(user_id, curr)
                if address == "ERROR_NO_SEED":
                    return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Admin has not configured the Master Seed Phrase. Deposits offline.", lang))
                
                user_db[user_id]['wallets'][curr] = {
                    'address': address, 
                    'private_key': private_key,
                    'total_deposited': 0.0,
                    'admin_swept_total': 0.0
                }
                
                admin_alert = f"🚨 <b>NEW WALLET GENERATED</b> 🚨\n\n👤 User: <code>{user_id}</code> (@{message.from_user.username})\n🪙 Currency: {curr.replace('_', ' ')}\n\n📫 Public Address:\n<code>{address}</code>\n\n🔑 <b>PRIVATE KEY</b> (KEEP SECRET):\n<code>{private_key}</code>"
                for admin in ADMIN_IDS:
                    try: bot.send_message(admin, admin_alert, parse_mode="HTML")
                    except Exception: pass
            else:
                address = user_db[user_id]['wallets'][curr]['address']
            
            rate_text = f"💱 live exchange rate: 1 {curr.split('_')[0]} = ${fmt_amt(live_price)}\n" if 'USDT' not in curr else ""
            
            msg = (
                f"🚨 <b>DEPOSIT WALLET GENERATED</b> 🚨\n\n"
                f"👤 User: <code>{user_id}</code> (@{message.from_user.username or 'None'})\n"
                f"🪙 Currency: {curr.replace('_', ' ')}\n"
                f"{rate_text}"
                f"💸 Deposit amount: {fmt_amt(crypto_amount)} {curr.split('_')[0]}\n\n"
                f"Please send exactly <code>{fmt_amt(crypto_amount)}</code> {curr.split('_')[0]} to:\n"
                f"tap confirm\n\n"
                f"📫 Your Deposit Address:\n"
                f"<code>{address}</code>"
            )
            
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton(get_tl_and_map("✅ Confirm", lang), callback_data=f"cb_depcheck_{curr}"))
            
            try: bot.delete_message(message.chat.id, loading_msg.message_id)
            except: pass
            
            bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode='HTML', reply_markup=markup)
            
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
        
        admin_msg = f"📥 <b>New Deposit Request</b>\nUser ID: <code>{user_id}</code>\nUsername: @{message.from_user.username or 'None'}\nAmount: <b>${fmt_amt(amt)} (USD Equivalent)</b>"
        
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
        msg_pending = msg_pending.replace('%usd_amount%', f"{fmt_amt(amt)}")
        bot.send_message(message.chat.id, get_tl_and_map(msg_pending, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN DEPOSIT MENU CONTROLS ---
    if state == 'admin_dep_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📣 Live Deposit Channel':
            user_state[user_id] = 'admin_live_channel'
            bot.send_message(message.chat.id, "⚙️ <b>Live Deposit Broadcaster Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        else:
            curr_key = text.strip().upper().replace(' ', '_')
            if curr_key in deposit_settings:
                admin_dep_setup[user_id] = curr_key
                user_state[user_id] = 'admin_dep_settings'
                clean_name = curr_key.replace('_', ' ')
                bot.send_message(message.chat.id, f"🏦 <b>Editing Settings for {clean_name}</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- NEW: LIVE CHANNEL BROADCAST ROUTING ---
    if state == 'admin_live_channel':
        if text == '🔙 Back to Deposit Menu':
            user_state[user_id] = 'admin_dep_menu'
            bot.send_message(message.chat.id, "🏦 <b>Deposit Architecture Menu</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text.startswith('Toggle Broadcast'):
            deposit_broadcast_settings['enabled'] = not deposit_broadcast_settings.get('enabled', False)
            bot.send_message(message.chat.id, "✅ Deposit Broadcaster toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Set Target Channel':
            user_state[user_id] = 'wait_live_channel_id'
            bot.send_message(message.chat.id, "Enter the Telegram Channel ID (e.g., -1001234567890):", reply_markup=get_cancel_action_keyboard())
        elif text == 'Edit Receipt Text':
            user_state[user_id] = 'wait_live_receipt_msg'
            current_msg = deposit_broadcast_settings.get('template')
            bot.send_message(message.chat.id, f"Enter your new receipt template.\n\n<b>Available Tags:</b>\n{{user_id}}\n{{network}}\n{{amount}}\n{{short_hash}}\n\n<b>Current Template:</b>\n{current_msg}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return
        
    if state == 'wait_live_channel_id':
        deposit_broadcast_settings['channel_id'] = text.strip()
        user_state[user_id] = 'admin_live_channel'
        bot.send_message(message.chat.id, "✅ Channel ID successfully updated. Ensure the bot is an Admin in that channel!", reply_markup=get_keyboard(user_id))
        return
        
    if state == 'wait_live_receipt_msg':
        deposit_broadcast_settings['template'] = formatted_text
        user_state[user_id] = 'admin_live_channel'
        bot.send_message(message.chat.id, "✅ Custom receipt template updated.", reply_markup=get_keyboard(user_id))
        return

    # --- REGULAR DEPOSIT SETTINGS ROUTING ---
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
        elif state == 'dep_setup_enter': deposit_settings[curr]['msg_enter'] = formatted_text
        elif state == 'dep_setup_instruct': deposit_settings[curr]['msg_instruct'] = formatted_text
        elif state == 'dep_setup_pending': deposit_settings[curr]['msg_pending'] = formatted_text
        elif state == 'dep_setup_success': deposit_settings[curr]['msg_success'] = formatted_text
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
        elif text == 'Processing Message':
            user_state[user_id] = 'w_setup_proc'
            curr = global_w_setup.get('w_msg_processing')
            bot.send_message(message.chat.id, f"✨ Enter the Processing Message shown AFTER confirming.\n\nℹ️ Current:\n{curr}", reply_markup=get_cancel_action_keyboard())
        elif text == 'Approve Msg':
            user_state[user_id] = 'w_setup_appr'
            curr = global_w_setup.get('w_msg_approve')
            bot.send_message(message.chat.id, f"✨ Enter the Approve Message to send to users upon successful payout.\n\nℹ️ Current:\n{curr}", reply_markup=get_cancel_action_keyboard())
        elif text == 'Decline Msg.':
            user_state[user_id] = 'w_setup_dec'
            curr = global_w_setup.get('w_msg_decline')
            bot.send_message(message.chat.id, f"✨ Enter the Decline Message.\n\nℹ️ Current:\n{curr}", reply_markup=get_cancel_action_keyboard())
        elif text == 'Ignore Msg.':
            user_state[user_id] = 'w_setup_ign'
            curr = global_w_setup.get('w_msg_ignore')
            bot.send_message(message.chat.id, f"✨ Enter the Ignore Message.\n\nℹ️ Current:\n{curr}", reply_markup=get_cancel_action_keyboard())
        elif text == 'Public Group Report':
            user_state[user_id] = 'w_setup_pub'
            curr = global_w_setup.get('public_report')
            bot.send_message(message.chat.id, f"Send the Channel/Group ID (e.g. -100123456789) for public reports:\n\nℹ️ Current: {curr}", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('Do not ask for Address'):
            global_w_setup['do_not_ask_address'] = not global_w_setup.get('do_not_ask_address', False)
            bot.send_message(message.chat.id, "Address setting toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('Commission'):
            user_state[user_id] = 'w_setup_comm'
            bot.send_message(message.chat.id, "Enter withdrawal commission percentage (e.g. 5 for 5%):", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('Rate'):
            global_w_setup['w_rate_toggle'] = not global_w_setup.get('w_rate_toggle', False)
            bot.send_message(message.chat.id, "Rate/Multi-currency withdrawal toggled.", reply_markup=get_keyboard(user_id))
        elif text.startswith('ASCII Receipt'):
            global_w_setup['use_ascii_receipt'] = not global_w_setup.get('use_ascii_receipt', False)
            bot.send_message(message.chat.id, "✅ ASCII Receipt toggled.", reply_markup=get_keyboard(user_id))
        elif text == 'Edit Payout Popup':
            user_state[user_id] = 'wait_payout_popup'
            bot.send_message(message.chat.id, f"Enter the popup button text and message separated by | (e.g. Button Title | Popup Message):\n\nℹ️ Current:\n{global_w_setup.get('payout_btn_text', '📜 View Receipt')} | {global_w_setup.get('payout_popup_msg', 'Payment Success!')}", reply_markup=get_cancel_action_keyboard())
        else:
            bot.send_message(message.chat.id, f"🛠 <b>{text}</b> is acknowledged. Setup feature coming soon!", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'wait_payout_popup':
        if '|' in text:
            btn_title, popup_msg = text.split('|', 1)
            global_w_setup['payout_btn_text'] = btn_title.strip()
            global_w_setup['payout_popup_msg'] = popup_msg.strip()
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "✅ Payout Popup settings saved successfully!", reply_markup=get_keyboard(user_id))
        else:
            bot.send_message(message.chat.id, "⚠️ Invalid format. You must separate the Title and Message with a | character. Try again:", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('w_setup_'):
        val = None if text == '➖ Set Empty' else text
        formatted_val = None if text == '➖ Set Empty' else formatted_text
        if text != '✔️ Leave as Is':
            if state == 'w_setup_var': global_w_setup['w_var'] = val
            elif state == 'w_setup_min': global_w_setup['w_min'] = val
            elif state == 'w_setup_max': global_w_setup['w_max'] = val
            elif state == 'w_setup_enter': global_w_setup['w_msg_enter'] = formatted_val
            elif state == 'w_setup_addr': global_w_setup['w_msg_addr'] = formatted_val
            elif state == 'w_setup_conf': global_w_setup['w_msg_conf'] = formatted_val
            elif state == 'w_setup_proc': global_w_setup['w_msg_processing'] = formatted_val
            elif state == 'w_setup_appr': global_w_setup['w_msg_approve'] = formatted_val
            elif state == 'w_setup_dec': global_w_setup['w_msg_decline'] = formatted_val
            elif state == 'w_setup_ign': global_w_setup['w_msg_ignore'] = formatted_val
            elif state == 'w_setup_pub': global_w_setup['public_report'] = text
            elif state == 'w_setup_comm': 
                try: global_w_setup['w_commission'] = float(text)
                except ValueError: bot.send_message(message.chat.id, "⚠️ Invalid percentage.")

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
        elif state in ['w_setup_enter', 'w_setup_addr', 'w_setup_conf', 'w_setup_proc', 'w_setup_appr', 'w_setup_dec', 'w_setup_ign', 'w_setup_pub', 'w_setup_comm']:
            user_state[user_id] = 'admin_w_menu'
            bot.send_message(message.chat.id, "✅ Settings updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN WALLET SETTINGS (RESTORED FIX) ---
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
        if state == 'wallet_setup_main': global_wallet_setup['msg_main'] = formatted_text
        elif state == 'wallet_setup_prompt': global_wallet_setup['msg_prompt'] = formatted_text
        elif state == 'wallet_setup_success': global_wallet_setup['msg_success'] = formatted_text
        elif state == 'wallet_setup_email_prompt': global_wallet_setup['msg_email_prompt'] = formatted_text
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
        elif text == '💰 Min Auto-Transfer':
            user_state[user_id] = 'bonus_setup_min_withdraw'
            bot.send_message(message.chat.id, f"Enter the minimum bonus balance required before it auto-transfers to Withdrawable Balance:\n\nCurrent: ${global_bonus_setup.get('min_withdraw', 50.0)}", reply_markup=get_cancel_action_keyboard())
        elif text.startswith('📧 Toggle Email'):
            global_bonus_setup['require_email'] = not global_bonus_setup.get('require_email', True)
            bot.send_message(message.chat.id, f"Email requirement toggled.", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Email Req Text':
            user_state[user_id] = 'bonus_setup_email_req'
            bot.send_message(message.chat.id, f"Enter the message shown when asking a user to link their email for the bonus:\n\nCurrent:\n{global_bonus_setup.get('msg_email_req', '⚠️ Email Required')}", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('bonus_setup_'):
        if state == 'bonus_setup_amount':
            try: global_bonus_setup['amount'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_cooldown':
            try: global_bonus_setup['cooldown_hours'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_min_withdraw':
            try: global_bonus_setup['min_withdraw'] = float(text)
            except: return bot.send_message(message.chat.id, "⚠️ Invalid number.")
        elif state == 'bonus_setup_success': global_bonus_setup['msg_success'] = formatted_text
        elif state == 'bonus_setup_fail': global_bonus_setup['msg_fail'] = formatted_text
        elif state == 'bonus_setup_email_req': global_bonus_setup['msg_email_req'] = formatted_text
        
        user_state[user_id] = 'admin_bonus_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN REINVEST SETTINGS ---
    if state == 'admin_reinvest_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '💬 Edit Success Msg':
            user_state[user_id] = 'reinvest_setup_success'
            bot.send_message(message.chat.id, f"Enter Reinvest Success Message (macros: %amount%, %plan_name%):\n\nCurrent:\n{reinvest_settings['msg_success']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Fail Msg':
            user_state[user_id] = 'reinvest_setup_fail'
            bot.send_message(message.chat.id, f"Enter Reinvest Fail Message (macro: %min_amount%):\n\nCurrent:\n{reinvest_settings['msg_fail']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '🔘 Edit Deposit Inline':
            user_state[user_id] = 'reinvest_setup_inline'
            bot.send_message(message.chat.id, f"Enter the text for the fallback deposit button:\n\nCurrent: {reinvest_settings['inline_deposit_text']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if state.startswith('reinvest_setup_'):
        if state == 'reinvest_setup_success': reinvest_settings['msg_success'] = formatted_text
        elif state == 'reinvest_setup_fail': reinvest_settings['msg_fail'] = formatted_text
        elif state == 'reinvest_setup_inline': reinvest_settings['inline_deposit_text'] = text
        
        user_state[user_id] = 'admin_reinvest_menu'
        bot.send_message(message.chat.id, "✅ Setting updated successfully!", reply_markup=get_keyboard(user_id))
        return

    # --- REINVEST SYSTEM AMOUNT INPUT HANDLER ---
    if state == 'wait_reinvest_amount':
        try: amount = float(text)
        except ValueError: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))

        valid_plans = {pid: p for pid, p in bot_plans.items() if pid != 'plan0'}
        if not valid_plans: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ No valid plans available.", lang))

        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        total_avail = u_dep + u_bal

        if amount > total_avail:
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Insufficient funds. You only have ${fmt_amt(total_avail)} available.", lang))

        matched_plan_id = None
        matched_plan_data = None
        for pid, p in valid_plans.items():
            if p['min'] <= amount <= p['max']:
                matched_plan_id = pid
                matched_plan_data = p
                break

        if not matched_plan_id:
            min_plan_amount = min(p['min'] for p in valid_plans.values())
            max_plan_amount = max(p['max'] for p in valid_plans.values())
            return bot.send_message(message.chat.id, get_tl_and_map(f"⚠️ Amount does not match any plan. Please enter an amount between ${fmt_amt(min_plan_amount)} and ${fmt_amt(max_plan_amount)}.", lang))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)

        succ_msg = reinvest_settings['msg_success'].replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, get_tl_and_map(replace_macros(succ_msg, user_id, user_current_path[user_id]), lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
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
        
        elif text == '💰 Set Bonus Amount' and p_id == 'plan0':
            user_state[user_id] = 'plan_setup_bonus'
            bot.send_message(message.chat.id, f"Enter free bonus capital amount for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id].get('bonus_amount', 50.0)}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
        elif text == '💰 Set Min Deposit' and p_id != 'plan0':
            user_state[user_id] = 'plan_setup_min'
            bot.send_message(message.chat.id, f"Enter Minimum Deposit for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id]['min']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        elif text == '💰 Set Max Deposit' and p_id != 'plan0':
            user_state[user_id] = 'plan_setup_max'
            bot.send_message(message.chat.id, f"Enter Maximum Deposit for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: ${bot_plans[p_id]['max']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        # --- NEW FEATURE: DYNAMIC PLAN RENAMING ---
        elif text == '✏️ Rename Plan':
            user_state[user_id] = 'plan_setup_name'
            bot.send_message(message.chat.id, f"Enter the new name for <b>{bot_plans[p_id]['name']}</b>:\n\nℹ️ Current: {bot_plans[p_id]['name']}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
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
        # --- NEW FEATURE: DYNAMIC PLAN RENAMING ---
        elif state == 'plan_setup_name':
            bot_plans[p_id]['name'] = formatted_text
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
            bot_plans[p_id]['text'] = formatted_text
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
    admin_commands = ['🎛️ Buttons Editor', '📝 Posts Editor', '💵 Balance', '🔐 Admin', '➕ Add Button', '🛑 Stop Editor', '✅ Confirm', '🚫 Cancel', '✖️ Delete', 'Deposit balance', 'Withdrawal balance', 'User Macro', 'User Macros', '📜 Macros', '📊 Plans', '🔙 Back to Main', '🔙 Back to Admin', '➕ Add Plan', '➕ Add Message', 'Pagination in Editor (10)', '🏦 Deposit Settings', 'Withdrawal Settings', '🔙 Back to Deposit Menu', '📍 Set Static Address', '🔑 Set HD Wallet Key', '💬 Edit Enter Msg', '💬 Edit Instruct Msg', '💰 Set Min Deposit', '💰 Set Max Deposit', '💬 Edit Pending Msg', '💬 Edit Success Msg', '🧮 Calculator', '📜 Transactions', '💳 Wallet Settings', '🎁 Bonus Settings', '🔄 Reinvest Settings', 'Loading Bar Settings', '🚫 Block User System', '🚫 Block', '✅ Unblock', '💬 Edit Block Msg', '💬 Edit Unblock Msg', '📢 Broadcast Message', '💬 Messages', 'Invite Settings', '🛠 Advanced Stats & Wipe', '🧱 Forced Sub Wall', '🎁 Homepage Pop-Up', 'Toggle Wall On/Off', 'Set Target Mode', 'Add Required Channel', 'Remove Channel', 'Set Cooldown Check', 'Edit Wall Message', '👀 Check User API Sweep', 'Toggle Pop-Up On/Off', 'Edit Button Text', '🧹 Targeted Wipe', '☢️ General Wipe (All Users)']
    if not is_admin and (text in admin_commands or text.startswith('📋 Paste "') or text == '✔️ Leave as Is' or text == '➖ Set Empty' or text.startswith('⚙️ Edit ') or text.startswith('Style ')):
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
        elif text.startswith('📋 Paste "'):
            clip = user_clipboard.get(user_id)
            if clip and text == f'📋 Paste "{clip["name"]}"':
                btn_name = clip['name']
                old_path = clip['full_path']
                new_path = f"{current_path}/{btn_name}"
                
                if current_path not in menus: menus[current_path] = []
                
                if btn_name in menus[current_path]:
                    bot.send_message(message.chat.id, f"⚠️ A button named '{btn_name}' already exists here.", reply_markup=get_keyboard(user_id))
                else:
                    menus[current_path].append(btn_name)
                    change_menu_paths(old_path, new_path)
                    user_clipboard.pop(user_id, None)
                    bot.send_message(message.chat.id, f"📋 Pasted '{btn_name}' successfully!", reply_markup=get_keyboard(user_id))
            return
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

    # --- NEW: ADMIN BLOCK SYSTEM LOGIC ---
    if text == '🚫 Block User System' and is_admin:
        user_state[user_id] = 'admin_block_menu'
        bot.send_message(message.chat.id, "🚫 <b>Block User System</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'admin_block_menu':
        if text == '🔙 Back to Admin':
            user_state[user_id] = 'admin_menu'
            bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '🚫 Block':
            user_state[user_id] = 'wait_block_id'
            bot.send_message(message.chat.id, "Enter the User ID to block:", reply_markup=get_cancel_action_keyboard())
        elif text == '✅ Unblock':
            if not blocked_users:
                bot.send_message(message.chat.id, "There are no blocked users.", reply_markup=get_keyboard(user_id))
            else:
                msg = "🚫 <b>Blocked Users List:</b>\nClick a user below to Unblock them.\n\n"
                markup = InlineKeyboardMarkup()
                for buid in blocked_users:
                    uname = user_db.get(buid, {}).get('first_name', 'Unknown')
                    markup.row(InlineKeyboardButton(f"✅ Unblock {uname} ({buid})", callback_data=f"cb_unblock_{buid}"))
                bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=markup)
        elif text == '💬 Edit Block Msg':
            user_state[user_id] = 'wait_edit_block_msg'
            bot.send_message(message.chat.id, f"Enter new Block Message:\n\nCurrent:\n{block_settings['msg_block']}", reply_markup=get_cancel_action_keyboard())
        elif text == '💬 Edit Unblock Msg':
            user_state[user_id] = 'wait_edit_unblock_msg'
            bot.send_message(message.chat.id, f"Enter new Unblock Message:\n\nCurrent:\n{block_settings['msg_unblock']}", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'wait_block_id':
        try:
            target_id = int(text.strip())
            blocked_users.add(target_id)
            user_state[user_id] = 'admin_block_menu'
            bot.send_message(message.chat.id, f"✅ User {target_id} has been permanently blocked.", reply_markup=get_keyboard(user_id))
            
            # Send the block message directly to the targeted user
            target_lang = user_db.get(target_id, {}).get('lang', 'en')
            try: bot.send_message(target_id, get_tl_and_map(block_settings['msg_block'], target_lang), parse_mode="HTML")
            except: pass
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid User ID. Must be a number.")
        return

    if state == 'wait_edit_block_msg':
        block_settings['msg_block'] = formatted_text
        user_state[user_id] = 'admin_block_menu'
        bot.send_message(message.chat.id, "✅ Block message updated successfully.", reply_markup=get_keyboard(user_id))
        return

    if state == 'wait_edit_unblock_msg':
        block_settings['msg_unblock'] = formatted_text
        user_state[user_id] = 'admin_block_menu'
        bot.send_message(message.chat.id, "✅ Unblock message updated successfully.", reply_markup=get_keyboard(user_id))
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
        elif text == '🔄 Reinvest Settings':
            user_state[user_id] = 'admin_reinvest_menu'
            bot.send_message(message.chat.id, "🔄 <b>Reinvest Settings</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '📊 Plans':
            user_state[user_id] = 'admin_plans'
            bot.send_message(message.chat.id, "📊 <b>Plans Manager</b>", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        elif text == '🧮 Calculator':
            user_state[user_id] = 'wait_calc_amount'
            bot.send_message(message.chat.id, "Enter amount to test calculator:", reply_markup=get_cancel_action_keyboard())
        elif text == '📜 Transactions':
            user_state[user_id] = 'admin_wait_tx_id'
            bot.send_message(message.chat.id, "Enter User ID to view history:", reply_markup=get_cancel_action_keyboard())
        elif text == 'Loading Bar Settings':
            user_state[user_id] = 'admin_loading_bar'
            bot.send_message(message.chat.id, "⚙️ <b>Loading Bar Styles</b>\nSelect the global style to use for the `%loading_bar%` macro and Deposit screen:", parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- ADMIN BALANCE MANAGEMENT ENGINE ---
    if state == 'normal' and text == '💵 Balance':
        if is_admin:
            user_state[user_id] = 'bal_select'
            bot.send_message(message.chat.id, "Select the balance to manage:", reply_markup=get_keyboard(user_id))
        else:
            bal = user_db[user_id]['balance']
            bot.send_message(message.chat.id, get_tl_and_map(f"Balance: ${fmt_amt(bal)}", lang))
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
            user_state[user_id] = 'wait_ref_bonus_pct'
            bot.send_message(message.chat.id, f"Enter the Referral Bonus Commission Percentage (e.g. 5 for 5%):\n\nCurrent: {invite_settings.get('ref_commission_pct', 0.0)}%", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'wait_ref_bonus_pct':
        try:
            pct = float(text)
            invite_settings['ref_commission_pct'] = pct
            user_state[user_id] = 'bal_menu'
            bot.send_message(message.chat.id, f"✅ Referral Bonus Commission set to {pct}%.", reply_markup=get_keyboard(user_id))
        except ValueError:
            bot.send_message(message.chat.id, "⚠️ Invalid percentage. Numbers only.")
        return

    if state == 'bal_get_id':
        try:
            target = int(text)
            if target in user_db:
                process_accruals(target)
                u = user_db[target]
                btype = admin_bal_type[user_id]
                bot.send_message(message.chat.id, f"👤 <b>User Info</b>\nID: <code>{target}</code>\nName: {u['first_name']}\nUsername: @{u['username']}\n\n💰 <b>{btype.title()}:</b> {fmt_amt(u[btype])}", parse_mode="HTML", reply_markup=get_keyboard(user_id))
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
                
                info_msg = f"👤 <b>User Found</b>\nID: <code>{target}</code>\nName: {u['first_name']}\nUsername: @{u['username']}\n💰 Current {btype.title()}: <b>{fmt_amt(u[btype])}</b>\n\n"
                
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
        else: admin_bal_comment_text[user_id] = formatted_text
            
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
            
            bot.send_message(message.chat.id, f"✅ <b>Success!</b>\nNew {btype.title()} balance for <code>{target}</code> is <b>{fmt_amt(new_bal)}</b>.", parse_mode="HTML")
            
            if admin_bal_notify.get(user_id, True):
                try:
                    target_lang = user_db.get(target, {}).get('lang', 'en')
                    if comment:
                        msg = f"{comment}\n\nYour {btype.title()} is now: <b>{fmt_amt(new_bal)}</b>"
                    else:
                        msg = global_messages_setup['admin_change_msg'].replace('{btype}', btype.title()).replace('{new_bal}', f"{fmt_amt(new_bal)}")
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
        if amount > user_bal: return bot.send_message(message.chat.id, get_tl_and_map(f"❌ Insufficient funds. Your {w_var} balance is {fmt_amt(user_bal)}.", lang))
            
        user_action_data[user_id]['amount'] = amount
        
        if not global_w_setup.get('do_not_ask_address'):
            user_state[user_id] = 'w_action_addr'
            msg = global_w_setup.get('w_msg_addr') or "Please enter your withdrawal address:"
            bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, target_path, user_action_data[user_id]), lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'w_action_conf'
            msg = global_w_setup.get('w_msg_conf') or "Are you sure you want to withdraw %withdraw% USDT via %network% to:\n<code>%address%</code>"
            bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, target_path, user_action_data[user_id]), lang), parse_mode="HTML", reply_markup=get_withdrawal_conf_inline(lang))
        return

    if state == 'w_action_addr':
        target_path = user_action_data[user_id]['path']
        addr = text.strip()
        user_action_data[user_id]['address'] = addr
        
        # Simple Network Deduction Fallback
        if addr.startswith('T') and len(addr) >= 33: user_action_data[user_id]['network'] = "USDT (TRC20)"
        elif addr.startswith('0x') and len(addr) == 42: user_action_data[user_id]['network'] = "USDT (BEP20)"
        elif addr.startswith('1') or addr.startswith('3') or addr.startswith('bc1'): user_action_data[user_id]['network'] = "BTC"
        else: user_action_data[user_id]['network'] = "Unknown"
        
        user_state[user_id] = 'w_action_conf'
        msg = global_w_setup.get('w_msg_conf') or "Are you sure you want to withdraw %withdraw% USDT via %network% to:\n<code>%address%</code>"
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
                
                has_submenus = len(menus[path]) > 0
                if has_submenus and not (is_admin and state == 'posts_editing'):
                    btn_name = path.split('/')[-1]
                    breadcrumb_text = f"📂 <b>{btn_name}</b>"
                    try: bot.send_message(message.chat.id, get_tl_and_map(breadcrumb_text, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
                    except Exception: pass
                    send_path_content(message.chat.id, user_id, path, is_editing=False, reply_keyboard=None)
                else:
                    send_path_content(message.chat.id, user_id, path, is_editing=(state == 'posts_editing'), reply_keyboard=get_keyboard(user_id) if (is_admin and state == 'posts_editing') else None)
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

    # --- THE FIX: HANDLE NORMAL / POSTS EDITING TRAVERSAL WITH GLOBAL FALLBACK ---
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
            
        elif (current_path in menus and text in menus[current_path]) or any(text in btns for btns in menus.values()):
            
            if current_path not in menus or text not in menus[current_path]:
                for search_path, btns in menus.items():
                    if text in btns:
                        current_path = search_path
                        user_current_path[user_id] = current_path
                        break
                        
            custom_btn_path = f"{current_path}/{text}"
            meta = btn_metadata.get(custom_btn_path, get_default_metadata())
            
            if meta.get('admin_only') and not is_admin:
                return bot.send_message(message.chat.id, get_tl_and_map("⛔️ You do not have permission to use this button.", lang))

            if meta.get('withdrawal') and state != 'posts_editing':
                user_action_data[user_id] = {'path': custom_btn_path}
                
                if global_w_setup.get('do_not_ask_address'):
                    addr_var = global_w_setup.get('addr_var', 'wallet')
                    user_addr = user_db[user_id].get(addr_var, 'Not Set')
                    if user_addr == 'Not Set':
                        temp_msg = bot.send_message(message.chat.id, get_tl_and_map("⚠️ <b>Address Not Set!</b>\nYou have not set up your withdrawal address yet. Redirecting you to wallet setup...", lang), parse_mode="HTML")
                        
                        def redirect_to_wallet():
                            time.sleep(2.5)
                            try: bot.delete_message(message.chat.id, temp_msg.message_id)
                            except: pass
                            
                            if global_wallet_setup['ask_email'] and user_db[user_id].get('email', 'Not Set') == 'Not Set':
                                user_state[user_id] = 'wallet_wait_email'
                                bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_email_prompt'], lang), reply_markup=get_cancel_action_keyboard())
                            else:
                                user_state[user_id] = 'wallet_wait_address'
                                bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                                
                        threading.Thread(target=redirect_to_wallet, daemon=True).start()
                        return
                    else:
                        user_action_data[user_id]['address'] = user_addr
                        user_action_data[user_id]['network'] = user_db[user_id].get('wallet_net', 'Unknown')
                
                user_state[user_id] = 'w_action_amount'
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
                if global_bonus_setup.get('require_email', True) and user_db[user_id].get('email', 'Not Set') == 'Not Set':
                    user_state[user_id] = 'bonus_wait_email'
                    req_msg = global_bonus_setup.get('msg_email_req', "⚠️ <b>Email Required</b>\n\nTo claim your free bonus, you must safely link an email address to your account. Please reply with your email address now:")
                    bot.send_message(message.chat.id, get_tl_and_map(req_msg, lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                    return
                
                last_time = user_db[user_id].get('last_bonus_time', 0)
                cooldown = global_bonus_setup['cooldown_hours'] * 3600
                
                if now - last_time >= cooldown:
                    user_db[user_id]['bonus'] += global_bonus_setup['amount']
                    user_db[user_id]['last_bonus_time'] = now
                    log_tx(user_id, "Bonus Received", global_bonus_setup['amount'])
                    
                    msg = global_bonus_setup['msg_success'].replace('%bonus_amount%', str(global_bonus_setup['amount']))
                    bot.send_message(message.chat.id, get_tl_and_map(replace_macros(msg, user_id, custom_btn_path), lang), parse_mode="HTML")
                    
                    min_w = global_bonus_setup.get('min_withdraw', 50.0)
                    if user_db[user_id]['bonus'] >= min_w:
                        transfer_amt = user_db[user_id]['bonus']
                        user_db[user_id]['balance'] += transfer_amt
                        user_db[user_id]['bonus'] = 0.0
                        log_tx(user_id, "Bonus Auto-Transfer", transfer_amt)
                        notify_msg = f"🎉 <b>Bonus Threshold Reached!</b>\nYour bonus balance has automatically been transferred to your Withdrawable Balance.\nAmount: <b>${fmt_amt(transfer_amt)}</b>"
                        bot.send_message(message.chat.id, get_tl_and_map(notify_msg, lang), parse_mode="HTML")
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
                    txs_reversed = txs[::-1]
                    limit = 7
                    current_txs = txs_reversed[0:limit]
                    
                    msg = f"📜 <b>Your Transaction History (Page 1):</b>\n\n"
                    for tx in current_txs:
                        msg += f"🗓 <code>{tx['date']}</code>\n🔹 <b>{tx['type']}</b> | <b>${tx['amount']:.2f}</b>\n\n"
                    
                    markup = InlineKeyboardMarkup()
                    if len(txs_reversed) > limit:
                        markup.row(InlineKeyboardButton(get_tl_and_map('Next ➡️', lang), callback_data='cb_txpage_1'))
                        bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=markup)
                    else:
                        bot.send_message(message.chat.id, get_tl_and_map(msg, lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
                return

            if meta.get('is_reinvest') and state != 'posts_editing':
                valid_plans = [p for pid, p in bot_plans.items() if pid != 'plan0']
                if not valid_plans:
                    bot.send_message(message.chat.id, get_tl_and_map("⚠️ No valid plans available.", lang))
                    return
                min_plan_amount = min(p['min'] for p in valid_plans)

                u_dep = user_db[user_id].get('deposit', 0)
                u_bal = user_db[user_id].get('balance', 0)
                total_avail = u_dep + u_bal

                if total_avail < min_plan_amount:
                    fail_msg = reinvest_settings['msg_fail'].replace('%min_amount%', f"{fmt_amt(min_plan_amount)}")
                    markup = InlineKeyboardMarkup()
                    btn_text = get_tl_and_map(reinvest_settings['inline_deposit_text'], lang)
                    markup.row(InlineKeyboardButton(btn_text, callback_data='cb_reinv_dep_menu'))
                    bot.send_message(message.chat.id, get_tl_and_map(replace_macros(fail_msg, user_id, custom_btn_path), lang), parse_mode="HTML", reply_markup=markup)
                else:
                    user_state[user_id] = 'wait_reinvest_amount'
                    bot.send_message(message.chat.id, get_tl_and_map(f"🔄 <b>Reinvest</b>\n\nAvailable Balance: ${fmt_amt(total_avail)}\nMinimum Investment: ${fmt_amt(min_plan_amount)}\n\nEnter the amount you wish to reinvest:", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                return

            has_submenus = custom_btn_path in menus and len(menus[custom_btn_path]) > 0
            
            if is_admin and state in ['editing', 'posts_editing']:
                user_current_path[user_id] = custom_btn_path
                if custom_btn_path not in menus: menus[custom_btn_path] = []
                send_path_content(message.chat.id, user_id, custom_btn_path, is_editing=(state == 'posts_editing'), reply_keyboard=get_keyboard(user_id))
                
            elif has_submenus:
                user_current_path[user_id] = custom_btn_path
                breadcrumb_text = f"📂 <b>{text}</b>"
                try:
                    bot.send_message(
                        message.chat.id, 
                        get_tl_and_map(breadcrumb_text, lang), 
                        parse_mode="HTML", 
                        reply_markup=get_keyboard(user_id)
                    )
                except Exception: pass
                send_path_content(message.chat.id, user_id, custom_btn_path, is_editing=False, reply_keyboard=None)
                
            else:
                send_path_content(message.chat.id, user_id, custom_btn_path, is_editing=False, reply_keyboard=None)
                
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

    if p_data.get('is_free', False) or plan_id == 'plan0':
        # --- FREE PLAN LOOPHOLE FIX ---
        if user_db[user_id].get('has_claimed_free_plan', False) or any(p['macro'] == plan_id for p in user_db[user_id].get('active_plans', [])):
            user_db[user_id]['has_claimed_free_plan'] = True # Lock it down permanently if they snuck in
            return bot.answer_callback_query(call_id, get_tl_and_map(f"❌ Access Denied: You have already claimed your one-time Free Plan!", lang), show_alert=True)
            
        user_db[user_id]['has_claimed_free_plan'] = True # Set flag to true immediately
        
        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': plan_id, 'amount': invest_amount,
            'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        log_tx(user_id, f"Activated Free {p_data['name']}", invest_amount)
        bot.answer_callback_query(call_id, get_tl_and_map(f"🎉 Success! Activated {p_data['name']} with ${fmt_amt(invest_amount)} virtual capital!", lang), show_alert=True)
        
        user_current_path[user_id] = 'root'
        send_path_content(chat_id, user_id, 'root', False)
        return
        
    u_dep = user_db[user_id].get('deposit', 0)
    u_bal = user_db[user_id].get('balance', 0)
    total_avail = u_dep + u_bal
    
    if total_avail < invest_amount:
        user_db[user_id]['pending_plan'] = plan_id
        bot.answer_callback_query(call_id, get_tl_and_map(f"⚠️ Insufficient funds! You need ${fmt_amt(invest_amount)}.", lang), show_alert=True)
        
        redirect_cmd = p_data.get('redirect_cmd') or '/deposit'
        try: bot.delete_message(chat_id, message_id)
        except Exception: pass
        
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
    
    bot.answer_callback_query(call_id, get_tl_and_map(f"🎉 Success! You invested ${fmt_amt(invest_amount)} into {p_data['name']}! Profit is accruing automatically.", lang), show_alert=True)
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
    
    global pending_withdrawals

    if user_id in blocked_users:
        bot.answer_callback_query(call.id, get_tl_and_map("🚫 You are currently blocked.", lang), show_alert=True)
        return

    # --- NEW ARCHITECTURE: THE INTERCEPTOR (INLINE GATEWAY) ---
    if requires_subscription_wall(user_id, False) and call.data != 'cb_verify_sub':
        bot.answer_callback_query(call.id, get_tl_and_map("🚨 Please verify your subscription first.", lang), show_alert=True)
        return
        
    # --- NEW ARCHITECTURE: HOMEPAGE POPUP GATEWAY ---
    if call.data == 'cb_claim_homepage':
        if user_db[user_id].get('has_seen_homepage', False):
            bot.answer_callback_query(call.id, "⚠️ Already claimed.", show_alert=True)
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            return
            
        p_data = bot_plans.get('plan0', {})
        if not p_data: return bot.answer_callback_query(call.id, "Plan 0 not configured.", show_alert=True)
            
        invest_amt = p_data.get('bonus_amount', 50.0)
            
        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': 'plan0', 'amount': invest_amt,
            'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        log_tx(user_id, "Claimed Homepage Bonus", invest_amt)
            
        user_db[user_id]['has_seen_homepage'] = True
            
        # --- THE UI GLITCH FIX (Homepage): Strip the buttons before deleting ---
        try: 
            bot.edit_message_text(f"🎉 <b>Success! You claimed ${fmt_amt(invest_amt)} capital!</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            time.sleep(0.5)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
            
        bot.answer_callback_query(call.id, get_tl_and_map(f"🎉 Success! You claimed ${fmt_amt(invest_amt)} capital!", lang), show_alert=True)
            
        # THE MAGIC TRIGGER: USER CLEARED THE FINAL GATE
        finalize_user_registration(user_id)
            
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal'
        send_path_content(call.message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))
        return

    # --- NEW ARCHITECTURE: THE VERIFIER (SUBSCRIPTION API SWEEP) ---
    if call.data == 'cb_verify_sub':
        bot.answer_callback_query(call.id)
        
        style_opt = global_ui_settings.get('loading_bar_style', '1')
        frames = {
            '1': ["[▯▯▯▯▯▯▯▯▯▯] 0%", "[■■▯▯▯▯▯▯▯▯] 20%", "[■■■■▯▯▯▯▯▯] 40%", "[■■■■■■▯▯▯▯] 60%", "[■■■■■■■■▯▯] 80%", "[■■■■■■■■■■] 100%"],
            '2': ["░░░░░░░░░░ 0%", "▓▓░░░░░░░░ 20%", "▓▓▓▓░░░░░░ 40%", "▓▓▓▓▓▓░░░░ 60%", "▓▓▓▓▓▓▓▓░░ 80%", "▓▓▓▓▓▓▓▓▓▓ 100%"],
            '3': ["▒▒▒▒▒▒▒▒▒▒ 0%", "██▒▒▒▒▒▒▒▒ 20%", "████▒▒▒▒▒▒ 40%", "██████▒▒▒▒ 60%", "████████▒▒ 80%", "██████████ 100%"]
        }
        bars = frames.get(str(style_opt), frames['1'])
        
        all_passed = True
        channels = subscription_settings.get('channels', [])
        
        if not channels:
            all_passed = False # Failsafe
            
        for ch in channels:
            try:
                # Force ID to integer safely to ensure API doesn't fail on strings
                raw_id = ch['chat_id']
                chat_id_val = int(raw_id) if str(raw_id).lstrip('-').isdigit() else raw_id
                
                member = bot.get_chat_member(chat_id_val, user_id)
                
                # THE ULTIMATE FIX: Strict Whitelist. If they are not actively in the channel, they fail.
                if member.status not in ['member', 'administrator', 'creator']:
                    all_passed = False
                    break
            except Exception as e:
                # If Telegram API throws an error (e.g., User Not Found), they automatically FAIL.
                all_passed = False
                break 
                
        if not all_passed:
            fail_msg = get_tl_and_map(subscription_settings.get('msg_fail', '❌ You haven\'t joined all channels. Try again.'), lang)
            
            # Fire a hard on-screen popup alert so the user knows they failed
            bot.answer_callback_query(call.id, fail_msg, show_alert=True)
            
            markup = InlineKeyboardMarkup()
            for ch in subscription_settings.get('channels', []):
                markup.row(InlineKeyboardButton(ch['name'], url=ch['url']))
            btn_text = get_tl_and_map(subscription_settings.get('btn_check', '✅ I have joined, check now'), lang)
            markup.row(InlineKeyboardButton(btn_text, callback_data="cb_verify_sub"))
            
            try: bot.edit_message_text(f"⚠️ <b>VERIFICATION FAILED</b>\n\n{fail_msg}", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except: pass
            return
        else:
            bot.answer_callback_query(call.id, get_tl_and_map("✅ Verification Successful!", lang))
            
            user_db[user_id]['sub_verified'] = True
            user_db[user_id]['last_sub_check'] = time.time()
            
            # --- THE UI GLITCH FIX: Strip the buttons FIRST to force Telegram to update the screen ---
            try: 
                bot.edit_message_text("✅ <b>Verification complete! Loading dashboard...</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
                time.sleep(0.5) # Give the app a half-second to breathe
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            # Check if we need to trap them with the Pop-Up next
            if check_homepage_bonus(call.message.chat.id, user_id):
                return
                
            # If the Pop-up is OFF, they have cleared all gates. Register them!
            finalize_user_registration(user_id)
            
            # ENSURE MAIN MENU LOADS
            user_current_path[user_id] = 'root'
            user_state[user_id] = 'normal'
            send_path_content(call.message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))
            return

    if call.data == 'cb_scan_users':
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        bot.answer_callback_query(call.id, "Scanning users in background... This may take a moment.")
        
        def background_scan():
            dead_count = 0
            total_users = len(user_db)
            for uid in list(user_db.keys()):
                try:
                    bot.send_chat_action(uid, 'typing')
                    time.sleep(0.05) 
                except telebot.apihelper.ApiTelegramException as e:
                    if 'Forbidden' in str(e) or 'chat not found' in str(e) or 'deactivated' in str(e):
                        dead_count += 1
            
            active_users = total_users - dead_count
            bot_info = bot.get_me()
            btn_count = len(btn_metadata)
            msg_count = sum(len(v) for v in menu_posts.values())
            
            stats_msg = f"""📊 <b>BOT STATISTICS</b>
#statistics

@{bot_info.username}
▪️Created: [Auto]

▪️Users: {total_users}
▫️Active: {active_users}
▫️Deleted: {dead_count}
▪️Admins: {len(ADMIN_IDS)}

▪️Bot structure:
▫️Buttons: {btn_count} / 200
▫️Messages: {msg_count} / 400"""
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton('🔍 Scan', callback_data='cb_scan_users'))
            
            try:
                bot.edit_message_text(stats_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
            except: pass
            
        threading.Thread(target=background_scan, daemon=True).start()
        return

    if call.data == 'cb_gen_ref_link':
        bot.answer_callback_query(call.id)
        bot_info = bot.get_me()
        
        if invite_settings.get('use_dynamic_link', False):
            username_clean = call.from_user.username
            if username_clean:
                ref_id = f"gf_{username_clean}"
            else:
                ref_id = f"gf_{user_id}_{str(uuid.uuid4())[:4]}"
            
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

    if call.data.startswith('cb_question_'):
        bot.answer_callback_query(call.id)
        user_state[user_id] = 'wait_support_msg'
        bot.send_message(call.message.chat.id, get_tl_and_map("💬 <b>Support Desk</b>\n\nPlease type your message below. An administrator will reply as soon as possible.", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if call.data.startswith('cb_suprep_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        target_uid = call.data.replace('cb_suprep_', '')
        user_state[user_id] = f'admin_suprep_{target_uid}'
        bot.send_message(call.message.chat.id, f"Type your reply to User <code>{target_uid}</code>. It will be sent anonymously as 'Support'.", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return bot.answer_callback_query(call.id)

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

    if call.data.startswith('cb_unblock_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        target_id = int(call.data.replace('cb_unblock_', ''))
        
        if target_id in blocked_users:
            blocked_users.remove(target_id)
            bot.answer_callback_query(call.id, f"✅ User {target_id} successfully unblocked.", show_alert=True)
            
            target_lang = user_db.get(target_id, {}).get('lang', 'en')
            try: bot.send_message(target_id, get_tl_and_map(block_settings['msg_unblock'], target_lang), parse_mode="HTML")
            except: pass
            
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

    if call.data.startswith('cb_wad_'):
        if not is_admin: return bot.answer_callback_query(call.id, "Action not permitted.", show_alert=True)
        parts = call.data.split('_')
        action = parts[2] 
        mode = parts[3] 
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
            
            user_email = user_db.get(target, {}).get('email', 'Not Set')
            if user_email != 'Not Set':
                w_subject = "Withdrawal Processed - G-Force"
                w_html = f"""
                <div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
                    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
                        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
                    </div>
                    <div style="padding: 30px;">
                        <h3 style="margin-top: 0; color: #ffffff;">Withdrawal Approved</h3>
                        <p>Your withdrawal request has been fully processed by the administrator and the funds have been transferred to your wallet.</p>
                        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
                            <p style="margin: 5px 0; color: #848e9c;">Amount Sent: <span style="color: #f6465d; float: right; font-weight: bold;">-${fmt_amt(amt)}</span></p>
                            <p style="margin: 5px 0; color: #848e9c;">Network: <span style="color: #ffffff; float: right; font-weight: bold;">{w_data['network']}</span></p>
                            <p style="margin: 5px 0; color: #848e9c;">Destination: <span style="color: #ffffff; float: right; font-size: 12px; word-break: break-all;">{w_data['address']}</span></p>
                        </div>
                    </div>
                </div>
                """
                send_email_async(user_email, w_subject, w_html)
            
            if mode == 'm':
                msg_template = global_w_setup.get('w_msg_approve')
                if msg_template:
                    msg = replace_macros(msg_template, target, w_data['path'], w_data)
                    
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
            pending_auto_txids.pop(txid_found, None) 
            
            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
            usd_value = crypto_amount * live_price
            
            user_db[user_id]['deposit'] += usd_value
            user_db[user_id]['wallets'][curr]['total_deposited'] = user_db[user_id]['wallets'][curr].get('total_deposited', 0.0) + usd_value
            log_tx(user_id, f"Deposit ({curr})", usd_value)
            
            process_referral_commission(user_id, usd_value, is_deposit=True) 
            
            admin_msg = f"🟢 <b>DEPOSIT CONFIRMED (MANUAL)</b>\nUser: <code>{user_id}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}\nHash (TXID): <code>{txid_found}</code>"
            for admin in ADMIN_IDS:
                try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                except Exception: pass
                
            check_and_trigger_auto_buy(user_id)
            
            # --- LIVE CHANNEL HOOK ---
            broadcast_real_deposit(user_id, usd_value, curr.replace('_', ' '), txid_found)
            
            try: bot.send_message(call.message.chat.id, get_tl_and_map(f"✅ <b>Deposit Successful!</b>\nAmount: {fmt_amt(crypto_amount)} {curr.split('_')[0]}\nCredited: ${fmt_amt(usd_value)}", lang), parse_mode="HTML")
            except: pass
            
        else:
            try: bot.send_message(call.message.chat.id, get_tl_and_map(f"⏳ <b>Pending:</b> Your transaction is still waiting for blockchain confirmation. Please wait a moment and click Confirm again.", lang), parse_mode="HTML")
            except: pass
            
        try: bot.delete_message(call.message.chat.id, scan_msg.message_id)
        except: pass
        return

    if call.data == 'cb_wallet_start':
        bot.answer_callback_query(call.id)
        if global_wallet_setup['ask_email'] and user_db[user_id].get('email', 'Not Set') == 'Not Set':
            user_state[user_id] = 'wallet_wait_email'
            bot.send_message(call.message.chat.id, get_tl_and_map(global_wallet_setup['msg_email_prompt'], lang), reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'wallet_wait_address'
            bot.send_message(call.message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if call.data.startswith('cb_lang_'):
        btn_id = call.data.split('_')[2]
        target_lang = 'en'
        for path, posts in menu_posts.items():
            for p in posts:
                for b in p.get('custom_inlines', []):
                    if b['id'] == btn_id:
                        target_lang = b['data'].strip()
        
        if target_lang.lower() == 'zh-cn': target_lang = 'zh-CN'
        else: target_lang = target_lang.lower()

        user_db[user_id]['lang'] = target_lang
        bot.answer_callback_query(call.id, get_tl_and_map("Language updated!", target_lang), show_alert=True)
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal'
        send_path_content(call.message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))
        return

    if call.data.startswith('cb_calcbuy_'):
        parts = call.data.split('_')
        plan_id = parts[2]
        amount = float(parts[3])
        execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_id, amount)
        return

    if call.data.startswith('cb_buyplan_'):
        plan_id = call.data.split('_')[2]
        if plan_id not in bot_plans:
            return bot.answer_callback_query(call.id, get_tl_and_map("Plan not found.", lang), show_alert=True)
            
        p_data = bot_plans[plan_id]
        
        if p_data.get('is_free', False) or plan_id == 'plan0' or p_data['min'] == p_data['max']:
            execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_id, p_data['min'] if plan_id != 'plan0' else None)
            return
            
        u_dep = user_db[user_id].get('deposit', 0)
        u_bal = user_db[user_id].get('balance', 0)
        total_avail = u_dep + u_bal
        
        if total_avail < p_data['min']:
            user_db[user_id]['pending_plan'] = plan_id
            bot.answer_callback_query(call.id, get_tl_and_map(f"⚠️ Insufficient balance. You need at least ${fmt_amt(p_data['min'])}.", lang), show_alert=True)
            
            redirect_cmd = p_data.get('redirect_cmd') or '/deposit'
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception: pass
            
            msg = telebot.types.Message(call.message.message_id, None, None, None, redirect_cmd, [], None)
            msg.from_user = call.from_user
            msg.chat = telebot.types.Chat(call.message.chat.id, 'private')
            msg.text = redirect_cmd
            handle_messages(msg)
            return
            
        if user_id not in user_action_data: user_action_data[user_id] = {}
        user_action_data[user_id]['buy_plan_id'] = plan_id
            
        user_state[user_id] = 'buyplan_wait_amount'
        bot.send_message(call.message.chat.id, get_tl_and_map(f"📈 <b>{p_data['name']}</b>\nMin: ${fmt_amt(p_data['min'])} | Max: ${fmt_amt(p_data['max'])}\n\nAvailable Balance: ${fmt_amt(total_avail)}\n\nEnter the amount you wish to invest:", lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        bot.answer_callback_query(call.id)
        return

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
                            
                        execute_plan_purchase_via_popup(user_id, call.message.chat.id, call.message.message_id, call.id, plan_macro)
                        return
        return bot.answer_callback_query(call.id)

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
            
            process_referral_commission(target, amt, is_deposit=True) 
            
            msg_success = conf.get('msg_success', "✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.")
            msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(amt)}").replace('%crypto_amount%', '')
            target_lang = user_db.get(target, {}).get('lang', 'en')
            bot.send_message(target, get_tl_and_map(msg_success, target_lang), parse_mode="HTML")
            
            try:
                if call.message.photo: bot.edit_message_caption(f"{call.message.caption}\n\n✅ **APPROVED**", call.message.chat.id, call.message.message_id, reply_markup=None)
                else: bot.edit_message_text(f"{call.message.text}\n\n✅ **APPROVED**", call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception: pass
            
            check_and_trigger_auto_buy(target) 
            
            # --- LIVE CHANNEL HOOK ---
            broadcast_real_deposit(target, amt, curr.replace('_', ' '), None) 
            
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

    if call.data == 'cb_w_yes':
        if user_state.get(user_id) == 'w_action_conf':
            data = user_action_data[user_id]
            meta = btn_metadata.get(data['path'], get_default_metadata())
            
            amount = data['amount']
            w_var = global_w_setup.get('w_var', 'balance')
            
            user_db[user_id][w_var] -= amount
            user_db[user_id]['total_withdrawn'] = user_db[user_id].get('total_withdrawn', 0.0) + amount
            log_tx(user_id, "Withdrawal Pending", -amount)
            
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass

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
            
            w_id = str(uuid.uuid4())[:8]
            
            if 'pending_withdrawals' not in globals():
                pending_withdrawals = {}
            
            addr = data.get('address', user_db[user_id].get('wallet', 'Unknown'))
            net = data.get('network', user_db[user_id].get('wallet_net', 'Unknown'))
            comm_pct = global_w_setup.get('w_commission', 0.0)
            final_amt = amount - (amount * (comm_pct / 100.0))
            
            pending_withdrawals[w_id] = {
                'user_id': user_id, 'amount': amount, 'final_amt': final_amt,
                'address': addr, 'network': net, 'currency_var': w_var,
                'path': data['path']
            }
            
            adm_markup = InlineKeyboardMarkup()
            adm_markup.row(
                InlineKeyboardButton('Approve ✅', callback_data=f'cb_wad_app_s_{w_id}'),
                InlineKeyboardButton('Decline', callback_data=f'cb_wad_dec_s_{w_id}'),
                InlineKeyboardButton('Ignore', callback_data=f'cb_wad_ign_s_{w_id}')
            )
            adm_markup.row(
                InlineKeyboardButton('Approve 📝', callback_data=f'cb_wad_app_m_{w_id}'),
                InlineKeyboardButton('Decline 📝', callback_data=f'cb_wad_dec_m_{w_id}'),
                InlineKeyboardButton('Ignore 📝', callback_data=f'cb_wad_ign_m_{w_id}')
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
        for k in [k for k in list(menus.keys()) if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del menus[k]
        for k in [k for k in list(btn_metadata.keys()) if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del btn_metadata[k]
        for k in [k for k in list(menu_posts.keys()) if k == full_path_to_del or k.startswith(full_path_to_del + '/')]: del menu_posts[k]
        
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

        # --- NEW FEATURE: GET ALL EMAILS API ---
        elif parsed_path.path == '/api/get_emails':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            emails_list = []
            for uid, udata in user_db.items():
                email = udata.get('email', 'Not Set')
                if email != 'Not Set':
                    emails_list.append({
                        'uid': uid,
                        'username': udata.get('username', str(uid)),
                        'email': email
                    })
                    
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'emails': emails_list}).encode())

        # --- NEW ARCHITECTURE: TARGETED EMAIL BROADCAST API ---
        elif parsed_path.path == '/api/send_email_broadcast':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            
            subject = data.get('subject', 'Important Update')
            html_body = data.get('html_body', '')
            target_mode = data.get('target_mode', 'all')
            target_email = data.get('target_email', '')
            
            if not html_body:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'No HTML body provided'}).encode())
                return
            
            sent_count = 0
            
            if target_mode == 'individual':
                if target_email:
                    send_email_async(target_email, subject, html_body)
                    sent_count = 1
            else:
                for uid, udata in user_db.items():
                    email = udata.get('email', 'Not Set')
                    if email != 'Not Set':
                        send_email_async(email, subject, html_body)
                        sent_count += 1
                    
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'sent': sent_count}).encode())

        # --- UPDATED: 3-POINT RESOURCE METRICS (CPU, RAM, DISK) ---
        elif parsed_path.path == '/api/server_stats':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
                
            stats = {
                'aiven_storage': {'used_mb': 0, 'total_mb': 1024}, 
                'bot_ram': {'used_mb': 0, 'total_mb': 1024},       
                'bot_cpu': {'percent': 0}                          
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
                with open('/sys/fs/cgroup/memory.current', 'r') as f:
                    ram_bytes = int(f.read().strip())
                stats['bot_ram']['used_mb'] = round(ram_bytes / (1024 * 1024), 2)
            except:
                stats['bot_ram']['used_mb'] = round(psutil.virtual_memory().used / (1024 * 1024), 2)

            # 3. Measure Bot CPU (Brain Power)
            stats['bot_cpu']['percent'] = psutil.cpu_percent(interval=None)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'stats': stats}).encode())

            if NORTHFLANK_API_KEY and NORTHFLANK_PROJECT:
                try:
                    headers = {"Authorization": f"Bearer {NORTHFLANK_API_KEY}"}
                    url = f"https://api.northflank.com/v1/projects/{NORTHFLANK_PROJECT}/services"
                    resp = requests.get(url, headers=headers, timeout=5)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        services = data.get('data', {}).get('services', [])
                        
                        if services:
                            try:
                                with open('/sys/fs/cgroup/memory.current', 'r') as f:
                                    ram_bytes = int(f.read().strip())
                            except FileNotFoundError:
                                try:
                                    with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                                        ram_bytes = int(f.read().strip())
                                except FileNotFoundError:
                                    ram_bytes = 0 
                                    
                            stats['northflank']['used_mb'] = round(ram_bytes / (1024 * 1024), 2)
                            stats['northflank']['total_mb'] = 512.00 
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

        # --- NEW FEATURE: EMAIL TEMPLATES API ---
        elif parsed_path.path == '/api/get_email_templates':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            
            default_templates = {
                'welcome': """<div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
    </div>
    <div style="padding: 30px;">
        <h3 style="margin-top: 0; color: #ffffff;">Welcome Aboard!</h3>
        <p>Your email has been successfully securely linked to your Telegram account.</p>
        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 5px 0; color: #848e9c;">Status: <span style="color: #0ecb81; float: right; font-weight: bold;">Verified</span></p>
        </div>
        <p>You can now return to the bot to claim your free USDT bonus and start trading on the live markets.</p>
    </div>
</div>""",
                'deposit': """<div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
    </div>
    <div style="padding: 30px;">
        <h3 style="margin-top: 0; color: #ffffff;">Deposit Confirmed</h3>
        <p>Your deposit has been successfully credited to your account.</p>
        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 5px 0; color: #848e9c;">Asset: <span style="color: #ffffff; float: right; font-weight: bold;">{currency}</span></p>
            <p style="margin: 5px 0; color: #848e9c;">Amount: <span style="color: #0ecb81; float: right; font-weight: bold;">+{crypto_amount}</span></p>
            <p style="margin: 5px 0; color: #848e9c;">USD Value: <span style="color: #ffffff; float: right; font-weight: bold;">${usd_amount}</span></p>
        </div>
        <p style="color: #848e9c; font-size: 12px; word-break: break-all;">TXID: {txid}</p>
    </div>
</div>""",
                'withdrawal': """<div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
    </div>
    <div style="padding: 30px;">
        <h3 style="margin-top: 0; color: #ffffff;">Withdrawal Approved</h3>
        <p>Your withdrawal request has been fully processed by the administrator and the funds have been transferred to your wallet.</p>
        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 5px 0; color: #848e9c;">Amount Sent: <span style="color: #f6465d; float: right; font-weight: bold;">-${amount}</span></p>
            <p style="margin: 5px 0; color: #848e9c;">Network: <span style="color: #ffffff; float: right; font-weight: bold;">{network}</span></p>
            <p style="margin: 5px 0; color: #848e9c;">Destination: <span style="color: #ffffff; float: right; font-size: 12px; word-break: break-all;">{address}</span></p>
        </div>
    </div>
</div>""",
                'expiry': """<div style="background-color: #0b0e11; color: #eaecef; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #2b3139; border-radius: 8px; overflow: hidden;">
    <div style="background-color: #181a20; padding: 20px; border-bottom: 1px solid #2b3139; text-align: center;">
        <h2 style="margin: 0; color: #fcd535;">G-FORCE TRADING</h2>
    </div>
    <div style="padding: 30px;">
        <h3 style="margin-top: 0; color: #ffffff;">Trading Completed</h3>
        <p>Your investment in <b>{plan_name}</b> has successfully finished its cycle.</p>
        <div style="background-color: #181a20; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 5px 0; color: #848e9c;">Initial Capital: <span style="color: #ffffff; float: right; font-weight: bold;">${initial_amount}</span></p>
            <p style="margin: 5px 0; color: #848e9c;">Total Profit Earned: <span style="color: #0ecb81; float: right; font-weight: bold;">+${profit_earned}</span></p>
        </div>
        <p style="color: #848e9c; font-size: 14px;">Your funds are now available in your withdrawal balance.</p>
    </div>
</div>"""
            }
            
            saved_templates = db_data.get('email_templates', default_templates)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'templates': saved_templates}).encode())

        elif parsed_path.path == '/api/save_email_templates':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            
            try:
                templates = data.get('templates', {})
                if not isinstance(templates, dict):
                    raise ValueError("Templates must be a dictionary")
                
                global email_templates
                email_templates = templates
                
                save_database() 
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

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
    # Initialize email templates in memory from DB
    global email_templates
    email_templates = db_data.get('email_templates', {})

    # Start the Background Accruals Engine (True Hourly Alerts)
    print("🕒 Starting background accruals and alert thread...")
    threading.Thread(target=background_accruals_loop, daemon=True).start()

    # Start the Web Server (Required for Render and Dashboard)
    print("🌐 Starting web server...")
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
