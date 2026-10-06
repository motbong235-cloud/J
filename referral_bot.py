"""
Kairozen Earn - Referral Bot (with Protection)
----------------------------------------------
- ណែនាំ 1 នាក់ = $0.05
- ដកលុយបានពេល Balance >= $0.50
- មានប្រព័ន្ធការពារ: Ban, Cooldown, Anti-spam, Min stay time
"""

import os
import json
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ChatMemberUpdated
)

load_dotenv()

# ========================
# Config
# ========================
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID      = os.getenv("CHANNEL_ID", "")
CHANNEL_LINK    = os.getenv("CHANNEL_LINK", "")
REF_REWARD      = 0.05
MIN_WITHDRAW    = 0.50

# ── ការពារ ──
WITHDRAW_COOLDOWN   = 3600         # ដកលុយបាន 1 ដង / ម៉ោង
SPAM_COOLDOWN       = 2            # រវាងការចុចប៊ូតុង 2 វិនាទី
MAX_REFS_PER_DAY    = 30           # ដែនកំណត់ណែនាំក្នុង 1 ថ្ងៃ (ការពារ farm)

DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE     = os.path.join(DATA_DIR, "ref_users.json")
BALANCES_FILE  = os.path.join(DATA_DIR, "ref_balances.json")
WITHDRAWS_FILE = os.path.join(DATA_DIR, "ref_withdraws.json")
LOGS_FILE      = os.path.join(DATA_DIR, "ref_logs.json")
BANS_FILE      = os.path.join(DATA_DIR, "ref_bans.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ========================
# Data
# ========================
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users     = _load(USERS_FILE, {})
balances  = _load(BALANCES_FILE, {})
withdraws = _load(WITHDRAWS_FILE, {})
logs      = _load(LOGS_FILE, [])
bans      = _load(BANS_FILE, {})          # uid -> {"reason": "...", "ts": ...}

# Anti-spam memory (in-memory)
last_action = {}      # uid -> timestamp
last_withdraw = {}    # uid -> timestamp

def get_bal(uid):
    return float(balances.get(str(uid), 0))

def add_bal(uid, amount):
    balances[str(uid)] = round(get_bal(uid) + amount, 2)
    _save(BALANCES_FILE, balances)

def set_bal(uid, amount):
    balances[str(uid)] = round(float(amount), 2)
    _save(BALANCES_FILE, balances)

def is_banned(uid):
    return str(uid) in bans

def ban_user(uid, reason=""):
    bans[str(uid)] = {"reason": reason, "ts": int(time.time())}
    _save(BANS_FILE, bans)

def unban_user(uid):
    bans.pop(str(uid), None)
    _save(BANS_FILE, bans)

def add_log(event_type, uid, name="", extra=None):
    entry = {
        "type": event_type,
        "uid": str(uid),
        "name": name,
        "ts": int(time.time()),
        "extra": extra or {}
    }
    logs.append(entry)
    if len(logs) > 500:
        logs[:] = logs[-500:]
    _save(LOGS_FILE, logs)

def check_spam(uid):
    """True បើកំពុង spam"""
    now = time.time()
    last = last_action.get(uid, 0)
    if now - last < SPAM_COOLDOWN:
        return True
    last_action[uid] = now
    return False

def can_withdraw(uid):
    """True បើអាចដកលុយបាន (cooldown)"""
    last = last_withdraw.get(uid, 0)
    return time.time() - last >= WITHDRAW_COOLDOWN

def refs_today(uid):
    """ចំនួនណែនាំថ្ងៃនេះ"""
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for e in logs:
        if e["type"] == "reward" and e["uid"] == str(uid):
            if datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d") == today:
                count += 1
    return count

# ========================
# Keyboards
# ========================
def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("💰 សមតុល្យ"), KeyboardButton("🔗 តំណភ្ជាប់របស់ខ្ញុំ"))
    kb.row(KeyboardButton("👥 មិត្តដែលខ្ញុំណែនាំ"), KeyboardButton("💸 ដកលុយ"))
    kb.row(KeyboardButton("📖 របៀបប្រើ"))
    return kb

