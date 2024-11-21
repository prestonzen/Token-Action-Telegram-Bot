import os
from datetime import datetime, timedelta
import asyncio
import json  # Import json to parse JSON strings
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient  # Use AsyncClient for async operations
from solders.pubkey import Pubkey
from telegram import Bot

# Load environment variables from .env file
load_dotenv()

# Configuration variables
TELEGRAM_BOT_TOKEN = os.getenv('Kaizen_Apps_Telegram_Token')
TELEGRAM_CHAT_ID = os.getenv('Kaizen_Telegram_group_ID')
SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Get the wallet address and convert it to a Pubkey object
wallet_address = os.getenv('Watch_Wallet_1')
if not wallet_address:
    print("No wallet address provided in the .env file.")
    exit(1)

try:
    WATCH_WALLET = Pubkey.from_string(wallet_address.strip())
except ValueError as e:
    print(f"Invalid wallet address: {e}")
    exit(1)

# Keep track of last processed signature
last_signature = None

# Keep-alive message timer
last_keep_alive = datetime.utcnow()

def get_token_name_from_mint(mint_address):
    # Implement a mapping or API call to get the token name from mint address
    # For simplicity, we'll return the mint address itself
    return mint_address

async def send_keep_alive_message(bot):
    wallet_str = str(WATCH_WALLET)
    message = f"Keep-alive: Monitoring wallet {wallet_str}"
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

async def monitor_wallet(wallet, client, bot, initial_run=False):
    global last_signature

    # Get recent transaction signatures
    response = await client.get_signatures_for_address(wallet, limit=10)
    if response.value is None:
        return

    signatures = response.value
    if not signatures:
        return

    wallet_str = str(wallet)

    # On initial run, process the latest 5 transactions
    if initial_run:
        new_signatures = [sig_info.signature for sig_info in signatures[:5]]
    else:
        latest_signature = signatures[0].signature

        if last_signature is None:
            last_signature = latest_signature
            return  # Skip processing on the first regular run

        # Find new signatures since the last processed one
        new_signatures = []
        for sig_info in signatures:
            if sig_info.signature == last_signature:
                break
            new_signatures.append(sig_info.signature)

        if not new_signatures:
            return

    # Process new transactions
    for sig in reversed(new_signatures):
        txn_resp = await client.get_transaction(sig, encoding='jsonParsed')
        if txn_resp.value is None:
            continue

        txn = txn_resp.value
        # Convert transaction to JSON string and then to dictionary
        txn_json = txn.to_json()
        txn_dict = json.loads(txn_json)
        meta = txn_dict.get('meta')
        if meta is None:
            continue

        pre_balances = meta.get('preTokenBalances', [])
        post_balances = meta.get('postTokenBalances', [])

        # Map account indices to public keys
        account_keys = [key.get('pubkey') for key in txn_dict['transaction']['message']['accountKeys']]

        # Build balances before and after the transaction
        balances = {}
        for balance in pre_balances + post_balances:
            idx = balance['accountIndex']
            owner = balance.get('owner') or account_keys[idx]
            mint = balance['mint']
            amount_info = balance['uiTokenAmount']
            amount_str = amount_info.get('uiAmountString') if amount_info else None
            amount = float(amount_str) if amount_str is not None else 0
            key = (owner, mint)
            if balance in pre_balances:
                balances.setdefault(key, {})['pre'] = amount
            else:
                balances.setdefault(key, {})['post'] = amount

        # Detect changes in balances
        for (owner, mint), amounts in balances.items():
            pre_amount = amounts.get('pre', 0)
            post_amount = amounts.get('post', 0)
            delta = post_amount - pre_amount
            if delta != 0 and owner == wallet_str:
                action = 'bought' if delta > 0 else 'sold'
                token_name = get_token_name_from_mint(mint)
                amount = abs(delta)
                message = f"Wallet {wallet_str} {action} {amount} of {token_name}."
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

    # Update the last processed signature
    if not initial_run and signatures:
        last_signature = signatures[0].signature

async def main():
    global last_keep_alive
    initial_run = True

    # Initialize Solana client and Telegram bot within the async context
    async with AsyncClient(SOLANA_RPC_URL) as client, Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        # Send initial keep-alive message
        await send_keep_alive_message(bot)

        while True:
            try:
                await monitor_wallet(WATCH_WALLET, client, bot, initial_run)
                initial_run = False
            except Exception as e:
                print(f"Error monitoring wallet {WATCH_WALLET}: {e}")

            # Check if it's time to send a keep-alive message (every hour)
            current_time = datetime.utcnow()
            if current_time - last_keep_alive >= timedelta(hours=1):
                await send_keep_alive_message(bot)
                last_keep_alive = current_time

            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
