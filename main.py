import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import uuid
import time
import os
import threading
import concurrent.futures
import requests
import json
import html
import re
import io
import base64
import hashlib
import hmac
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
        def translate_batch(self, texts): return list(texts)

TL_CACHE = {}
REVERSE_TL_MAP = {}

# Tokens that must be preserved verbatim through translation:
#   - macros like %amount%, %balance%, %loading_bar_3s%
#   - slash commands like /setwallet, /start
#   - HTML tags like <b>, </code>
_MACRO_RE = re.compile(r'(%[^%\n]+?%|/[A-Za-z][A-Za-z0-9_]*|</?[A-Za-z][^>]*>)')

# Private-Use Area: characters U+E000..U+F8FF have no defined meaning, so
# Google Translate (and every other translation engine) passes them through
# verbatim — no spacing, no full-width conversion, no case changes. This is
# critical for Chinese / Japanese / Arabic where ASCII placeholders break.
_PUA_BASE = 0xE000

def _protect_tokens(text):
    """Replace macros/commands/HTML tags with PUA placeholders that survive
    every translation engine intact. Returns (protected_text, token_map)."""
    tokens = []
    def _sub(m):
        ph = chr(_PUA_BASE + len(tokens))
        tokens.append((ph, m.group(0)))
        return ph
    protected = _MACRO_RE.sub(_sub, text)
    return protected, tokens

def _restore_tokens(text, tokens):
    if not tokens or not isinstance(text, str):
        return text
    for ph, original in tokens:
        text = text.replace(ph, original)
    return text

# Normalize various language code aliases to what deep-translator expects.
# Common pitfalls: Telegram/legacy codes vs Google's expected codes.
_LANG_ALIAS = {
    'iw': 'he',        # legacy Hebrew code -> Modern Hebrew
    'in': 'id',        # legacy Indonesian
    'ji': 'yi',        # legacy Yiddish
    'jv': 'jw',        # Javanese
    'zh': 'zh-CN',     # default Chinese to Simplified
    'zh-cn': 'zh-CN',
    'zh-tw': 'zh-TW',
    'pt-br': 'pt',     # Brazilian Portuguese -> pt
    'pt-pt': 'pt',
    'nb': 'no',        # Norwegian Bokmål -> Norwegian
}

def _normalize_lang(code):
    if not code or not isinstance(code, str):
        return 'en'
    low = code.strip().lower()
    return _LANG_ALIAS.get(low, code if code == 'zh-CN' else low)

# --- GLOBAL SPEED CACHE (Instant Translations for All 13 Languages) ---
# This dictionary prevents timeouts by hardcoding core withdrawal phrases.
CORE_TL_DATA = {
    'Please enter the amount you wish to withdraw:': {
        'zh': '请输入您要提取的金额：', 'es': 'Por favor, ingrese la cantidad a retirar:', 'hi': 'कृपया वह राशि दर्ज करें जिसे आप निकालना चाहते हैं:',
        'ar': 'يرجى إدخال المبلغ الذي ترغب في سحبه:', 'pt': 'Por favor, insira o valor que deseja retirar:', 'ru': 'Введите сумму, которую хотите снять:',
        'ja': '引き出し額を入力してください：', 'fr': 'Veuillez saisir le montant à retirer :', 'de': 'Bitte geben Sie den Abhebungsbetrag ein:',
        'vi': 'Vui lòng nhập số tiền bạn muốn rút:', 'tr': 'Lütfen çekmek istediğiniz tutarı giriniz:', 'ko': '출금하실 금액을 입력해 주세요:', 'it': 'Inserisci l\'importo che desideri prelevare:'
    },
    'Please enter your withdrawal address:': {
        'zh': '请输入您的提现地址：', 'es': 'Por favor, ingrese su dirección de retiro:', 'hi': 'कृपया अपना निकासी पता दर्ज करें:',
        'ar': 'يرجى إدخال عنوان السحب الخاص بك:', 'pt': 'Por favor, insira o seu endereço de levantamento:', 'ru': 'Введите ваш адрес для вывода:',
        'ja': '引き出し先アドレスを入力してください：', 'fr': 'Veuillez saisir votre adresse de retrait :', 'de': 'Geben Sie Ihre Auszahlungsadresse ein:',
        'vi': 'Vui lòng nhập địa chỉ rút tiền của bạn:', 'tr': 'Lütfen çekim adresinizi giriniz:', 'ko': '출금 주소를 입력해 주세요:', 'it': 'Inserisci il tuo indirizzo di prelievo:'
    },
    '⚠️ Invalid amount. Numbers only.': {
        'zh': '⚠️ 金额无效。仅限数字。', 'es': '⚠️ Cantidad inválida. Solo números.', 'hi': '⚠️ अमान्य राशि। केवल नंबर।',
        'ar': '⚠️ مبلغ غير صحيح. أرقام فقط.', 'pt': '⚠️ Valor inválido. Apenas números.', 'ru': '⚠️ Неверная сумма. Только цифры.',
        'ja': '⚠️ 無効な金額です。数字のみ。', 'fr': '⚠️ Montant invalide. Chiffres uniquement.', 'de': '⚠️ Ungültiger Betrag. Nur Zahlen.',
        'vi': '⚠️ Số tiền không hợp lệ. Chỉ nhập số.', 'tr': '⚠️ Geçersiz tutar. Sadece sayılar.', 'ko': '⚠️ 유효하지 않은 금액입니다. 숫자만 입력 가능합니다.', 'it': '⚠️ Importo non valido. Solo numeri.'
    },
    '⚠️ Insufficient balance.': {
        'zh': '⚠️ 余额不足。', 'es': '⚠️ Saldo insuficiente.', 'hi': '⚠️ अपर्याप्त शेष राशि।',
        'ar': '⚠️ رصيد غير كافٍ.', 'pt': '⚠️ Saldo insuficiente.', 'ru': '⚠️ Недостаточный баланс.',
        'ja': '⚠️ 残高不足です。', 'fr': '⚠️ Solde insuffisant.', 'de': '⚠️ Unzureichendes Guthaben.',
        'vi': '⚠️ Số dư không đủ.', 'tr': '⚠️ Yetersiz bakiye.', 'ko': '⚠️ 잔액이 부족합니다.', 'it': '⚠️ Saldo insufficiente.'
    },
    'Confirm withdrawal of %withdraw% to %address%': {
        'zh': '确认将 %withdraw% 提取至 %address%', 'es': 'Confirmar retiro de %withdraw% a %address%', 'hi': '%address% को %withdraw% की निकासी की पुष्टि करें',
        'ar': 'تأكيد سحب %withdraw% إلى %address%', 'pt': 'Confirmar levantamento de %withdraw% para %address%', 'ru': 'Подтвердите вывод %withdraw% на %address%',
        'ja': '%address% への %withdraw% の出金を確認する', 'fr': 'Confirmer le retrait de %withdraw% vers %address%', 'de': 'Auszahlung von %withdraw% an %address% bestätigen',
        'vi': 'Xác nhận rút %withdraw% về %address%', 'tr': '%withdraw% tutarının %address% adresine çekimini onayla', 'ko': '%withdraw%을(를) %address%(으)로 출금 확인', 'it': 'Conferma il prelievo di %withdraw% su %address%'
    }
}

# Bounded thread pool for non-blocking Google Translate calls.
# Larger pool = many strings translate in parallel on first language switch.
_TL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix='tl')
_TL_INFLIGHT = {}  # cache_key -> Future, to coalesce duplicate fetches and let callers wait
_TL_INFLIGHT_LOCK = threading.Lock()
# Max time we let the user wait for a single fresh translation before falling
# back to English. Buttons MUST translate before being shown, but we cap the
# wait short so a slow Google response never freezes the UI. The translation
# still completes in the background and is cached for next time.
_TL_WAIT_SECONDS = 2.5
# Total wall-clock budget for the bulk prewarm we run before each render.
# Most languages return ≤1.5s even for 30 strings (single batch HTTP call).
_TL_BULK_TIMEOUT = 3.0

def _tl_fetch_and_cache(cache_key, text, target_lang):
    """Worker run inside _TL_EXECUTOR. Returns the translated string on success
    (also caching it persistently via TL_CACHE), or None on any failure /
    when Google returned the source unchanged. Callers can `.result(timeout=…)`
    on the Future returned by submit() to either wait or move on."""
    try:
        protected, tokens = _protect_tokens(text)
        target_norm = _normalize_lang(target_lang)
        result = GoogleTranslator(source='en', target=target_norm).translate(protected)
        if result:
            result = _restore_tokens(result, tokens)
            # Skip caching when Google returned the input unchanged: that means
            # the translation didn't actually happen (rate limit, unsupported
            # source, etc.) and we don't want to lock in the English version.
            # Also skip if any %macro%, /command, or HTML tag from the source
            # didn't make it back into the result.
            if (result.strip()
                    and result.strip() != text.strip()
                    and _tokens_intact(text, result)):
                TL_CACHE[cache_key] = result
                if target_lang not in REVERSE_TL_MAP: REVERSE_TL_MAP[target_lang] = {}
                REVERSE_TL_MAP[target_lang][result] = text
                return result
    except Exception as e:
        print(f"Translate error ({target_lang}): {e}")
    finally:
        # Always clear the inflight slot so future calls can re-attempt this key.
        with _TL_INFLIGHT_LOCK:
            _TL_INFLIGHT.pop(cache_key, None)
    return None

def _tokens_intact(source, translated):
    """Return True iff every %macro% / /command / HTML tag that appears in
    `source` also appears verbatim in `translated`. Used to detect cached
    translations that lost their macros (e.g. older entries cached before the
    PUA-placeholder fix, where Chinese turned %address% into %地址%)."""
    if not isinstance(translated, str):
        return False
    for tok in _MACRO_RE.findall(source):
        if tok not in translated:
            return False
    return True

def get_tl_and_map(text, target_lang, wait=True):
    """Translate `text` from English to `target_lang` and remember the mapping
    so the bot can recognise the translated string when the user taps it.

    If the translation is already in CORE_TL_DATA (instant) or TL_CACHE
    (persistent across restarts), it is returned immediately.

    Otherwise we submit a fetch to the bounded thread pool. With wait=True
    (default) we block up to _TL_WAIT_SECONDS for the result so buttons /
    short prompts always come back fully translated. Set wait=False from
    long-running background jobs (broadcasts, prewarm) where blocking would
    slow the whole loop."""
    if not text or target_lang == 'en': return text
    target_lang = _normalize_lang(target_lang)
    if target_lang == 'en': return text

    tl_text = None

    # 1. Instant Global Speed Cache (hand-curated, ships with the bot).
    if text in CORE_TL_DATA and target_lang in CORE_TL_DATA[text]:
        candidate = CORE_TL_DATA[text][target_lang]
        if _tokens_intact(text, candidate):
            tl_text = candidate

    cache_key = ('en', target_lang, text)

    # 2. Persistent memory cache (validate macros survived).
    if not tl_text and cache_key in TL_CACHE:
        candidate = TL_CACHE[cache_key]
        if _tokens_intact(text, candidate):
            tl_text = candidate
        else:
            # Stale entry from before the PUA fix; drop it so we re-fetch.
            TL_CACHE.pop(cache_key, None)

    # 3. Not cached: submit a fetch and (if wait) block briefly for the result.
    if not tl_text:
        with _TL_INFLIGHT_LOCK:
            future = _TL_INFLIGHT.get(cache_key)
            if future is None:
                try:
                    future = _TL_EXECUTOR.submit(_tl_fetch_and_cache, cache_key, text, target_lang)
                    _TL_INFLIGHT[cache_key] = future
                except Exception:
                    future = None

        if wait and future is not None:
            try:
                fetched = future.result(timeout=_TL_WAIT_SECONDS)
                if isinstance(fetched, str) and fetched.strip():
                    tl_text = fetched
            except concurrent.futures.TimeoutError:
                # Fetch is still running — fall through to English. The
                # background job will populate TL_CACHE so the next call
                # for the same string is instant.
                pass
            except Exception:
                pass

        if not tl_text:
            tl_text = text

    # Update REVERSE_TL_MAP so the bot recognises this localised string when
    # the user taps it as a reply-keyboard button.
    if target_lang not in REVERSE_TL_MAP: REVERSE_TL_MAP[target_lang] = {}
    REVERSE_TL_MAP[target_lang][tl_text] = text

    return tl_text


def _collect_ui_strings():
    """Collect all UI strings that may be shown to a user, for batch pre-translation."""
    strings = set()
    try:
        for path, posts in menu_posts.items():
            for p in posts:
                if p.get('text'): strings.add(p['text'])
                for b in p.get('custom_inlines', []) or []:
                    if b.get('text') and b.get('mode') != 'set_lang':
                        strings.add(b['text'])
        for path, btns in menus.items():
            for b in btns or []:
                if isinstance(b, dict) and b.get('name'): strings.add(b['name'])
                elif isinstance(b, str): strings.add(b)
        for d in (global_w_setup, global_wallet_setup, global_bonus_setup,
                  reinvest_settings, global_messages_setup, block_settings,
                  subscription_settings, homepage_bonus_settings, invite_settings,
                  deposit_broadcast_settings):
            if isinstance(d, dict):
                for v in d.values():
                    if isinstance(v, str) and v.strip(): strings.add(v)
        for c, dd in (deposit_settings or {}).items():
            if isinstance(dd, dict):
                for v in dd.values():
                    if isinstance(v, str) and v.strip(): strings.add(v)
        for p_macro, p_data in (bot_plans or {}).items():
            if isinstance(p_data, dict):
                for v in p_data.values():
                    if isinstance(v, str) and v.strip(): strings.add(v)
    except Exception as e:
        print(f"_collect_ui_strings warning: {e}")
    # Core UI strings that appear on every keyboard / state for regular users.
    strings.update([
        "Language updated!", "✅ Language updated!", "Action cancelled.",
        "Select a currency to deposit:", "Error: Currency not configured.",
        "Action not permitted.", "Post not found.",
        "Switching language...", "🌐 Switching language...",
        # Reply keyboard core buttons
        "❌ Cancel Action", "🔙 Back", "🏠 Home", "💵 Balance",
        "🔐 Admin", "🎛️ Buttons Editor", "📝 Posts Editor",
        "🔙 Back to Main", "🔙 Exit Balance", "🔙 Exit Button Settings",
        # Common error / fallback messages
        "⚠️ Invalid amount. Please enter numbers only.",
        "⚠️ Invalid amount. Numbers only.",
        "⚠️ Insufficient funds.",
        "⛔️ You do not have permission to use this button.",
        "🚫 You are currently blocked.",
    ])
    return [s for s in strings if isinstance(s, str) and s.strip()]


def prewarm_language(target_lang, timeout=12.0):
    """Translate every UI string into target_lang via batch API and store in TL_CACHE.

    Returns the number of newly translated strings. Blocks up to `timeout` seconds.
    """
    if not target_lang or target_lang == 'en':
        return 0
    target_norm = _normalize_lang(target_lang)
    if target_norm == 'en':
        return 0
    all_strings = _collect_ui_strings()
    # Only translate strings not already cached (memory or CORE_TL_DATA)
    pending = []
    for s in all_strings:
        if ('en', target_lang, s) in TL_CACHE:
            continue
        if s in CORE_TL_DATA and target_lang in CORE_TL_DATA[s]:
            TL_CACHE[('en', target_lang, s)] = CORE_TL_DATA[s][target_lang]
            continue
        pending.append(s)
    if not pending:
        return 0

    BATCH_SIZE = 80  # bigger batches = fewer HTTP round-trips on language switch
    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]

    def _do_batch(batch):
        # Protect macros/commands/HTML in each string before sending to Google
        protected_batch = []
        token_maps = []
        for s in batch:
            p, toks = _protect_tokens(s)
            protected_batch.append(p)
            token_maps.append(toks)
        translator = GoogleTranslator(source='en', target=target_norm)
        # First try the batch endpoint (fast: one HTTP request).
        try:
            results = translator.translate_batch(protected_batch)
        except Exception as e:
            print(f"prewarm batch error ({target_lang}): {e}; falling back to per-string")
            results = None
        # If batch failed or returned bad data, fall back to per-string.
        if not results or not isinstance(results, list) or len(results) != len(protected_batch):
            results = []
            for p in protected_batch:
                try:
                    r = translator.translate(p)
                except Exception as e:
                    print(f"per-string translate error ({target_lang}): {e}")
                    r = None
                results.append(r)
        # Restore the original tokens in each result
        results = [
            _restore_tokens(r, t) if isinstance(r, str) else r
            for r, t in zip(results, token_maps)
        ]
        return batch, results

    futures = [_TL_EXECUTOR.submit(_do_batch, b) for b in batches]
    done, _ = concurrent.futures.wait(futures, timeout=timeout)
    added = 0
    for fut in done:
        try:
            batch, results = fut.result()
        except Exception:
            continue
        if not results:
            continue
        for src, tr in zip(batch, results):
            # Skip empty results and anything that came back equal to the source
            # (means Google didn't actually translate it for this language).
            if not (isinstance(tr, str) and tr.strip()):
                continue
            if tr.strip() == src.strip():
                continue
            # Skip results that lost a %macro% / /command / HTML tag.
            if not _tokens_intact(src, tr):
                continue
            TL_CACHE[('en', target_lang, src)] = tr
            REVERSE_TL_MAP.setdefault(target_lang, {})[tr] = src
            added += 1
    return added


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

def _is_admin_panel_state(state):
    """Return True when an admin user is currently inside the admin panel
    (admin menus, wizards, content editor, balance manager, etc.). Anything
    else — normal browsing, withdraw, deposit, plan-buy, calculator, support —
    is the regular user-facing interface and should be translated."""
    if not state or state == 'normal':
        return False
    # Explicit prefixes that always mean "admin panel"
    admin_prefixes = (
        'admin_', 'bal_', 'posts_', 'pi_wait_', 'bc_wait_',
        'w_setup_', 'dep_setup_', 'wallet_setup_', 'bonus_setup_',
        'reinvest_setup_', 'msg_setup_', 'plan_setup_',
        'wait_block', 'wait_edit_block', 'wait_edit_unblock',
        'wait_wipe', 'wait_general_wipe', 'wait_sub_', 'wait_home_',
        'wait_invite_', 'wait_ref_', 'wait_payout_popup',
    )
    if state.startswith(admin_prefixes):
        return True
    # Explicit state names (content/button editor, broadcast)
    admin_exact = {
        'editing', 'adding_button', 'renaming_button', 'button_settings',
        'assign_command', 'assign_plan', 'admin_wait_tx_id',
        'admin_loading_time', 'wait_support_msg',
    }
    return state in admin_exact

def get_user_lang(uid):
    """Resolve a user's UI language.

    Admins see English ONLY while they are inside the admin panel itself
    (admin menus, content/button editor, balance manager, wizards, broadcast,
    etc.). When an admin browses the bot like a normal user (main menu,
    withdraw, deposit, plan-buy, support chat, calculator…), their selected
    language is respected just like any other user."""
    if 'user_db' not in globals():
        return 'en'
    try:
        is_admin = uid in ADMIN_IDS
    except Exception:
        is_admin = False
    if is_admin:
        try:
            state = user_state.get(uid, 'normal') if 'user_state' in globals() else 'normal'
        except Exception:
            state = 'normal'
        if _is_admin_panel_state(state):
            return 'en'
    try:
        return user_db.get(uid, {}).get('lang', 'en')
    except Exception:
        return 'en'

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
# --- MULTI-KEY SUPPORT: accept 2nd/3rd keys so rate limits fail over ---
# You CANNOT have two env vars with the same name, so we accept all of:
#   TRONGRID_API_KEY="key1,key2"  (comma / space / semicolon separated)
#   TRONGRID_API_KEY_2="key2"     (extra slot for a second key)
#   TRONGRID_API_KEY_3="key3"     (optional third key)
#   TRONGRID_API_KEYS="key1,key2" (plural alias)
# All callers below try keys in round-robin order and fail over on 429/401.
def _split_tron_keys(s):
    if not s or not isinstance(s, str):
        return []
    s = s.replace('"', '').replace("'", "")
    parts = re.split(r'[,;\s]+', s)
    return [p.strip() for p in parts if p.strip()]

TRONGRID_API_KEYS = []
for _raw in (os.getenv('TRONGRID_API_KEY', ''),
             os.getenv('TRONGRID_API_KEY_2', ''),
             os.getenv('TRONGRID_API_KEY_3', ''),
             os.getenv('TRONGRID_API_KEYS', '')):
    for _k in _split_tron_keys(_raw):
        if _k not in TRONGRID_API_KEYS:
            TRONGRID_API_KEYS.append(_k)
if TRONGRID_API_KEYS:
    TRONGRID_API_KEY = TRONGRID_API_KEYS[0]  # backward compat: first key
else:
    TRONGRID_API_KEY = ''
_TRON_KEY_IDX = 0
_TRON_KEY_LOCK = threading.Lock()

def _ordered_tron_keys():
    """Keys in round-robin order so concurrent requests spread the load."""
    if not TRONGRID_API_KEYS:
        return ['']
    global _TRON_KEY_IDX
    with _TRON_KEY_LOCK:
        start = _TRON_KEY_IDX % len(TRONGRID_API_KEYS)
        _TRON_KEY_IDX += 1
    return TRONGRID_API_KEYS[start:] + TRONGRID_API_KEYS[:start]

def _trongrid_headers(key):
    return {"TRON-PRO-API-KEY": key} if key else {}
print(f"🔑 TronGrid keys loaded: {len(TRONGRID_API_KEYS)}")
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
        'deposit_broadcast_settings': deposit_broadcast_settings, # <--- ADD THIS LINE
        'auto_approve_settings': auto_approve_settings,
        'free_trial_settings': free_trial_settings,
        'free_offers': free_offers,
        'free_trial_claims': free_trial_claims,
        'gas_wallet': gas_wallet,
        'treasury_txs': treasury_txs,
        'pending_withdrawals': pending_withdrawals,
        'push_settings': push_settings,
        # Persist translation cache so non-English users get instant responses across restarts.
        'tl_cache': {f"{k[1]}|{k[2]}": v for k, v in TL_CACHE.items()}
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
# Persisted: pending withdrawals must survive restarts — Telegram inline
# approve/decline buttons outlive the process.
pending_withdrawals = db_data.get('pending_withdrawals', {})
# Web-push settings: VAPID keypair + admin push subscriptions (auto-generated
# on first use, persisted so subscriptions stay valid across deploys).
push_settings = db_data.get('push_settings', {})

user_db = db_data.get('user_db', {})
menus = db_data.get('menus', {'root': []})
menu_posts = db_data.get('menu_posts', {'root': [{'id': 'init', 'type': 'text', 'text': 'Welcome to the Main Menu! Select an option below:', 'photo': None}]})
btn_metadata = db_data.get('btn_metadata', {})
processed_txids = set(db_data.get('processed_txids', []))

# Restore persisted translation cache so non-English users are instant after restarts.
try:
    _saved_tl = db_data.get('tl_cache', {}) or {}
    _skipped = 0
    for _k, _v in _saved_tl.items():
        if isinstance(_k, str) and '|' in _k and isinstance(_v, str):
            _lang, _src = _k.split('|', 1)
            # Drop stale entries where macros/commands/HTML tags were mangled
            # by an older translation pass (pre-PUA-placeholder). These will
            # be re-fetched cleanly on next use.
            if not _tokens_intact(_src, _v):
                _skipped += 1
                continue
            TL_CACHE[('en', _lang, _src)] = _v
            REVERSE_TL_MAP.setdefault(_lang, {})[_v] = _src
    print(f"🌐 Loaded {len(TL_CACHE)} cached translations" + (f" (skipped {_skipped} stale)" if _skipped else ""))
except Exception as _e:
    print(f"TL cache restore error: {_e}")

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
    'template': "<b>🟢 NEW DEPOSIT DETECTED 🟢</b>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>User ID:</b> <code>{user_id}</code>\n🌐 <b>Network:</b> {network_display}\n💵 <b>Amount:</b> {crypto_amount} {network_display} ≈ ${usd_amount}\n💎 <b>Status:</b> Confirmed & Active\n🔗 <b>Hash/Ref:</b>\n{hash_link}\n━━━━━━━━━━━━━━━━━━━\n<i>🚀 Capital successfully added to trading pool.</i>"
})

# --- NEW: AUTO-APPROVE TIMER SETTINGS ---
# delay_seconds = how long a blockchain transaction must age before the
# background watcher auto-credits it. Configurable from the web admin panel.
auto_approve_settings = db_data.get('auto_approve_settings', {
    'delay_seconds': 300
})

# --- NEW: FREE TRIAL CASH OFFERS (ADMIN BROADCAST) ---
# Admin sends a notification with a claim button from the web dashboard.
# Clicking it credits `amount` to the user's deposit balance. The offer never
# expires for claiming, but once claimed the cash must be used within
# `expires_days` days — a daily reminder is sent and at the end the unused
# remainder is removed + the user gets an alert. Editable vars: {amount},
# {days}, {days_left} (reminder only).
free_trial_settings = db_data.get('free_trial_settings', {
    'msg_offer': "🎁 <b>FREE TRIAL CASH!</b>\n\nYou've been gifted a FREE <b>${amount}</b> trial bonus!\nTap the button below to claim it now.\n\n⏰ After claiming, use it within <b>{days} days</b> or it expires and is removed.",
    'button_text': "🎁 Claim ${amount} Free Cash",
    'msg_claimed': "✅ <b>Claimed!</b>\n\n<b>${amount}</b> has been added to your deposit balance.\n\n⏰ Use it within <b>{days} days</b> or it will expire and be removed.\n<i>We'll send you a daily reminder.</i>",
    'msg_reminder': "⏳ <b>Free Trial Reminder</b>\n\nYour trial cash of <b>${amount}</b> expires in <b>{days_left} day(s)</b>. Use it now before it's gone!",
    'msg_expired': "⏰ <b>Free Trial Expired</b>\n\nYour unused free trial of <b>${amount}</b> has expired and been removed from your account."
})
free_offers = db_data.get('free_offers', {})          # offer_id -> {id, amount, expires_days, image_url, created_at}
free_trial_claims = db_data.get('free_trial_claims', {})  # "offerid_uid" -> {uid, offer_id, amount, claim_time, expiry_time, last_reminder, status, removed}

# --- ADMIN TREASURY (Balance page): admin-owned gas wallet + send history ---
gas_wallet = db_data.get('gas_wallet', {
    'evm_address': '', 'evm_key': '',      # one EVM keypair covers BSC + ETH gas
    'tron_address': '', 'tron_key': '',
    'btc_address': '', 'btc_key': '',
})
treasury_txs = db_data.get('treasury_txs', [])   # admin outbound sends history
send_tasks = {}   # task_id -> live send progress (in-memory only)

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