def admin_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📊 ស្ថិតិ"), KeyboardButton("👥 បញ្ជី User"))
    kb.row(KeyboardButton("💸 សំណើដកលុយ"), KeyboardButton("📝 Log ចូល/ចេញ"))
    kb.row(KeyboardButton("➕ បន្ថែមលុយ"), KeyboardButton("💔 កាត់លុយ"))
    kb.row(KeyboardButton("🚫 Ban User"), KeyboardButton("✅ Unban User"))
    kb.row(KeyboardButton("🔙 User Menu"))
    return kb

# ========================
# Helpers
# ========================
def ensure_user(uid, name="", username="", ref_by=None):
    uid = str(uid)
    if uid not in users:
        users[uid] = {
            "name": name,
            "username": username,
            "ref_by": ref_by,
            "joined": int(time.time()),
            "refs": [],
            "in_channel": False
        }
        _save(USERS_FILE, users)
        if uid not in balances:
            balances[uid] = 0.0
            _save(BALANCES_FILE, balances)
    else:
        if name:
            users[uid]["name"] = name
        if username:
            users[uid]["username"] = username
        _save(USERS_FILE, users)
    return users[uid]

def check_channel_member(uid):
    try:
        member = bot.get_chat_member(CHANNEL_ID, uid)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

def make_ref_link(uid):
    me = bot.get_me()
    return f"https://t.me/{me.username}?start=ref{uid}"

waiting = {}

# ========================
# Channel Join / Leave + Delayed Reward
# ========================
# Channel Join / Leave
# ========================
@bot.chat_member_handler()
def on_chat_member(update: ChatMemberUpdated):
    try:
        if str(update.chat.id) != str(CHANNEL_ID):
            return

        old = update.old_chat_member.status
        new = update.new_chat_member.status
        user = update.new_chat_member.user
        uid = user.id
        name = user.first_name or ""
        username = user.username or ""

        if is_banned(uid):
            return

        ensure_user(uid, name, username)

        # ── ចូល Channel → ផ្តល់រង្វាន់ភ្លាម ──
        if new in ("member", "administrator", "creator") and old in ("left", "kicked", "restricted"):
            users[str(uid)]["in_channel"] = True
            users[str(uid)]["join_ts"] = int(time.time())
            _save(USERS_FILE, users)
            add_log("join", uid, name)

            try:
                bot.send_message(
                    ADMIN_ID,
                    f"🟢 <b>User ចូល Channel</b>\n"
                    f"👤 {name} (@{username})\n"
                    f"🆔 <code>{uid}</code>\n"
                    f"⏰ {datetime.now().strftime('%H:%M %d/%m')}"
                )
            except:
                pass

            # ផ្តល់រង្វាន់ភ្លាមៗ
            ref_by = users[str(uid)].get("ref_by")
            if ref_by and str(uid) not in users.get(str(ref_by), {}).get("refs", []):
                if refs_today(ref_by) >= MAX_REFS_PER_DAY:
                    try:
                        bot.send_message(int(ref_by), f"⚠️ អ្នកណែនាំគ្រប់ដែនកំណត់ថ្ងៃនេះហើយ ({MAX_REFS_PER_DAY} នាក់)")
                    except:
                        pass
                else:
                    users[str(ref_by)]["refs"].append(str(uid))
                    _save(USERS_FILE, users)
                    add_bal(ref_by, REF_REWARD)
                    add_log("reward", ref_by, extra={"from": uid, "amount": REF_REWARD})

                    try:
                        bot.send_message(
                            int(ref_by),
                            f"🎉 <b>អ្នកទទួលបាន ${REF_REWARD:.2f}!</b>\n"
                            f"មិត្ត <b>{name}</b> បានចូល Channel។\n"
                            f"💰 សមតុល្យ: <b>${get_bal(ref_by):.2f}</b>\n\n"
                            f"⚠️ បើមិត្តចេញ Channel លុយនឹងត្រូវកាត់វិញ។"
                        )
                    except:
                        pass

        # ── ចេញ Channel → កាត់លុយពីអ្នកណែនាំ ──
        elif new in ("left", "kicked") and old in ("member", "administrator", "creator"):
            users[str(uid)]["in_channel"] = False
            _save(USERS_FILE, users)
            add_log("leave", uid, name)

            try:
                bot.send_message(
                    ADMIN_ID,
                    f"🔴 <b>User ចេញ Channel</b>\n"
                    f"👤 {name} (@{username})\n"
                    f"🆔 <code>{uid}</code>\n"
                    f"⏰ {datetime.now().strftime('%H:%M %d/%m')}"
                )
            except:
                pass

            # កាត់លុយពីអ្នកណែនាំ (បើធ្លាប់បានរង្វាន់)
            ref_by = users[str(uid)].get("ref_by")
            if ref_by and str(uid) in users.get(str(ref_by), {}).get("refs", []):
                # ដកចេញពីបញ្ជី refs
                users[str(ref_by)]["refs"] = [r for r in users[str(ref_by)]["refs"] if r != str(uid)]
                _save(USERS_FILE, users)

                # កាត់លុយ
                add_bal(ref_by, -REF_REWARD)
                add_log("clawback", ref_by, extra={"from": uid, "amount": REF_REWARD})

                try:
                    bot.send_message(
                        int(ref_by),
                        f"⚠️ <b>កាត់លុយ ${REF_REWARD:.2f}</b>\n"
                        f"មិត្ត <b>{name}</b> បានចេញពី Channel។\n"
                        f"💰 សមតុល្យនៅសល់: <b>${get_bal(ref_by):.2f}</b>"
                    )
                except:
                    pass

    except Exception as e:
        logger.error(f"chat_member error: {e}")

