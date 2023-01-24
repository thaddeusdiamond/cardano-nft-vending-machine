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
from cardano.wt.whitelist.no_whitelist import NoWhitelist
from cardano.wt.whitelist.asset_whitelist import SingleUseWhitelist, UnlimitedWhitelist
from cardano.wt.whitelist.wallet_whitelist import WalletWhitelist

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
WL_CONSUMED_DIR_SUBDIR = 'wl_consumed'
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
    os.makedirs(os.path.join(output_dir, WL_CONSUMED_DIR_SUBDIR), exist_ok=True)

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
    print(cardanocli_protocol_json)
    protocol_filename = os.path.join(output_dir, 'protocol.json')
    with open(protocol_filename, 'w') as protocol_file:
        json.dump(cardanocli_protocol_json, protocol_file)
    return protocol_filename

def get_whitelist_type(args, wl_output_dir):
    assert(not (args.no_whitelist and (args.single_use_asset_whitelist or args.unlimited_asset_whitelist)))
    if args.no_whitelist:
        return NoWhitelist()
    if args.single_use_asset_whitelist:
        return SingleUseWhitelist(args.single_use_asset_whitelist, wl_output_dir)
    if args.unlimited_asset_whitelist:
        return UnlimitedWhitelist(args.unlimited_asset_whitelist, wl_output_dir)
    if args.wallet_whitelist:
        return WalletWhitelist(args.wallet_whitelist[0], wl_output_dir, int(args.wallet_whitelist[1]))

def get_mint_price(mint_price, free_mint):
    assert(not (free_mint and mint_price))
    return 0 if free_mint else mint_price

def get_parser():
    parser = argparse.ArgumentParser(add_help=False)

    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument('--mint-price', type=int, help='Price in LOVELACE that is being charged for each NFT (min 5₳)')
    price.add_argument('--free-mint', action='store_true', help='Perform a free mint (user gets a rebate of their ADA and receives "--single-vend-max")')

    parser.add_argument('--payment-addr', required=True, help='Cardano address where mint payments are sent to')
    parser.add_argument('--payment-sign-key', required=True, help='Location on disk of wallet signing keys for payment landing zone')
    parser.add_argument('--profit-addr', required=True, help='Cardano address where mint profits should be taken (NOTE: HARDWARE/LEDGER RECOMMENDED)')
    parser.add_argument('--mint-policy', required=True, help='Policy ID of the mint being performed')
    parser.add_argument('--mint-script', required=True, help='Local path of scripting file for mint')
    parser.add_argument('--mint-sign-key', required=True, help='Location on disk of signing keys used for the mint')
    parser.add_argument('--metadata-dir', required=True, help='Local folder where Cardano NFT metadata (e.g., 721s) are stored')
    parser.add_argument('--output-dir', required=True, help='Local folder where vending machine output stored')
    parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    parser.add_argument('--mainnet', action='store_true', help='Run the vending machine in production (default is False [preprod])')
    parser.add_argument('--preview', action='store_true', help='Run the vending machine on the preview network (default is False [preprod])')
    parser.add_argument('--single-vend-max', type=int, required=True, help='Backend limit enforced on NFTs vended at once')
    parser.add_argument('--vend-randomly', action='store_true', help='Randomly pick from the metadata directory (using seed 321) when listing')
    parser.add_argument('--dev-fee', type=int, required=False, help='Developer fee (in lovelace, 1/1,000,000 ₳)')
    parser.add_argument('--dev-addr', type=str, required=False, help='Address of developer wallet to send fee to')

    whitelist = parser.add_mutually_exclusive_group(required=True)
    whitelist.add_argument('--no-whitelist', action='store_true', help='No whitelist required for mints')
    whitelist.add_argument('--single-use-asset-whitelist', type=str, help='Use an asset-based whitelist.  The provided directory should have empty files where the filenames represent asset IDs on the whitelist.  Each asset can mint exactly 1 NFT')
    whitelist.add_argument('--unlimited-asset-whitelist', type=str, help='Use an asset-based whitelist.  The provided directory should have empty files where the filenames represent asset IDs on the whitelist.  Each asset can mint unlimited NFTs')
    whitelist.add_argument('--wallet-whitelist', nargs=2, metavar=('WALLET_WHITELIST_DIR', 'WALLET_WHITELIST_NUM'), help='Use a wallet-based whitelist.  The provided directory should have empty files where the filenames represent wallet stake keys or payment addresses on the whitelist.  Each wallet can mint up to <N> NFTs')

    cli_parser = argparse.ArgumentParser(description='A vending machine for a specific NFT collection')
    subcommands = cli_parser.add_subparsers(title='subcommands', required=True, dest='command', description='valid subcommands', help='Options for the vending machine instantiation')
    subcommands.add_parser('run', help='Run the vending machine with the specified configuration', parents=[parser])
    subcommands.add_parser('validate', help='Only validate the vending machine with the specified configuration, do NOT run', parents=[parser])
    return cli_parser

if __name__ == "__main__":
    _args = get_parser().parse_args()

    set_interrupt_signal(end_program)
    seed_random()
    ensure_output_dirs_made(_args.output_dir)

    _mint_price = get_mint_price(_args.mint_price, _args.free_mint)
    _whitelist = get_whitelist_type(_args, os.path.join(_args.output_dir, WL_CONSUMED_DIR_SUBDIR))
    _dev_fee = _args.dev_fee if _args.dev_fee else 0
    _mint = Mint(_args.mint_policy, _mint_price, _dev_fee, _args.dev_addr, _args.metadata_dir, _args.mint_script, _args.mint_sign_key, _whitelist)

    _blockfrost_api = BlockfrostApi(_args.blockfrost_project, mainnet=_args.mainnet, preview=_args.preview)

    _blockfrost_protocol_params = _blockfrost_api.get_protocol_parameters()
    _protocol_params = rewritten_protocol_params(_blockfrost_protocol_params, _args.output_dir)
    max_txn_fee = (_blockfrost_protocol_params['min_fee_a'] * _blockfrost_protocol_params['max_tx_size']) + _blockfrost_protocol_params['min_fee_b']
    print(f"Max txn fee is a * size(tx) + b: {max_txn_fee}");
    _cardano_cli = CardanoCli(protocol_params=_protocol_params)

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
    _nft_vending_machine.validate()
    print(f"Initialized vending machine with the following parameters")
    print(_nft_vending_machine.as_json())

    if _args.command == 'validate':
        print('Successfully validated vending machine configuration!')
    elif _args.command == 'run':
        exclusions = set()
        while _program_is_running:
            _nft_vending_machine.vend(_args.output_dir, LOCKED_SUBDIR, METADATA_SUBDIR, exclusions)
            time.sleep(WAIT_TIMEOUT)
    else:
        raise ValueError(f"Unknown vending machine subcommand: {_args.subparser_name}")