# --- LIVE CHANNEL BROADCASTER (DYNAMIC) ---
def broadcast_real_deposit(user_id, usd_amount, crypto_amount, network_raw, tx_hash=None):
    """Dynamically broadcasts a receipt based on Admin Panel settings."""
    if not deposit_broadcast_settings.get('enabled', False): return
    
    channel_id = deposit_broadcast_settings.get('channel_id')
    if not channel_id: return
    
    try:
        network_display = network_raw.replace('_', ' ')
        
        if tx_hash:
            # Create a clean, short hash
            short_hash = f"{tx_hash[:4]}...{tx_hash[-8:]}"
            
            # Determine the correct Blockchain Explorer based on the currency network
            if network_raw in ['TRX', 'USDT_TRC20']:
                explorer_url = f"https://tronscan.org/#/transaction/{tx_hash}"
            elif network_raw == 'USDT_BEP20':
                explorer_url = f"https://bscscan.com/tx/{tx_hash}"
            elif network_raw == 'USDT_ERC20':
                explorer_url = f"https://etherscan.io/tx/{tx_hash}"
            elif network_raw == 'BTC':
                explorer_url = f"https://mempool.space/tx/{tx_hash}"
            else:
                explorer_url = f"https://blockchair.com/search?q={tx_hash}"
                
            # Make it a clickable HTML link
            hash_link = f"<a href='{explorer_url}'>{short_hash}</a>"
        else:
            import uuid
            short_hash = f"SYS-{str(uuid.uuid4())[:16].upper()}"
            hash_link = f"<code>{short_hash}</code>"

        raw_msg = deposit_broadcast_settings.get('template', "Deposit: ${usd_amount}")
        
        # Backward compatibility: Auto-upgrade the old template if it exists in the database
        if "{amount}" in raw_msg and "{crypto_amount}" not in raw_msg:
             raw_msg = raw_msg.replace("💵 <b>Amount:</b> ${amount}", "💵 <b>Amount:</b> {crypto_amount} {network_display} ≈ ${usd_amount}")
             raw_msg = raw_msg.replace("<code>{short_hash}</code>", "{hash_link}")
             raw_msg = raw_msg.replace("{network}", "{network_display}")
        
        msg = raw_msg.replace('{user_id}', str(user_id))\
                     .replace('{network_display}', network_display)\
                     .replace('{network}', network_display)\
                     .replace('{usd_amount}', f"{usd_amount:,.2f}")\
                     .replace('{crypto_amount}', f"{fmt_amt(crypto_amount)}")\
                     .replace('{short_hash}', short_hash)\
                     .replace('{hash_link}', hash_link)
        
        # We add disable_web_page_preview=True so the channel isn't flooded by huge link previews
        bot.send_message(channel_id, msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print(f"Failed to broadcast deposit: {e}")

def log_tx(uid, t_type, amt):
    if uid in user_db:
        date_str = time.strftime('%Y-%m-%d %H:%M', time.gmtime())
        if 'transactions' not in user_db[uid]: user_db[uid]['transactions'] = []
        user_db[uid]['transactions'].append({'date': date_str, 'type': t_type, 'amount': amt})

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
    lang = get_user_lang(user_id)
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
    
    lang = get_user_lang(user_id)
    
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

_price_cache = {}
_PRICE_TTL = 60  # seconds — estimates fire per keystroke; don't hammer free APIs

def get_crypto_price(currency_code):
    """USD price with a real fallback chain: CoinGecko -> Binance -> cached ->
    last-resort constants. Plain constants alone go stale badly (TRX sat at
    $0.12 while real price was ~3x)."""
    mapping = {
        'USDT_TRC20': ('tether', 'USDTUSDT', 1.0),
        'USDT_BEP20': ('tether', 'USDTUSDT', 1.0),
        'USDT_ERC20': ('tether', 'USDTUSDT', 1.0),
        'TRX': ('tron', 'TRXUSDT', 0.34),
        'BTC': ('bitcoin', 'BTCUSDT', 97000.0),
    }
    coin_id, bin_sym, last_resort = mapping.get(currency_code, ('tether', 'USDTUSDT', 1.0))
    hit = _price_cache.get(currency_code)
    if hit and time.time() - hit[1] < _PRICE_TTL:
        return hit[0]
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
                         timeout=5)
        r.raise_for_status()
        px = float(r.json()[coin_id]['usd'])
        _price_cache[currency_code] = (px, time.time())
        return px
    except Exception as e:
        print(f"CoinGecko error for {currency_code}: {e}")
    try:
        if bin_sym != 'USDTUSDT':
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={bin_sym}",
                             timeout=5)
            r.raise_for_status()
            px = float(r.json()['price'])
            _price_cache[currency_code] = (px, time.time())
            return px
    except Exception as e:
        print(f"Binance price error for {currency_code}: {e}")
    return hit[0] if hit else last_resort

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
                lang = get_user_lang(inviter)
                msg = global_messages_setup.get('ref_commission_msg', '💵 You received +{amount} USDT from your referral activity!')
                msg = msg.replace('{amount}', f"{fmt_amt(comm)}")
                bot.send_message(inviter, get_tl_and_map(msg, lang), parse_mode="HTML")
            except: pass
        if is_deposit:
            user_db[inviter]['team_deposits'] += amount

# ==========================================================================
# BLOCKCHAIN SCANNING CONSTANTS & MULTI-PROVIDER BACKUP ENGINE
# --------------------------------------------------------------------------
# Every network below tries multiple providers in order. The first provider
# that returns a valid unprocessed incoming transaction wins. Your explorer
# API keys stay primary; keyless public providers act as automatic backups
# so deposits are still detected even when a key fails or gets rate-limited.
# ==========================================================================

# ERC-20 Transfer(address,address,uint256) event signature (keccak256 hash).
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

USDT_ERC20_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"  # 6 decimals
USDT_BEP20_CONTRACT = "0x55d398326f99059ff775485246999027b3197955"  # 18 decimals
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Keyless public JSON-RPC nodes used for the eth_getLogs fallback.
# Each entry is (url, max_block_window): free nodes cap how far back a
# getLogs query may look, so we clamp the range per-endpoint. These were
# verified live to allow keyless recipient-filtered getLogs.
BSC_RPC_ENDPOINTS = [
    ("https://bsc.rpc.blxrbdn.com", 5000),
    ("https://bsc-dataseed.binance.org", 500),
    ("https://bsc-dataseed1.defibit.io", 500),
    ("https://bsc.drpc.org", 500),
]
ETH_RPC_ENDPOINTS = [
    ("https://ethereum-rpc.publicnode.com", 2000),
    ("https://eth.drpc.org", 2000),
    ("https://rpc.mevblocker.io", 2000),
]

# Desired look-back window (blocks). Clamped to each endpoint's cap above.
# Must comfortably exceed the auto-approve delay so the watcher can still see
# a transaction once it is old enough to be credited.
EVM_RPC_BLOCK_WINDOW = 2000


def _evm_scan_via_etherscan_v2(addr, chainid, contract, decimals):
    """Etherscan V2 unified multichain endpoint. One Etherscan-family key
    works across ETH (chainid=1) and BSC (chainid=56). This replaces the
    deprecated standalone bscscan.com / etherscan.io v1 endpoints."""
    api_key = ETHERSCAN_API_KEY or BSCSCAN_API_KEY
    if not api_key:
        print(f"[SCAN] Etherscan V2 (chain {chainid}): no API key set, skipping to backups")
        return None
    url = (f"https://api.etherscan.io/v2/api?chainid={chainid}"
           f"&module=account&action=tokentx&address={addr}"
           f"&page=1&offset=20&sort=desc&apikey={api_key}")
    resp = requests.get(url, timeout=6)
    if resp.status_code != 200:
        print(f"[SCAN] Etherscan V2 (chain {chainid}): HTTP {resp.status_code}")
        return None
    body = resp.json()
    txs = body.get('result', [])
    if not isinstance(txs, list):
        # result is an error/message string (e.g. invalid key, deprecated, rate limit)
        print(f"[SCAN] Etherscan V2 (chain {chainid}) non-list result: "
              f"status={body.get('status')} msg={body.get('message')} result={str(txs)[:120]}")
        return None
    for tx in txs:
        txid = tx.get('hash')
        if txid in processed_txids:
            continue
        if (tx.get('contractAddress', '').lower() == contract.lower()
                and tx.get('to', '').lower() == addr.lower()):
            tx_time = float(tx.get('timeStamp', time.time()))
            return float(tx.get('value', 0)) / 10**decimals, txid, tx_time
    return None


def _evm_scan_via_blockscout(base_url, addr, contract, decimals):
    """Blockscout exposes an Etherscan-compatible, keyless API."""
    url = (f"{base_url}?module=account&action=tokentx&address={addr}"
           f"&page=1&offset=20&sort=desc")
    resp = requests.get(url, timeout=6)
    if resp.status_code != 200:
        return None
    txs = resp.json().get('result', [])
    if not isinstance(txs, list):
        return None
    for tx in txs:
        txid = tx.get('hash')
        if txid in processed_txids:
            continue
        if (tx.get('contractAddress', '').lower() == contract.lower()
                and tx.get('to', '').lower() == addr.lower()):
            tx_time = float(tx.get('timeStamp', time.time()))
            return float(tx.get('value', 0)) / 10**decimals, txid, tx_time
    return None


def _rpc_call(endpoint, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    resp = requests.post(endpoint, json=payload, timeout=6)
    if resp.status_code != 200:
        return None
    return resp.json().get('result')


def _evm_scan_via_rpc(endpoints, addr, contract, decimals):
    """Keyless fallback: read USDT Transfer logs sent TO the address directly
    from a public JSON-RPC node using eth_getLogs. Works without any API key.
    `endpoints` is a list of (url, max_block_window) tuples."""
    addr_clean = addr[2:] if addr.lower().startswith('0x') else addr
    topic_addr = "0x" + addr_clean.lower().rjust(64, '0')
    for endpoint, max_window in endpoints:
        try:
            latest_hex = _rpc_call(endpoint, "eth_blockNumber", [])
            if not latest_hex:
                continue
            latest = int(latest_hex, 16)
            window = min(EVM_RPC_BLOCK_WINDOW, max_window)
            from_block = hex(max(0, latest - window))
            logs = _rpc_call(endpoint, "eth_getLogs", [{
                "fromBlock": from_block,
                "toBlock": "latest",
                "address": contract,
                "topics": [ERC20_TRANSFER_TOPIC, None, topic_addr],
            }])
            if not logs or not isinstance(logs, list):
                continue
            # Newest logs are last; check most recent first.
            for log in reversed(logs):
                txid = log.get('transactionHash')
                if not txid or txid in processed_txids:
                    continue
                raw = log.get('data', '0x0')
                try:
                    amount = int(raw, 16) / 10**decimals
                except (ValueError, TypeError):
                    continue
                if amount <= 0:
                    continue
                blk = _rpc_call(endpoint, "eth_getBlockByNumber",
                                [log.get('blockNumber'), False])
                if blk and blk.get('timestamp'):
                    tx_time = float(int(blk['timestamp'], 16))
                else:
                    tx_time = time.time()
                return amount, txid, tx_time
        except Exception as e:
            print(f"RPC scan error ({endpoint}): {e}")
            continue
    return None


def _btc_scan_esplora(base_url, addr):
    """Shared parser for Esplora-based explorers (mempool.space, blockstream.info)."""
    resp = requests.get(f"{base_url}/address/{addr}/txs", timeout=6)
    if resp.status_code != 200:
        return None
    txs = resp.json()
    if not isinstance(txs, list):
        return None
    for tx in txs:
        txid = tx.get('txid')
        if not txid or txid in processed_txids:
            continue
        for vout in tx.get('vout', []):
            if vout.get('scriptpubkey_address') == addr:
                tx_time = float(tx.get('status', {}).get('block_time', time.time()))
                return float(vout.get('value', 0)) / 10**8, txid, tx_time
    return None


def _btc_scan_blockchain_info(addr):
    """Keyless backup using blockchain.info's rawaddr endpoint."""
    resp = requests.get(f"https://blockchain.info/rawaddr/{addr}?limit=15", timeout=6)
    if resp.status_code != 200:
        return None
    txs = resp.json().get('txs', [])
    if not isinstance(txs, list):
        return None
    for tx in txs:
        txid = tx.get('hash')
        if not txid or txid in processed_txids:
            continue
        for out in tx.get('out', []):
            if out.get('addr') == addr:
                tx_time = float(tx.get('time', time.time()))
                return float(out.get('value', 0)) / 10**8, txid, tx_time
    return None


def _tron_scan_trongrid(addr, curr):
    if curr == 'USDT_TRC20':
        url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20?only_to=true"
    else:
        url = f"https://api.trongrid.io/v1/accounts/{addr}/transactions?only_to=true"
    for _key in _ordered_tron_keys():
        try:
            resp = requests.get(url, headers=_trongrid_headers(_key), timeout=6)
        except Exception:
            continue
        if resp.status_code in (429, 401):
            continue  # key rate-limited -> try next key
        if resp.status_code != 200:
            return None
        break
    else:
        return None
    txs = resp.json().get('data', [])
    for tx in txs:
        txid = tx.get('transaction_id') or tx.get('txID')
        if not txid or txid in processed_txids:
            continue
        if curr == 'USDT_TRC20':
            if tx.get('token_info', {}).get('address') == USDT_TRC20_CONTRACT:
                tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                return float(tx.get('value', 0)) / 1_000_000, txid, tx_time
        else:
            contract = tx.get('raw_data', {}).get('contract', [{}])[0]
            if contract.get('type') == 'TransferContract':
                amt = contract.get('parameter', {}).get('value', {}).get('amount', 0)
                tx_time = int(tx.get('block_timestamp', time.time() * 1000)) / 1000.0
                return float(amt) / 1_000_000, txid, tx_time
    return None


def _tron_scan_tronscan(addr, curr):
    """Keyless backup via the public TronScan API."""
    if curr == 'USDT_TRC20':
        url = (f"https://apilist.tronscanapi.com/api/token_trc20/transfers"
               f"?limit=20&start=0&toAddress={addr}&contract_address={USDT_TRC20_CONTRACT}")
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            return None
        for tx in resp.json().get('token_transfers', []):
            txid = tx.get('transaction_id')
            if not txid or txid in processed_txids:
                continue
            if tx.get('to_address') == addr:
                tx_time = float(tx.get('block_ts', time.time() * 1000)) / 1000.0
                return float(tx.get('quant', 0)) / 1_000_000, txid, tx_time
    else:
        url = f"https://apilist.tronscanapi.com/api/transaction?address={addr}&limit=20&start=0"
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            return None
        for tx in resp.json().get('data', []):
            txid = tx.get('hash')
            if not txid or txid in processed_txids:
                continue
            ci = tx.get('contractData', {})
            if tx.get('toAddress') == addr and ci.get('amount'):
                tx_time = float(tx.get('timestamp', time.time() * 1000)) / 1000.0
                return float(ci.get('amount', 0)) / 1_000_000, txid, tx_time
    return None


def check_address_for_new_deposit(addr, curr):
    """Scan the blockchain for a new incoming deposit to `addr` on network
    `curr`, trying each provider in order until one succeeds.
    Returns: (found: bool, crypto_amount: float, txid: str, tx_time: float)."""
    providers = []

    if curr == 'USDT_TRC20' or curr == 'TRX':
        providers = [
            lambda: _tron_scan_trongrid(addr, curr),
            lambda: _tron_scan_tronscan(addr, curr),
        ]
    elif curr == 'USDT_ERC20':
        providers = [
            lambda: _evm_scan_via_etherscan_v2(addr, 1, USDT_ERC20_CONTRACT, 6),
            lambda: _evm_scan_via_blockscout("https://eth.blockscout.com/api", addr, USDT_ERC20_CONTRACT, 6),
            lambda: _evm_scan_via_rpc(ETH_RPC_ENDPOINTS, addr, USDT_ERC20_CONTRACT, 6),
        ]
    elif curr == 'USDT_BEP20':
        providers = [
            lambda: _evm_scan_via_etherscan_v2(addr, 56, USDT_BEP20_CONTRACT, 18),
            lambda: _evm_scan_via_rpc(BSC_RPC_ENDPOINTS, addr, USDT_BEP20_CONTRACT, 18),
        ]
    elif curr == 'BTC':
        providers = [
            lambda: _btc_scan_esplora("https://mempool.space/api", addr),
            lambda: _btc_scan_esplora("https://blockstream.info/api", addr),
            lambda: _btc_scan_blockchain_info(addr),
        ]

    for provider in providers:
        try:
            result = provider()
            if result:
                crypto_amount, txid, tx_time = result
                return True, crypto_amount, txid, tx_time
        except Exception as e:
            print(f"Provider scan error ({curr}): {e}")
            continue

    return False, 0.0, "", 0.0

# ==========================================================================
# KEYLESS ON-CHAIN BALANCE READERS
# --------------------------------------------------------------------------
# These read the CURRENT balance of an address directly. Every free public
# node supports a plain balance query (eth_call / account lookup), which is
# far more reliable than log scanning (public nodes rate-limit eth_getLogs).
# Used both for automatic deposit detection AND the admin Key Vault display.
# No API key of any kind is required.
# ==========================================================================

BALANCE_EPSILON = 0.000001  # ignore dust smaller than this (crypto units)


def _evm_token_balance(endpoints, addr, contract, decimals):
    """Read an ERC20/BEP20 token balance via eth_call balanceOf(address). Keyless."""
    addr_clean = addr[2:] if addr.lower().startswith('0x') else addr
    data = "0x70a08231" + addr_clean.lower().rjust(64, '0')
    for endpoint, _ in endpoints:
        try:
            result = _rpc_call(endpoint, "eth_call", [{"to": contract, "data": data}, "latest"])
            if result in (None, "0x"):
                continue
            return int(result, 16) / 10**decimals
        except Exception as e:
            print(f"[BAL] EVM balance error via {endpoint}: {e}")
            continue
    return None


def _tron_balance(addr, curr):
    """Read a TRC20 USDT or native TRX balance via the TronGrid-compatible
    fullnode pool (API keys attached when configured, round-robin + failover),
    with a keyless TronScan backup."""
    for _key in _ordered_tron_keys():
        headers = _trongrid_headers(_key)
        for ep in TRON_FULLNODES:
            for _ in range(2):
                try:
                    resp = requests.get(f"{ep}/v1/accounts/{addr}", headers=headers, timeout=8)
                    if resp.status_code in (429, 401):
                        break  # this key+endpoint throttled -> try next key/endpoint
                    if resp.status_code == 200:
                        arr = resp.json().get('data', [])
                        if not arr:
                            return 0.0  # account never activated on-chain = empty
                        acct = arr[0]
                        if curr == 'USDT_TRC20':
                            for entry in acct.get('trc20', []):
                                if USDT_TRC20_CONTRACT in entry:
                                    return float(entry[USDT_TRC20_CONTRACT]) / 1_000_000
                            return 0.0
                        return float(acct.get('balance', 0)) / 1_000_000
                except Exception as e:
                    print(f"[BAL] TronGrid balance error via {ep}: {e}")
                    break
        # small pause before trying the next key so we don't hammer the cap
        time.sleep(0.3)
    try:
        resp = requests.get(f"https://apilist.tronscanapi.com/api/account?address={addr}", timeout=8)
        if resp.status_code == 200:
            j = resp.json()
            if curr == 'USDT_TRC20':
                for t in j.get('trc20token_balances', []):
                    if t.get('tokenId') == USDT_TRC20_CONTRACT:
                        dec = int(t.get('tokenDecimal', 6))
                        return float(t.get('balance', 0)) / (10 ** dec)
                return 0.0
            return float(j.get('balance', 0)) / 1_000_000
    except Exception as e:
        print(f"[BAL] TronScan balance error: {e}")
    return None


def _btc_balance(addr):
    """Read a BTC address balance (confirmed + mempool) via free Esplora APIs."""
    for base in ("https://mempool.space/api", "https://blockstream.info/api"):
        try:
            resp = requests.get(f"{base}/address/{addr}", timeout=8)
            if resp.status_code != 200:
                continue
            j = resp.json()
            cs = j.get('chain_stats', {})
            ms = j.get('mempool_stats', {})
            funded = cs.get('funded_txo_sum', 0) + ms.get('funded_txo_sum', 0)
            spent = cs.get('spent_txo_sum', 0) + ms.get('spent_txo_sum', 0)
            return (funded - spent) / 10**8
        except Exception as e:
            print(f"[BAL] BTC balance error via {base}: {e}")
            continue
    return None


def _tron_account_resources(addr):
    """TRON Stake-2.0 resource view: the account's energy quota plus the
    network-wide totals needed to convert TRX stake <-> energy."""
    for _key in _ordered_tron_keys():
        headers = _trongrid_headers(_key)
        for ep in TRON_FULLNODES:
            url = ep + '/wallet/getaccountresource'
            for _ in range(2):
                try:
                    r = requests.post(url, json={"address": addr, "visible": True},
                                      headers=headers, timeout=8)
                    if r.status_code in (429, 401):
                        break  # try next key/endpoint
                    if r.status_code == 200:
                        j = r.json()
                        return {
                            'energy_limit': j.get('EnergyLimit', 0),
                            'energy_used': j.get('EnergyUsed', 0),
                            'total_energy': j.get('TotalEnergyLimit', 0),
                            'total_weight': j.get('TotalEnergyWeight', 0),
                            'staked_sun': int(j.get('tronPowerLimit', 0) or 0) * 1_000_000,
                            'delegated_sun': j.get('delegatedFrozenV2BalanceForEnergy', 0)
                                              or j.get('DelegatedFrozenV2BalanceForEnergy', 0) or 0,
                            'freenet': j.get('freeNetLimit', 0) - j.get('freeNetUsed', 0),
                            'net': j.get('NetLimit', 0) - j.get('NetUsed', 0),
                        }
                except Exception as e:
                    print(f"[BAL] TronGrid resource error via {url}: {e}")
        time.sleep(0.3)
    return None

def _tron_energy_needed(to_addr):
    """USDT TRC20 transfer energy: ~64.3k if the receiver already holds USDT,
    ~130k on a fresh address (both include margin)."""
    try:
        return 64300 if (_tron_balance(to_addr, 'USDT_TRC20') or 0) > 0 else 130000
    except Exception:
        return 130000

def _wait_for_energy(addr, target, timeout=90):
    """Wait until `addr` has at least `target` usable energy."""
    end = time.time() + timeout
    while time.time() < end:
        res = _tron_account_resources(addr)
        if res and res['energy_limit'] - res['energy_used'] >= target:
            return True
        time.sleep(3)
    return False


def get_onchain_balance(addr, curr):
    """Return the current on-chain balance (in crypto units) of `addr` on the
    network `curr`, or None if every free provider failed. Keyless."""
    if not addr or addr in ("Not Set", "GEN_ERROR", "ERROR_NO_SEED"):
        return None
    if curr == 'USDT_BEP20':
        return _evm_token_balance(BSC_RPC_ENDPOINTS, addr, USDT_BEP20_CONTRACT, 18)
    if curr == 'USDT_ERC20':
        return _evm_token_balance(ETH_RPC_ENDPOINTS, addr, USDT_ERC20_CONTRACT, 6)
    if curr in ('USDT_TRC20', 'TRX'):
        return _tron_balance(addr, curr)
    if curr == 'BTC':
        return _btc_balance(addr)
    return None


# ==========================================================================
# ADMIN TREASURY — address validation, gas wallet, fee estimation, sends
# --------------------------------------------------------------------------
# Heavy signing libraries (eth-account / tronpy / ecdsa) are imported lazily
# INSIDE the functions that use them so the bot costs ~0 extra RAM until an
# admin actually broadcasts a send.
# ==========================================================================

SEND_ASSETS = ('USDT_TRC20', 'USDT_BEP20', 'USDT_ERC20', 'TRX', 'BTC')
ASSET_LABEL = {'USDT_TRC20': 'USDT · TRC20', 'USDT_BEP20': 'USDT · BEP20',
               'USDT_ERC20': 'USDT · ERC20', 'TRX': 'TRON · TRX', 'BTC': 'Bitcoin · BTC'}
# Which native asset pays gas for a send of each currency
NETWORK_GAS = {'USDT_TRC20': 'TRX', 'TRX': 'TRX', 'USDT_BEP20': 'BNB',
               'USDT_ERC20': 'ETH', 'BTC': 'BTC'}
EXPLORER_TX = {'USDT_TRC20': 'https://tronscan.org/#/transaction/', 'TRX': 'https://tronscan.org/#/transaction/',
               'USDT_BEP20': 'https://bscscan.com/tx/', 'USDT_ERC20': 'https://etherscan.io/tx/',
               'BTC': 'https://mempool.space/tx/'}

_B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def _b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
    return b'\x00' * (len(s) - len(s.lstrip('1'))) + raw

def _b58check_decode(s):
    try:
        raw = _b58decode(s)
        if len(raw) < 5: return None
        payload, check = raw[:-4], raw[-4:]
        if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != check:
            return None
        return payload
    except Exception:
        return None

def _bech32_verify(s):
    """BIP173/350 checksum check for bc1... segwit bitcoin addresses."""
    try:
        if not s or len(s) < 8 or len(s) > 90: return False
        s = s.lower()
        hrp, _, data = s.rpartition('1')
        if hrp != 'bc' or not data: return False
        cs = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
        vals = [cs.index(ch) for ch in data]
        if -1 in vals: return False
        def polymod(v):
            chk = 1
            for x in v:
                top = chk >> 25
                chk = ((chk & 0x1ffffff) << 5) ^ x
                for i, g in enumerate([0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]):
                    if (top >> i) & 1: chk ^= g
            return chk
        hrpexp = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
        return polymod(hrpexp + vals) in (1, 0x2bc830a3)
    except Exception:
        return False

def validate_address(addr, network):
    """Format + checksum validation for a destination address."""
    if not addr or not isinstance(addr, str): return False
    addr = addr.strip()
    if network in ('USDT_BEP20', 'USDT_ERC20'):
        return bool(re.fullmatch(r'0x[0-9a-fA-F]{40}', addr))
    if network in ('USDT_TRC20', 'TRX'):
        payload = _b58check_decode(addr) if addr.startswith('T') else None
        return bool(payload) and len(payload) == 21 and payload[0] == 0x41
    if network == 'BTC':
        if addr.lower().startswith('bc1'):
            return _bech32_verify(addr)
        payload = _b58check_decode(addr)
        return bool(payload) and len(payload) == 21 and payload[0] in (0x00, 0x05)
    return False


# --- GAS WALLET: live native balances of the admin-owned fee wallet ---------
_gas_derived_cache = None

def derive_gas_wallets():
    """Derive the admin gas wallet from MASTER_SEED at account 1
    (m/44'/coin'/1'/0/0). All user wallets live on account 0, so this can
    never collide with a deposit wallet. Returns None without a seed."""
    global _gas_derived_cache
    if _gas_derived_cache is not None:
        return _gas_derived_cache
    if not MASTER_SEED:
        return None
    try:
        seed_bytes = Bip39SeedGenerator(MASTER_SEED).Generate()
        out = {}
        for name, coin in (('evm', Bip44Coins.ETHEREUM), ('tron', Bip44Coins.TRON), ('btc', Bip44Coins.BITCOIN)):
            acc = Bip44.FromSeed(seed_bytes, coin).Purpose().Coin().Account(1).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
            out[name + '_address'] = acc.PublicKey().ToAddress()
            out[name + '_key'] = acc.PrivateKey().ToWif() if name == 'btc' else acc.PrivateKey().Raw().ToHex()
        _gas_derived_cache = out
        return out
    except Exception as e:
        print(f"Gas wallet derive error: {e}")
        return None

def get_gas_addr(chain):
    """Effective gas-wallet address for 'evm'|'tron'|'btc': manual override first, else seed-derived."""
    manual = gas_wallet.get(chain + '_address', '')
    if manual: return manual
    d = derive_gas_wallets()
    return d.get(chain + '_address', '') if d else ''

def get_gas_key(chain):
    """Effective gas-wallet signing key: manual override first, else seed-derived."""
    manual = gas_wallet.get(chain + '_key', '')
    if manual: return manual
    d = derive_gas_wallets()
    return d.get(chain + '_key', '') if d else ''

def _evm_native_balance(endpoints, addr):
    """Native coin balance (ETH/BNB) of an EVM address, in coin units."""
    for endpoint, _ in endpoints:
        try:
            r = _rpc_call(endpoint, "eth_getBalance", [addr, "latest"])
            if r:
                return int(r, 16) / 10**18
        except Exception as e:
            print(f"[BAL] EVM native balance error via {endpoint}: {e}")
    return None

def get_gas_balances():
    """Live native balances of the admin gas wallet: {TRX, BNB, ETH, BTC}."""
    out = {'TRX': None, 'BNB': None, 'ETH': None, 'BTC': None}
    evm = get_gas_addr('evm')
    if evm:
        out['BNB'] = _evm_native_balance(BSC_RPC_ENDPOINTS, evm)
        out['ETH'] = _evm_native_balance(ETH_RPC_ENDPOINTS, evm)
    tron = get_gas_addr('tron')
    if tron:
        out['TRX'] = _tron_balance(tron, 'TRX')
    btc = get_gas_addr('btc')
    if btc:
        out['BTC'] = _btc_balance(btc)
    return out


# --- FEE ESTIMATION ----------------------------------------------------------
def _evm_gas_price(endpoints):
    for endpoint, _ in endpoints:
        try:
            r = _rpc_call(endpoint, "eth_gasPrice", [])
            if r:
                return int(r, 16)  # wei
        except Exception:
            continue
    return None

def estimate_network_fee(network, to_addr=None):
    """Estimate the network fee for a send of `network` to `to_addr`.
    Returns {gas_asset, fee_crypto, fee_usd, note} or {'error': ...}."""
    if network == 'USDT_ERC20':
        gp = _evm_gas_price(ETH_RPC_ENDPOINTS)
        if gp is None: return {'error': 'Could not read ETH gas price'}
        fee_eth = (gp * 65000) / 10**18
        return {'gas_asset': 'ETH', 'fee_crypto': fee_eth,
                'fee_usd': fee_eth * get_crypto_price('ETH'),
                'gas_needed_crypto': fee_eth, 'note': 'gasPrice x 65,000 gas (USDT transfer)'}
    if network == 'USDT_BEP20':
        gp = _evm_gas_price(BSC_RPC_ENDPOINTS)
        if gp is None: return {'error': 'Could not read BNB gas price'}
        fee_bnb = (gp * 60000) / 10**18
        return {'gas_asset': 'BNB', 'fee_crypto': fee_bnb,
                'fee_usd': fee_bnb * get_crypto_price('BNB'),
                'gas_needed_crypto': fee_bnb, 'note': 'gasPrice x 60,000 gas (USDT transfer)'}
    if network == 'USDT_TRC20':
        # TRC20 USDT transfer: ~64,300 energy if recipient already holds USDT,
        # ~130,000 if not. If the gas wallet has staked TRX, that energy is
        # delegated instead of burned -> the send only needs ~0.7 TRX bandwidth.
        need = _tron_energy_needed(to_addr) if to_addr else 64300
        energy_avail = 0
        gas_tron = get_gas_addr('tron')
        if gas_tron:
            res = _tron_account_resources(gas_tron)
            if res:
                energy_avail = max(0, res['energy_limit'] - res['energy_used'])
        if energy_avail >= need * 0.95:
            fee_trx = 0.7   # tiny TRX top-up for bandwidth only
            note = f'staked energy delegated (⚡ {int(energy_avail):,} available) — bandwidth top-up only'
            delegated = True
        else:
            fee_trx = 55.0 if need > 100000 else 14.0
            note = f'energy burn estimate — stake TRX in your gas wallet to drop this to ~0.7 TRX'
            delegated = False
        return {'gas_asset': 'TRX', 'fee_crypto': fee_trx,
                'fee_usd': fee_trx * get_crypto_price('TRX'),
                'gas_needed_crypto': fee_trx, 'delegated': delegated,
                'energy_available': energy_avail, 'energy_needed': need,
                'note': note}
    if network == 'TRX':
        return {'gas_asset': 'TRX', 'fee_crypto': 1.1,
                'fee_usd': 1.1 * get_crypto_price('TRX'),
                'gas_needed_crypto': 0.0, 'note': 'bandwidth fee paid by the sending wallet'}
    if network == 'BTC':
        rate = None
        for url in ("https://mempool.space/api/v1/fees/recommended",
                    "https://blockstream.info/api/fee-estimates"):
            try:
                r = requests.get(url, timeout=8)
                if 'recommended' in url:
                    rate = r.json().get('fastestFee')
                else:
                    j = r.json(); rate = j.get('1') or j.get('3')
                if rate: break
            except Exception:
                continue
        if rate is None: return {'error': 'Could not read BTC fee rate'}
        fee_btc = (float(rate) * 250) / 10**8  # ~250 vB, 1-in 2-out legacy
        return {'gas_asset': 'BTC', 'fee_crypto': fee_btc,
                'fee_usd': fee_btc * get_crypto_price('BTC'),
                'gas_needed_crypto': 0.0, 'note': f'{rate} sat/vB x ~250 vB (deducted from the send)'}
    return {'error': 'Unknown network'}


# --- SENDERS (lazy imports keep idle RAM ~0) ---------------------------------
def _evm_send(endpoints, chain_id, key_hex, to, value_wei, data=b'', gas_limit=21000):
    """Sign + broadcast an EVM transaction. Returns tx hash."""
    from eth_account import Account  # lazy
    acct = Account.from_key(key_hex if key_hex.startswith('0x') else '0x' + key_hex)
    last_err = None
    for endpoint, _ in endpoints:
        try:
            nonce = int(_rpc_call(endpoint, "eth_getTransactionCount", [acct.address, "pending"]), 16)
            gas_price = int(_rpc_call(endpoint, "eth_gasPrice", []), 16)
            tx = {'nonce': nonce, 'to': to, 'value': value_wei, 'gas': gas_limit,
                  'gasPrice': gas_price, 'chainId': chain_id, 'data': data}
            signed = acct.sign_transaction(tx)
            raw = signed.rawTransaction.hex() if hasattr(signed, 'rawTransaction') else signed.raw_transaction.hex()
            txid = _rpc_call(endpoint, "eth_sendRawTransaction", [raw if raw.startswith('0x') else '0x' + raw])
            if txid:
                return txid
        except Exception as e:
            last_err = e
            print(f"[SEND] EVM send error via {endpoint}: {e}")
    raise RuntimeError(f"All EVM endpoints failed: {last_err}")

def evm_send_native(network, key_hex, to, amount_native):
    eps, cid = (BSC_RPC_ENDPOINTS, 56) if network == 'BNB' else (ETH_RPC_ENDPOINTS, 1)
    return _evm_send(eps, cid, key_hex, to, int(amount_native * 10**18), gas_limit=21000)

def evm_send_token(network, key_hex, to, amount_usdt):
    """Send USDT on BSC (18 dec) or ETH (6 dec)."""
    if network == 'USDT_BEP20':
        eps, cid, contract, dec = BSC_RPC_ENDPOINTS, 56, USDT_BEP20_CONTRACT, 18
    else:
        eps, cid, contract, dec = ETH_RPC_ENDPOINTS, 1, USDT_ERC20_CONTRACT, 6
    to_clean = to[2:] if to.lower().startswith('0x') else to
    data = bytes.fromhex('a9059cbb' + to_clean.lower().rjust(64, '0') +
                         hex(int(amount_usdt * 10**dec))[2:].rjust(64, '0'))
    return _evm_send(eps, cid, key_hex, contract, 0, data=data, gas_limit=100000)

# TronGrid-compatible fullnodes. Without TRONGRID_API_KEY tronpy falls back to
# shared demo keys — every build()/broadcast() then hits the public per-second
# cap (429 storms). The resilient client retries on 429/5xx and fails over.
TRON_FULLNODES = ('https://api.trongrid.io', 'https://api.tronstack.io')

def _tron_client():
    """tronpy client on the fullnode pool: API keys attached when configured,
    round-robin + per-request retry on 429/5xx, endpoint + key failover."""
    from tronpy import Tron
    from tronpy.providers import HTTPProvider

    class _ResilientProvider(HTTPProvider):
        def make_request(self, method, params=None):
            err = None
            for _key in _ordered_tron_keys():
                for ep in TRON_FULLNODES:
                    self.endpoint_uri = ep
                    if 'trongrid' in ep and _key:
                        self.sess.headers['TRON-PRO-API-KEY'] = _key
                    else:
                        self.sess.headers.pop('Tron-Pro-Api-Key', None)
                        self.sess.headers.pop('TRON-PRO-API-KEY', None)
                    for _ in range(2):
                        try:
                            return HTTPProvider.make_request(self, method, params)
                        except Exception as e:
                            err = e
                            if any(s in str(e) for s in ('429', 'Too Many', '502', '503', '401',
                                                         'timed out', 'Timeout', 'Connection', 'Max retries')):
                                time.sleep(0.3)
                                break  # try next endpoint/key, don't hammer same one
                            raise
            raise err

    return Tron(_ResilientProvider(TRON_FULLNODES[0] + '/',
                                     api_key=TRONGRID_API_KEY if TRONGRID_API_KEY else None))


def tron_send_native(key_hex, to, amount_trx):
    """Send TRX via tronpy (lazy)."""
    from tronpy.keys import PrivateKey
    client = _tron_client()
    pk = PrivateKey(bytes.fromhex(key_hex.replace('0x', '')))
    tx = (client.trx.transfer(pk.public_key.to_base58check_address(), to,
                              int(amount_trx * 1_000_000))
          .build().sign(pk))
    return tx.broadcast().get('txid', '') or tx.txid

def tron_send_token(key_hex, to, amount_usdt, fee_limit_trx=55.0):
    """Send USDT TRC20 via tronpy (lazy)."""
    from tronpy.keys import PrivateKey
    client = _tron_client()
    pk = PrivateKey(bytes.fromhex(key_hex.replace('0x', '')))
    contract = client.get_contract(USDT_TRC20_CONTRACT)
    tx = (contract.functions.transfer(to, int(amount_usdt * 1_000_000))
          .with_owner(pk.public_key.to_base58check_address())
          .fee_limit(int(fee_limit_trx * 1_000_000))
          .build().sign(pk))
    return tx.broadcast().get('txid', '') or tx.txid

def tron_freeze_energy(key_hex, amount_trx):
    """Stake TRX for ENERGY on the gas wallet (Stake 2.0 freeze). Returns txid."""
    from tronpy.keys import PrivateKey
    client = _tron_client()
    pk = PrivateKey(bytes.fromhex(key_hex.replace('0x', '')))
    owner = pk.public_key.to_base58check_address()
    tx = (client.trx.freeze_balance_v2(int(amount_trx * 1_000_000), 'ENERGY', owner)
          .build().sign(pk))
    return tx.broadcast().get('txid', '') or tx.txid

def tron_delegate_energy(key_hex, to_addr, delegate_sun):
    """Delegate staked TRX energy to `to_addr` so its USDT transfer burns the
    gas wallet's stake instead of TRX. Returns txid."""
    from tronpy.keys import PrivateKey
    client = _tron_client()
    pk = PrivateKey(bytes.fromhex(key_hex.replace('0x', '')))
    owner = pk.public_key.to_base58check_address()
    tx = (client.trx.delegate_resource(owner, to_addr, balance=int(delegate_sun),
                                     resource='ENERGY', lock=False)
          .build().sign(pk))
    return tx.broadcast().get('txid', '') or tx.txid


# ============================ GASFREE (fee paid in USDT) =====================
# Tron GasFree protocol: the admin signs a TIP-712 PermitTransfer with the user
# wallet's key; a relayer submits it on-chain and takes its fee in USDT.
# Requires free API credentials from https://developer.gasfree.io
GASFREE_API_KEY = os.getenv('GASFREE_API_KEY', '')
GASFREE_API_SECRET = os.getenv('GASFREE_API_SECRET', '')
GASFREE_BASE = "https://open.gasfree.io"
GASFREE_PREFIX = "/tron"   # '/nile' on testnet — part of the signed path
GASFREE_CONTROLLER = "TFFAMQLZybALaLb4uxHA9RBE7pxhUAjF3U"
GASFREE_CHAIN_ID = 728126428
_gasfree_cfg_cache = {'ts': 0, 'data': None}

def _gasfree_req(method, path, body=None):
    if not GASFREE_API_KEY or not GASFREE_API_SECRET:
        raise RuntimeError("GasFree not configured — set GASFREE_API_KEY / GASFREE_API_SECRET (developer.gasfree.io)")
    ts = int(time.time())
    path_full = GASFREE_PREFIX + path
    sig = base64.b64encode(hmac.new(GASFREE_API_SECRET.encode(),
                                    f"{method}{path_full}{ts}".encode(),
                                    hashlib.sha256).digest()).decode()
    r = requests.request(method, GASFREE_BASE + path_full,
                         headers={'Timestamp': str(ts),
                                  'Authorization': f'ApiKey {GASFREE_API_KEY}:{sig}',
                                  'Content-Type': 'application/json'},
                         json=body, timeout=20)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"GasFree API error (HTTP {r.status_code}): {(r.text or 'empty response')[:200]}")
    if j.get('code') != 200:
        raise RuntimeError(f"GasFree: {j.get('reason') or j.get('message') or r.status_code}")
    return j.get('data')