# ========================
# /start
# ========================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.from_user.id
    name = message.from_user.first_name or ""
    username = message.from_user.username or ""
    text = message.text or ""

    if is_banned(uid):
        bot.send_message(uid, "🚫 គណនីរបស់អ្នកត្រូវបាន Ban។")
        return

    if check_spam(uid):
        return

    ref_by = None
    if " " in text:
        payload = text.split(" ", 1)[1]
        if payload.startswith("ref"):
            try:
                ref_by = int(payload[3:])
            except:
                pass

    if ref_by == uid:
        ref_by = None

    # ការពារ: បើ ref_by ត្រូវ ban
    if ref_by and is_banned(ref_by):
        ref_by = None

    user = ensure_user(uid, name, username, str(ref_by) if ref_by else None)

    # បើមាន ref + នៅក្នុង channel រួច → ផ្តល់រង្វាន់ភ្លាម
    if ref_by and str(ref_by) in users and str(uid) not in users.get(str(ref_by), {}).get("refs", []):
        if check_channel_member(uid):
            if refs_today(ref_by) < MAX_REFS_PER_DAY:
                users[str(ref_by)]["refs"].append(str(uid))
                users[str(uid)]["in_channel"] = True
                _save(USERS_FILE, users)
                add_bal(ref_by, REF_REWARD)
                add_log("reward", ref_by, extra={"from": uid, "amount": REF_REWARD})
                try:
                    bot.send_message(
                        ref_by,
                        f"🎉 <b>អ្នកទទួលបាន ${REF_REWARD:.2f}!</b>\n"
                        f"មិត្ត <b>{name}</b> បានចូល Channel។\n"
                        f"💰 សមតុល្យ: <b>${get_bal(ref_by):.2f}</b>\n\n"
                        f"⚠️ បើមិត្តចេញ Channel លុយនឹងត្រូវកាត់វិញ។"
                    )
                except:
                    pass

    bal = get_bal(uid)
    link = make_ref_link(uid)

    msg = (
        f"សួស្តី <b>{name}</b>! 👋\n\n"
        f"នេះជា <b>Kairozen Earn</b>\n"
        f"ណែនាំមិត្តចូល Channel រកលុយ។\n\n"
        f"📌 ណែនាំ ១ នាក់ = <b>${REF_REWARD:.2f}</b>\n"
        f"💸 ដកលុយបានពេលមាន <b>${MIN_WITHDRAW:.2f}</b> ឡើងទៅ\n\n"
        f"💰 សមតុល្យ: <b>${bal:.2f}</b>\n\n"
        f"🔗 តំណភ្ជាប់របស់អ្នក:\n<code>{link}</code>"
    )

    if CHANNEL_ID and not check_channel_member(uid):
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📢 ចូល Channel ឥឡូវ", url=CHANNEL_LINK))
        bot.send_message(uid, msg, reply_markup=kb)
    else:
        bot.send_message(uid, msg, reply_markup=main_kb())

