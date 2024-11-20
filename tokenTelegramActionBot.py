from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from telegram import Bot
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot API token and Chat ID from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Solana network setup
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
TARGET_ADDRESS = Pubkey.from_string(os.getenv("TARGET_ADDRESS"))

# Initialize Solana and Telegram clients
solana_client = AsyncClient(SOLANA_RPC_URL)
telegram_bot = Bot(token=TELEGRAM_TOKEN)

async def get_recent_transactions(address):
    # Fetch recent transactions for the target address
    response = await solana_client.get_signatures_for_address(address, limit=1)
    if response.value:
        return response.value
    return []

async def get_transaction_details(signature):
    # Fetch transaction details for a given signature
    response = await solana_client.get_transaction(
        signature,
        max_supported_transaction_version=0
    )
    if response.value:
        tx_details = response.value
        return tx_details
    return None

async def check_transaction():
    seen_signatures = set()
    
    while True:
        try:
            transactions = await get_recent_transactions(TARGET_ADDRESS)

            if transactions:
                for tx in transactions:
                    signature = tx['signature']

                    if signature not in seen_signatures:
                        seen_signatures.add(signature)

                        # Fetch transaction details
                        tx_details = await get_transaction_details(signature)
                        if tx_details:
                            # Access the meta data as a dictionary
                            meta = tx_details.get('meta', {})
                            if meta:
                                pre_balances = meta.get('preTokenBalances', [])
                                post_balances = meta.get('postTokenBalances', [])

                                # Calculate the amount purchased
                                if pre_balances and post_balances:
                                    pre_balance = int(pre_balances[0]['uiTokenAmount']['amount'])
                                    post_balance = int(post_balances[0]['uiTokenAmount']['amount'])
                                    decimals = pre_balances[0]['uiTokenAmount']['decimals']
                                    amount_bought = (post_balance - pre_balance) / (10 ** decimals)

                                    # Assuming a fixed price for $BALLZ
                                    price_per_token_usd = float(os.getenv("PRICE_PER_TOKEN_USD", "1"))
                                    total_usd = amount_bought * price_per_token_usd

                                    # Post a message to Telegram
                                    await telegram_bot.send_message(
                                        chat_id=CHAT_ID,
                                        text=f"Someone went BALLZ DEEP and bought {amount_bought:.2f} $BALLZ (${total_usd:.2f} equivalent)"
                                    )

        except Exception as e:
            print(f"Error checking transactions: {e}")

        # Wait before checking again
        await asyncio.sleep(10)

async def main():
    try:
        await check_transaction()
    finally:
        await solana_client.close()  # Ensure the client is closed properly

# Run the bot
if __name__ == "__main__":
    asyncio.run(main())
