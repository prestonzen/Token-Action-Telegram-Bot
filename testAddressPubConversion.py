from solders.pubkey import Pubkey

try:
    address = Pubkey.from_string("HH3eXS4ysQQLJCusWqoNboqrPHuYRYF75abXoJihpump")
    print(f"Valid address: {address}")
except ValueError as e:
    print(f"Invalid address: {e}")