# ========================
# User Menu
# ========================
@bot.message_handler(func=lambda m: m.text == "💰 សមតុល្យ")
def bal_handler(message):
    uid = message.from_user.id
    if is_banned(uid) or check_spam(uid):
        return

    ensure_user(uid, message.from_user.first_name or "", message.from_user.username or "")
    bal = get_bal(uid)
    refs = len(users.get(str(uid), {}).get("refs", []))

    bot.send_message(
        uid,
        f"💰 <b>សមតុល្យរបស់អ្នក</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Balance: <b>${bal:.2f}</b>\n"
        f"👥 មិត្តដែលណែនាំ: <b>{refs}</b> នាក់\n"
        f"📌 រង្វាន់: ${REF_REWARD:.2f} / នាក់\n"
        f"💸 ដកបានពី: ${MIN_WITHDRAW:.2f}",
        reply_markup=main_kb()
    )

@bot.message_handler(func=lambda m: m.text == "🔗 តំណភ្ជាប់របស់ខ្ញុំ")
def link_handler(message):
    uid = message.from_user.id
    if is_banned(uid) or check_spam(uid):
        return
    ensure_user(uid, message.from_user.first_name or "", message.from_user.username or "")
    link = make_ref_link(uid)
    bot.send_message(
        uid,
        f"🔗 <b>តំណភ្ជាប់ណែនាំ</b>\n\n<code>{link}</code>\n\n"
        f"ផ្ញើទៅមិត្ត → ពេលគេចូល Channel អ្នកបាន ${REF_REWARD:.2f}\n"
        f"⚠️ បើមិត្តចេញ Channel លុយនឹងត្រូវកាត់វិញ។",
        reply_markup=main_kb()
    )

@bot.message_handler(func=lambda m: m.text == "👥 មិត្តដែលខ្ញុំណែនាំ")
def refs_handler(message):
    uid = message.from_user.id
    if is_banned(uid) or check_spam(uid):
        return
    user = ensure_user(uid, message.from_user.first_name or "", message.from_user.username or "")
    refs = user.get("refs", [])

    if not refs:
        bot.send_message(uid, "អ្នកមិនទាន់មានមិត្តណែនាំទេ។", reply_markup=main_kb())
        return

    lines = [f"👥 <b>មិត្តដែលអ្នកណែនាំ ({len(refs)})</b>\n"]
    for i, rid in enumerate(refs[:30], 1):
        u = users.get(rid, {})
        lines.append(f"{i}. {u.get('name','?')} (<code>{rid}</code>)")
    if len(refs) > 30:
        lines.append(f"\n... +{len(refs)-30} នាក់ទៀត")

    bot.send_message(uid, "\n".join(lines), reply_markup=main_kb())

@bot.message_handler(func=lambda m: m.text == "📖 របៀបប្រើ")
def howto_handler(message):
    if check_spam(message.from_user.id):
        return
    bot.send_message(
        message.chat.id,
        f"📖 <b>របៀបប្រើ</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"1️⃣ ចូល Channel\n"
        f"2️⃣ យកតំណភ្ជាប់ផ្ញើទៅមិត្ត\n"
        f"3️⃣ មិត្តចូល Channel + Start Bot\n"
        f"4️⃣ អ្នកទទួល ${REF_REWARD:.2f} ភ្លាមៗ\n"
        f"5️⃣ បើមិត្តចេញ Channel → លុយត្រូវកាត់វិញ\n"
        f"6️⃣ មាន ${MIN_WITHDRAW:.2f} ឡើងទៅ → ដកលុយ",
        reply_markup=main_kb()
    )

# ========================
# Withdraw
# ========================
@bot.message_handler(func=lambda m: m.text == "💸 ដកលុយ")
def withdraw_start(message):
    uid = message.from_user.id
    if is_banned(uid) or check_spam(uid):
        return

    if not can_withdraw(uid):
        remain = int(WITHDRAW_COOLDOWN - (time.time() - last_withdraw.get(uid, 0)))
        bot.send_message(uid, f"⏳ សូមរង់ចាំ {remain//60} នាទីទៀត ទើបដកលុយបានម្ដងទៀត។", reply_markup=main_kb())
        return

    bal = get_bal(uid)
    if bal < MIN_WITHDRAW:
        bot.send_message(uid, f"❌ សមតុល្យមិនគ្រប់ (${bal:.2f})\nត្រូវការ ${MIN_WITHDRAW:.2f} ឡើងទៅ", reply_markup=main_kb())
        return

    waiting[uid] = "await_amount"
    bot.send_message(
        uid,
        f"💸 សមតុល្យ: <b>${bal:.2f}</b>\nវាយចំនួនដែលចង់ដក (អប្បបរមា ${MIN_WITHDRAW:.2f}):",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ បោះបង់"))
    )

