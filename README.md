# svarog-bot

## Configuration

Copy `svarog/.env.example` to `svarog/.env` and set `BOT_TOKEN` and `ADMIN_IDS`.
Set `ADMIN_IDS` to one or more numeric Telegram IDs separated by commas.
Set `DEPOSIT_ADDRESS` to the wallet address the bot should display. Keep `.env`
private; it is ignored by Git. After exposing a token, revoke it with BotFather
and configure the replacement locally.