import os
import time
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from telegram import Bot

# Load environment variables from .env file
load_dotenv()

# Configuration variables
TELEGRAM_BOT_TOKEN = os.getenv('Kaizen_Apps_Telegram_Token')
TELEGRAM_CHAT_ID = os.getenv('Kaizen_Telegram_group_ID')
SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
PRICE_PER_TOKEN_USD = float(os.getenv('PRICE_PER_TOKEN_USD', '1'))

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

# Initialize Solana client and Telegram bot
client = Client(SOLANA_RPC_URL)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Keep track of last processed signature
last_signature = None

def get_token_name_from_mint(mint_address):
    # Implement a mapping or API call to get the token name from mint address
    # For simplicity, we'll return the mint address itself
    return mint_address

def monitor_wallet(wallet):
    global last_signature

    # Get recent transaction signatures
    response = client.get_signatures_for_address(wallet, limit=10)
    if response.value is None:
        return

    signatures = response.value
    if not signatures:
        return

    latest_signature = signatures[0].signature
    wallet_str = str(wallet)

    if last_signature is None:
        last_signature = latest_signature
        return  # Skip processing on the first run

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
        txn_resp = client.get_transaction(sig, encoding='jsonParsed')
        if txn_resp.value is None:
            continue

        txn = txn_resp.value
        meta = txn.meta
        if meta is None:
            continue

        pre_balances = meta.pre_token_balances or []
        post_balances = meta.post_token_balances or []

        # Map account indices to public keys
        account_keys = [str(key.pubkey) for key in txn.transaction.message.account_keys]

        # Build balances before and after the transaction
        balances = {}
        for balance in pre_balances + post_balances:
            idx = balance.account_index
            owner = balance.owner or account_keys[idx]
            mint = balance.mint
            amount_info = balance.ui_token_amount
            amount = float(amount_info.ui_amount_string) if amount_info.ui_amount_string is not None else 0
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
                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

    # Update the last processed signature
    last_signature = latest_signature

def main():
    while True:
        try:
            monitor_wallet(WATCH_WALLET)
        except Exception as e:
            print(f"Error monitoring wallet {WATCH_WALLET}: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