@bot.message_handler(func=lambda m: waiting.get(m.from_user.id) == "await_amount")
def withdraw_amount(message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    if text == "❌ បោះបង់":
        waiting.pop(uid, None)
        bot.send_message(uid, "បានបោះបង់។", reply_markup=main_kb())
        return

    try:
        amount = float(text.replace("$", ""))
        if amount < MIN_WITHDRAW or amount > get_bal(uid):
            bot.send_message(uid, "ចំនួនមិនត្រឹមត្រូវ")
            return
    except:
        bot.send_message(uid, "សូមវាយជាលេខ")
        return

    waiting[uid] = {"step": "await_info", "amount": amount}
    bot.send_message(uid, f"ចំនួន: <b>${amount:.2f}</b>\n\nផ្ញើព័ត៌មានទទួលលុយ (ធនាគារ + លេខគណនី + ឈ្មោះ):")

@bot.message_handler(func=lambda m: isinstance(waiting.get(m.from_user.id), dict) and waiting[m.from_user.id].get("step") == "await_info")
def withdraw_info(message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    if text == "❌ បោះបង់":
        waiting.pop(uid, None)
        bot.send_message(uid, "បានបោះបង់។", reply_markup=main_kb())
        return

    data = waiting.pop(uid)
    amount = data["amount"]
    add_bal(uid, -amount)
    last_withdraw[uid] = time.time()

    wid = f"W{int(time.time())}{uid}"
    withdraws[wid] = {
        "uid": str(uid),
        "amount": amount,
        "info": text,
        "status": "pending",
        "ts": int(time.time())
    }
    _save(WITHDRAWS_FILE, withdraws)

    bot.send_message(uid, f"✅ សំណើដកលុយ <code>{wid}</code> ចំនួន <b>${amount:.2f}</b> បានផ្ញើ!", reply_markup=main_kb())

    try:
        u = users.get(str(uid), {})
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("✅ អនុម័ត", callback_data=f"wd:ok:{wid}"),
            InlineKeyboardButton("❌ បដិសេធ", callback_data=f"wd:no:{wid}")
        )
        bot.send_message(
            ADMIN_ID,
            f"💸 <b>សំណើដកលុយ</b>\n🆔 <code>{wid}</code>\n👤 {u.get('name','?')} (<code>{uid}</code>)\n💰 <b>${amount:.2f}</b>\n📝 {text}",
            reply_markup=kb
        )
    except:
        pass

# ========================
# Admin Panel
# ========================
@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(message.chat.id, "⚙️ <b>Admin Panel</b>", reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "📊 ស្ថិតិ" and m.from_user.id == ADMIN_ID)
def admin_stats(message):
    total_users = len(users)
    total_refs = sum(len(u.get("refs", [])) for u in users.values())
    total_bal = sum(balances.values())
    pending_wd = sum(1 for w in withdraws.values() if w.get("status") == "pending")
    in_channel = sum(1 for u in users.values() if u.get("in_channel"))
    banned = len(bans)

    bot.send_message(
        message.chat.id,
        f"📊 <b>ស្ថិតិ</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Users: <b>{total_users}</b>\n"
        f"📢 នៅក្នុង Channel: <b>{in_channel}</b>\n"
        f"🔗 Total Refs: <b>{total_refs}</b>\n"
        f"💰 Total Balance: <b>${total_bal:.2f}</b>\n"
        f"💸 Pending Withdraw: <b>{pending_wd}</b>\n"
        f"🚫 Banned: <b>{banned}</b>",
        reply_markup=admin_kb()
    )

@bot.message_handler(func=lambda m: m.text == "👥 បញ្ជី User" and m.from_user.id == ADMIN_ID)
def admin_users(message):
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("joined", 0), reverse=True)[:25]
    lines = ["👥 <b>User ថ្មីៗ (25)</b>\n"]
    for uid, u in sorted_users:
        bal = get_bal(uid)
        refs = len(u.get("refs", []))
        status = "🟢" if u.get("in_channel") else "🔴"
        ban_icon = "🚫" if is_banned(uid) else ""
        lines.append(f"{status}{ban_icon} <code>{uid}</code> | {u.get('name','?')[:12]} | ${bal:.2f} | refs:{refs}")

    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "📝 Log ចូល/ចេញ" and m.from_user.id == ADMIN_ID)
