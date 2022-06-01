#!/usr/bin/env python3

import argparse
import os
import signal
import time

from cardano.wt.blockfrost import BlockfrostApi
from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine

# Vending machine internal constants (global required)
LOCKED_SUBDIR = 'in_proc'
METADATA_SUBDIR = 'metadata'
WAIT_TIMEOUT = 5

_program_is_running = True

def end_program(signum, frame):
    global _program_is_running
    _program_is_running = False

def set_interrupt_signal(end_program_func):
    signal.signal(signal.SIGINT, end_program_func)

def ensure_output_dirs_made(output_dir):
    os.makedirs(os.path.join(output_dir, LOCKED_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, METADATA_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, CardanoCli.TXN_DIR), exist_ok=True)

def get_donation_amt(do_not_donate):
    return 0 if do_not_donate else 1000000

def get_parser():
    parser = argparse.ArgumentParser(description='Generate NFTs for Mild Tangs')
    parser.add_argument('--payment-addr', required=True, help='Cardano address where mint payments are sent to')
    parser.add_argument('--payment-sign-key', required=True, help='Location on disk of wallet signing keys for payment landing zone')
    parser.add_argument('--profit-addr', required=True, help='Cardano address where mint profits should be taken (NOTE: HARDWARE/LEDGER RECOMMENDED)')
    parser.add_argument('--mint-price', type=int, required=True, help='Price in lovelace that is being charged for each NFT')
    parser.add_argument('--mint-rebate', type=int, required=True, help='Amount user expects to receive back (gross of fees)')
    parser.add_argument('--mint-policy', required=True, help='Policy ID of the mint being performed')
    parser.add_argument('--mint-script', required=True, help='Local path of scripting file for mint')
    parser.add_argument('--mint-sign-key', required=True, help='Location on disk of signing keys used for the mint')
    parser.add_argument('--protocol-params', required=True, help='Path to the protocol.json file for the network')
    parser.add_argument('--metadata-dir', required=True, help='Local folder where Cardano NFT metadata (e.g., 721s) are stored')
    parser.add_argument('--output-dir', required=True, help='Local folder where vending machine output stored')
    parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    parser.add_argument('--mainnet', action='store_true', help='Run the vending machine in production (default is testnet)')
    parser.add_argument('--no-donation', action='store_true', help='Do not send a 1₳ donation to the dev (no worries!)')
    return parser

if __name__ == "__main__":
    _args = get_parser().parse_args()

    _donation_amt = get_donation_amt(_args.no_donation)
    _mint = Mint(_args.mint_policy, _args.mint_price, _args.mint_rebate, _donation_amt, _args.metadata_dir, _args.mint_script, _args.mint_sign_key)
    _blockfrost_api = BlockfrostApi(_args.blockfrost_project, mainnet=_args.mainnet)
    _cardano_cli = CardanoCli(mainnet=_args.mainnet, protocol_params=_args.protocol_params)
    _nft_vending_machine = NftVendingMachine(_args.payment_addr, _args.payment_sign_key, _args.profit_addr, _mint, _blockfrost_api, _cardano_cli, mainnet=_args.mainnet)

    set_interrupt_signal(end_program)
    ensure_output_dirs_made(_args.output_dir)

    exclusions = set()
    while _program_is_running:
        _nft_vending_machine.vend(_args.output_dir, LOCKED_SUBDIR, METADATA_SUBDIR, exclusions)
        time.sleep(WAIT_TIMEOUT)
