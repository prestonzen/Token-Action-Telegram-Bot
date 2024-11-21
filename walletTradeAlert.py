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

wallet_address = wallet_address.strip()
wallet_address_lower = wallet_address.lower()

try:
    WATCH_WALLET = Pubkey.from_string(wallet_address)
except ValueError as e:
    print(f"Invalid wallet address: {e}")
    exit(1)

# Keep track of last processed signature
last_signature = None

# Token list cache
token_list = None

# Known exchange program IDs
EXCHANGE_PROGRAM_IDS = {
    'Serum DEX': '9xQeWvG816bUx9EPuJ9p6gNZQY39Yod89VLvT93mC8Ln',
    'Raydium Swap': 'RVKd61ztZW9jzWz6pL9dp25o7FH5DVV7PQQ3hqRvnkW',
    # Add other known program IDs as needed
}

async def get_token_name_from_mint(mint_address):
    global token_list
    if token_list is None:
        print("Fetching token list...")
        # Fetch the token list
        url = 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json'
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        # Read the response text and parse JSON manually
                        text_data = await resp.text()
                        data = json.loads(text_data)
                        token_list = data.get('tokens', [])
                        print(f"Fetched {len(token_list)} tokens.")
                    else:
                        print(f"Failed to fetch token list. Status code: {resp.status}")
                        token_list = []
            except Exception as e:
                print(f"Exception while fetching token list: {e}")
                token_list = []

    # Search for the token in the token list
    for token in token_list:
        if token.get('address') == mint_address:
            symbol = token.get('symbol', None)
            name = token.get('name', None)
            print(f"Found token symbol '{symbol}' for mint address {mint_address}.")
            return symbol or name or None
    # If not found, return None
    print(f"Token symbol not found for mint address {mint_address}.")
    return None

def is_purchase_transaction(instructions):
    for instr in instructions:
        program_id = instr.get('programId')
        if program_id in EXCHANGE_PROGRAM_IDS.values():
            print(f"Transaction involves known exchange program: {program_id}")
            return True
    return False

async def send_keep_alive_message(bot):
    message = f"🔥 Kaizen Crypto Wallet Tracker Bot is active! 🔥"
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    print("Sent keep-alive message.")

async def monitor_wallet(wallet, client, bot):
    global last_signature

    try:
        print("Fetching recent transaction signatures...")
        # Get recent transaction signatures
        response = await client.get_signatures_for_address(wallet, limit=1)
        if response.value is None or not response.value:
            print("No transaction signatures found.")
            return

        signature_info = response.value[0]
        latest_signature = signature_info.signature
        print(f"Latest signature: {latest_signature}")

        # Skip processing if the latest signature has already been processed
        if latest_signature == last_signature:
            print("No new transactions to process.")
            return

        print(f"Processing transaction {latest_signature} for wallet {wallet_address}")

        # Process the latest transaction
        txn_resp = await client.get_transaction(
            latest_signature,
            encoding='jsonParsed',
            max_supported_transaction_version=0
        )
        if txn_resp.value is None:
            print("Transaction details not found.")
            return

        txn = txn_resp.value
        txn_json = txn.to_json()
        txn_dict = json.loads(txn_json)
        meta = txn_dict.get('meta')
        if meta is None:
            print("Transaction metadata not found.")
            return

        pre_balances = meta.get('preTokenBalances', [])
        post_balances = meta.get('postTokenBalances', [])
        print(f"Pre-token balances: {pre_balances}")
        print(f"Post-token balances: {post_balances}")

        # Map account indices to public keys
        account_keys = [key.get('pubkey') for key in txn_dict.get('transaction', {}).get('message', {}).get('accountKeys', [])]
        print(f"Account keys: {account_keys}")

        balances = {}
        for balance in pre_balances + post_balances:
            idx = balance.get('accountIndex')
            if idx is None or idx >= len(account_keys):
                print(f"Invalid account index {idx}. Skipping balance entry.")
                continue  # Skip if index is invalid

            owner = balance.get('owner')
            if owner is None:
                owner = account_keys[idx]

            owner = str(owner).strip().lower()
            mint = balance.get('mint')
            amount_info = balance.get('uiTokenAmount')
            amount_str = amount_info.get('uiAmountString') if amount_info else None
            amount = float(amount_str) if amount_str is not None else 0
            key = (owner, mint)
            if balance in pre_balances:
                balances.setdefault(key, {})['pre'] = amount
            else:
                balances.setdefault(key, {})['post'] = amount

            print(f"Processed balance entry: Owner={owner}, Mint={mint}, Amount={amount}")

        # Get transaction timestamp
        block_time = txn_dict.get('blockTime')
        if block_time:
            txn_time = datetime.utcfromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            txn_time = 'Unknown time'
        print(f"Transaction time: {txn_time}")

        # Extract transaction instructions
        transaction_message = txn_dict.get('transaction', {}).get('message', {})
        instructions = transaction_message.get('instructions', [])
        is_purchase = is_purchase_transaction(instructions)

        # Detect changes in balances
        for (owner, mint), amounts in balances.items():
            pre_amount = amounts.get('pre', 0)
            post_amount = amounts.get('post', 0)
            delta = post_amount - pre_amount

            print(f"Owner: {owner}, Mint: {mint}, Pre-Amount: {pre_amount}, Post-Amount: {post_amount}, Delta: {delta}")

            if delta != 0 and owner == wallet_address_lower:
                if delta > 0:
                    if is_purchase:
                        action = 'bought'
                    else:
                        action = 'received'
                else:
                    if is_purchase:
                        action = 'sold'
                    else:
                        action = 'sent'

                token_name = await get_token_name_from_mint(mint)
                amount = abs(delta)
                # Construct URLs
                dexscreener_url = f"https://dexscreener.com/solana/{mint}"
                solscan_token_url = f"https://solscan.io/token/{mint}"
                # Use "this token" as per your request
                token_display_name = token_name if token_name else "this token"
                # Prepare the message with the requested format
                message = (
                    f"🔥🚀 Kaizen Crypto Wallet Tracker Bot Alert! 🚀🔥\n\n"
                    f"{wallet_nickname} {action} {amount} of [{token_display_name}]({solscan_token_url}) with the contract address of:\n"
                    f"📝 {mint} 📝\n"
                    f"At {txn_time} 🕒\n\n"
                    f"🔗 [View on Solscan]({solscan_token_url})\n"
                    f"🔗 [View on Dexscreener]({dexscreener_url})\n"
                    f"💰💎📈"
                )
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
                print("Sent transaction alert message.")
                break  # Only process the first relevant change
            else:
                print(f"Owner {owner} does not match the monitored wallet {wallet_address_lower} or delta is zero.")

        # Update the last processed signature
        last_signature = latest_signature
        print(f"Updated last_signature to {last_signature}")

    except Exception as e:
        print(f"Error in monitor_wallet: {e}")
        traceback.print_exc()

async def main():
    print("Starting wallet trade alert bot...")
    print(f"Monitoring wallet: {wallet_address} ({wallet_nickname})")
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