def admin_logs(message):
    recent = logs[-20:][::-1]
    if not recent:
        bot.send_message(message.chat.id, "គ្មាន log ទេ។", reply_markup=admin_kb())
        return

    lines = ["📝 <b>Log (20 ចុងក្រោយ)</b>\n"]
    for e in recent:
        t = datetime.fromtimestamp(e["ts"]).strftime("%d/%m %H:%M")
        icon = {"join": "🟢", "leave": "🔴", "reward": "💰", "admin_add": "➕", "admin_cut": "💔"}.get(e["type"], "•")
        lines.append(f"{icon} {t} | {e.get('name','?')} (<code>{e['uid']}</code>) | {e['type']}")

    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=admin_kb())

@bot.message_handler(func=lambda m: m.text == "💸 សំណើដកលុយ" and m.from_user.id == ADMIN_ID)
def admin_withdraws(message):
    pending = [(k, v) for k, v in withdraws.items() if v.get("status") == "pending"]
    if not pending:
        bot.send_message(message.chat.id, "គ្មានសំណើរង់ចាំទេ។", reply_markup=admin_kb())
        return

    for wid, w in pending[:10]:
        u = users.get(w["uid"], {})
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("✅ អនុម័ត", callback_data=f"wd:ok:{wid}"),
            InlineKeyboardButton("❌ បដិសេធ", callback_data=f"wd:no:{wid}")
        )
        bot.send_message(
            message.chat.id,
            f"🆔 <code>{wid}</code>\n👤 {u.get('name','?')} (<code>{w['uid']}</code>)\n💰 ${w['amount']:.2f}\n📝 {w['info']}",
            reply_markup=kb
        )

# ── បន្ថែម / កាត់លុយ ──
@bot.message_handler(func=lambda m: m.text == "➕ បន្ថែមលុយ" and m.from_user.id == ADMIN_ID)
def admin_add_start(message):
    waiting[ADMIN_ID] = "admin_add_uid"
    bot.send_message(ADMIN_ID, "វាយ User ID ដែលចង់បន្ថែមលុយ:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ បោះបង់")))

@bot.message_handler(func=lambda m: waiting.get(m.from_user.id) == "admin_add_uid" and m.from_user.id == ADMIN_ID)
def admin_add_uid(message):
    text = (message.text or "").strip()
    if text == "❌ បោះបង់":
        waiting.pop(ADMIN_ID, None)
        bot.send_message(ADMIN_ID, "បោះបង់។", reply_markup=admin_kb())
        return
    if not text.isdigit():
        bot.send_message(ADMIN_ID, "User ID ត្រូវជាលេខ")
        return
    waiting[ADMIN_ID] = {"step": "admin_add_amount", "uid": text}
    bot.send_message(ADMIN_ID, f"User: <code>{text}</code>\nវាយចំនួនលុយ ($):")

@bot.message_handler(func=lambda m: isinstance(waiting.get(m.from_user.id), dict) and waiting[m.from_user.id].get("step") == "admin_add_amount" and m.from_user.id == ADMIN_ID)
def admin_add_amount(message):
    data = waiting.pop(ADMIN_ID)
    try:
        amount = float((message.text or "").replace("$", ""))
        if amount <= 0: raise ValueError
    except:
        bot.send_message(ADMIN_ID, "ចំនួនខុស", reply_markup=admin_kb())
        return

    uid = data["uid"]
    add_bal(uid, amount)
    add_log("admin_add", uid, extra={"amount": amount})
    bot.send_message(ADMIN_ID, f"✅ បន្ថែម ${amount:.2f} ឲ្យ <code>{uid}</code>\nBalance: ${get_bal(uid):.2f}", reply_markup=admin_kb())
    try:
        bot.send_message(int(uid), f"💰 Admin បានបន្ថែម <b>${amount:.2f}</b>។\nសមតុល្យថ្មី: <b>${get_bal(uid):.2f}</b>")
    except:
        pass