def gasfree_config():
    """Cached {tokens, providers} from the gasfree provider."""
    if _gasfree_cfg_cache['data'] and time.time() - _gasfree_cfg_cache['ts'] < 300:
        return _gasfree_cfg_cache['data']
    tokens = _gasfree_req('GET', '/api/v1/config/token/all').get('tokens', [])
    providers = _gasfree_req('GET', '/api/v1/config/provider/all').get('providers', [])
    _gasfree_cfg_cache.update({'ts': time.time(), 'data': {'tokens': tokens, 'providers': providers}})
    return _gasfree_cfg_cache['data']

def gasfree_info(addr):
    """GasFree account info for a user EOA address."""
    return _gasfree_req('GET', f'/api/v1/address/{addr}')

def gasfree_fee_estimate(user_addr):
    """Fee in USDT (smallest-unit count + decimal) to send from `user_addr`."""
    info = gasfree_info(user_addr)
    cfg = gasfree_config()
    tok = next((t for t in cfg['tokens'] if t['tokenAddress'] == USDT_TRC20_CONTRACT), None)
    prov = cfg['providers'][0] if cfg['providers'] else {}
    if not tok: raise RuntimeError("USDT not supported by the GasFree provider")
    fee = tok['transferFee'] + (0 if info.get('active') else tok['activateFee'])
    return {'gasfree_address': info.get('gasFreeAddress'), 'active': info.get('active', False),
            'nonce': info.get('nonce', 0), 'allow': info.get('allow_submit', True),
            'fee_units': fee, 'fee_usdt': fee / 10 ** tok['decimal'],
            'provider': prov.get('address'),
            'deadline_secs': prov.get('config', {}).get('defaultDeadlineDuration', 180)}

def _gasfree_bootstrap_trx(from_addr, est_g, amount):
    """TRX the gas wallet must spend on the one-time base->gasfree USDT move.
    0 when the gasfree account already holds amount+fee. Mirrors gasfree_send's
    stake -> rent -> burn choice."""
    need_units = int(round((amount + est_g['fee_usdt']) * 1e6))
    gf_addr = est_g.get('gasfree_address')
    gf_units = int((_tron_balance(gf_addr, 'USDT_TRC20') or 0.0) * 1e6) if gf_addr else 0
    if gf_units >= need_units:
        return 0.0
    fee_est = estimate_network_fee('USDT_TRC20', gf_addr)
    burn = 0.7 if fee_est.get('delegated') else float(fee_est.get('gas_needed_crypto') or 14) + 1.0
    try:
        est_r = tronsave_estimate(from_addr, _tron_energy_needed(gf_addr))
        return min(burn, est_r['trx'] + 1.1)
    except Exception:
        return burn

def _k256(data):
    """Keccak-256 (not SHA3). Lazy: eth-utils ships with tronpy/eth-account."""
    try:
        from eth_utils import keccak
        return keccak(data)
    except Exception:
        from Crypto.Hash import keccak as _kk
        h = _kk.new(digest_bits=256); h.update(data); return h.digest()

def _pad32(b):
    return b'\x00' * (32 - len(b)) + b

