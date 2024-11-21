import os
from datetime import datetime, timezone
import asyncio
import json
import traceback
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey  # Use solders.Pubkey
from telegram import Bot
import aiohttp
import base64

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

# Token Program ID
TOKEN_PROGRAM_ID_STR = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_PROGRAM_ID = Pubkey.from_string(TOKEN_PROGRAM_ID_STR)

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

        # Get transaction timestamp
        block_time = txn_dict.get('blockTime')
        if block_time:
            txn_time = datetime.utcfromtimestamp(block_time).strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            txn_time = 'Unknown time'
        print(f"Transaction time: {txn_time}")

        # Extract transaction message and instructions
        transaction_message = txn_dict.get('transaction', {}).get('message', {})
        instructions = transaction_message.get('instructions', [])
        account_keys = transaction_message.get('accountKeys', [])
        print(f"Account keys: {account_keys}")

        # Map account indices to public keys
        idx_to_pubkey = [key.get('pubkey') for key in account_keys]

        # Fetch token accounts owned by the wallet
        opts = TokenAccountOpts(program_id=TOKEN_PROGRAM_ID)
        response = await client.get_token_accounts_by_owner(wallet, opts)
        owned_token_accounts = set()
        token_account_to_mint = {}
        if response.value:
            for account_info in response.value:
                token_account_pubkey = str(account_info.pubkey)
                owned_token_accounts.add(token_account_pubkey)
                # Decode account data
                account_data_base64 = account_info.account.data[0]
                account_data_bytes = base64.b64decode(account_data_base64)
                # Parse the account data to get the mint address
                if len(account_data_bytes) >= 64:
                    mint_pubkey_bytes = account_data_bytes[0:32]
                    mint_address = str(Pubkey.from_bytes(mint_pubkey_bytes))
                    token_account_to_mint[token_account_pubkey] = mint_address

        print(f"Owned token accounts: {owned_token_accounts}")

        # Process each instruction to find token transfers involving the wallet
        for instr in instructions:
            program_id = instr.get('programId')
            if program_id != TOKEN_PROGRAM_ID_STR:
                continue  # Skip if not the Token Program

            print(f"Processing Token Program instruction: {instr}")

            # Get the instruction data and decode it
            data_base64 = instr.get('data')
            data_bytes = base64.b64decode(data_base64)
            instruction_code = data_bytes[0]

            # Check if it's a Transfer or TransferChecked instruction
            if instruction_code in (3, 12):  # 3: Transfer, 12: TransferChecked
                accounts = instr.get('accounts')
                if len(accounts) < 2:
                    continue  # Not enough accounts, skip

                source_idx = accounts[0]
                dest_idx = accounts[1]

                source_account = idx_to_pubkey[source_idx]
                dest_account = idx_to_pubkey[dest_idx]

                print(f"Transfer from {source_account} to {dest_account}")

                # Check if the source or destination account is owned by the wallet
                is_source_owned = source_account in owned_token_accounts
                is_dest_owned = dest_account in owned_token_accounts

                if not (is_source_owned or is_dest_owned):
                    continue  # Neither account is owned by the wallet

                # Get the mint address
                mint = None
                if is_source_owned:
                    mint = token_account_to_mint.get(source_account)
                if is_dest_owned and not mint:
                    mint = token_account_to_mint.get(dest_account)

                if not mint:
                    print(f"Mint address not found for accounts {source_account} or {dest_account}")
                    continue

                # Amount is encoded in data bytes
                # For TransferChecked (12), amount is at bytes 1-9 (8 bytes)
                # For Transfer (3), amount is at bytes 1-9 (8 bytes)
                if len(data_bytes) >= 9:
                    amount_bytes = data_bytes[1:9]
                    amount = int.from_bytes(amount_bytes, "little")
                    # Get decimals for the token to compute ui amount
                    token_name = await get_token_name_from_mint(mint)
                    decimals = 0
                    for token in token_list:
                        if token.get('address') == mint:
                            decimals = token.get('decimals', 0)
                            break
                    ui_amount = amount / (10 ** decimals)
                else:
                    print("Amount not found in instruction data.")
                    continue

                # Determine action
                if is_source_owned and not is_dest_owned:
                    action = 'sent'
                elif is_dest_owned and not is_source_owned:
                    action = 'received'
                elif is_source_owned and is_dest_owned:
                    action = 'transferred within own accounts'
                    continue  # Ignore transfers within own accounts
                else:
                    continue  # Should not happen

                token_display_name = token_name if token_name else "this token"

                # Construct URLs
                dexscreener_url = f"https://dexscreener.com/solana/{mint}"
                solscan_token_url = f"https://solscan.io/token/{mint}"

                # Prepare the message with the requested format
                message = (
                    f"🔥🚀 Kaizen Crypto Wallet Tracker Bot Alert! 🚀🔥\n\n"
                    f"{wallet_nickname} {action} {ui_amount} of [{token_display_name}]({solscan_token_url}) with the contract address of:\n"
                    f"📝 {mint} 📝\n"
                    f"At {txn_time} 🕒\n\n"
                    f"🔗 [View on Solscan](https://solscan.io/tx/{latest_signature})\n"
                    f"🔗 [View on Dexscreener]({dexscreener_url})\n"
                    f"💰💎📈"
                )
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
                print("Sent transaction alert message.")
                break  # Only process the first relevant transfer

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