@bot.message_handler(func=lambda m: m.text == "💔 កាត់លុយ" and m.from_user.id == ADMIN_ID)
def admin_cut_start(message):
    waiting[ADMIN_ID] = "admin_cut_uid"
    bot.send_message(ADMIN_ID, "វាយ User ID ដែលចង់កាត់លុយ:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ បោះបង់")))

@bot.message_handler(func=lambda m: waiting.get(m.from_user.id) == "admin_cut_uid" and m.from_user.id == ADMIN_ID)
def admin_cut_uid(message):
    text = (message.text or "").strip()
    if text == "❌ បោះបង់":
        waiting.pop(ADMIN_ID, None)
        bot.send_message(ADMIN_ID, "បោះបង់។", reply_markup=admin_kb())
        return
    if not text.isdigit():
        bot.send_message(ADMIN_ID, "User ID ត្រូវជាលេខ")
        return
    waiting[ADMIN_ID] = {"step": "admin_cut_amount", "uid": text}
    bot.send_message(ADMIN_ID, f"User: <code>{text}</code>\nBalance: <b>${get_bal(text):.2f}</b>\nវាយចំនួនដែលចង់កាត់:")

@bot.message_handler(func=lambda m: isinstance(waiting.get(m.from_user.id), dict) and waiting[m.from_user.id].get("step") == "admin_cut_amount" and m.from_user.id == ADMIN_ID)
def admin_cut_amount(message):
    data = waiting.pop(ADMIN_ID)
    try:
        amount = float((message.text or "").replace("$", ""))
        if amount <= 0: raise ValueError
    except:
        bot.send_message(ADMIN_ID, "ចំនួនខុស", reply_markup=admin_kb())
        return

    uid = data["uid"]
    cut = min(amount, get_bal(uid))
    add_bal(uid, -cut)
    add_log("admin_cut", uid, extra={"amount": cut})
    bot.send_message(ADMIN_ID, f"✅ កាត់ ${cut:.2f} ពី <code>{uid}</code>\nBalance: ${get_bal(uid):.2f}", reply_markup=admin_kb())
    try:
        bot.send_message(int(uid), f"⚠️ Admin បានកាត់ <b>${cut:.2f}</b>។\nសមតុល្យនៅសល់: <b>${get_bal(uid):.2f}</b>")
    except:
        pass

# ── Ban / Unban ──
@bot.message_handler(func=lambda m: m.text == "🚫 Ban User" and m.from_user.id == ADMIN_ID)
def admin_ban_start(message):
    waiting[ADMIN_ID] = "admin_ban_uid"
    bot.send_message(ADMIN_ID, "វាយ User ID ដែលចង់ Ban:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ បោះបង់")))

@bot.message_handler(func=lambda m: waiting.get(m.from_user.id) == "admin_ban_uid" and m.from_user.id == ADMIN_ID)
def admin_ban_uid(message):
    text = (message.text or "").strip()
    if text == "❌ បោះបង់":
        waiting.pop(ADMIN_ID, None)
        bot.send_message(ADMIN_ID, "បោះបង់។", reply_markup=admin_kb())
        return
    if not text.isdigit():
        bot.send_message(ADMIN_ID, "User ID ត្រូវជាលេខ")
        return

    waiting[ADMIN_ID] = {"step": "admin_ban_reason", "uid": text}
    bot.send_message(ADMIN_ID, "វាយមូលហេតុ (ឬវាយ - បើមិនចង់ដាក់):")

@bot.message_handler(func=lambda m: isinstance(waiting.get(m.from_user.id), dict) and waiting[m.from_user.id].get("step") == "admin_ban_reason" and m.from_user.id == ADMIN_ID)
def admin_ban_reason(message):
    data = waiting.pop(ADMIN_ID)
    reason = (message.text or "").strip()
    if reason == "-":
        reason = "Banned by admin"

    uid = data["uid"]
    ban_user(uid, reason)
    add_log("ban", uid, extra={"reason": reason})

    bot.send_message(ADMIN_ID, f"🚫 បាន Ban <code>{uid}</code>\nមូលហេតុ: {reason}", reply_markup=admin_kb())
    try:
        bot.send_message(int(uid), f"🚫 គណនីរបស់អ្នកត្រូវបាន Ban។\nមូលហេតុ: {reason}")
    except:
        pass