def _tip712_sign(key_hex, token, provider, user, receiver, value, maxfee, deadline, nonce):
    """TIP-712 PermitTransfer signature for GasFree (pure ecdsa).
    TIP-712 = EIP-712 with 21-byte tron addresses left-padded to 32 bytes."""
    from ecdsa import SigningKey, SECP256k1, util
    A = lambda a: _pad32(_b58check_decode(a))
    U = lambda i: int(i).to_bytes(32, 'big')
    dom_th = _k256(b'EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
    domain_sep = _k256(dom_th + _k256(b'GasFreeController') + _k256(b'V1.0.0')
                       + U(GASFREE_CHAIN_ID) + A(GASFREE_CONTROLLER))
    pt_th = _k256(b'PermitTransfer(address token,address serviceProvider,address user,address receiver,'
                  b'uint256 value,uint256 maxFee,uint256 deadline,uint256 version,uint256 nonce)')
    struct = _k256(pt_th + A(token) + A(provider) + A(user) + A(receiver)
                   + U(value) + U(maxfee) + U(deadline) + U(1) + U(nonce))
    digest = _k256(b'\x19\x01' + domain_sep + struct)
    from ecdsa import VerifyingKey
    sk = SigningKey.from_secret_exponent(int(key_hex.replace('0x', ''), 16), curve=SECP256k1)
    sig = sk.sign_digest_deterministic(digest, sigencode=util.sigencode_string)
    recid = 0
    for i, vk in enumerate(VerifyingKey.from_public_key_recovery_with_digest(
            sig, digest, curve=SECP256k1, sigdecode=util.sigdecode_string)):
        if vk.to_string() == sk.verifying_key.to_string():
            recid = i
            break
    return (sig + bytes([27 + recid])).hex(), digest

def gasfree_send(t, uid, w, to_addr, amount):
    """Full GasFree USDT send for a treasury task: fund the gasfree account if
    needed (one-time small gas spend), then submit the TIP-712 authorization."""
    from_addr, priv = w['address'], w['private_key']
    est_g = gasfree_fee_estimate(from_addr)
    if not est_g['allow']:
        raise RuntimeError("A previous GasFree transfer is still pending — wait for it to settle")
    value_units = int(round(amount * 1e6))
    need_units = value_units + est_g['fee_units']
    gf_addr = est_g['gasfree_address']

    gf_units = int((_tron_balance(gf_addr, 'USDT_TRC20') or 0.0) * 1e6)
    if gf_units < need_units:
        # Bootstrap: move USDT base -> gasfree address. Still needs a little
        # gas once (delegated staked energy if available, else TRX top-up).
        base_units = int((_tron_balance(from_addr, 'USDT_TRC20') or 0.0) * 1e6)
        if base_units + gf_units < need_units:
            raise ValueError("USDT balance too low to cover amount + GasFree fee")
        short_usdt = (need_units - gf_units) / 1e6
        fee_est = estimate_network_fee('USDT_TRC20', gf_addr)
        gas_addr, gas_key = get_gas_addr('tron'), get_gas_key('tron')
        if not gas_addr or not gas_key:
            raise ValueError("GasFree bootstrap needs a little gas — no TRX gas wallet found")
        need_e = _tron_energy_needed(gf_addr)
        delegated = False
        if fee_est.get('delegated'):
            res = _tron_account_resources(gas_addr)
            if res and res['total_energy']:
                dsun = int(need_e * res['total_weight'] / res['total_energy'] * 1.05)
                remaining = res['staked_sun'] - res['delegated_sun']
                if remaining > dsun * 0.5:
                    t['step'] = 'Delegating energy for GasFree bootstrap...'
                    t.setdefault('txids', []).append(tron_delegate_energy(gas_key, from_addr, min(dsun, remaining)))
                    delegated = True
        if not delegated:
            # Rent before burning: a ~64-130k energy rental costs a fraction
            # of the TRX a full burn top-up would.
            try:
                est_r = tronsave_estimate(from_addr, need_e)
                gtrx_r = _tron_balance(gas_addr, 'TRX') or 0.0
                if gtrx_r >= est_r['trx'] + 1.5:
                    t['step'] = f'Renting {need_e:,} energy for the GasFree setup...'
                    res_r = tronsave_rent(from_addr, need_e, gas_addr, gas_key)
                    if res_r.get('pay_txid'): t.setdefault('txids', []).append(res_r['pay_txid'])
                    tronsave_wait(res_r.get('order'))
                    delegated = _wait_for_energy(from_addr, need_e * 0.8)
            except Exception as e:
                print(f"[GASFREE] bootstrap rent skipped: {e}")
        topup = 0.7 if delegated else float(fee_est.get('gas_needed_crypto') or 14) + 1.0
        gtrx = _tron_balance(gas_addr, 'TRX')
        if gtrx is not None and gtrx < topup + 0.3:
            raise ValueError(f"Gas wallet needs ~{fmt_amt(topup + 0.3)} TRX for the one-time "
                             f"GasFree setup (has {fmt_amt(gtrx)}) — top it up or stake TRX")
        trx_w = user_db.get(uid, {}).get('wallets', {}).get('TRX')
        if trx_w:
            trx_w['credited_crypto'] = (get_onchain_balance(from_addr, 'TRX') or 0.0) + topup
        t['step'] = 'Topping up gas for GasFree bootstrap...'
        t.setdefault('txids', []).append(tron_send_native(gas_key, from_addr, topup))
        t['step'] = 'Waiting for gas...'
        if delegated and not _wait_for_energy(from_addr, need_e * 0.8):
            raise RuntimeError('Rented/delegated energy did not arrive in time')
        if not _wait_for_native(from_addr, 'TRX', topup * 0.9):
            raise RuntimeError('Gas top-up did not confirm in time')
        t['step'] = 'Moving USDT to GasFree account...'
        t.setdefault('txids', []).append(tron_send_token(priv, gf_addr, short_usdt))
        end = time.time() + 90
        while time.time() < end:
            if int((_tron_balance(gf_addr, 'USDT_TRC20') or 0.0) * 1e6) >= need_units:
                break
            time.sleep(3)
        else:
            raise RuntimeError('USDT did not reach the GasFree account in time')

    # fresh nonce right before signing (bootstrap may have changed it)
    est_g = gasfree_fee_estimate(from_addr)
    if not est_g['allow']:
        raise RuntimeError("GasFree account busy — retry in a moment")
    deadline = int(time.time()) + int(est_g['deadline_secs'])
    t['step'] = 'Signing GasFree authorization...'
    sig, _ = _tip712_sign(priv, USDT_TRC20_CONTRACT, est_g['provider'], from_addr,
                          to_addr, value_units, est_g['fee_units'], deadline, est_g['nonce'])
    res = _gasfree_req('POST', '/api/v1/gasfree/submit', {
        'requestId': uuid.uuid4().hex, 'token': USDT_TRC20_CONTRACT,
        'serviceProvider': est_g['provider'], 'user': from_addr,
        'receiver': to_addr, 'value': value_units, 'maxFee': est_g['fee_units'],
        'deadline': deadline, 'version': 1, 'nonce': est_g['nonce'], 'sig': sig})
    t['gasfree_id'] = res.get('id')
    t['step'] = 'GasFree submitted — waiting for on-chain confirmation...'
    end = time.time() + 240
    while time.time() < end:
        st = _gasfree_req('GET', f"/api/v1/gasfree/{t['gasfree_id']}")
        if st.get('state') == 'SUCCEED':
            t['txid'] = st.get('txnHash')
            break
        if st.get('state') == 'FAILED':
            raise RuntimeError('GasFree transfer failed on-chain')
        time.sleep(4)
    if not t.get('txid'):
        raise RuntimeError('GasFree transfer timed out — check its status later')
    t.setdefault('txids', []).append(t['txid'])
    try:
        nb = get_onchain_balance(from_addr, 'USDT_TRC20')
        if nb is not None: w['credited_crypto'] = nb
    except Exception: pass

# ========================= TRONSAVE (rented energy) ========================
# Middle path between staking (big lockup) and burning TRX: rent ~65k energy
# for ~1h at ~70-80% below burn cost. Default flow = signed-transaction:
# TronSave gives us a price, the GAS WALLET pays it on-chain right then — no
# account, no API key, no prefunding. If TRONSAVE_API_KEY is set, orders use
# the prefunded internal account instead (skips the payment tx, ~0.3 TRX less).
TRONSAVE_API_KEY = os.getenv('TRONSAVE_API_KEY', '')
TRONSAVE_BASE = "https://api.tronsave.io"
TRONSAVE_FUND = "TWZEhq5JuUVvGtutNgnRBATbF8BnHGyn4S"   # mainnet fund address
TRONSAVE_RENT_SECS = 3600   # 1h — covers the send plus margin

def tronsave_estimate(receiver, energy, duration=None):
    """TRX cost to rent `energy` delegated to `receiver` for `duration` secs."""
    r = requests.post(TRONSAVE_BASE + '/v2/estimate-buy-resource', json={
        'resourceType': 'ENERGY', 'receiver': receiver,
        'resourceAmount': int(energy), 'durationSec': int(duration or TRONSAVE_RENT_SECS),
        'unitPrice': 'MEDIUM', 'options': {'allowPartialFill': True}}, timeout=20)
    j = r.json()
    if j.get('error') or not isinstance(j.get('data'), dict):
        raise RuntimeError(f"TronSave estimate: {j.get('message') or r.status_code}")
    d = j['data']
    if d.get('availableResource', 0) < energy * 0.9:
        raise RuntimeError('TronSave market has insufficient energy right now — use TRX mode')
    return {'trx': d['estimateTrx'] / 1e6, 'sun': int(d['estimateTrx']),
            'unit_price': d.get('unitPrice')}

def _tron_signed_transfer_json(key_hex, to, amount_sun):
    """Build + sign a TRX transfer locally, return the TronGrid-style JSON.
    NEVER broadcast here and NEVER send the key to TronSave — the signed tx
    object itself is the payment proof they submit."""
    from tronpy.keys import PrivateKey
    client = _tron_client()
    pk = PrivateKey(bytes.fromhex(key_hex.replace('0x', '')))
    tx = (client.trx.transfer(pk.public_key.to_base58check_address(), to, int(amount_sun))
          .build().sign(pk))
    j = tx.to_json() if hasattr(tx, 'to_json') else getattr(tx, '_tx', None)
    if isinstance(j, str):
        j = json.loads(j)
    if not isinstance(j, dict) or 'signature' not in j:
        raise RuntimeError('Could not serialize the signed payment tx')
    return j

def tronsave_rent(receiver, energy, gas_addr, gas_key, duration=None):
    """Rent `energy` for `receiver`. Pays from the gas wallet: prefunded
    TronSave account if TRONSAVE_API_KEY set, else an on-chain signed payment.
    Returns {'order': orderId|None, 'pay_txid': str|None}."""
    est = tronsave_estimate(receiver, energy, duration)
    dur = int(duration or TRONSAVE_RENT_SECS)
    if TRONSAVE_API_KEY:
        body = {'resourceType': 'ENERGY', 'receiver': receiver, 'requester': gas_addr,
                'resourceAmount': int(energy), 'durationSec': dur, 'unitPrice': 'MEDIUM',
                'options': {'allowPartialFill': True, 'onlyCreateWhenFulfilled': True,
                            'preventDuplicateIncompleteOrders': True}}
        r = requests.post(TRONSAVE_BASE + '/v2/buy-resource',
                          headers={'apikey': TRONSAVE_API_KEY, 'Content-Type': 'application/json'},
                          json=body, timeout=30)
        j = r.json()
        if j.get('error'):
            raise RuntimeError(f"TronSave order failed: {j.get('message')}")
        d = j.get('data') or {}
        return {'order': d.get('orderId') or d.get('id'), 'pay_txid': None, 'trx': est['trx']}
    # signed-tx path — the gas wallet's signed payment IS the auth
    signed = _tron_signed_transfer_json(gas_key, TRONSAVE_FUND, est['sun'])
    body = {'resourceType': 'ENERGY', 'receiver': receiver,
            'resourceAmount': int(energy), 'durationSec': dur,
            'unitPrice': int(est['unit_price'] or 0) or 'MEDIUM',
            'options': {'allowPartialFill': True, 'onlyCreateWhenFulfilled': True,
                        'preventDuplicateIncompleteOrders': True},
            'signedTx': signed}
    r = requests.post(TRONSAVE_BASE + '/v2/buy-resource',
                      headers={'Content-Type': 'application/json'}, json=body, timeout=30)
    j = r.json()
    if j.get('error'):
        raise RuntimeError(f"TronSave order failed: {j.get('message')}")
    d = j.get('data') or {}
    return {'order': d.get('orderId') or d.get('id'),
            'pay_txid': signed.get('txID'), 'trx': est['trx']}

def tronsave_wait(order_id, timeout=150):
    """Best-effort order polling; the real check is _wait_for_energy after."""
    if not order_id:
        return True
    end = time.time() + timeout
    headers = {'apikey': TRONSAVE_API_KEY} if TRONSAVE_API_KEY else {}
    while time.time() < end:
        try:
            r = requests.get(f"{TRONSAVE_BASE}/v2/order/{order_id}",
                             headers=headers, timeout=15)
            d = (r.json() or {}).get('data') or {}
            if float(d.get('fulfilledPercent') or 0) >= 100:
                return True
            if str(d.get('status', '')).upper() in ('CANCELLED', 'FAILED', 'EXPIRED'):
                return False
        except Exception:
            pass
        time.sleep(4)
    return False

def _tron_self_sufficient(addr, need_energy):
    """True if the wallet already holds enough energy + bandwidth to send USDT
    itself (leftover rented/delegated energy from earlier buys or sends)."""
    res = _tron_account_resources(addr)
    return bool(res and res['energy_limit'] - res['energy_used'] >= need_energy * 0.95
                and res['freenet'] + res['net'] >= 400)

def btc_send(wif, to, amount_btc, fee_sat_vb):
    """Build, sign and broadcast a legacy P2PKH BTC tx (lazy ecdsa import).
    The network fee is paid out of the sent inputs."""
    from ecdsa import SigningKey, SECP256k1
    import io as _io
    key_bytes = _b58check_decode(wif)
    if not key_bytes or len(key_bytes) != 34:
        raise ValueError("Invalid WIF key")
    compressed = key_bytes[-1] == 0x01
    priv = SigningKey.from_string(key_bytes[1:-1] if compressed else key_bytes[1:], curve=SECP256k1)
    pub = priv.get_verifying_key()
    pub_ser = (b'\x02' if pub.pubkey.point.y() % 2 == 0 else b'\x03') + pub.pubkey.point.x().to_bytes(32, 'big') if compressed \
        else b'\x04' + pub.pubkey.point.x().to_bytes(32, 'big') + pub.pubkey.point.y().to_bytes(32, 'big')

    def h160(b):
        return hashlib.new('ripemd160', hashlib.sha256(b).digest()).digest()
    our_h160 = h160(pub_ser)
    from_addr = _b58check_encode(b'\x00' + our_h160)

    # gather UTXOs via esplora
    utxos = None
    for base in ("https://mempool.space/api", "https://blockstream.info/api"):
        try:
            r = requests.get(f"{base}/address/{from_addr}/utxo", timeout=10)
            if r.status_code == 200:
                utxos = r.json(); break
        except Exception:
            continue
    if not utxos: raise RuntimeError("No spendable UTXOs found")

    amount_sat = int(amount_btc * 10**8)
    # largest-first coin selection until amount+fee covered
    utxos.sort(key=lambda u: u['value'], reverse=True)
    picked, total = [], 0
    est_vb = 0
    for u in utxos:
        picked.append(u); total += u['value']
        est_vb = len(picked) * 148 + 2 * 34 + 10
        if total >= amount_sat + int(fee_sat_vb * est_vb):
            break
    fee_sat = int(fee_sat_vb * est_vb)
    if total < amount_sat + fee_sat:
        raise ValueError(f"Insufficient BTC: have {total/1e8}, need {(amount_sat+fee_sat)/1e8} (incl. fee)")
    change = total - amount_sat - fee_sat

    def ser_varint(n):
        if n < 0xfd: return bytes([n])
        if n <= 0xffff: return b'\xfd' + n.to_bytes(2, 'little')
        return b'\xfe' + n.to_bytes(4, 'little')
    def dest_script(address):
        p = _b58check_decode(address)
        if not p or len(p) != 21: raise ValueError("Unsupported destination (P2PKH/P2SH only for BTC sends)")
        if p[0] == 0x00:
            return bytes.fromhex('76a914') + p[1:] + bytes.fromhex('88ac')
        return bytes.fromhex('a914') + p[1:] + bytes.fromhex('87')
    our_script = bytes.fromhex('76a914') + our_h160 + bytes.fromhex('88ac')

    def build_tx(signing_idx=-1):
        b = (1).to_bytes(4, 'little') + ser_varint(len(picked))
        for i, u in enumerate(picked):
            b += bytes.fromhex(u['txid'])[::-1] + u['vout'].to_bytes(4, 'little')
            script = our_script if i == signing_idx else b''
            b += ser_varint(len(script)) + script + (0xffffffff).to_bytes(4, 'little')
        b += ser_varint(2 if change > 546 else 1)
        b += amount_sat.to_bytes(8, 'little')
        ds = dest_script(to); b += ser_varint(len(ds)) + ds
        if change > 546:
            b += change.to_bytes(8, 'little') + ser_varint(len(our_script)) + our_script
        return b

    sig_scripts = []
    for i in range(len(picked)):
        sighash = hashlib.sha256(hashlib.sha256(build_tx(i) + (1).to_bytes(4, 'little')).digest()).digest()
        sig = priv.sign_digest_deterministic(sighash, sigencode=__import__('ecdsa').util.sigencode_der)
        sig_scripts.append(ser_varint(len(sig) + 1) + sig + b'\x01' + ser_varint(len(pub_ser)) + pub_ser)

    raw = (1).to_bytes(4, 'little') + ser_varint(len(picked))
    for i, u in enumerate(picked):
        raw += bytes.fromhex(u['txid'])[::-1] + u['vout'].to_bytes(4, 'little')
        raw += ser_varint(len(sig_scripts[i])) + sig_scripts[i] + (0xffffffff).to_bytes(4, 'little')
    raw += ser_varint(2 if change > 546 else 1)
    raw += amount_sat.to_bytes(8, 'little')
    ds = dest_script(to); raw += ser_varint(len(ds)) + ds
    if change > 546:
        raw += change.to_bytes(8, 'little') + ser_varint(len(our_script)) + our_script

    for base in ("https://mempool.space/api", "https://blockstream.info/api"):
        try:
            r = requests.post(f"{base}/tx", data=raw.hex(), timeout=15,
                              headers={'Content-Type': 'text/plain'})
            if r.status_code == 200:
                return r.text.strip()
        except Exception as e:
            print(f"[SEND] BTC broadcast error via {base}: {e}")
    raise RuntimeError("BTC broadcast failed on all explorers")

def _b58check_encode(payload):
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    raw = payload + chk
    n = int.from_bytes(raw, 'big')
    s = ''
    while n:
        n, r = divmod(n, 58); s = _B58[r] + s
    return '1' * (len(raw) - len(raw.lstrip(b'\x00'))) + s


# --- SEND ORCHESTRATOR --------------------------------------------------------
def _wait_for_native(addr, network_coin, target, timeout=90):
    """Poll until a wallet's native balance reaches `target` (gas arrival)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if network_coin in ('BNB',):
                bal = _evm_native_balance(BSC_RPC_ENDPOINTS, addr)
            elif network_coin in ('ETH',):
                bal = _evm_native_balance(ETH_RPC_ENDPOINTS, addr)
            else:
                bal = _tron_balance(addr, 'TRX')
            if bal is not None and bal >= target:
                return True
        except Exception:
            pass
        time.sleep(6)
    return False

def execute_treasury_send(task_id):
    """Runs a treasury send in a background thread, updating send_tasks[task_id].
    For token sends the admin gas wallet funds the sending address first
    (two-step); for BTC/TRX the fee rides on the send itself."""
    t = send_tasks[task_id]
    net, uid, to_addr, amount = t['network'], t['uid'], t['to_addr'], t['amount']
    try:
        w = user_db.get(uid, {}).get('wallets', {}).get(net)
        if not w: raise ValueError("Source wallet not found")
        from_addr, priv = w['address'], w['private_key']
        t['from_addr'] = from_addr

        if net == 'USDT_TRC20' and t.get('fee_mode') == 'usdt':
            gasfree_send(t, uid, w, to_addr, amount)

        elif net in ('USDT_TRC20', 'USDT_BEP20', 'USDT_ERC20'):
            est = estimate_network_fee(net, to_addr)
            if 'error' in est: raise RuntimeError(est['error'])
            gas_needed = float(est.get('gas_needed_crypto') or est.get('fee_crypto'))
            gas_asset = est['gas_asset']
            gas_chain = 'tron' if gas_asset == 'TRX' else 'evm'
            gas_addr, gas_key = get_gas_addr(gas_chain), get_gas_key(gas_chain)
            if not gas_addr or not gas_key:
                raise ValueError(f"Gas wallet {gas_asset} not configured (no manual key and no MASTER_SEED)")

            trx_w = user_db.get(uid, {}).get('wallets', {}).get('TRX')
            if gas_asset == 'TRX':
                need_energy = _tron_energy_needed(to_addr)
                src_free = _tron_self_sufficient(from_addr, need_energy)
                delegated = False
                if src_free:
                    # the wallet already holds rented/delegated energy from an
                    # earlier buy — the send burns it for ~0 TRX total
                    t['step'] = 'Wallet already charged — burning its own energy...'
                elif t.get('fee_mode') == 'rent':
                    t['step'] = f'Renting {need_energy:,} energy (gas wallet pays)...'
                    res_r = tronsave_rent(from_addr, need_energy, gas_addr, gas_key)
                    t['rent_cost_trx'] = res_r.get('trx')
                    if res_r.get('order'): t['rent_order'] = res_r['order']
                    if res_r.get('pay_txid'): t.setdefault('txids', []).append(res_r['pay_txid'])
                    t['step'] = 'Waiting for rented energy to arrive...'
                    tronsave_wait(res_r.get('order'))
                    if not _wait_for_energy(from_addr, need_energy * 0.8):
                        raise RuntimeError('Rented energy did not arrive in time — check TronSave, then retry')
                    delegated = True
                elif est.get('delegated'):
                    res = _tron_account_resources(gas_addr)
                    if res and res['total_energy']:
                        ratio = res['total_weight'] / res['total_energy']  # sun per energy
                        delegate_sun = int(need_energy * ratio * 1.05)
                        remaining = res['staked_sun'] - res['delegated_sun']
                        if remaining > delegate_sun * 0.5:
                            t['step'] = 'Delegating staked energy (gas stays in your wallet)...'
                            t['gas_txid'] = tron_delegate_energy(gas_key, from_addr,
                                                                 min(delegate_sun, remaining))
                            t['txids'] = [t['gas_txid']]
                            delegated = True
                # trx mode last resort before burning: auto-rent when cheaper
                if not delegated and not src_free and t.get('fee_mode') == 'trx':
                    try:
                        est_r = tronsave_estimate(from_addr, need_energy)
                        gtrx = _tron_balance(gas_addr, 'TRX') or 0.0
                        if est_r['trx'] + 1.1 < gas_needed and gtrx >= est_r['trx'] + 1.5:
                            t['step'] = f'Auto-renting {need_energy:,} energy (cheaper than a TRX burn)...'
                            res_r = tronsave_rent(from_addr, need_energy, gas_addr, gas_key)
                            t['rent_cost_trx'] = res_r.get('trx')
                            if res_r.get('order'): t['rent_order'] = res_r['order']
                            if res_r.get('pay_txid'): t.setdefault('txids', []).append(res_r['pay_txid'])
                            tronsave_wait(res_r.get('order'))
                            if not _wait_for_energy(from_addr, need_energy * 0.8):
                                raise RuntimeError('Rented energy did not arrive in time')
                            delegated = True
                    except Exception as e:
                        print(f"[TREASURY] auto-rent skipped/failed: {e}")
                if src_free:
                    topup = 0.0
                elif delegated:
                    # skip the bandwidth top-up when the wallet's free daily
                    # bandwidth already covers the transfer — saves ~30s
                    res_bw = _tron_account_resources(from_addr) or {}
                    topup = 0.0 if (res_bw.get('freenet', 0) + res_bw.get('net', 0)) >= 400 else 0.7
                else:
                    topup = gas_needed + 1.0
                if topup > 0:
                    gb_now = _tron_balance(gas_addr, 'TRX')
                    if gb_now is not None and gb_now < topup + 0.3:
                        raise RuntimeError(f"Gas wallet is short on TRX: needs ~{fmt_amt(topup + 0.3)} "
                                           f"(has {fmt_amt(gb_now)}) — top it up, stake, or switch fee mode")
                    if trx_w:
                        # pre-count the incoming TRX so the watcher can't treat it as a deposit
                        cur_bal = get_onchain_balance(from_addr, 'TRX') or 0.0
                        trx_w['credited_crypto'] = cur_bal + topup
                    t['topup_txid'] = tron_send_native(gas_key, from_addr, topup)
                    t.setdefault('txids', []).append(t['topup_txid'])
                    t['step'] = 'Waiting for gas confirmation...'
                    if delegated and not _wait_for_energy(from_addr, need_energy * 0.8):
                        raise RuntimeError("Delegated energy did not arrive in time; retry")
                    if not _wait_for_native(from_addr, 'TRX', topup * 0.9):
                        raise RuntimeError("Gas top-up did not confirm in time; check the gas tx then retry")
                elif delegated and not src_free:
                    # no top-up needed — just confirm the delegated energy landed
                    if not _wait_for_energy(from_addr, need_energy * 0.8):
                        raise RuntimeError("Delegated energy did not arrive in time; retry")
            else:
                t['step'] = f'Funding gas ({gas_asset} from your gas wallet)...'
                t['gas_txid'] = evm_send_native(gas_asset, gas_key, from_addr, gas_needed)
                t['txids'] = [t['gas_txid']]
                t['step'] = 'Waiting for gas confirmation...'
                if not _wait_for_native(from_addr, gas_asset, gas_needed * 0.9):
                    raise RuntimeError("Gas top-up did not confirm in time; check the gas tx then retry")
            t['step'] = 'Broadcasting token transfer...'
            if net == 'USDT_TRC20':
                t['txid'] = tron_send_token(priv, to_addr, amount)
            else:
                t['txid'] = evm_send_token(net, priv, to_addr, amount)
            t['txids'].append(t['txid'])

            # resync the watcher's mark to post-send balances
            try:
                nb = get_onchain_balance(from_addr, net)
                if nb is not None: w['credited_crypto'] = nb
                if gas_asset == 'TRX' and trx_w:
                    tb = get_onchain_balance(from_addr, 'TRX')
                    if tb is not None: trx_w['credited_crypto'] = tb
            except Exception: pass

        elif net == 'TRX':
            t['step'] = 'Broadcasting TRX transfer...'
            t['txid'] = tron_send_native(priv, to_addr, amount)
            t['txids'] = [t['txid']]
            try:
                nb = get_onchain_balance(from_addr, 'TRX')
                if nb is not None: w['credited_crypto'] = nb
            except Exception: pass

        elif net == 'BTC':
            est = estimate_network_fee('BTC')
            if 'error' in est: raise RuntimeError(est['error'])
            t['step'] = 'Broadcasting BTC transaction...'
            rate = round(est['fee_crypto'] * 10**8 / 250)
            t['txid'] = btc_send(priv, to_addr, amount, max(1, rate))
            t['txids'] = [t['txid']]
            try:
                nb = get_onchain_balance(from_addr, 'BTC')
                if nb is not None: w['credited_crypto'] = nb
            except Exception: pass

        t['status'] = 'done'
        t['step'] = 'Complete'
        treasury_txs.append({
            'ts': time.time(), 'network': net, 'uid': uid,
            'from': t.get('from_addr'), 'to': to_addr, 'amount': amount,
            'fee_crypto': t.get('fee_crypto'), 'gas_asset': NETWORK_GAS.get(net),
            'txids': t.get('txids', []), 'status': 'done'
        })
        save_database()
    except Exception as e:
        t['status'] = 'error'
        t['error'] = str(e)
        t['step'] = 'Failed'
        treasury_txs.append({
            'ts': time.time(), 'network': net, 'uid': uid, 'to': to_addr,
            'amount': amount, 'status': 'error', 'error': str(e),
            'txids': t.get('txids', [])
        })
        save_database()


def _credited_baseline(w_data, curr, onchain):
    """High-water mark of crypto already credited for this wallet. Migrates
    legacy wallets (created before balance tracking) so deposits that were
    already credited in the past are NOT credited a second time."""
    if 'credited_crypto' in w_data:
        return w_data['credited_crypto']
    prior_usd = w_data.get('total_deposited', 0.0)
    if 'USDT' in curr:
        # USDT is 1:1 with USD, so USD already credited == crypto already credited.
        base = prior_usd
    else:
        # We can't reconstruct the exact crypto from stored USD; if anything was
        # credited before, treat the current balance as already accounted for so
        # we never double-credit. Fresh wallets start from zero.
        base = onchain if prior_usd > 0 else 0.0
    w_data['credited_crypto'] = base
    return base


def _meets_min_deposit(curr, crypto_diff):
    """True if a detected on-chain balance increase meets the configured USD
    minimum deposit for that currency. Deposits below the minimum are never
    credited or announced."""
    usd = crypto_diff * (get_crypto_price(curr) if 'USDT' not in curr else 1.0)
    return usd >= deposit_settings.get(curr, {}).get('min', 0.0)


def _spend_trial_first(u, spent_from_deposit):
    """Free-trial cash is always treated as spent BEFORE real money. Whenever
    the deposit pool is debited we shrink the user's outstanding trial pool,
    so an expired claim can never claw back money that was already used."""
    u['trial_credit'] = max(0.0, u.get('trial_credit', 0.0) - spent_from_deposit)


def credit_deposit(uid, curr, crypto_amount, txid="", is_manual=False):
    """Credit a confirmed deposit to a user and fire all the usual
    notifications. Shared by the automatic balance watcher and the manual
    dashboard 'Credit' button. `crypto_amount` is in crypto units."""
    if uid not in user_db or crypto_amount <= 0:
        return 0.0

    live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
    usd_value = crypto_amount * live_price

    user_db[uid]['deposit'] = user_db[uid].get('deposit', 0.0) + usd_value
    w_data = user_db[uid].get('wallets', {}).get(curr, {})
    w_data['total_deposited'] = w_data.get('total_deposited', 0.0) + usd_value
    log_tx(uid, f"{'Manual' if is_manual else 'Auto'}-Deposit ({curr})", usd_value)

    process_referral_commission(uid, usd_value, is_deposit=True)

    try:
        conf = deposit_settings[curr]
        msg_success = conf.get('msg_success', "✅ <b>Deposit Detected!</b>\n\nThe blockchain confirmed a deposit of <b>%crypto_amount% %currency%</b>.\n<b>$%usd_amount% USD</b> has been automatically added to your balance!")
        msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(usd_value)}").replace('%crypto_amount%', f"{fmt_amt(crypto_amount)}").replace('%currency%', curr.replace('_', ' '))
        lang = get_user_lang(uid)
        bot.send_message(uid, get_tl_and_map(msg_success, lang), parse_mode="HTML")
    except Exception: pass

    tag = "MANUAL DEPOSIT CREDITED" if is_manual else "AUTO-DEPOSIT APPROVED (ON-CHAIN BALANCE)"
    admin_msg = (f"🟢 <b>{tag}</b>\nUser: <code>{uid}</code>\nCurrency: {curr.replace('_', ' ')}\n"
                 f"Crypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}")
    if txid:
        admin_msg += f"\nHash (TXID): <code>{txid}</code>"
    for admin in ADMIN_IDS:
        try: bot.send_message(admin, admin_msg, parse_mode="HTML")
        except Exception: pass

    send_admin_push('💰 Deposit Credited',
                    f"${fmt_amt(usd_value)} · {fmt_amt(crypto_amount)} {curr.replace('_', ' ')} — user {uid}",
                    '/', tag=f'dep_{txid or uid}')

    check_and_trigger_auto_buy(uid)
    broadcast_real_deposit(uid, usd_value, crypto_amount, curr, txid or "ON-CHAIN")

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
            </div>
        </div>
        """
        send_email_async(user_email, dep_subject, dep_html)

    return usd_value


def blockchain_watcher_loop():
    """Reliable, keyless deposit watcher. Reads each wallet's real on-chain
    balance and credits any confirmed increase above the last credited level
    (a high-water mark). This catches new AND previously-missed deposits, and
    automatically rebases when funds are swept out. A balance change must stay
    stable for the auto-approve delay before it is acted on (reorg safety)."""
    while True:
        try:
            for uid, data in list(user_db.items()):
                for curr, w_data in list(data.get('wallets', {}).items()):
                    addr = w_data.get('address')
                    if not addr or addr in ("Not Set", "GEN_ERROR", "ERROR_NO_SEED"):
                        continue

                    try:
                        onchain = get_onchain_balance(addr, curr)
                    except Exception as e:
                        print(f"[WATCHER] balance read failed ({curr}) for {uid}: {e}")
                        onchain = None
                    if onchain is None:
                        continue  # all providers failed this cycle; leave state untouched

                    # Cache the live balance so the admin Key Vault can show it fast.
                    w_data['live_balance'] = onchain
                    w_data['live_balance_ts'] = time.time()

                    baseline = _credited_baseline(w_data, curr, onchain)
                    diff = onchain - baseline
                    if abs(diff) <= BALANCE_EPSILON:
                        w_data.pop('pending_credit', None)
                        continue

                    now = time.time()
                    approve_delay = auto_approve_settings.get('delay_seconds', 300)
                    pending = w_data.get('pending_credit')
                    if not pending or abs(pending.get('balance', 0.0) - onchain) > BALANCE_EPSILON:
                        # New/changed balance level: start (or restart) the stability timer.
                        w_data['pending_credit'] = {'balance': onchain, 'first_seen': now}
                        continue
                    if (now - pending['first_seen']) < approve_delay:
                        continue  # wait until the balance has been stable long enough

                    # Stable confirmed change.
                    if diff > BALANCE_EPSILON:
                        if _meets_min_deposit(curr, diff):
                            credit_deposit(uid, curr, diff)
                            w_data['credited_crypto'] = onchain
                        # Below the configured minimum: no credit, no alert —
                        # keep the mark so a later top-up can push it over.
                    else:
                        # Balance dropped (sweep) — always rebase downward.
                        w_data['credited_crypto'] = onchain
                    w_data.pop('pending_credit', None)

        except Exception as e:
            print(f"Watcher Loop Error: {e}")
        time.sleep(30)

def _vapid_keys():
    """Return (public_b64, private_pem) for Web Push, generating + persisting
    on first use. Stored in push_settings (DB-backed) so subscriptions stay
    valid across restarts/redeploys."""
    if push_settings.get('vapid_pub') and push_settings.get('vapid_priv'):
        return push_settings['vapid_pub'], push_settings['vapid_priv']
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        import base64
        priv = ec.generate_private_key(ec.SECP256R1())
        push_settings['vapid_priv'] = priv.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode()
        pub_bytes = priv.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        push_settings['vapid_pub'] = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()
        save_database()
        return push_settings['vapid_pub'], push_settings['vapid_priv']
    except Exception as e:
        print(f"[PUSH] VAPID key generation failed: {e}")
        return None, None


def _push_worker(subs, payload, priv, pub):
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[PUSH] pywebpush not installed — pip install pywebpush")
        return
    dead = []
    for sub in list(subs):
        try:
            webpush(subscription_info=sub, data=payload,
                    vapid_private_key=priv,
                    vapid_claims={'sub': 'mailto:admin@gforce.local'},
                    ttl=86400, timeout=15)
        except WebPushException as e:
            code = getattr(getattr(e, 'response', None), 'status_code', 0)
            if code in (404, 410):
                dead.append(sub)  # subscription revoked/expired — prune it
            print(f"[PUSH] send error (HTTP {code}): {e}")
        except Exception as e:
            print(f"[PUSH] send error: {e}")
    for d in dead:
        try: subs.remove(d)
        except ValueError: pass
    if dead: save_database()


def send_admin_push(title, body, url='/', tag=None):
    """Fire-and-forget Web Push to every subscribed admin device. Silent no-op
    when nothing is subscribed or pywebpush is missing."""
    subs = push_settings.get('subs') or []
    pub, priv = _vapid_keys()
    if not subs or not priv:
        return
    payload = json.dumps({'title': title, 'body': body, 'url': url, 'tag': tag})
    threading.Thread(target=_push_worker,
                     args=(subs, payload, priv, pub), daemon=True).start()


def notify_admin_plan_purchase(user_id, plan):
    """DMs all admins whenever a user activates or buys a plan (any path)."""
    try:
        macro = plan.get('macro', '?')
        p_name = bot_plans.get(macro, {}).get('name', macro)
        amount = plan.get('amount', 0.0)
        uname = user_db.get(user_id, {}).get('username', 'None')
        admin_msg = (f"📈 <b>NEW PLAN ACTIVATED</b>\nUser: <code>{user_id}</code> (@{uname})\n"
                     f"Plan: <b>{p_name}</b>\nInvested: <b>${fmt_amt(amount)}</b>")
        for admin in ADMIN_IDS:
            try: bot.send_message(admin, admin_msg, parse_mode="HTML")
            except Exception: pass
        send_admin_push('📈 Plan Activated',
                        f"{p_name} · ${fmt_amt(amount)} — user {user_id}",
                        '/', tag=f'plan_{user_id}')
    except Exception as e:
        print(f"Admin plan alert error: {e}")

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
                _spend_trial_first(user_db[user_id], invest_amt)
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
        notify_admin_plan_purchase(user_id, new_plan)
        user_db[user_id]['pending_plan'] = None
        
        try:
            lang = get_user_lang(user_id)
            msg = (get_tl_and_map("🎉 <b>Auto-Purchase Successful!</b>\n\nYour deposit triggered your pending plan.\n<b>%plan_name%</b> is now active with an investment of <b>$%amount%</b>!", lang)
                   .replace('%plan_name%', p_data['name'])
                   .replace('%amount%', fmt_amt(invest_amt)))
            bot.send_message(user_id, msg, parse_mode="HTML")
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
                    lang = get_user_lang(user_id)
                    bot.send_message(user_id, get_tl_and_map(msg, lang), parse_mode="HTML")
                except: pass
                
        if p['length_hours'] > 0:
            total_elapsed = (now - p['start_time']) / 3600.0
            if total_elapsed >= p['length_hours']:
                p['status'] = 'expired'
                try:
                    msg = global_messages_setup.get('expiry_dm', '💰You have received a total profit of +{total_profit} USDT.\n⏰Trading Completed')
                    msg = msg.replace('{total_profit}', f"{fmt_amt(p['earned'])}")
                    lang = get_user_lang(user_id)
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
            lang = get_user_lang(user_id)
            updated_text = replace_macros(get_tl_and_map(base_text, lang), user_id, full_path)
            if is_photo:
                bot.edit_message_caption(caption=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                bot.edit_message_text(text=updated_text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "deleted" in err_str:
                break
            pass

def _bulk_translate_batch(strings, target_lang):
    """Translate a list of English strings into target_lang in ONE Google
    Translate batch HTTP request (much faster than one request per string).
    Writes successful results into TL_CACHE + REVERSE_TL_MAP. Returns nothing."""
    if not strings:
        return
    target_norm = _normalize_lang(target_lang)
    protected_batch, token_maps = [], []
    for s in strings:
        p, toks = _protect_tokens(s)
        protected_batch.append(p)
        token_maps.append(toks)
    translator = GoogleTranslator(source='en', target=target_norm)
    try:
        results = translator.translate_batch(protected_batch)
    except Exception as e:
        print(f"bulk_prewarm batch error ({target_lang}): {e}")
        results = None
    if not results or not isinstance(results, list) or len(results) != len(protected_batch):
        # Batch failed — fall back to per-string so we still cache what we can.
        results = []
        for p in protected_batch:
            try:
                results.append(translator.translate(p))
            except Exception:
                results.append(None)
    for src, raw, toks in zip(strings, results, token_maps):
        if not (isinstance(raw, str) and raw.strip()):
            continue
        tr = _restore_tokens(raw, toks)
        if tr.strip() == src.strip():
            continue
        if not _tokens_intact(src, tr):
            continue
        TL_CACHE[('en', target_lang, src)] = tr
        REVERSE_TL_MAP.setdefault(target_lang, {})[tr] = src


def _bulk_prewarm(strings, target_lang, timeout=None):
    """Translate all uncached `strings` into `target_lang` and store them in
    TL_CACHE. Uses Google's batch endpoint = one HTTP request for the whole
    set, instead of one request per string. Total wall-clock is dominated by
    a single Google round-trip (~300ms-1.5s). Capped at `timeout` seconds.

    Call this right BEFORE rendering a menu so the per-string get_tl_and_map()
    calls below mostly hit cache and the user never sees English text flash."""
    if not strings or not target_lang or target_lang == 'en':
        return
    target_lang = _normalize_lang(target_lang)
    if target_lang == 'en':
        return
    pending = []
    for s in strings:
        if not s or not isinstance(s, str):
            continue
        if s in CORE_TL_DATA and target_lang in CORE_TL_DATA[s]:
            continue
        if ('en', target_lang, s) in TL_CACHE:
            continue
        pending.append(s)
    if not pending:
        return
    fut = _TL_EXECUTOR.submit(_bulk_translate_batch, pending, target_lang)
    try:
        fut.result(timeout=timeout or _TL_BULK_TIMEOUT)
    except concurrent.futures.TimeoutError:
        # Still translating — strings the user doesn't see immediately will
        # be cached for the next render.
        pass
    except Exception as e:
        print(f"_bulk_prewarm error: {e}")


def _collect_path_strings(path):
    """Return the set of English strings that would be rendered for `path`
    (button labels, post bodies, inline button labels). Used to prewarm
    translations in parallel right before render."""
    strings = set()
    try:
        for name in menus.get(path, []) or []:
            if isinstance(name, str): strings.add(name)
        for p in menu_posts.get(path, []) or []:
            if p.get('text'): strings.add(p['text'])
            for b in p.get('custom_inlines', []) or []:
                if b.get('text') and b.get('mode') != 'set_lang':
                    strings.add(b['text'])
    except Exception:
        pass
    return strings


def send_path_content(chat_id, user_id, path, is_editing=False, reply_keyboard=None):
    if is_editing and user_id in editor_msg_ids:
        for m_id in editor_msg_ids[user_id]:
            try: bot.delete_message(chat_id, m_id)
            except Exception: pass
        editor_msg_ids[user_id] = []

    lang = get_user_lang(user_id)
    # Parallel-prewarm everything we are about to render so the per-string
    # get_tl_and_map() calls below mostly hit cache instead of blocking
    # sequentially. Keeps the menu rendering snappy on uncached languages.
    if lang and lang != 'en':
        _bulk_prewarm(_collect_path_strings(path), lang)
    meta = btn_metadata.get(path, get_default_metadata())
    assigned_plan = meta.get('assigned_plan')
    
    kb_attached = False
    
    if assigned_plan and assigned_plan in bot_plans:
        p_data = bot_plans[assigned_plan]
        p_text = replace_macros(get_tl_and_map(p_data.get('text', ''), lang), user_id, path)
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
        raw_text = replace_macros(get_tl_and_map(p['text'], lang), user_id, path)
        
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
        
        ptype = p.get('type', 'text')
        # Telegram caption limit is 1024 chars for photo/video/animation/document.
        # Plain message limit is 4096. Truncate captions to avoid 400 errors.
        is_media_post = ptype in ('photo', 'video', 'animation', 'document') and p.get(ptype)
        cap_full = final_text if final_text else None
        if is_media_post and isinstance(cap_full, str) and len(cap_full) > 1024:
            cap = cap_full[:1020] + '…'
        else:
            cap = cap_full

        sent = _safe_render_post(
            chat_id, ptype, p, cap, markup,
            is_live_trading=meta.get('is_live_trading') and not is_editing,
            user_id=user_id, path=path,
        )
        if sent is not None and is_editing:
            editor_msg_ids.setdefault(user_id, []).append(sent.message_id)

def _safe_send_media(send_func, *args, **kwargs):
    """Try to send media with HTML parse_mode; on 400 (e.g. malformed entities
    in a translated caption), retry with the caption / text HTML-stripped and
    parse_mode dropped. Returns the sent Message or None."""
    try:
        return send_func(*args, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if '400' not in str(e):
            raise
        # Retry: strip HTML tags from caption (kw) and text (kw OR positional
        # arg index 1, e.g. bot.send_message(chat_id, text)) and drop HTML mode.
        try:
            if kwargs.get('caption'):
                kwargs['caption'] = re.sub(r'<[^>]+>', '', kwargs['caption'])
            if kwargs.get('text'):
                kwargs['text'] = re.sub(r'<[^>]+>', '', kwargs['text'])
            args = list(args)
            if len(args) >= 2 and isinstance(args[1], str) and '<' in args[1]:
                args[1] = re.sub(r'<[^>]+>', '', args[1])
            kwargs.pop('parse_mode', None)
            return send_func(*args, **kwargs)
        except Exception as e2:
            print(f"_safe_send_media fallback failed: {e2}")
            return None


def _safe_render_post(chat_id, ptype, p, cap, markup, is_live_trading=False, user_id=None, path=None):
    """Render a single menu post with type-aware sending and graceful fallbacks.
    Catches Telegram 400 errors (malformed HTML, expired file_id, etc.) and
    degrades to plain text rather than dumping a stack trace into chat."""
    sent = None
    try:
        if ptype == 'photo' and p.get('photo'):
            sent = _safe_send_media(bot.send_photo, chat_id, p['photo'],
                                    caption=cap, parse_mode="HTML", reply_markup=markup)
            if sent and is_live_trading:
                threading.Thread(target=execute_live_trading_animation,
                                 args=(chat_id, sent.message_id, user_id, p['text'], path, True),
                                 daemon=True).start()
        elif ptype == 'video' and p.get('video'):
            # Send as animation so the video AUTOPLAYS in the chat (silent,
            # GIF-style preview) — admins requested videos to play without
            # the user having to tap the play button.
            sent = _safe_send_media(bot.send_animation, chat_id, p['video'],
                                    caption=cap, parse_mode="HTML", reply_markup=markup)
            if sent is None:
                # Fallback: some file_ids only work via send_video.
                sent = _safe_send_media(bot.send_video, chat_id, p['video'],
                                        caption=cap, parse_mode="HTML",
                                        reply_markup=markup, supports_streaming=True)
        elif ptype == 'animation' and p.get('animation'):
            sent = _safe_send_media(bot.send_animation, chat_id, p['animation'],
                                    caption=cap, parse_mode="HTML", reply_markup=markup)
        elif ptype == 'document' and p.get('document'):
            sent = _safe_send_media(bot.send_document, chat_id, p['document'],
                                    caption=cap, parse_mode="HTML", reply_markup=markup)
        else:
            safe_text = cap if cap else " "
            sent = _safe_send_media(bot.send_message, chat_id, safe_text,
                                    parse_mode="HTML", reply_markup=markup)
            if sent and is_live_trading:
                threading.Thread(target=execute_live_trading_animation,
                                 args=(chat_id, sent.message_id, user_id, p['text'], path, False),
                                 daemon=True).start()
    except Exception as e:
        # Only show the error in chat for ADMINS — regular users should never
        # see a stack trace inside a bot menu.
        is_admin_view = user_id in ADMIN_IDS
        if is_admin_view:
            err_msg = f"⚠️ <b>Error rendering post:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>Fix or delete this using the buttons below.</i>"
            try:
                sent = bot.send_message(chat_id, err_msg, parse_mode="HTML", reply_markup=markup)
            except Exception:
                sent = None
        else:
            # Last-resort plain-text send so the user still sees something.
            try:
                fallback = re.sub(r'<[^>]+>', '', cap) if cap else " "
                sent = bot.send_message(chat_id, fallback or " ", reply_markup=markup)
            except Exception:
                sent = None
    return sent


def _bc_send_media(chat_id, bc_data, caption, markup):
    """Send a broadcast item using whichever media type was attached
    (photo / video / animation / document) or fall back to plain text."""
    cap = caption if caption else None
    if bc_data.get('photo'):
        bot.send_photo(chat_id, bc_data['photo'], caption=cap, parse_mode="HTML", reply_markup=markup)
    elif bc_data.get('video'):
        bot.send_video(chat_id, bc_data['video'], caption=cap, parse_mode="HTML", reply_markup=markup, supports_streaming=True)
    elif bc_data.get('animation'):
        bot.send_animation(chat_id, bc_data['animation'], caption=cap, parse_mode="HTML", reply_markup=markup)
    elif bc_data.get('document'):
        bot.send_document(chat_id, bc_data['document'], caption=cap, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(chat_id, cap or " ", parse_mode="HTML", reply_markup=markup)

def _build_post_from_message(message, formatted_text):
    """Build a menu_posts entry from an incoming Telegram message,
    auto-detecting photo / video / animation (GIF) / document."""
    post = {
        'id': str(uuid.uuid4())[:8],
        'type': 'text',
        'text': formatted_text,
        'photo': None,
        'video': None,
        'animation': None,
        'document': None,
        'custom_inlines': []
    }
    if getattr(message, 'photo', None):
        post['type'] = 'photo'
        post['photo'] = message.photo[-1].file_id
    elif getattr(message, 'video', None):
        post['type'] = 'video'
        post['video'] = message.video.file_id
    elif getattr(message, 'animation', None):
        post['type'] = 'animation'
        post['animation'] = message.animation.file_id
    elif getattr(message, 'document', None):
        post['type'] = 'document'
        post['document'] = message.document.file_id
    return post

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

def get_withdrawal_conf_inline(lang):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(get_tl_and_map("✅ Confirm", lang), callback_data='cb_w_yes'),
        InlineKeyboardButton(get_tl_and_map("❌ Cancel", lang), callback_data='cb_w_no')
    )
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
        # NOTE: posts_editing used to return here, hiding all the menu buttons.
        # That blocked navigation while editing posts. Now it falls through to
        # the regular menu rendering below (just like the 'editing' state),
        # and the post-editor specific buttons get appended near the bottom.
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
    elif state == 'posts_editing':
        # Post-editor specific bottom bar — menu nav buttons above remain
        # visible so admin can navigate submenus while editing posts.
        markup.row(KeyboardButton('➕ Add Message'), KeyboardButton('🎛️ Buttons Editor'))
        markup.row(KeyboardButton('🛑 Stop Editor'))
    elif state == 'normal':
        markup.row(KeyboardButton('🎛️ Buttons Editor'), KeyboardButton('📝 Posts Editor'))
        if current_path == 'root':
            markup.row(KeyboardButton('💵 Balance'), KeyboardButton('🔐 Admin'))
        
    return markup

def get_keyboard(user_id):
    markup = get_keyboard_raw(user_id)
    lang = get_user_lang(user_id)
    if lang == 'en' or not markup: return markup

    # Pre-fetch all button labels in parallel before translating each one
    # sequentially. Total wall-clock = slowest fetch, not sum of fetches.
    all_labels = [btn['text'] for row in markup.keyboard for btn in row]
    _bulk_prewarm(set(all_labels), lang)

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
            lang = get_user_lang(inviter_id)
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
    # 🛑 1. THE GROUP KILL SWITCH (Destroys stuck keyboards)
    if message.chat.type != 'private':
        wipe_keyboard = ReplyKeyboardRemove()
        bot.send_message(message.chat.id, "🤖 <b>Bot Active.</b> Please DM me to interact.", reply_markup=wipe_keyboard, parse_mode="HTML")
        return

    user_id = message.from_user.id
    
    if user_id in blocked_users:
        lang = get_user_lang(user_id)
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


@bot.message_handler(content_types=['text', 'photo', 'video', 'animation', 'document'])
def handle_messages(message):
    # 🛑 2. THE STEALTH SILENCER (Ignores all group chat text instantly)
    if message.chat.type != 'private':
        return

    user_id = message.from_user.id
    text = message.text if message.text else (message.caption if message.caption else "")
    
    if user_id in blocked_users:
        lang = get_user_lang(user_id)
        bot.send_message(message.chat.id, get_tl_and_map(block_settings['msg_block'], lang), parse_mode="HTML")
        return
    
    formatted_text = extract_html(message)
    is_admin = user_id in ADMIN_IDS
    
    is_new = init_user_db(message)

    # --- UNIVERSAL WITHDRAWAL STATE ENGINE (Bulletproof Version) ---
    state = user_state.get(user_id, 'normal')
    lang = get_user_lang(user_id)

    if state == 'withdraw_wait_amount':
        # 🛡️ SAFETY 1: Ensure user data exists to prevent the "glitch"
        if user_id not in user_action_data:
            user_action_data[user_id] = {}
        
        # Clean the input
        clean_text = text.replace('$', '').replace(',', '').strip()
        
        try:
            amount = float(clean_text)
            
            # 🛡️ SAFETY 2: Fallback values if global_w_setup is missing something
            w_min = global_w_setup.get('w_min', 10.0)
            w_max = global_w_setup.get('w_max', 10000.0)
            u_bal = user_db.get(user_id, {}).get('balance', 0.0)

            # Check limits
            if amount < w_min or amount > w_max:
                err_msg = f"⚠️ Amount must be between ${fmt_amt(w_min)} and ${fmt_amt(w_max)}."
                return bot.send_message(message.chat.id, get_tl_and_map(err_msg, lang), parse_mode="HTML")
            
            # Check balance
            if amount > u_bal:
                return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Insufficient balance.", lang))

            # ✅ SUCCESS: Save and move to the next step
            user_action_data[user_id]['withdraw_amount'] = amount
            user_state[user_id] = 'withdraw_wait_wallet'
            
            # Translate the next prompt (Instant via CORE_TL_DATA)
            addr_prompt = global_w_setup.get('w_msg_addr', 'Please enter your withdrawal address:')
            return bot.send_message(message.chat.id, get_tl_and_map(addr_prompt, lang), parse_mode="HTML")

        except ValueError:
            # If they typed something that isn't a number
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Numbers only.", lang))
        except Exception as e:
            # 🛡️ SAFETY 3: Catch any other error so the bot doesn't "glitch"
            print(f"Withdrawal Error: {e}")
            return bot.send_message(message.chat.id, "⚠️ An error occurred. Please try clicking Withdraw again.")

    if state == 'withdraw_wait_wallet':
        # 🛡️ SAFETY 4: Ensure the amount was actually saved
        if user_id not in user_action_data or 'withdraw_amount' not in user_action_data[user_id]:
            user_state[user_id] = 'normal'
            return bot.send_message(message.chat.id, "⚠️ Session lost. Please start the withdrawal again.")

        user_action_data[user_id]['withdraw_wallet'] = text
        user_state[user_id] = 'normal' 
        
        # FIX: Translate the TEMPLATE first, then replace the placeholders
        # This prevents the translator from getting confused by the wallet address
        raw_conf_tpl = global_w_setup.get('w_msg_conf', 'Confirm withdrawal of %withdraw% to %address%')
        translated_conf = get_tl_and_map(raw_conf_tpl, lang)
        
        # Now replace the %tags% with the actual formatted data
        final_conf = translated_conf.replace('%withdraw%', f"<b>${fmt_amt(user_action_data[user_id]['withdraw_amount'])}</b>")
        final_conf = final_conf.replace('%address%', f"<code>{text}</code>")
        
        # If your template uses %network%, add it here
        method = user_action_data[user_id].get('withdraw_method', 'USDT')
        final_conf = final_conf.replace('%network%', method)
        
        # Send the translated and formatted confirmation
        return bot.send_message(message.chat.id, final_conf, parse_mode="HTML")

    # --- 4. YOUR EXISTING BUTTON TEXT LOGIC ---
    # The rest of your code (if text == "Withdraw", etc.) continues here...

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
    
    lang = get_user_lang(user_id)
    
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
        bot.send_message(message.chat.id, get_tl_and_map("Sending... ⏳", lang))
        time.sleep(1.5)
        bot.send_message(message.chat.id, get_tl_and_map("✅ Your message has been routed securely to Support.", lang), reply_markup=get_keyboard(user_id))
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
        target_lang = get_user_lang(target_uid)
        
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
        user_action_data[user_id] = {'broadcast': {'text': '', 'photo': None, 'video': None, 'animation': None, 'document': None, 'inlines': []}}
        bot.send_message(message.chat.id, "Send the text, photo, video, GIF, or document for the broadcast message:", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'admin_broadcast_input':
        user_action_data[user_id]['broadcast']['text'] = formatted_text
        bc = user_action_data[user_id]['broadcast']
        # Reset any previously attached media so re-sends work cleanly.
        bc['photo'] = bc['video'] = bc['animation'] = bc['document'] = None
        if message.photo:
            bc['photo'] = message.photo[-1].file_id
        elif getattr(message, 'video', None):
            bc['video'] = message.video.file_id
        elif getattr(message, 'animation', None):
            bc['animation'] = message.animation.file_id
        elif getattr(message, 'document', None):
            bc['document'] = message.document.file_id
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
            _bc_send_media(message.chat.id, bc_data, bc_data.get('text'), markup if markup.keyboard else None)
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
                    lang = get_user_lang(uid)
                    tl_text = replace_macros(get_tl_and_map(bc_data['text'], lang), uid, 'root') if bc_data['text'] else None
                    
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

                    _bc_send_media(uid, bc_data, tl_text, tl_markup)
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
                user_db[target]['trial_credit'] = 0.0
                user_db[target]['bonus'] = 0.0
                user_db[target]['hourly'] = 0.0
                user_db[target]['active_plans'] = []
                user_db[target]['total_withdrawn'] = 0.0
                user_db[target]['team_deposits'] = 0.0
                user_db[target]['affiliate_earnings'] = 0.0
                # Reset one-time gateway flags so the wiped user can claim
                # the homepage bonus and free plan again from scratch.
                user_db[target]['has_claimed_free_plan'] = False
                user_db[target]['has_seen_homepage'] = False
                user_db[target]['pending_plan'] = None
                
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
                user_db[uid]['trial_credit'] = 0.0
                user_db[uid]['bonus'] = 0.0
                user_db[uid]['hourly'] = 0.0
                user_db[uid]['active_plans'] = []
                user_db[uid]['total_withdrawn'] = 0.0
                user_db[uid]['team_deposits'] = 0.0
                user_db[uid]['affiliate_earnings'] = 0.0
                # Reset one-time gateway flags so wiped users can claim
                # homepage bonus and free plan from scratch again.
                user_db[uid]['has_claimed_free_plan'] = False
                user_db[uid]['has_seen_homepage'] = False
                user_db[uid]['pending_plan'] = None
                
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
        new_post = _build_post_from_message(message, formatted_text)
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
            rebuilt = _build_post_from_message(message, formatted_text)
            # Preserve id and custom_inlines; replace media + text
            post['type'] = rebuilt['type']
            post['text'] = rebuilt['text']
            post['photo'] = rebuilt.get('photo')
            post['video'] = rebuilt.get('video')
            post['animation'] = rebuilt.get('animation')
            post['document'] = rebuilt.get('document')
        user_state[user_id] = 'posts_editing'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Message completely replaced!", lang), reply_markup=get_keyboard(user_id))
        send_path_content(message.chat.id, user_id, current_path, True)
        return

    if state == 'posts_insert_after':
        p_id = user_action_data[user_id]['post_id']
        posts_list = menu_posts.get(current_path, [])
        idx = next((i for i, p in enumerate(posts_list) if p['id'] == p_id), -1)
        
        new_post = _build_post_from_message(message, formatted_text)
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
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Insufficient funds. You only have $%avail% available.", lang).replace('%avail%', fmt_amt(total_avail)))

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
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Amount does not match any plan. Please enter an amount between $%min% and $%max%.", lang).replace('%min%', fmt_amt(min_plan_amount)).replace('%max%', fmt_amt(max_plan_amount)))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem
        _spend_trial_first(user_db[user_id], min(u_dep, amount))

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        notify_admin_plan_purchase(user_id, new_plan)

        succ_template = reinvest_settings['msg_success']
        translated = get_tl_and_map(succ_template, lang)
        succ_msg = translated.replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, replace_macros(succ_msg, user_id, user_current_path[user_id]), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

        if not matched_plan_id:
            min_plan_amount = min(p['min'] for p in valid_plans.values())
            max_plan_amount = max(p['max'] for p in valid_plans.values())
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Amount does not match any plan. Please enter an amount between $%min% and $%max%.", lang).replace('%min%', fmt_amt(min_plan_amount)).replace('%max%', fmt_amt(max_plan_amount)))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem
        _spend_trial_first(user_db[user_id], min(u_dep, amount))

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        notify_admin_plan_purchase(user_id, new_plan)

        # Translate the TEMPLATE first (with %amount% / %plan_name% intact),
        # then substitute the actual amount and plan name.
        succ_translated = get_tl_and_map(reinvest_settings['msg_success'], lang)
        succ_msg = succ_translated.replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, replace_macros(succ_msg, user_id, user_current_path[user_id]), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        user_state[user_id] = 'normal'
        return

   # --- USER WALLET & EMAIL SETUP ENGINE (DASHBOARD FIX) ---
    if state == 'wallet_wait_email':
        email_input = text.strip().lower()
        if "@" not in email_input or "." not in email_input:
            bot.send_message(message.chat.id, "⚠️ <b>Invalid Email!</b>\n\nPlease enter a valid email address.", parse_mode="HTML")
            return
        
        # This line saves it to the database that your HTML Dashboard reads
        user_db[user_id]['email'] = email_input 
        
        user_state[user_id] = 'wallet_wait_address'
        bot.send_message(message.chat.id, get_tl_and_map(global_wallet_setup['msg_prompt'], lang), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        return

    if state == 'wallet_wait_address':
        addr = text.strip()
        
        # Validation for USDT/BTC
        is_trc20 = addr.startswith('T') and 33 <= len(addr) <= 35
        is_bep20 = addr.startswith('0x') and len(addr) == 42
        is_btc = (addr.startswith('1') or addr.startswith('3') or addr.startswith('bc1')) and len(addr) >= 26
        
        if not (is_trc20 or is_bep20 or is_btc):
            bot.send_message(message.chat.id, "⚠️ <b>Invalid Address!</b>\n\nPlease enter a valid <b>USDT (TRC20/BEP20)</b> or <b>BTC</b> address.", parse_mode="HTML")
            return

        # Save Wallet and Network
        user_db[user_id]['wallet'] = addr
        user_db[user_id]['wallet_net'] = "USDT (TRC20)" if is_trc20 else "USDT (BEP20)" if is_bep20 else "BTC"
        
        # IMPORTANT: This ensures the Dashboard sees the changes immediately
        user_state[user_id] = 'normal'
        
        # Success message with both Email and Wallet confirmed.
        # Translate the LABELS only; the user's email/address/network stay
        # verbatim because they are inserted AFTER translation via macros.
        user_email = user_db[user_id].get('email', 'Not Set')
        msg_tpl = "✅ <b>Success!</b>\n\n<b>Email:</b> %email%\n<b>Wallet:</b> %wallet%\n<b>Network:</b> %network%"
        msg = (get_tl_and_map(msg_tpl, lang)
               .replace('%email%', user_email)
               .replace('%wallet%', addr)
               .replace('%network%', user_db[user_id]['wallet_net']))
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    if state == 'bonus_wait_email':
        email = text.strip()
        if "@" not in email or "." not in email:
            bot.send_message(message.chat.id, "⚠️ <b>Invalid Email!</b>\n\nPlease enter a valid email address.", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            return
        user_db[user_id]['email'] = email
        user_state[user_id] = 'normal'
        bot.send_message(message.chat.id, get_tl_and_map("✅ Email successfully linked! Please click the Bonus button again to claim.", lang), parse_mode="HTML", reply_markup=get_keyboard(user_id))
        return

    # --- PROFIT CALCULATOR ENGINE ---
    if state == 'wait_calc_amount':
        # Clean user input to prevent crashing on $, commas, or text
        clean_text = text.replace('$', '').replace(',', '').replace('USD', '').replace('usd', '').strip()
        try: 
            amount = float(clean_text)
        except ValueError: 
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Invalid amount. Please enter numbers only (e.g. 100).", lang))

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
                msg += f"Profit Rate: {p_data['profit']}% / Hour\n"
                msg += f"Hourly Profit: ${fmt_amt(hourly)}\nDaily Profit: ${fmt_amt(daily)}\n"
                
                if p_data['length'] > 0:
                    total = hourly * p_data['length']
                    msg += f"Total Return ({p_data['length']}h): ${fmt_amt(total)}\n\n"
                else:
                    msg += f"Total Return: Lifetime\n\n"

                markup.row(InlineKeyboardButton(get_tl_and_map("🛒 Buy %plan_name%", lang).replace('%plan_name%', p_data['name']), callback_data=f"cb_calcbuy_{p_id}_{amount}"))

        if not found:
            msg += "❌ No plans available for this exact amount. Please check the minimum and maximum limits."

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
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Amount must be between <b>$%min%</b> and <b>$%max%</b>.", lang).replace('%min%', str(p_data['min'])).replace('%max%', str(p_data['max'])), parse_mode="HTML")
            
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
        _spend_trial_first(user_db[user_id], min(u_dep, invest_amount))
            
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
        notify_admin_plan_purchase(user_id, new_plan)
        
        user_state[user_id] = 'normal'
        # Translate the static template first, then inject dynamic values.
        msg = (get_tl_and_map("🎉 <b>Success!</b>\nYou invested <b>$%amount%</b> into <b>%plan_name%</b>!\nYour profit is accruing automatically.", lang)
               .replace('%amount%', fmt_amt(invest_amount))
               .replace('%plan_name%', p_data['name']))
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=get_keyboard(user_id))
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
        if usd_amount < c_min: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Minimum deposit is <b>$%min% USD</b>.", lang).replace('%min%', fmt_amt(c_min)), parse_mode="HTML")
        if usd_amount > c_max: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Maximum deposit is <b>$%max% USD</b>.", lang).replace('%max%', fmt_amt(c_max)), parse_mode="HTML")

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
            
            loading_msg = bot.send_message(message.chat.id, get_tl_and_map("🔄 <b>Initializing Secure Connection...</b>\n%bar%", lang).replace('%bar%', bars[0]), parse_mode="HTML")
            for bar in bars[1:]:
                time.sleep(0.5)
                try: bot.edit_message_text(get_tl_and_map("🔄 <b>Generating Wallet...</b>\n%bar%", lang).replace('%bar%', bar), message.chat.id, loading_msg.message_id, parse_mode="HTML")
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
            bot.send_message(message.chat.id, f"Enter your new receipt template.\n\n<b>Available Tags:</b>\n{{user_id}}\n{{network_display}}\n{{usd_amount}}\n{{crypto_amount}}\n{{hash_link}}\n\n<b>Current Template:</b>\n{current_msg}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        
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
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Insufficient funds. You only have $%avail% available.", lang).replace('%avail%', fmt_amt(total_avail)))

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
            return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Amount does not match any plan. Please enter an amount between $%min% and $%max%.", lang).replace('%min%', fmt_amt(min_plan_amount)).replace('%max%', fmt_amt(max_plan_amount)))

        if u_dep >= amount:
            user_db[user_id]['deposit'] -= amount
        else:
            rem = amount - u_dep
            user_db[user_id]['deposit'] = 0
            user_db[user_id]['balance'] -= rem
        _spend_trial_first(user_db[user_id], min(u_dep, amount))

        log_tx(user_id, f"Reinvested {matched_plan_data['name']}", -amount)

        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': matched_plan_id, 'amount': amount,
            'profit_pct': matched_plan_data['profit'], 'length_hours': matched_plan_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        notify_admin_plan_purchase(user_id, new_plan)

        # Translate the TEMPLATE first (with %amount% / %plan_name% intact),
        # then substitute the actual amount and plan name.
        succ_translated = get_tl_and_map(reinvest_settings['msg_success'], lang)
        succ_msg = succ_translated.replace('%amount%', f"{fmt_amt(amount)}").replace('%plan_name%', matched_plan_data['name'])
        bot.send_message(message.chat.id, replace_macros(succ_msg, user_id, user_current_path[user_id]), parse_mode="HTML", reply_markup=get_keyboard(user_id))
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
            bot.send_message(message.chat.id, "Send the text, photo, video, GIF, or document for the new message:", reply_markup=get_cancel_action_keyboard())
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
            target_lang = get_user_lang(target_id)
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
            bot.send_message(message.chat.id, get_tl_and_map("Balance: $%bal%", lang).replace('%bal%', fmt_amt(bal)))
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
                    target_lang = get_user_lang(target)
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
        
        if amount < w_min: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Minimum withdrawal is %min%.", lang).replace('%min%', str(w_min)))
        if amount > w_max: return bot.send_message(message.chat.id, get_tl_and_map("⚠️ Maximum withdrawal is %max%.", lang).replace('%max%', str(w_max)))
            
        w_var = global_w_setup.get('w_var', 'balance')
        user_bal = user_db[user_id].get(w_var, 0)
        if amount > user_bal: return bot.send_message(message.chat.id, get_tl_and_map("❌ Insufficient funds. Your %balance_type% balance is %balance%.", lang).replace('%balance_type%', w_var).replace('%balance%', fmt_amt(user_bal)))
            
        user_action_data[user_id]['amount'] = amount
        
        if not global_w_setup.get('do_not_ask_address'):
            user_state[user_id] = 'w_action_addr'
            msg = global_w_setup.get('w_msg_addr') or "Please enter your withdrawal address:"
            bot.send_message(message.chat.id, replace_macros(get_tl_and_map(msg, lang), user_id, target_path, user_action_data[user_id]), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'w_action_conf'
            msg = global_w_setup.get('w_msg_conf') or "Are you sure you want to withdraw %withdraw% USDT via %network% to:\n<code>%address%</code>"
            bot.send_message(message.chat.id, replace_macros(get_tl_and_map(msg, lang), user_id, target_path, user_action_data[user_id]), parse_mode="HTML", reply_markup=get_withdrawal_conf_inline(lang))
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
        bot.send_message(message.chat.id, replace_macros(get_tl_and_map(msg, lang), user_id, target_path, user_action_data[user_id]), parse_mode="HTML", reply_markup=get_withdrawal_conf_inline(lang))
        return

    # --- GLOBAL FEATURE: Move by Command ---
    # Slash-style commands (e.g. /withdraw) assigned to a button. We do NOT
    # just navigate to the button's path — we simulate clicking it so all its
    # assigned features (withdrawal, wallet, bonus, balance, calculator, etc.)
    # actually fire. Otherwise typing /withdraw on a leaf "Withdraw" button
    # would only show its posts and never start the withdrawal flow.
    if state in ['normal', 'posts_editing']:
        matched_btn_path = None
        for path, meta in btn_metadata.items():
            if meta.get('move_by_command') and meta.get('command') == text:
                if meta.get('admin_only') and not is_admin:
                    return bot.send_message(message.chat.id, get_tl_and_map("⛔️ You do not have permission to use this button.", lang))
                matched_btn_path = path
                break

        if matched_btn_path:
            parts = matched_btn_path.split('/')
            btn_name = parts[-1]
            parent_path = '/'.join(parts[:-1]) or 'root'
            # Reposition the user at the parent so the regular button-click
            # logic below treats `text` as a button on the current page.
            user_current_path[user_id] = parent_path
            current_path = parent_path
            text = btn_name
            # Fall through to the normal button-click handler — do NOT return.

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
                bot.send_message(message.chat.id, replace_macros(get_tl_and_map(msg, lang), user_id, custom_btn_path), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
                return

            if meta.get('is_wallet') and state != 'posts_editing':
                # Bulk-prewarm the two strings we're about to translate so the
                # second get_tl_and_map() call hits cache instead of blocking.
                w_status = user_db[user_id].get('wallet', 'Not Set')
                inline_label_src = global_wallet_setup['inline_change'] if w_status != 'Not Set' else global_wallet_setup['inline_set']
                _bulk_prewarm({global_wallet_setup['msg_main'], inline_label_src}, lang)

                msg = replace_macros(get_tl_and_map(global_wallet_setup['msg_main'], lang), user_id, custom_btn_path)
                btn_text = get_tl_and_map(inline_label_src, lang)

                markup = InlineKeyboardMarkup()
                markup.row(InlineKeyboardButton(btn_text, callback_data='cb_wallet_start'))
                # Use safe-send so a malformed-HTML translation can't silently
                # 400 and leave the user staring at an unresponsive button.
                sent = _safe_send_media(bot.send_message, message.chat.id, msg,
                                        parse_mode='HTML', reply_markup=markup)
                if sent is None:
                    # Final fallback: send the English original so the user
                    # always sees the wallet panel even if Google glitched.
                    try:
                        en_msg = replace_macros(global_wallet_setup['msg_main'], user_id, custom_btn_path)
                        bot.send_message(message.chat.id, en_msg,
                                         parse_mode='HTML', reply_markup=markup)
                    except Exception as e:
                        print(f"wallet panel send error: {e}")
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
                    
                    msg = get_tl_and_map(global_bonus_setup['msg_success'], lang).replace('%bonus_amount%', str(global_bonus_setup['amount']))
                    bot.send_message(message.chat.id, replace_macros(msg, user_id, custom_btn_path), parse_mode="HTML")
                    
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
                    
                    msg = get_tl_and_map(global_bonus_setup['msg_fail'], lang).replace('%time_left%', time_str)
                    bot.send_message(message.chat.id, replace_macros(msg, user_id, custom_btn_path), parse_mode="HTML")
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
                    bot.send_message(message.chat.id, replace_macros(get_tl_and_map(fail_msg, lang), user_id, custom_btn_path), parse_mode="HTML", reply_markup=markup)
                else:
                    user_state[user_id] = 'wait_reinvest_amount'
                    bot.send_message(message.chat.id, get_tl_and_map("🔄 <b>Reinvest</b>\n\nAvailable Balance: $%avail%\nMinimum Investment: $%min%\n\nEnter the amount you wish to reinvest:", lang).replace('%avail%', fmt_amt(total_avail)).replace('%min%', fmt_amt(min_plan_amount)), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
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
    lang = get_user_lang(user_id)
    if plan_id not in bot_plans:
        return bot.answer_callback_query(call_id, get_tl_and_map("⚠️ Plan not found.", lang), show_alert=True)
        
    p_data = bot_plans[plan_id]
    
    if plan_id == 'plan0':
        invest_amount = p_data.get('bonus_amount', 50.0)
    elif invest_amount is None:
        invest_amount = p_data['min']

    if p_data.get('is_free', False) or plan_id == 'plan0':
        # --- FREE PLAN LOOPHOLE FIX ---
        if user_db[user_id].get('has_claimed_free_plan', False) or any(p['macro'] == plan_id for p in user_db[user_id].get('active_plans', [])):
            user_db[user_id]['has_claimed_free_plan'] = True # Lock it down permanently if they snuck in
            return bot.answer_callback_query(call_id, get_tl_and_map("❌ Access Denied: You have already claimed your one-time Free Plan!", lang), show_alert=True)
            
        user_db[user_id]['has_claimed_free_plan'] = True # Set flag to true immediately
        
        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': plan_id, 'amount': invest_amount,
            'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        notify_admin_plan_purchase(user_id, new_plan)
        log_tx(user_id, f"Activated Free {p_data['name']}", invest_amount)
        bot.answer_callback_query(call_id, get_tl_and_map("🎉 Success! Activated %plan_name% with $%amount% virtual capital!", lang).replace('%plan_name%', p_data['name']).replace('%amount%', fmt_amt(invest_amount)), show_alert=True)
        
        user_current_path[user_id] = 'root'
        send_path_content(chat_id, user_id, 'root', False)
        return
        
    u_dep = user_db[user_id].get('deposit', 0)
    u_bal = user_db[user_id].get('balance', 0)
    total_avail = u_dep + u_bal
    
    if total_avail < invest_amount:
        user_db[user_id]['pending_plan'] = plan_id
        bot.answer_callback_query(call_id, get_tl_and_map("⚠️ Insufficient funds! You need $%amount%.", lang).replace('%amount%', fmt_amt(invest_amount)), show_alert=True)
        
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
    _spend_trial_first(user_db[user_id], min(u_dep, invest_amount))
        
    log_tx(user_id, f"Bought {p_data['name']}", -invest_amount)
    
    new_plan = {
        'id': str(uuid.uuid4())[:8], 'macro': plan_id, 'amount': invest_amount,
        'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
        'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
    }
    user_db[user_id]['active_plans'].append(new_plan)
    notify_admin_plan_purchase(user_id, new_plan)
    
    bot.answer_callback_query(call_id, get_tl_and_map("🎉 Success! You invested $%amount% into %plan_name%! Profit is accruing automatically.", lang).replace('%amount%', fmt_amt(invest_amount)).replace('%plan_name%', p_data['name']), show_alert=True)
    try: bot.delete_message(chat_id, message_id)
    except Exception: pass
    
    user_current_path[user_id] = 'root'
    send_path_content(chat_id, user_id, 'root', False)

def execute_withdrawal_action(w_id, action, mode):
    """Shared approve/decline/ignore for the Telegram inline buttons AND the
    web dashboard's withdrawal panel. Pops the record atomically, performs the
    balance/email/notification side effects, stamps every stored admin alert
    message (removing the inline buttons), and persists the result.

    Returns (ok, detail_message)."""
    w_data = pending_withdrawals.pop(w_id, None)
    if w_data is None:
        return False, 'Withdrawal no longer pending or already handled.'

    target = w_data['user_id']
    amt = w_data['amount']
    w_var = w_data['currency_var']
    target_lang = get_user_lang(target)

    if action == 'app':
        stamp = f"✅ <b>APPROVED ({'Silent' if mode == 's' else 'Msg sent'})</b>"
        log_tx(target, "Withdrawal Approved", 0)

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
                # Translate TEMPLATE first (with macros intact), THEN replace
                # macros — otherwise the user's name/address would be sent
                # to Google and mangled in CJK/Arabic.
                msg = replace_macros(get_tl_and_map(msg_template, target_lang), target, w_data['path'], w_data)
                payout_markup = InlineKeyboardMarkup()
                btn_text = global_w_setup.get('payout_btn_text', '📜 View Receipt')
                payout_markup.row(InlineKeyboardButton(get_tl_and_map(btn_text, target_lang), callback_data='cb_payout_popup_alert'))
                try: bot.send_message(target, msg, parse_mode="HTML", reply_markup=payout_markup)
                except: pass

        pub_chat = global_w_setup.get('public_report')
        if pub_chat:
            try:
                pub_msg = f"💸 <b>SUCCESSFUL WITHDRAWAL</b> 💸\n\n👤 User: {user_db.get(target, {}).get('first_name', 'Unknown')}\n💰 Amount: {fmt_amt(amt)}\n🌐 Network: {w_data['network']}\n🔗 Address: {w_data['address'][:6]}...{w_data['address'][-4:]}"
                bot.send_message(pub_chat, pub_msg, parse_mode="HTML")
            except: pass

    elif action == 'dec':
        stamp = "❌ <b>DECLINED (Refunded to user)</b>"
        if target in user_db:
            user_db[target][w_var] = user_db[target].get(w_var, 0) + amt
            user_db[target]['total_withdrawn'] = max(0, user_db[target].get('total_withdrawn', 0.0) - amt)
            log_tx(target, "Withdrawal Refunded", amt)
        if mode == 'm':
            msg_template = global_w_setup.get('w_msg_decline')
            if msg_template:
                msg = replace_macros(get_tl_and_map(msg_template, target_lang), target, w_data['path'], w_data)
                try: bot.send_message(target, msg, parse_mode="HTML")
                except: pass

    elif action == 'ign':
        stamp = "🚫 <b>IGNORED (No Refund)</b>"
        if mode == 'm':
            msg_template = global_w_setup.get('w_msg_ignore')
            if msg_template:
                msg = replace_macros(get_tl_and_map(msg_template, target_lang), target, w_data['path'], w_data)
                try: bot.send_message(target, msg, parse_mode="HTML")
                except: pass
    else:
        # Unknown action — put it back so nothing is lost
        pending_withdrawals[w_id] = w_data
        return False, 'Unknown action.'

    # Stamp every admin alert copy we know about so no buttons linger anywhere
    alert_text = w_data.get('alert_text', 'Withdrawal request')
    for aid, mid in (w_data.get('admin_msgs') or {}).items():
        try:
            bot.edit_message_text(f"{alert_text}\n\n{stamp}", int(aid), int(mid),
                                  parse_mode="HTML", reply_markup=None)
        except Exception:
            try: bot.edit_message_reply_markup(int(aid), int(mid), reply_markup=None)
            except Exception: pass

    save_database()
    return True, 'Action executed successfully.'


# --- INLINE BUTTON LOGIC ---
@bot.callback_query_handler(func=lambda call: True)
def handle_inline(call):
    user_id = call.from_user.id
    current_path = user_current_path.get(user_id, 'root')
    target_btn = user_selected_button.get(user_id)
    is_admin = user_id in ADMIN_IDS
    lang = get_user_lang(user_id)
    
    global pending_withdrawals

    if user_id in blocked_users:
        bot.answer_callback_query(call.id, get_tl_and_map("🚫 You are currently blocked.", lang), show_alert=True)
        return

    # --- PAYOUT POPUP RECEIPT LOGIC ---
    if call.data == 'cb_payout_popup_alert':
        popup_msg = global_w_setup.get('payout_popup_msg', 'Payment Success!')
        return bot.answer_callback_query(call.id, get_tl_and_map(popup_msg, lang), show_alert=True)

    # --- NEW ARCHITECTURE: THE INTERCEPTOR (INLINE GATEWAY) ---
    if requires_subscription_wall(user_id, False) and call.data != 'cb_verify_sub':
        bot.answer_callback_query(call.id, get_tl_and_map("🚨 Please verify your subscription first.", lang), show_alert=True)
        return
        
    # --- NEW ARCHITECTURE: HOMEPAGE POPUP GATEWAY ---
    if call.data == 'cb_claim_homepage':
        if user_db[user_id].get('has_seen_homepage', False):
            bot.answer_callback_query(call.id, get_tl_and_map("⚠️ Already claimed.", lang), show_alert=True)
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            return
            
        p_data = bot_plans.get('plan0', {})
        if not p_data: return bot.answer_callback_query(call.id, get_tl_and_map("Plan 0 not configured.", lang), show_alert=True)
            
        invest_amt = p_data.get('bonus_amount', 50.0)
            
        new_plan = {
            'id': str(uuid.uuid4())[:8], 'macro': 'plan0', 'amount': invest_amt,
            'profit_pct': p_data['profit'], 'length_hours': p_data.get('length', 0),
            'start_time': time.time(), 'last_accrual': time.time(), 'earned': 0.0, 'status': 'active'
        }
        user_db[user_id]['active_plans'].append(new_plan)
        notify_admin_plan_purchase(user_id, new_plan)
        log_tx(user_id, "Claimed Homepage Bonus", invest_amt)
            
        user_db[user_id]['has_seen_homepage'] = True
            
        # --- THE UI GLITCH FIX (Homepage): Strip the buttons before deleting ---
        try: 
            bot.edit_message_text(f"🎉 <b>Success! You claimed ${fmt_amt(invest_amt)} capital!</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            time.sleep(0.5)
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
            
        bot.answer_callback_query(call.id, get_tl_and_map("🎉 Success! You claimed $%amount% capital!", lang).replace('%amount%', fmt_amt(invest_amt)), show_alert=True)
            
        # THE MAGIC TRIGGER: USER CLEARED THE FINAL GATE
        finalize_user_registration(user_id)
            
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal'
        send_path_content(call.message.chat.id, user_id, 'root', is_editing=False, reply_keyboard=get_keyboard(user_id))
        return

    # --- FREE TRIAL CASH: CLAIM BUTTON ---
    if call.data.startswith('claim_trial_'):
        offer_id = call.data[len('claim_trial_'):]
        offer = free_offers.get(offer_id)
        if not offer:
            return bot.answer_callback_query(call.id, get_tl_and_map("⚠️ This offer is no longer available.", lang), show_alert=True)

        claim_key = f"{offer_id}_{user_id}"
        if claim_key in free_trial_claims:
            return bot.answer_callback_query(call.id, get_tl_and_map("⚠️ You already claimed this offer.", lang), show_alert=True)
        if user_id not in user_db:
            return bot.answer_callback_query(call.id, "Account not found.", show_alert=True)

        amount = float(offer['amount'])
        days = offer['expires_days']
        now = time.time()
        user_db[user_id]['deposit'] = user_db[user_id].get('deposit', 0.0) + amount
        user_db[user_id]['trial_credit'] = user_db[user_id].get('trial_credit', 0.0) + amount
        free_trial_claims[claim_key] = {
            'uid': user_id, 'offer_id': offer_id, 'amount': amount,
            'claim_time': now, 'expiry_time': now + days * 86400,
            'last_reminder': now,
            'status': 'claimed'
        }
        log_tx(user_id, "Free Trial Claim", amount)
        save_database()

        try:
            done_msg = get_tl_and_map(_ft_fill(free_trial_settings.get('msg_claimed', ''), amount, days), lang)
            try:
                bot.edit_message_text(done_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
            except Exception:
                bot.edit_message_caption(done_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=None)
        except Exception: pass

        bot.answer_callback_query(call.id, get_tl_and_map("🎉 $%amount% claimed!", lang).replace('%amount%', fmt_amt(amount)), show_alert=True)

        for admin in ADMIN_IDS:
            try:
                bot.send_message(admin, f"🎁 <b>FREE TRIAL CLAIMED</b>\nUser: <code>{user_id}</code> (@{user_db[user_id].get('username', '?')})\nAmount: ${fmt_amt(amount)}\nExpires: in {days} days", parse_mode="HTML")
            except Exception: pass
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
            
            loading_msg = bot.send_message(call.message.chat.id, get_tl_and_map("⏳ <b>Generating Unique Link...</b>\n%bar%", lang).replace('%bar%', bars[0]), parse_mode="HTML")
            for bar in bars[1:]:
                time.sleep(0.4)
                try: bot.edit_message_text(get_tl_and_map("⏳ <b>Generating Unique Link...</b>\n%bar%", lang).replace('%bar%', bar), call.message.chat.id, loading_msg.message_id, parse_mode="HTML")
                except: pass
                
            try: bot.delete_message(call.message.chat.id, loading_msg.message_id)
            except: pass
            
        # IMPORTANT: translate the label only; the link itself must NEVER
        # pass through the translator (it would be mangled in CJK / Arabic).
        bot.send_message(call.message.chat.id, get_tl_and_map("✅ <b>Your Unique Referral Link:</b>\n\n%link%", lang).replace('%link%', ref_link), parse_mode="HTML")
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
            
            target_lang = get_user_lang(target_id)
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

        if w_id not in pending_withdrawals:
            # Expired or already handled — strip the buttons so it can't be pressed again
            try:
                bot.edit_message_text(f"{call.message.text}\n\n⏰ <b>EXPIRED / ALREADY HANDLED</b>",
                                      call.message.chat.id, call.message.message_id,
                                      parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
            return bot.answer_callback_query(call.id, "Withdrawal no longer pending or expired.", show_alert=True)

        # Register the pressing admin's message so it gets updated alongside
        # every other admin's copy of this alert.
        pw = pending_withdrawals.get(w_id)
        if pw is not None:
            pw.setdefault('admin_msgs', {})[str(call.message.chat.id)] = call.message.message_id

        ok, detail = execute_withdrawal_action(w_id, action, mode)
        return bot.answer_callback_query(call.id, detail, show_alert=not ok)

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
        
        scan_msg = bot.send_message(call.message.chat.id, get_tl_and_map("⏳ <b>Checking Blockchain...</b>\n%bar%", lang).replace('%bar%', '[▯▯▯▯▯▯▯▯▯▯] 0%'), parse_mode="HTML")
        
        for bar in bar_styles:
            time.sleep(0.4) 
            try: bot.edit_message_text(get_tl_and_map("⏳ <b>Checking Blockchain...</b>\n%bar%", lang).replace('%bar%', bar), call.message.chat.id, scan_msg.message_id, parse_mode="HTML")
            except: pass

        found_deposit, crypto_amount, txid_found, _ = check_address_for_new_deposit(addr, curr)

        if found_deposit:
            live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
            usd_value = crypto_amount * live_price

            c_min = deposit_settings.get(curr, {}).get('min', 0.0)
            if usd_value < c_min:
                try: bot.send_message(call.message.chat.id, get_tl_and_map("⚠️ Deposit detected but below the minimum. Minimum deposit is <b>$%min% USD</b>.", lang).replace('%min%', fmt_amt(c_min)), parse_mode="HTML")
                except: pass
                try: bot.delete_message(call.message.chat.id, scan_msg.message_id)
                except: pass
                return

            processed_txids.add(txid_found)
            pending_auto_txids.pop(txid_found, None)

            user_db[user_id]['deposit'] += usd_value
            user_db[user_id]['wallets'][curr]['total_deposited'] = user_db[user_id]['wallets'][curr].get('total_deposited', 0.0) + usd_value
            log_tx(user_id, f"Deposit ({curr})", usd_value)

            # Sync the watcher's high-water mark so this deposit can never be
            # credited a second time by the automatic balance watcher.
            try:
                onchain_now = get_onchain_balance(addr, curr)
                w_sync = user_db[user_id]['wallets'][curr]
                if onchain_now is not None:
                    w_sync['credited_crypto'] = onchain_now
                else:
                    w_sync['credited_crypto'] = w_sync.get('credited_crypto', 0.0) + crypto_amount
                w_sync.pop('pending_credit', None)
            except Exception:
                pass
            
            process_referral_commission(user_id, usd_value, is_deposit=True) 
            
            admin_msg = f"🟢 <b>DEPOSIT CONFIRMED (MANUAL)</b>\nUser: <code>{user_id}</code>\nCurrency: {curr.replace('_', ' ')}\nCrypto Amount: {fmt_amt(crypto_amount)}\nUSD Credited: ${fmt_amt(usd_value)}\nHash (TXID): <code>{txid_found}</code>"
            for admin in ADMIN_IDS:
                try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                except Exception: pass
                
            check_and_trigger_auto_buy(user_id)
            
            # --- LIVE CHANNEL HOOK ---
            broadcast_real_deposit(user_id, usd_value, crypto_amount, curr, txid_found)
            
            try: bot.send_message(call.message.chat.id, get_tl_and_map("✅ <b>Deposit Successful!</b>\nAmount: %crypto% %currency%\nCredited: $%usd%", lang).replace('%crypto%', fmt_amt(crypto_amount)).replace('%currency%', curr.split('_')[0]).replace('%usd%', fmt_amt(usd_value)), parse_mode="HTML")
            except: pass
            
        else:
            try: bot.send_message(call.message.chat.id, get_tl_and_map("⏳ <b>Pending:</b> Your transaction is still waiting for blockchain confirmation. Please wait a moment and click Confirm again.", lang), parse_mode="HTML")
            except: pass
            
        try: bot.delete_message(call.message.chat.id, scan_msg.message_id)
        except: pass
        return

    if call.data == 'cb_wallet_start':
        bot.answer_callback_query(call.id)
        # Prewarm both possible prompts so the next get_tl_and_map() is instant.
        _bulk_prewarm({global_wallet_setup.get('msg_email_prompt', ''),
                       global_wallet_setup.get('msg_prompt', '')}, lang)
        if global_wallet_setup.get('ask_email') and user_db[user_id].get('email', 'Not Set') == 'Not Set':
            user_state[user_id] = 'wallet_wait_email'
            prompt_src = global_wallet_setup.get('msg_email_prompt', '✏️ Please enter your Email address:')
            prompt_tl = get_tl_and_map(prompt_src, lang)
            sent = _safe_send_media(bot.send_message, call.message.chat.id, prompt_tl,
                                    reply_markup=get_cancel_action_keyboard())
            if sent is None:
                bot.send_message(call.message.chat.id, prompt_src,
                                 reply_markup=get_cancel_action_keyboard())
        else:
            user_state[user_id] = 'wallet_wait_address'
            prompt_src = global_wallet_setup.get('msg_prompt', '✏️ Send your wallet address:')
            prompt_tl = get_tl_and_map(prompt_src, lang)
            sent = _safe_send_media(bot.send_message, call.message.chat.id, prompt_tl,
                                    parse_mode="HTML",
                                    reply_markup=get_cancel_action_keyboard())
            if sent is None:
                bot.send_message(call.message.chat.id, prompt_src,
                                 parse_mode="HTML",
                                 reply_markup=get_cancel_action_keyboard())
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
        chat_id = call.message.chat.id

        # Reset to root so the user always lands on a known, valid page after
        # switching language (avoids stale state from the language menu).
        user_current_path[user_id] = 'root'
        user_state[user_id] = 'normal'

        # 1. SYNCHRONOUSLY translate the root-page strings + reply keyboard
        # + the popup label before we answer the callback. This is what
        # guarantees the user never sees English flash on the first switch.
        # The batch endpoint sends all strings in ONE HTTP request so total
        # wall-clock is ~300-1500ms even for fresh languages. Subsequent
        # visits hit TL_CACHE → instant. Telegram allows up to ~10s before
        # the callback times out, so a 4s cap is safely within budget.
        try:
            root_strings = _collect_path_strings('root')
            # Also include the main reply keyboard labels (Balance, Admin,
            # 🏠 Home, 🔙 Back, etc.) so the keyboard appears fully translated.
            kb = get_keyboard_raw(user_id)
            if kb:
                for row in kb.keyboard:
                    for btn in row:
                        if btn.get('text'):
                            root_strings.add(btn['text'])
            # Always include the success popup string so the native alert
            # below is already cached and renders in the target language.
            root_strings.add("✅ Language updated!")
            _bulk_prewarm(root_strings, target_lang, timeout=4.0)
        except Exception as e:
            print(f"language sync prewarm error: {e}")

        # 2. Native Telegram alert popup (with OK button) — instant feedback
        # in the user's new language. The language-selection MESSAGE itself
        # stays in place so its title remains visible above the new main menu.
        try:
            bot.answer_callback_query(
                call.id,
                get_tl_and_map("✅ Language updated!", target_lang),
                show_alert=True,
            )
        except Exception:
            pass

        # 3. Render the main menu — every visible string is now cached.
        try:
            send_path_content(chat_id, user_id, 'root', is_editing=False,
                              reply_keyboard=get_keyboard(user_id))
        except Exception as e:
            print(f"language initial render error: {e}")

        # 4. Background prewarm of ALL remaining UI strings so future pages
        # (deposit, withdraw, plans, history…) are instant when navigated to.
        def _bg_prewarm_full(uid=user_id, tlang=target_lang):
            try:
                prewarm_language(tlang, timeout=30.0)
            except Exception as e:
                print(f"prewarm_language background error: {e}")

        threading.Thread(target=_bg_prewarm_full, daemon=True).start()
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
            bot.answer_callback_query(call.id, get_tl_and_map("⚠️ Insufficient balance. You need at least $%min%.", lang).replace('%min%', fmt_amt(p_data['min'])), show_alert=True)
            
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
        bot.send_message(call.message.chat.id, get_tl_and_map("📈 <b>%plan_name%</b>\nMin: $%min% | Max: $%max%\n\nAvailable Balance: $%avail%\n\nEnter the amount you wish to invest:", lang).replace('%plan_name%', p_data['name']).replace('%min%', fmt_amt(p_data['min'])).replace('%max%', fmt_amt(p_data['max'])).replace('%avail%', fmt_amt(total_avail)), parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
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

            # Keep the wallet's ledger in sync so the balance watcher can never
            # re-credit this deposit as a phantom new one.
            w_sync = user_db[target].get('wallets', {}).get(curr)
            if w_sync:
                w_sync['total_deposited'] = w_sync.get('total_deposited', 0.0) + amt
                try:
                    onchain_now = get_onchain_balance(w_sync.get('address'), curr)
                    if onchain_now is not None:
                        w_sync['credited_crypto'] = onchain_now
                except Exception:
                    pass
                w_sync.pop('pending_credit', None)
            
            process_referral_commission(target, amt, is_deposit=True) 
            
            msg_success = conf.get('msg_success', "✅ <b>Deposit Approved!</b>\n<b>$%usd_amount%</b> has been successfully added to your deposit balance.")
            msg_success = msg_success.replace('%usd_amount%', f"{fmt_amt(amt)}").replace('%crypto_amount%', '')
            target_lang = get_user_lang(target)
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
            target_lang = get_user_lang(target)
            bot.send_message(target, get_tl_and_map("❌ <b>Deposit Rejected</b>\nYour deposit request for <b>$%amount%</b> could not be verified.", target_lang).replace('%amount%', fmt_amt(dep['amount'])), parse_mode="HTML")
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
        suffix = call.data.replace('cb_dep_', '', 1)
        btn_id = suffix.split('_')[0]
        curr = None
        if suffix in deposit_settings:
            curr = suffix
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
            bot.send_message(call.message.chat.id, f"Send the new message (text, photo, video, GIF, or document):\n\nℹ️ <b>Current Text:</b>\n\n{curr_txt}", parse_mode="HTML", reply_markup=get_cancel_action_keyboard())
            
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
            raw_text = replace_macros(get_tl_and_map(proc_msg, lang), user_id, data['path'], data)
            
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
            
            admin_alert = (
                f"🚨 <b>NEW WITHDRAWAL REQUEST</b> 🚨\n\n"
                f"👤 User: <code>{user_id}</code> (@{call.from_user.username or 'None'})\n"
                f"💰 Requested: <b>{fmt_amt(amount)}</b>\n"
                f"💸 Final (after {comm_pct}% comm): <b>{fmt_amt(final_amt)}</b>\n"
                f"🔗 Address: <code>{addr}</code>\n"
                f"🌐 Network: {net}\n"
                f"🗃 Variable: {w_var}"
            )

            pending_withdrawals[w_id] = {
                'user_id': user_id, 'amount': amount, 'final_amt': final_amt,
                'address': addr, 'network': net, 'currency_var': w_var,
                'path': data['path'], 'alert_text': admin_alert,
                'admin_msgs': {}, 'ts': time.time()
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

            for admin in ADMIN_IDS:
                try:
                    sent = bot.send_message(admin, admin_alert, parse_mode="HTML", reply_markup=adm_markup)
                    pending_withdrawals[w_id]['admin_msgs'][str(admin)] = sent.message_id
                except: pass
            save_database()

            send_admin_push('🚨 Withdrawal Request',
                            f"{fmt_amt(amount)} from user {user_id} · {net} — tap to review",
                            '/#requests', tag=f'wad_{w_id}')

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

# --- FREE TRIAL CASH: SEND / CLAIM / EXPIRE ENGINE ---
def _ft_fill(tpl, amount, days=0, days_left=None):
    """Fill {amount}, {days} and {days_left} variables in a free-trial template."""
    out = (tpl or '').replace('{amount}', fmt_amt(amount)).replace('{days}', str(days))
    if days_left is not None:
        out = out.replace('{days_left}', str(days_left))
    return out

def send_free_trial_offer(uid, offer):
    """Send one free-trial offer to a user: text (or photo+caption) with a
    'Claim' inline button that credits the cash when clicked."""
    amount = offer['amount']
    days = offer['expires_days']
    lang = get_user_lang(uid)
    text = get_tl_and_map(_ft_fill(free_trial_settings.get('msg_offer', ''), amount, days), lang)
    btn_text = _ft_fill(free_trial_settings.get('button_text', '🎁 Claim ${amount} Free Cash'), amount, days)
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton(btn_text, callback_data=f"claim_trial_{offer['id']}"))
    img_b64 = offer.get('image_b64', '')
    img_url = offer.get('image_url', '')
    if img_b64:
        # Admin uploaded an image file — send it as a Telegram photo upload.
        payload = img_b64.split(',', 1)[1] if ',' in img_b64 else img_b64
        photo = io.BytesIO(base64.b64decode(payload))
        photo.name = 'offer.jpg'
        bot.send_photo(uid, photo, caption=text, parse_mode="HTML", reply_markup=markup)
    elif img_url:
        bot.send_photo(uid, img_url, caption=text, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(uid, text, parse_mode="HTML", reply_markup=markup)

def sweep_free_trial_claims_once():
    """One pass over all trial claims: sends the daily reminder for active
    claims and expires overdue ones — removing only the unspent trial money."""
    now = time.time()
    for ckey, claim in list(free_trial_claims.items()):
        if claim.get('status') != 'claimed':
            continue
        expiry = claim.get('expiry_time', 0)
        uid = claim.get('uid')
        amount = claim.get('amount', 0.0)

        if now >= expiry:
            # EXPIRED: remove the unspent remainder and alert the user.
            claim['status'] = 'expired'
            if uid in user_db:
                cur = user_db[uid].get('deposit', 0.0)
                # Only take back trial money still sitting unspent in the
                # deposit pool — never the user's real funds, and never trial
                # cash already spent into plans.
                removed = min(amount, user_db[uid].get('trial_credit', 0.0), cur)
                user_db[uid]['deposit'] = cur - removed
                user_db[uid]['trial_credit'] = max(0.0, user_db[uid].get('trial_credit', 0.0) - removed)
                claim['removed'] = removed
                if removed > 0:
                    log_tx(uid, "Free Trial Expired", -removed)
                try:
                    lang = get_user_lang(uid)
                    msg = _ft_fill(free_trial_settings.get('msg_expired', ''), removed)
                    bot.send_message(uid, get_tl_and_map(msg, lang), parse_mode="HTML")
                except Exception: pass
            continue

        # DAILY REMINDER: one per 24h while the claim is active.
        if now - claim.get('last_reminder', claim.get('claim_time', now)) >= 86400:
            claim['last_reminder'] = now
            if uid in user_db:
                days_left = int((expiry - now + 86399) // 86400) or 1
                try:
                    lang = get_user_lang(uid)
                    msg = _ft_fill(free_trial_settings.get('msg_reminder', ''), amount, days_left=days_left)
                    bot.send_message(uid, get_tl_and_map(msg, lang), parse_mode="HTML")
                except Exception: pass


def free_trial_expiry_loop():
    """Background loop for free-trial cash. Every 24h after a claim the user
    gets a reminder with the days remaining; when the countdown ends, the
    unspent remainder is removed and the user gets an expiry alert."""
    while True:
        try:
            sweep_free_trial_claims_once()
            save_database()
        except Exception as e:
            print(f"Free Trial Expiry Error: {e}")
        time.sleep(60)

# ===================== PWA — installable app + Web Push ======================
# The dashboard is installable (iOS "Add to Home Screen" / Android PWA); once
# installed, send_admin_push() reaches it even when the page is closed.
PWA_MANIFEST = json.dumps({
    "name": "G-Force Admin",
    "short_name": "G-Force",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0f2027",
    "theme_color": "#0f2027",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ],
})

PWA_SW = r"""
const CACHE = 'gf-admin-v1';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('push', e => {
    let d = { title: 'G-Force Admin', body: '', url: '/' };
    try { if (e.data) d = Object.assign(d, e.data.json()); } catch (_) {}
    e.waitUntil(self.registration.showNotification(d.title, {
        body: d.body, tag: d.tag || 'gf', icon: '/icon.png', badge: '/icon.png',
        data: { url: d.url || '/' }, renotify: true
    }));
});
self.addEventListener('notificationclick', e => {
    e.notification.close();
    const url = (e.notification.data && e.notification.data.url) || '/';
    e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
        for (const c of list) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
        return clients.openWindow(url);
    }));
});
"""

# 512x512 app icon (dark bg + bolt) — see also /icon-192.png for the manifest
PWA_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIACAIAAAB7GkOtAAAIH0lEQVR42u3WQRGEQBAEQRxggR/eMQkmeHVlRCoY7rr2OK8bgKDD"
    "CQAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAEAAABAEAAABAA"
    "AAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAEwBUABAAAAQBAAAAQAAAEAAABAEAA"
    "ABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAA"
    "EAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAABMAVAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEA"
    "QAAAEAAABAAAAQBAAAAQAAAEAAABgN//SM/rCAgACAAIAGTWXwAQABAAEAAorb8AIAAQXX8BQADA8x8EADz/QQBAAEAAYHD9BQAB"
    "AAEAAYDS+gsAAgACAAIApfUXAAQAPP9BAMDzHwQABAAEAAbXXwAQAIiuvwAgACAAIABQWn8BQABAAEAAoLT+AoAAgOc/CAB4/oMA"
    "gACAAMDg+gsAAgACAAIApfUXAAQABAAEAErrLwAIAAgACABYfxAA2F5/AUAAQABAAKC0/gKAAIAAgABAaf0FAAEAAQABgNL6CwAC"
    "AAIAAgDWHwQABAAEAAbXXwAQABAAEAAorb8AIAAQXX8BQABAAEAAoLT+AoAAgACAAID1BwEAAQABgMH1FwAEAAQABABK6y8ACAAI"
    "AAgAlNZfABAAEAAQALD+IAAgACAAMLj+AoAAQHT9BQABAAEAAYDS+gsAAgACAAIApfUXAAQABAAEAKw/CAAIAAgADK6/ACAAIAAg"
    "AFBafwFAAEAAQACgtP4CgABAdP0FAAEAAQABAOsPAgACAAIAg+svAAgACAAIAJTWXwAQABAAEAAorb8AIAAgACAAUFp/AUAAwPMf"
    "BAA8/0EAQABAAGBw/QUAAYDo+gsAAgACAAIApfUXAAQABAAEAErrLwAIAHj+gwCA5z8IAAgACAAMrr8AIAAgACAAUFp/AUAAQABA"
    "AKC0/gKAAID1BwEAAQABgO31FwAEAAQABABK6y8ACAAIAAgAlNZfABAAEAAQACitvwAgAOD5DwIAnv8gACAAIAAwuP4CgACAAIAA"
    "QGn9BQABgOj6CwACAAIAAgCl9RcABAA8/0EAwPMfBADmAyBOCABYfwFAAEAArD8CANbf+iMAIAACgACA9bf+CAAIgAAgAGD9rT8C"
    "gJ+dKRcABAABwPojAFh/BAABQACw/ggA1h/rjwAgAAIAAoD1t/4gAAiAAIAAYP2tPwgAAiAAIABYf+sPAoAAWH8QAKy/AOC/6QQI"
    "gPVHAMD6CwACANbf+iMAIAACgACA9bf+CAAIgAAgAGD9rT8CAAJg/REArD8CgAAgAFh/BADrjwAgAAgA1h8BwPoLAAgA5ELlcyAA"
    "UAyAb4EAgACAAEAmAD4EAgCe/yAA4PkPAgACAAIAawHwFRAAEAAQALD+IAAwHACfAAEAAQABgEwA3B8BAAEAAYBMABwfAQDPfxAA"
    "8PwHAYDhALg8AgACAAIAmQA4OwIAnv8gAOD5DwIAAgACAGsBcHMEAAQABAAyAXBwBACsPwgACAAIAAwHwLURABAAEADIBMCpEQDw"
    "/AcBAM9/EAAYDoA7IwAgACAAkAmAIyMAIAAgAGD9QQBAAEAAYC0ALowAgACAAEAmAM6LAID1BwEAAQABgOEAuC0CAAIAAgCZADgs"
    "AgACAAIA1h8EAIYD4KoIAAgACABkAuCkCAAIAAgAWH8QABAAEABYC4B7IgAgACAAkAmAYyIAUAyASyIA4PkPAgCe/yAAIAAgALAW"
    "AGdEAEAAQADA+oMAwHAA3BABAAEAAYBMABwQAQABAAGATABcDwEAz38QAPD8BwEAAQABgLUAOB0CAMUAuBsCAJ7/IADg+Q8CAAIA"
    "AgBrAXA0BAAEAAQAMgFwMQTAFbD+IAAgACAAMBwA5wIBQABAACATALcCAcDzHwQAPP9BAEAAQABgLQAOBQJAMQCuBAKAAAACgPUH"
    "AQABAAGAtQA4EQgAAgAIAJkAuA8IANYfEAAEABAAhgPgOCAACAAgAGQC4DIgAAgAIABYf0AAEABAAFgLgLOAAFAMgJuAACAAgABg"
    "/QEBQAAAAWAtAA4CAoAAAAJAJgCuAQJAMQBOAQKA5z8gAHj+AwKAAAACwFoA3AEEAAEABADrDwgAAgAIAGsBcAQQAAAEAAABAEAA"
    "ABAAAAQAAAEAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAEAAA"
    "BAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAEAAnABAAAAQAAAEAQAAA"
    "EAAABAAAAQBAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQ"
    "AAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBAAAAQAAAEAAABABAAVwAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAAAAQBA"
    "AAAQAAAEAAABAEAAAPjFBw84LYD7So+lAAAAAElFTkSuQmCC"
)
PWA_ICON_192_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAIAAADdvvtQAAACJElEQVR42u3dsQ2DQBREweuAFsjonSahAaK7YDntSK+Cr9EGtjHj"
    "OC9puuEEAkgACSABJAEkgASQAJIAEkACSABJAAkgASSAJIAEkAASQAJIAkgACSABJAEkgASQAJIAEkACSABJAAkgASSABJAEkAAS"
    "QAJIAkgA/fxw9+MIAAEEUEgPQAABBFBOD0AAAQRQTg9AAJkfgMwPQDvqAQgggADK6QEIIIAAyukBCCCAAMrpAQgg8wOQ+QEIIIDq"
    "9AAEEEAA5fQABNCSHoAAAgignB6AADI/AJkfgAACqE4PQAABBFBOD0AAAQRQTg9AAJkfgMwPQAABVKcHIICW9AAEEEAA5fQABBBA"
    "AOX0AASQ+QHI/AAEEEB1elYCCCCAAKIHIIAAogcgeugBCCCA6AEIIIDoaf7MGiCAAKIHIL/6AAigxm/sAfLQD0DmByDzAxBAAMkz"
    "8wABBBA9APnLKYAAAgggf/kLEEAAeecBQPQABJD5AQgggLxzDiCvbBZA5gcg8wMQQACVAHIcgAACKATIZQCiByCAANoOkLMABBBA"
    "IUBuApD5Acj8AAQQQF2AHASgeUCuARBAANEDEEAAdQFyCoAAAigEyB0AogcggADaDpAjAAQQQAJIAEkACSABJIAkgASQABJAEkAC"
    "SAAJIAHkCgJIAAkgASQBJIAEkACSABJAAkgASQAJIAEkgCSABJAAEkACSAJIAAkgASQBJIAEkACSvnsBa8xYTRQu8XoAAAAASUVO"
    "RK5CYII="
)


# --- NEW: LIGHTWEIGHT WEB SERVER FOR ADMIN DASHBOARD & UPTIMEROBOT ---
class AdminDashboardHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        p = parsed_path.path
        if p == '/':
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
        elif p == '/manifest.json':
            body = PWA_MANIFEST.encode()
            self.send_response(200)
            self.send_header('Content-type', 'application/manifest+json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == '/sw.js':
            # Service worker MUST be served as JS from the root to get '/' scope
            body = PWA_SW.encode()
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript')
            self.send_header('Service-Worker-Allowed', '/')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p in ('/icon.png', '/icon-192.png'):
            body = base64.b64decode(PWA_ICON_B64 if p == '/icon.png' else PWA_ICON_192_B64)
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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

        # --- NEW: AUTO-APPROVE TIMER API ---
        elif parsed_path.path == '/api/get_auto_approve':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'delay_seconds': auto_approve_settings.get('delay_seconds', 300)}).encode())

        elif parsed_path.path == '/api/save_auto_approve':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                delay = int(data.get('delay_seconds'))
                if delay < 0:
                    raise ValueError("Delay cannot be negative")
                auto_approve_settings['delay_seconds'] = delay
                save_database()
                print(f"⏱️ Dashboard Action: Auto-approve delay set to {delay} seconds")
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'delay_seconds': delay}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- NEW: KEY VAULT (ALL GENERATED WALLETS + KEYS + LIVE BALANCES) ---
        elif parsed_path.path == '/api/all_wallets':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return

            users_out = []
            grand_total_usd = 0.0
            for uid, udata in user_db.items():
                wallets = udata.get('wallets', {})
                if not wallets:
                    continue

                username = udata.get('username', str(uid))
                first_name = udata.get('first_name', 'Unknown')
                if username and username != 'No Username':
                    display_name = f"{first_name} (@{username})"
                else:
                    display_name = f"{first_name}"

                wlist = []
                for curr, wdata in wallets.items():
                    live_bal = wdata.get('live_balance')
                    credited = wdata.get('credited_crypto')
                    uncredited = None
                    if live_bal is not None and credited is not None:
                        uncredited = max(0.0, live_bal - credited)

                    live_price = get_crypto_price(curr) if 'USDT' not in curr else 1.0
                    if live_bal is not None:
                        grand_total_usd += live_bal * live_price

                    wlist.append({
                        'network': curr.replace('_', ' '),
                        'network_raw': curr,
                        'address': wdata.get('address', 'Not Set'),
                        'private_key': wdata.get('private_key', 'Not Found'),
                        'symbol': curr.split('_')[0],
                        'live_balance': live_bal,
                        'live_balance_ts': wdata.get('live_balance_ts'),
                        'uncredited': uncredited,
                        'credited_usd': wdata.get('total_deposited', 0.0),
                        'swept_usd': wdata.get('admin_swept_total', 0.0),
                    })

                users_out.append({
                    'uid': uid,
                    'name': display_name,
                    'wallets': wlist,
                })

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'users': users_out, 'grand_total_usd': grand_total_usd}).encode())

        # --- NEW: LIVE REFRESH OF A SINGLE WALLET BALANCE (on-demand read) ---
        elif parsed_path.path == '/api/refresh_balance':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                uid = int(data.get('uid'))
                network = str(data.get('network', '')).replace(' ', '_')
                wdata = user_db.get(uid, {}).get('wallets', {}).get(network)
                if not wdata:
                    raise ValueError("Wallet not found")

                bal = get_onchain_balance(wdata.get('address'), network)
                if bal is None:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': False, 'error': 'All free providers busy, try again'}).encode())
                    return

                wdata['live_balance'] = bal
                wdata['live_balance_ts'] = time.time()
                credited = _credited_baseline(wdata, network, bal)
                uncredited = max(0.0, bal - credited)

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'live_balance': bal,
                    'uncredited': uncredited,
                    'symbol': network.split('_')[0],
                }).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- NEW: MANUAL CREDIT (credit whatever the chain currently shows) ---
        elif parsed_path.path == '/api/manual_credit':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                uid = int(data.get('uid'))
                network = str(data.get('network', '')).replace(' ', '_')
                wdata = user_db.get(uid, {}).get('wallets', {}).get(network)
                if not wdata:
                    raise ValueError("Wallet not found")

                # Determine how much to credit: an explicit amount if provided,
                # otherwise the uncredited on-chain delta detected live.
                bal = get_onchain_balance(wdata.get('address'), network)
                if bal is None:
                    raise ValueError("Could not read on-chain balance right now, try again")
                wdata['live_balance'] = bal
                wdata['live_balance_ts'] = time.time()
                baseline = _credited_baseline(wdata, network, bal)

                amt_raw = data.get('amount')
                if amt_raw not in (None, ''):
                    credit_amt = float(amt_raw)
                else:
                    credit_amt = max(0.0, bal - baseline)

                if credit_amt <= BALANCE_EPSILON:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'success': False, 'error': 'Nothing new to credit (balance already credited).'}).encode())
                    return

                usd = credit_deposit(uid, network, credit_amt, txid="MANUAL", is_manual=True)
                # Rebase the high-water mark so the watcher won't re-credit it.
                wdata['credited_crypto'] = max(bal, baseline + credit_amt)
                wdata.pop('pending_credit', None)
                save_database()

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'credited_crypto': credit_amt, 'credited_usd': usd}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- NEW: USER ACCOUNT LOOKUP (balances + active plan deposits) ---
        elif parsed_path.path == '/api/get_account':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                uid = int(data.get('uid'))
                u = user_db.get(uid)
                if not u:
                    self.send_response(404)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'User not found'}).encode())
                    return

                now = time.time()
                plans_out = []
                total_invested = 0.0
                for p in u.get('active_plans', []):
                    if p.get('status') != 'active':
                        continue
                    p_data = bot_plans.get(p.get('macro'), {})
                    secs_left = None
                    if p.get('length_hours', 0) > 0:
                        secs_left = max(0, (p.get('start_time', now) + p['length_hours'] * 3600) - now)
                    amt = p.get('amount', 0.0)
                    total_invested += amt
                    plans_out.append({
                        'id': p.get('id'),
                        'name': p_data.get('name', p.get('macro', 'Plan')),
                        'macro': p.get('macro'),
                        'amount': amt,
                        'profit_pct': p.get('profit_pct', 0.0),
                        'earned': p.get('earned', 0.0),
                        'length_hours': p.get('length_hours', 0),
                        'time_left_sec': secs_left,
                        'status': p.get('status'),
                    })

                username = u.get('username', str(uid))
                first_name = u.get('first_name', 'Unknown')
                display_name = f"{first_name} (@{username})" if username != 'No Username' else first_name
                pending = u.get('pending_plan')
                pending_name = bot_plans.get(pending, {}).get('name', pending) if pending else None

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'uid': uid,
                    'name': display_name,
                    'username': username,
                    'email': u.get('email', 'Not Set'),
                    'deposit': u.get('deposit', 0.0),
                    'balance': u.get('balance', 0.0),
                    'bonus': u.get('bonus', 0.0),
                    'total_withdrawn': u.get('total_withdrawn', 0.0),
                    'pending_plan': pending_name,
                    'total_active_invested': total_invested,
                    'active_plans': plans_out,
                    'wallets': [c.replace('_', ' ') for c in u.get('wallets', {}).keys()],
                }).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- NEW: TERMINATE A USER'S ACTIVE PLAN (refund to deposit balance) ---
        elif parsed_path.path == '/api/terminate_plan':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                uid = int(data.get('uid'))
                plan_id = str(data.get('plan_id', ''))
                reason = str(data.get('reason', '') or '').strip() or "Trading plan cancelled due to violation of platform terms."

                u = user_db.get(uid)
                if not u:
                    raise ValueError("User not found")

                plan = next((p for p in u.get('active_plans', [])
                             if p.get('id') == plan_id and p.get('status') == 'active'), None)
                if not plan:
                    raise ValueError("Active plan not found (it may have already finished).")

                # Stopping the plan: the shared accrual engine skips any plan
                # whose status isn't 'active', so profits stop immediately.
                plan['status'] = 'terminated'
                plan['terminated_reason'] = reason
                refund = float(plan.get('amount', 0.0))
                u['deposit'] = u.get('deposit', 0.0) + refund
                log_tx(uid, "Plan Terminated (Refund)", refund)
                save_database()

                p_name = bot_plans.get(plan.get('macro'), {}).get('name', plan.get('macro', 'Plan'))
                try:
                    lang = get_user_lang(uid)
                    msg = (get_tl_and_map("🚨 <b>Plan Terminated</b>\n\nYour plan <b>%plan%</b> has been cancelled.\n\n<b>Reason:</b> %reason%\n\n<b>$%amount%</b> has been returned to your deposit balance.", lang)
                           .replace('%plan%', p_name)
                           .replace('%reason%', reason)
                           .replace('%amount%', fmt_amt(refund)))
                    bot.send_message(uid, msg, parse_mode="HTML")
                except Exception: pass

                admin_msg = (f"🚫 <b>PLAN TERMINATED</b>\nUser: <code>{uid}</code> (@{u.get('username', '?')})\n"
                             f"Plan: {p_name}\nRefunded to deposit: ${fmt_amt(refund)}\nReason: {reason}")
                for admin in ADMIN_IDS:
                    try: bot.send_message(admin, admin_msg, parse_mode="HTML")
                    except Exception: pass

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'refunded': refund}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- TREASURY: aggregated live balance overview (all user wallets) ---
        elif parsed_path.path == '/api/balance_overview':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            assets = {a: {'total_crypto': 0.0, 'total_usd': 0.0, 'wallets': []} for a in SEND_ASSETS}
            for uid, udata in user_db.items():
                uname = udata.get('username', str(uid))
                fname = udata.get('first_name', 'Unknown')
                name = f"{fname} (@{uname})" if uname and uname != 'No Username' else fname
                for net, wdata in udata.get('wallets', {}).items():
                    if net not in assets:
                        continue
                    live = wdata.get('live_balance')
                    if live is None:
                        continue
                    price = get_crypto_price(net) if 'USDT' not in net else 1.0
                    a = assets[net]
                    a['total_crypto'] += live
                    a['total_usd'] += live * price
                    a['wallets'].append({
                        'uid': uid, 'name': name, 'first': fname,
                        'address': wdata.get('address', ''),
                        'balance': live, 'usd': live * price,
                    })
            for a in assets.values():
                a['wallets'].sort(key=lambda x: -x['balance'])
            total_usd = sum(a['total_usd'] for a in assets.values())
            gas = get_gas_balances()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            derived = derive_gas_wallets() or {}
            gas_energy = None
            gas_tron = get_gas_addr('tron')
            if gas_tron:
                res = _tron_account_resources(gas_tron)
                if res:
                    gas_energy = {'available': max(0, res['energy_limit'] - res['energy_used']),
                                  'total': res['energy_limit'],
                                  'staked_trx': res['staked_sun'] / 1_000_000}
            self.wfile.write(json.dumps({
                'assets': assets, 'total_usd': total_usd, 'gas': gas,
                'gas_energy': gas_energy,
                'gas_addresses': {'evm': get_gas_addr('evm'), 'tron': get_gas_addr('tron'),
                                  'btc': get_gas_addr('btc')},
                'gas_derived': {'evm': derived.get('evm_address', ''),
                                'tron': derived.get('tron_address', ''),
                                'btc': derived.get('btc_address', '')},
                'gas_source': 'manual' if gas_wallet.get('evm_address') or gas_wallet.get('tron_address')
                              else ('seed' if derived else 'none'),
            }).encode())

        # --- TREASURY: per-asset history (deposits + admin sends) ---
        elif parsed_path.path == '/api/asset_history':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            net = str(data.get('network', ''))
            items = []
            if net in SEND_ASSETS:
                label_frag = net.replace('_', ' ')
                for uid, udata in user_db.items():
                    uname = udata.get('username', str(uid))
                    fname = udata.get('first_name', 'Unknown')
                    name = f"{fname} (@{uname})" if uname and uname != 'No Username' else fname
                    for tx in udata.get('transactions', []):
                        ttype = str(tx.get('type', ''))
                        # only real deposits (old + new) — never admin balance edits
                        if not ttype.startswith(('Auto-Deposit', 'Manual-Deposit', 'Deposit')):
                            continue
                        if 'admin' in ttype.lower():
                            continue
                        if label_frag in ttype or net in ttype:
                            items.append({'dir': 'in', 'user': name, 'uid': uid,
                                          'amount': tx.get('amount'), 'type': ttype,
                                          'date': tx.get('date')})
                for t in treasury_txs:
                    if t.get('network') == net:
                        items.append({'dir': 'out', 'user': f"uid {t.get('uid')}",
                                      'amount': -abs(float(t.get('amount', 0))),
                                      'type': 'Treasury Send', 'date': t.get('ts'),
                                      'txids': t.get('txids', []), 'to': t.get('to'),
                                      'status': t.get('status')})
            items.sort(key=lambda x: str(x.get('date') or ''), reverse=True)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'history': items[:500],
                                         'explorer': EXPLORER_TX.get(net, '')}).encode())

        # --- TREASURY: live address validation ---
        elif parsed_path.path == '/api/validate_addr':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            ok = validate_address(str(data.get('address', '')), str(data.get('network', '')))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'valid': ok}).encode())

        # --- TREASURY: live fee estimate ---
        elif parsed_path.path == '/api/estimate_fee':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            net = str(data.get('network', ''))
            if str(data.get('fee_mode', 'trx')) == 'rent' and net == 'USDT_TRC20':
                try:
                    uid = int(data.get('uid', 0))
                    w = user_db.get(uid, {}).get('wallets', {}).get(net) if uid else None
                    if not w:
                        raise ValueError('pick a source wallet')
                    energy = _tron_energy_needed(data.get('to_addr') or w['address'])
                    gb = (get_gas_balances() or {}).get('TRX')
                    if _tron_self_sufficient(w['address'], energy):
                        est = {'gas_asset': 'TRX', 'fee_crypto': 0, 'fee_usd': 0,
                               'gas_needed_crypto': 0, 'gas_balance': gb, 'gas_ok': True,
                               'rented': True, 'charged': True,
                               'note': 'wallet already holds enough energy — ~0 TRX'}
                    else:
                        est_r = tronsave_estimate(w['address'], energy)
                        cost = est_r['trx'] + 1.1   # rent + ~0.4 pay-tx + ~0.7 bandwidth top-up
                        est = {'gas_asset': 'TRX', 'fee_crypto': cost,
                               'fee_usd': cost * get_crypto_price('TRX'),
                               'gas_needed_crypto': cost, 'gas_balance': gb,
                               'gas_ok': gb is not None and gb >= cost, 'rented': True,
                               'note': 'rented energy via TronSave — gas wallet pays ~on-chain'}
                except Exception as e:
                    est = {'error': str(e)}
            elif str(data.get('fee_mode', 'trx')) == 'usdt' and net == 'USDT_TRC20':
                try:
                    uid = int(data.get('uid', 0))
                    w = user_db.get(uid, {}).get('wallets', {}).get(net) if uid else None
                    if not w:
                        raise ValueError('pick a source wallet')
                    est_g = gasfree_fee_estimate(w['address'])
                    # The USDT fee itself is relayer-paid, but the one-time
                    # base -> gasfree account move still costs gas-wallet TRX
                    # until the gasfree account is funded — surface that need.
                    boot = _gasfree_bootstrap_trx(w['address'], est_g,
                                                  float(data.get('amount') or 0))
                    gb = (get_gas_balances() or {}).get('TRX')
                    est = {'gas_asset': 'USDT', 'fee_crypto': est_g['fee_usdt'],
                           'fee_usd': est_g['fee_usdt'], 'gas_needed_crypto': boot,
                           'gas_balance': gb,
                           'gas_ok': boot == 0 or (gb is not None and gb >= boot + 0.3),
                           'gasfree': True,
                           'note': ('fee deducted in USDT via GasFree relayer' +
                                    ('' if est_g['active'] else ' — first use adds activation + a small gas-wallet setup transfer'))}
                except Exception as e:
                    est = {'error': str(e)}
            else:
                est = estimate_network_fee(net, data.get('to_addr') or None)
                # TRC20 trx mode: mirror the executor — free if the wallet is
                # already charged, else auto-rent if it beats a TRX burn
                if net == 'USDT_TRC20' and 'error' not in est and not est.get('delegated'):
                    try:
                        uid2 = int(data.get('uid', 0))
                        w2 = user_db.get(uid2, {}).get('wallets', {}).get(net) if uid2 else None
                        if w2:
                            need_e = _tron_energy_needed(data.get('to_addr') or w2['address'])
                            if _tron_self_sufficient(w2['address'], need_e):
                                est.update({'fee_crypto': 0.0, 'fee_usd': 0.0,
                                            'gas_needed_crypto': 0.0, 'charged': True,
                                            'note': 'wallet already holds energy — ~0 TRX'})
                            else:
                                est_r = tronsave_estimate(w2['address'], need_e)
                                if est_r['trx'] + 1.1 < float(est.get('gas_needed_crypto') or 999):
                                    est.update({'fee_crypto': est_r['trx'] + 1.1,
                                                'fee_usd': (est_r['trx'] + 1.1) * get_crypto_price('TRX'),
                                                'gas_needed_crypto': est_r['trx'] + 1.1,
                                                'auto_rent': True,
                                                'note': 'auto-rented energy — cheaper than burning TRX'})
                    except Exception:
                        pass
                if 'error' not in est:
                    gas = get_gas_balances()
                    have = gas.get(est['gas_asset'])
                    est['gas_balance'] = have
                    est['gas_ok'] = (have is not None and est.get('gas_needed_crypto', 0) > 0
                                     and have >= est['gas_needed_crypto']) or est.get('gas_needed_crypto', 0) == 0
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(est).encode())

        # --- TREASURY: gas wallet config (addresses + keys) ---
        elif parsed_path.path == '/api/gas_wallet':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            for k in ('evm_address', 'evm_key', 'tron_address', 'tron_key', 'btc_address', 'btc_key'):
                if k in data and data[k] is not None:
                    gas_wallet[k] = str(data[k]).strip()
            save_database()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            derived = derive_gas_wallets() or {}
            self.wfile.write(json.dumps({'success': True, 'gas': get_gas_balances(),
                                         'gas_addresses': {'evm': get_gas_addr('evm'),
                                                           'tron': get_gas_addr('tron'),
                                                           'btc': get_gas_addr('btc')},
                                         'gas_derived': {'evm': derived.get('evm_address', ''),
                                                         'tron': derived.get('tron_address', ''),
                                                         'btc': derived.get('btc_address', '')}}).encode())

        # --- TREASURY: stake TRX on the gas wallet for free energy ---
        elif parsed_path.path == '/api/stake_gas':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                amount = float(data.get('amount', 0))
                if amount <= 0:
                    raise ValueError("Enter a TRX amount to stake")
                gas_addr, gas_key = get_gas_addr('tron'), get_gas_key('tron')
                if not gas_addr or not gas_key:
                    raise ValueError("TRON gas wallet not configured")
                live = _tron_balance(gas_addr, 'TRX') or 0.0
                if amount > live - 1.0:
                    raise ValueError(f"Keep ~1 TRX free for fees — gas wallet has {fmt_amt(live)} TRX")
                txid = tron_freeze_energy(gas_key, amount)
                treasury_txs.append({'ts': time.time(), 'network': 'TRX', 'type': 'Gas Stake',
                                     'from': gas_addr, 'amount': amount, 'txids': [txid],
                                     'status': 'done'})
                save_database()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'txid': txid}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- TREASURY: rent quote (energy amount + duration -> TRX cost) ---
        elif parsed_path.path == '/api/rent_quote':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                energy = float(data.get('energy', 0))
                hours = float(data.get('hours', 1))
                if energy <= 0 or hours <= 0 or hours > 72:
                    raise ValueError("energy > 0 and duration 1–72h required")
                est_r = tronsave_estimate(get_gas_addr('tron') or 'T' + '0' * 33,
                                          energy, hours * 3600)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'trx': est_r['trx'],
                                             'usd': est_r['trx'] * get_crypto_price('TRX')}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- TREASURY: live energy on any tron address (for the rent ring) ---
        elif parsed_path.path == '/api/target_energy':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            addr = str(data.get('address', ''))
            res = _tron_account_resources(addr) if addr else None
            if not res:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'could not read energy for that address'}).encode())
                return
            avail = max(0, res['energy_limit'] - res['energy_used'])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'available': avail, 'limit': res['energy_limit'],
                                         'used': res['energy_used'],
                                         'sends': avail / 64300}).encode())

        # --- TREASURY: manual energy buy (gas wallet pays, energy -> target) ---
        elif parsed_path.path == '/api/buy_energy':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                energy = float(data.get('energy', 0))
                hours = float(data.get('hours', 24))
                if energy < 10000:
                    raise ValueError("Minimum sensible buy is ~10,000 energy")
                if hours <= 0 or hours > 72:
                    raise ValueError("Duration must be 1–72 hours")
                gas_addr, gas_key = get_gas_addr('tron'), get_gas_key('tron')
                if not gas_addr or not gas_key:
                    raise ValueError("TRON gas wallet not configured")
                target = str(data.get('target', 'gas'))
                if target == 'gas':
                    receiver = gas_addr
                else:
                    w = user_db.get(int(target), {}).get('wallets', {}).get('USDT_TRC20')
                    if not w or not w.get('address'):
                        raise ValueError("Target wallet not found")
                    receiver = w['address']
                est_r = tronsave_estimate(receiver, energy, hours * 3600)
                gtrx = _tron_balance(gas_addr, 'TRX') or 0.0
                if gtrx < est_r['trx'] + 1.0:
                    raise ValueError(f"Gas wallet needs ~{fmt_amt(est_r['trx'] + 1.0)} TRX (has {fmt_amt(gtrx)})")
                res_r = tronsave_rent(receiver, energy, gas_addr, gas_key, hours * 3600)
                tronsave_wait(res_r.get('order'), 90)
                treasury_txs.append({'ts': time.time(), 'network': 'TRX',
                                     'type': 'Energy Rent', 'to': receiver,
                                     'amount': res_r.get('trx'),
                                     'txids': [x for x in [res_r.get('pay_txid')] if x],
                                     'order': res_r.get('order'), 'status': 'done'})
                save_database()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'trx': res_r.get('trx'),
                                             'order': res_r.get('order'),
                                             'pay_txid': res_r.get('pay_txid')}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- TREASURY: execute a send (async task) ---
        elif parsed_path.path == '/api/send_asset':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                net = str(data.get('network', ''))
                uid = int(data.get('uid'))
                to_addr = str(data.get('to_addr', '')).strip()
                amount = float(data.get('amount'))
                if net not in SEND_ASSETS:
                    raise ValueError("Unsupported network")
                if not validate_address(to_addr, net):
                    raise ValueError("Invalid destination address for this network")
                w = user_db.get(uid, {}).get('wallets', {}).get(net)
                if not w or not w.get('address') or not w.get('private_key'):
                    raise ValueError("Source wallet not found")
                live = get_onchain_balance(w['address'], net)
                if live is None:
                    raise ValueError("Could not read the source wallet balance right now")
                if amount <= 0 or amount > live + BALANCE_EPSILON:
                    raise ValueError(f"Amount must be between 0 and the wallet balance ({fmt_amt(live)})")
                fee_mode = str(data.get('fee_mode', 'trx'))
                if fee_mode not in ('trx', 'usdt', 'rent'):
                    raise ValueError("Invalid fee_mode")
                if fee_mode in ('usdt', 'rent') and net != 'USDT_TRC20':
                    raise ValueError("USDT/rent fee modes are only available for USDT TRC20")
                if fee_mode == 'rent':
                    if not get_gas_key('tron'):
                        raise ValueError("TRON gas wallet not configured — rent needs it to pay on-chain")
                    need_e = _tron_energy_needed(to_addr)
                    if not _tron_self_sufficient(w['address'], need_e):
                        est_r = tronsave_estimate(w['address'], need_e)
                        gtrx = _tron_balance(get_gas_addr('tron'), 'TRX') or 0.0
                        if gtrx < est_r['trx'] + 1.5:
                            raise ValueError(f"Gas wallet needs ~{fmt_amt(est_r['trx'] + 1.5)} TRX to rent energy (has {fmt_amt(gtrx)})")
                if fee_mode == 'usdt':
                    if not GASFREE_API_KEY or not GASFREE_API_SECRET:
                        raise ValueError("GasFree not configured — set GASFREE_API_KEY / GASFREE_API_SECRET")
                    est_g = gasfree_fee_estimate(w['address'])
                    if amount + est_g['fee_usdt'] > live + BALANCE_EPSILON:
                        raise ValueError(f"Amount + GasFree fee ({fmt_amt(est_g['fee_usdt'])} USDT) exceeds balance")
                    # First use also needs a little gas-wallet TRX for the
                    # one-time base -> gasfree account move.
                    boot = _gasfree_bootstrap_trx(w['address'], est_g, amount)
                    if boot > 0:
                        gtrx = _tron_balance(get_gas_addr('tron'), 'TRX')
                        if gtrx is not None and gtrx < boot + 0.3:
                            raise ValueError(f"Gas wallet needs ~{fmt_amt(boot + 0.3)} TRX for the one-time "
                                             f"GasFree setup (has {fmt_amt(gtrx)}) — top it up or use another fee mode")
                elif net in ('TRX', 'BTC'):
                    est = estimate_network_fee(net)
                    need = est.get('fee_crypto', 0) if 'error' not in est else 0
                    if amount + need > live + BALANCE_EPSILON:
                        raise ValueError(f"Amount + network fee ({fmt_amt(need)} {NETWORK_GAS[net]}) exceeds balance")
                task_id = uuid.uuid4().hex[:12]
                send_tasks[task_id] = {'status': 'running', 'step': 'Queued',
                                       'network': net, 'uid': uid, 'to_addr': to_addr,
                                       'amount': amount, 'fee_mode': fee_mode, 'txids': []}
                threading.Thread(target=execute_treasury_send, args=(task_id,), daemon=True).start()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'task_id': task_id}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- TREASURY: poll send progress ---
        elif parsed_path.path == '/api/send_status':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            t = send_tasks.get(str(data.get('task_id', '')))
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(t or {'status': 'unknown'}).encode())

        # --- NEW: FREE TRIAL CASH — GET TEMPLATE + USER LIST ---
        elif parsed_path.path == '/api/get_free_trial':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            users_list = []
            for uid, udata in user_db.items():
                username = udata.get('username', str(uid))
                first_name = udata.get('first_name', 'Unknown')
                display = f"{first_name} (@{username})" if username != 'No Username' else first_name
                users_list.append({'uid': uid, 'name': display})
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'settings': free_trial_settings, 'users': users_list}).encode())

        # --- NEW: FREE TRIAL CASH — SEND OFFER (all users or one) ---
        elif parsed_path.path == '/api/send_free_trial':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            try:
                amount = float(data.get('amount'))
                days = float(data.get('expires_days'))
                if amount <= 0 or days <= 0:
                    raise ValueError("Amount and expiry days must be positive")

                # Persist the admin's edited texts so they become the new defaults.
                for key in ('msg_offer', 'button_text', 'msg_claimed', 'msg_reminder', 'msg_expired'):
                    val = data.get(key)
                    if val is not None and str(val).strip():
                        free_trial_settings[key] = str(val)

                offer_id = str(uuid.uuid4())[:8]
                offer = {
                    'id': offer_id,
                    'amount': amount,
                    'expires_days': days,
                    'image_url': str(data.get('image_url', '') or '').strip(),
                    'image_b64': str(data.get('image_b64', '') or ''),
                    'created_at': time.time(),
                }
                free_offers[offer_id] = offer
                save_database()

                target_mode = data.get('target_mode', 'all')
                if target_mode == 'individual':
                    t_uid = int(data.get('target_uid'))
                    targets = [t_uid] if t_uid in user_db else []
                else:
                    targets = list(user_db.keys())

                def _blast(tlist, off):
                    sent_n, fail_n = 0, 0
                    for t_uid in tlist:
                        try:
                            send_free_trial_offer(t_uid, off)
                            sent_n += 1
                        except Exception as e:
                            fail_n += 1
                            print(f"Free trial send failed for {t_uid}: {e}")
                        time.sleep(0.05)
                    print(f"🎁 Free trial offer {off['id']} sent: {sent_n} ok, {fail_n} failed")
                    for admin in ADMIN_IDS:
                        try:
                            bot.send_message(admin, f"🎁 <b>FREE TRIAL OFFER SENT</b>\nOffer ID: <code>{off['id']}</code>\nAmount: ${fmt_amt(off['amount'])}\nExpiry: {off['expires_days']} days\nDelivered: {sent_n} | Failed: {fail_n}", parse_mode="HTML")
                        except Exception: pass

                threading.Thread(target=_blast, args=(targets, offer), daemon=True).start()

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'queued': len(targets), 'offer_id': offer_id}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())

        # --- PWA: Web Push subscription management ---------------------------
        elif parsed_path.path == '/api/push_key':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            pub, _ = _vapid_keys()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'key': pub}).encode())

        elif parsed_path.path == '/api/push_subscribe':
            if pin != ADMIN_PIN:
                self.send_response(401)
                self.end_headers()
                return
            sub = data.get('sub')
            if isinstance(sub, dict) and sub.get('endpoint'):
                subs = push_settings.setdefault('subs', [])
                if not any(s.get('endpoint') == sub['endpoint'] for s in subs):
                    subs.append(sub)
                    save_database()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())

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

    # Start the Free Trial Cash expiry sweeper (removes unspent claims)
    print("🎁 Starting free-trial expiry thread...")
    threading.Thread(target=free_trial_expiry_loop, daemon=True).start()
    
    # Start the Telegram Bot
    print("🚀 Bot is running fast! Press Ctrl+C to stop.")
    bot.infinity_polling(skip_pending=True)
