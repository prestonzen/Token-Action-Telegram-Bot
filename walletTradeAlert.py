import os
from datetime import datetime, timezone
import asyncio
import json
import traceback
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from telegram import Bot
import aiohttp

# Load environment variables from .env file
load_dotenv()

# Configuration variables
TELEGRAM_BOT_TOKEN = os.getenv('Kaizen_Apps_Telegram_Token')
TELEGRAM_CHAT_ID = os.getenv('Kaizen_Telegram_group_ID')
SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Get the wallet address and nickname from the .env file
wallet_address = os.getenv('Watch_Wallet_1')
wallet_nickname = os.getenv('Watch_Wallet_1_Nickname', 'Wallet')

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

# Token list cache
token_list = None

async def get_token_name_from_mint(mint_address):
    global token_list
    if token_list is None:
        # Fetch the token list
        url = 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json'
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    # Read the response text and parse JSON manually
                    text_data = await resp.text()
                    data = json.loads(text_data)
                    token_list = data.get('tokens', [])
                else:
                    token_list = []

    # Search for the token in the token list
    for token in token_list:
        if token.get('address') == mint_address:
            symbol = token.get('symbol', mint_address)
            return symbol
    # If not found, return mint address
    return mint_address

async def send_keep_alive_message(bot):
    message = f"🔥 {wallet_nickname} Tracker Bot is active! 🔥"
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

async def monitor_wallet(wallet, client, bot):
    global last_signature

    try:
        # Get recent transaction signatures
        response = await client.get_signatures_for_address(wallet, limit=1)  # Process only the latest transaction
        if response.value is None or not response.value:
            return

        signature_info = response.value[0]
        latest_signature = signature_info.signature

        # Skip processing if the latest signature has already been processed
        if latest_signature == last_signature:
            return

        # Process the latest transaction
        txn_resp = await client.get_transaction(latest_signature, encoding='jsonParsed')
        if txn_resp.value is None:
            return

        txn = txn_resp.value
        # Convert transaction to JSON string and then to dictionary
        txn_json = txn.to_json()
        txn_dict = json.loads(txn_json)
        meta = txn_dict.get('meta')
        if meta is None:
            return

        pre_balances = meta.get('preTokenBalances', [])
        post_balances = meta.get('postTokenBalances', [])

        # Map account indices to public keys
        account_keys = [key.get('pubkey') for key in txn_dict.get('transaction', {}).get('message', {}).get('accountKeys', [])]

        # Build balances before and after the transaction
        balances = {}
        for balance in pre_balances + post_balances:
            idx = balance.get('accountIndex')
            if idx is None or idx >= len(account_keys):
                continue  # Skip if index is invalid

            owner = balance.get('owner') or account_keys[idx]
            mint = balance.get('mint')
            amount_info = balance.get('uiTokenAmount')
            amount_str = amount_info.get('uiAmountString') if amount_info else None
            amount = float(amount_str) if amount_str is not None else 0
            key = (owner, mint)
            if balance in pre_balances:
                balances.setdefault(key, {})['pre'] = amount
            else:
                balances.setdefault(key, {})['post'] = amount

        # Get transaction timestamp
        block_time = txn_dict.get('blockTime')
        if block_time:
            txn_time = datetime.utcfromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            txn_time = 'Unknown time'

        # Detect changes in balances
        for (owner, mint), amounts in balances.items():
            pre_amount = amounts.get('pre', 0)
            post_amount = amounts.get('post', 0)
            delta = post_amount - pre_amount
            if delta != 0 and owner == wallet_address:
                action = 'bought' if delta > 0 else 'sold'
                token_name = await get_token_name_from_mint(mint)
                amount = abs(delta)
                # Construct Dexscreener URL
                dexscreener_url = f"https://dexscreener.com/solana/{mint}"
                # Prepare the message with the requested format
                message = (
                    f"🔥🚀 {wallet_nickname} Tracker Bot Alert! 🚀🔥\n\n"
                    f"{wallet_nickname} {action} {amount} of {token_name} with the contract address of:\n"
                    f"📝 {mint} 📝\n"
                    f"At {txn_time} 🕒\n\n"
                    f"🔗 [View on Dexscreener]({dexscreener_url})\n"
                    f"💰💎📈"
                )
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
                break  # Only process the first relevant change

        # Update the last processed signature
        last_signature = latest_signature

    except Exception as e:
        print(f"Error in monitor_wallet: {e}")
        traceback.print_exc()

async def main():
    # Initialize Solana client and Telegram bot within the async context
    async with AsyncClient(SOLANA_RPC_URL) as client, Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        # Send initial keep-alive message
        await send_keep_alive_message(bot)

        while True:
            try:
                await monitor_wallet(WATCH_WALLET, client, bot)
            except Exception as e:
                print(f"Error monitoring wallet: {e}")
                traceback.print_exc()

            await asyncio.sleep(60)  # Check every 60 seconds

if __name__ == "__main__":
    asyncio.run(main())