@bot.message_handler(func=lambda m: m.text == "✅ Unban User" and m.from_user.id == ADMIN_ID)
def admin_unban_start(message):
    waiting[ADMIN_ID] = "admin_unban_uid"
    bot.send_message(ADMIN_ID, "វាយ User ID ដែលចង់ Unban:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("❌ បោះបង់")))

@bot.message_handler(func=lambda m: waiting.get(m.from_user.id) == "admin_unban_uid" and m.from_user.id == ADMIN_ID)
def admin_unban_uid(message):
    text = (message.text or "").strip()
    if text == "❌ បោះបង់":
        waiting.pop(ADMIN_ID, None)
        bot.send_message(ADMIN_ID, "បោះបង់។", reply_markup=admin_kb())
        return
    if not text.isdigit():
        bot.send_message(ADMIN_ID, "User ID ត្រូវជាលេខ")
        return

    waiting.pop(ADMIN_ID, None)
    unban_user(text)
    add_log("unban", text)
    bot.send_message(ADMIN_ID, f"✅ បាន Unban <code>{text}</code>", reply_markup=admin_kb())
    try:
        bot.send_message(int(text), "✅ គណនីរបស់អ្នកត្រូវបាន Unban ហើយ។")
    except:
        pass

@bot.message_handler(func=lambda m: m.text == "🔙 User Menu" and m.from_user.id == ADMIN_ID)
def back_user(message):
    waiting.pop(ADMIN_ID, None)
    bot.send_message(message.chat.id, "ត្រឡប់ទៅ User Menu", reply_markup=main_kb())

# ========================
# Withdraw Callback
# ========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("wd:"))
def cb_withdraw(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Admin only")
        return

    action, wid = call.data.split(":")[1], call.data.split(":")[2]
    w = withdraws.get(wid)
    if not w or w.get("status") != "pending":
        bot.answer_callback_query(call.id, "ដំណើរការរួចហើយ")
        return

    uid = int(w["uid"])
    amount = w["amount"]

    if action == "ok":
        w["status"] = "approved"
        _save(WITHDRAWS_FILE, withdraws)
        bot.answer_callback_query(call.id, "អនុម័តហើយ")
        bot.edit_message_text(call.message.text + "\n\n✅ <b>បានអនុម័ត</b>", call.message.chat.id, call.message.message_id)
        try:
            bot.send_message(uid, f"✅ សំណើ <code>{wid}</code> ចំនួន <b>${amount:.2f}</b> ត្រូវបានអនុម័ត!")
        except:
            pass
    else:
        add_bal(uid, amount)
        w["status"] = "rejected"
        _save(WITHDRAWS_FILE, withdraws)
        bot.answer_callback_query(call.id, "បដិសេធហើយ")
        bot.edit_message_text(call.message.text + "\n\n❌ <b>បដិសេធ (សងលុយវិញ)</b>", call.message.chat.id, call.message.message_id)
        try:
            bot.send_message(uid, f"❌ សំណើ <code>{wid}</code> ត្រូវបានបដិសេធ។ លុយ ${amount:.2f} ត្រូវបានសងវិញ។")
        except:
            pass

# ========================
# Fallback
# ========================
@bot.message_handler(func=lambda m: True)
def fallback(message):
    if message.from_user.id == ADMIN_ID:
        return
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 គណនីរបស់អ្នកត្រូវបាន Ban។")
        return
    bot.send_message(message.chat.id, "សូមប្រើប៊ូតុងខាងក្រោម។", reply_markup=main_kb())

# ========================
# Main
# ========================
if __name__ == "__main__":
    if not BOT_TOKEN or not ADMIN_ID:
        print("❌ សូមកំណត់ BOT_TOKEN និង ADMIN_ID")
        exit(1)

    print("🤖 Kairozen Earn Bot (Protected) is running...")
    bot.infinity_polling(allowed_updates=["message", "callback_query", "chat_member"])
