#!/usr/bin/env python3

import argparse
import json
import os
import random
import signal
import time

from cardano.wt.blockfrost import BlockfrostApi
from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.utxo import Utxo

# Blockfrost gives the wrong format back for protocol parameters so here's a translator
BLOCKFROST_PROTOCOL_TRANSLATOR = {
    'decentralization': 'decentralisation_param',
    'extraPraosEntropy': 'extra_entropy',
    'maxBlockBodySize': 'max_block_size',
    'maxBlockHeaderSize': 'max_block_header_size',
    'minPoolCost': 'min_pool_cost',
    'maxTxSize': 'max_tx_size',
    'minUTxOValue': 'min_utxo',
    'monetaryExpansion': 'rho',
    'poolPledgeInfluence': 'a0',
    'poolRetireMaxEpoch': 'e_max', 
    'protocolVersion': {
        'minor': 'protocol_minor_ver',
        'major': 'protocol_major_ver'
    },
    'stakeAddressDeposit': 'key_deposit',
    'stakePoolDeposit': 'pool_deposit',
    'stakePoolTargetNum': 'n_opt',
    'treasuryCut': 'tau',
    'txFeeFixed': 'min_fee_b',
    'txFeePerByte': 'min_fee_a'
}

# Vending machine internal constants (global required)
LOCKED_SUBDIR = 'in_proc'
METADATA_SUBDIR = 'metadata'
WAIT_TIMEOUT = 15

_program_is_running = True

def end_program(signum, frame):
    global _program_is_running
    _program_is_running = False

def set_interrupt_signal(end_program_func):
    signal.signal(signal.SIGINT, end_program_func)

def seed_random():
    random.seed(321)

def ensure_output_dirs_made(output_dir):
    os.makedirs(os.path.join(output_dir, LOCKED_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, METADATA_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, CardanoCli.TXN_DIR), exist_ok=True)

def generate_cardano_cli_protocol(translator, blockfrost_input):
    translated = {}
    for entry in translator:
        translation = translator[entry]
        if type(translation) is dict:
            translated[entry] = generate_cardano_cli_protocol(translation, blockfrost_input)
        else:
            input_val = blockfrost_input[translation]
            if type(input_val) is str and input_val.isdigit():
                translated[entry] = int(input_val)
            else:
                translated[entry] = input_val
    return translated

def rewritten_protocol_params(blockfrost_protocol_json, output_dir):
    cardanocli_protocol_json = generate_cardano_cli_protocol(BLOCKFROST_PROTOCOL_TRANSLATOR, blockfrost_protocol_json)
    protocol_filename = os.path.join(output_dir, 'protocol.json')
    with open(protocol_filename, 'w') as protocol_file:
        json.dump(cardanocli_protocol_json, protocol_file)
    return protocol_filename

def get_donation_amt(do_not_donate, free_mint):
    return 0 if (do_not_donate or free_mint) else 1000000

def get_mint_price(mint_price, free_mint):
    assert(not (free_mint and mint_price))
    if mint_price and mint_price < Utxo.MIN_UTXO_VALUE:
        raise ValueError(f'Provided mint price of {mint_price} but minimum allowed is {Utxo.MIN_UTXO_VALUE}')
    return 0 if free_mint else mint_price

def get_parser():
    parser = argparse.ArgumentParser(description='Generate NFTs for Mild Tangs')

    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument('--mint-price', type=int, help='Price in lovelace that is being charged for each NFT (min 1₳)')
    price.add_argument('--free-mint', action='store_true', help='Perform a free mint (user rebates all ADA')

    parser.add_argument('--payment-addr', required=True, help='Cardano address where mint payments are sent to')
    parser.add_argument('--payment-sign-key', required=True, help='Location on disk of wallet signing keys for payment landing zone')
    parser.add_argument('--profit-addr', required=True, help='Cardano address where mint profits should be taken (NOTE: HARDWARE/LEDGER RECOMMENDED)')
    parser.add_argument('--mint-policy', required=True, help='Policy ID of the mint being performed')
    parser.add_argument('--mint-script', required=True, help='Local path of scripting file for mint')
    parser.add_argument('--mint-sign-key', required=True, help='Location on disk of signing keys used for the mint')
    parser.add_argument('--metadata-dir', required=True, help='Local folder where Cardano NFT metadata (e.g., 721s) are stored')
    parser.add_argument('--output-dir', required=True, help='Local folder where vending machine output stored')
    parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    parser.add_argument('--mainnet', action='store_true', help='Run the vending machine in production (default is testnet)')
    parser.add_argument('--single-vend-max', type=int, required=False, help='Backend limit enforced on NFTs vended at once (recommended)')
    parser.add_argument('--vend-randomly', action='store_true', help='Randomly pick from the metadata directory (using seed 321) when listing')
    parser.add_argument('--no-donation', action='store_true', help='Do not send a 1₳ donation to the dev (no worries!)')
    return parser

if __name__ == "__main__":
    _args = get_parser().parse_args()

    set_interrupt_signal(end_program)
    seed_random()
    ensure_output_dirs_made(_args.output_dir)

    _mint_price = get_mint_price(_args.mint_price, _args.free_mint)
    _donation_amt = get_donation_amt(_args.no_donation, _args.free_mint)
    _mint = Mint(_args.mint_policy, _mint_price, _donation_amt, _args.metadata_dir, _args.mint_script, _args.mint_sign_key)

    _blockfrost_api = BlockfrostApi(_args.blockfrost_project, mainnet=_args.mainnet)

    _blockfrost_protocol_params = _blockfrost_api.get_protocol_parameters()
    _protocol_params = rewritten_protocol_params(_blockfrost_protocol_params, _args.output_dir)
    max_txn_fee = (_blockfrost_protocol_params['min_fee_a'] * _blockfrost_protocol_params['max_tx_size']) + _blockfrost_protocol_params['min_fee_b']
    print(f"Max txn fee is a * size(tx) + b: {max_txn_fee}");
    _cardano_cli = CardanoCli(mainnet=_args.mainnet, protocol_params=_protocol_params)

    _nft_vending_machine = NftVendingMachine(
            _args.payment_addr,
            _args.payment_sign_key,
            _args.profit_addr,
            _args.vend_randomly,
            _args.single_vend_max,
            _mint,
            _blockfrost_api,
            _cardano_cli,
            mainnet=_args.mainnet
    )

    exclusions = set()
    while _program_is_running:
        _nft_vending_machine.vend(_args.output_dir, LOCKED_SUBDIR, METADATA_SUBDIR, exclusions)
        time.sleep(WAIT_TIMEOUT)
