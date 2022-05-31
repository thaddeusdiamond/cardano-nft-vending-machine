#!/usr/bin/env python3

import argparse
import json
import math
import os
import shutil
import signal
import time

from cardano.wt.blockfrost import BlockfrostApi
from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.utxo import Utxo

# Cardano network constants
ADA_TO_LOVELACE = 1000000
ONE_ADA = 1 * ADA_TO_LOVELACE
WITNESS_COUNT = 2
ZERO_ADA = 0 * ADA_TO_LOVELACE

# Vending machine internal constants (global required)
LOCKED_SUBDIR = 'in_proc'
METADATA_SUBDIR = 'metadata'
WAIT_TIMEOUT = 5
_program_is_running = True

def nfts_as_cli(nft_names, mint):
    return '+'.join(['.'.join([f"1 {mint.policy}", nft_name]) for nft_name in nft_names])

def get_tx_out_args(input_addr, change, nft_names, profit_addr, total_profit, donation_addr, total_donation, mint):
    user_tokens = filter(None, [input_addr, str(change), nfts_as_cli(nft_names, mint)])
    user_output = f"--tx-out '{'+'.join(user_tokens)}'"
    profit_output = f"--tx-out '{profit_addr}+{total_profit}'" if total_profit else '' 
    donation_output = f"--tx-out '{donation_addr}+{total_donation}'" if total_donation else ''
    return [user_output, profit_output, donation_output]

def generate_nft_names_from(metadata_file, mint):
    with open(metadata_file, 'r') as metadata_filehandle:
        policy_json = json.load(metadata_filehandle)['721'][mint.policy]
        names = policy_json.keys()
        return [name.encode('UTF-8').hex() for name in names]

def lock_and_merge(available_mints, num_mints, mint, output_dir, txn_id):
    combined_nft_metadata = {}
    for i in range(num_mints):
        mint_metadata_filename = available_mints.pop()
        mint_metadata_orig = os.path.join(mint.nfts_dir, mint_metadata_filename)
        with open(mint_metadata_orig, 'r') as mint_metadata_handle:
            mint_metadata = json.load(mint_metadata_handle)
            for nft_name, nft_metadata in mint_metadata['721'][mint.policy].items():
                if nft_name in combined_nft_metadata:
                    raise ValueError(f"Duplicate NFT metadata for {nft_name} found")
                combined_nft_metadata[nft_name] = nft_metadata
        mint_metadata_locked = os.path.join(output_dir, LOCKED_SUBDIR, mint_metadata_filename)
        shutil.move(mint_metadata_orig, mint_metadata_locked)
    combined_output_path = os.path.join(output_dir, METADATA_SUBDIR, f"{txn_id}.json")
    with open(combined_output_path, 'w') as combined_metadata_handle:
        json.dump({'721': { mint.policy : combined_nft_metadata }}, combined_metadata_handle)
    return combined_output_path

def run_vending_machine(payment_addr, payment_sign_key, profit_addr, donation_addr, mint, output_dir, cardano_cli, blockfrost_api):
    exclusions = set()
    while _program_is_running:
        mint_reqs = cardano_cli.get_utxos(payment_addr, exclusions) 
        for mint_req in mint_reqs:
            available_mints = os.listdir(mint.nfts_dir)
            if not available_mints:
                print("Metadata directory is empty, please restock the vending machine...")
                break

            input_addr = blockfrost_api.get_input_address(mint_req.hash)
            lovelace_bals = [balance for balance in mint_req.balances if balance.policy == Utxo.Balance.LOVELACE_POLICY]
            if len(lovelace_bals) != 1:
                raise ValueError(f"Found too many/few lovelace balances for UTXO {mint_req}")

            lovelace_bal = lovelace_bals.pop()
            num_mints = min(len(available_mints), math.floor((lovelace_bal.lovelace - mint.rebate) / mint.price))
            total_profit = num_mints * (mint.price - mint.donation) 
            total_donation = num_mints * mint.donation
            change = lovelace_bal.lovelace - (total_profit + total_donation)
            print(f"Beginning to mint {num_mints} NFTs to send to address {input_addr} (change: {change})")

            exclusions.add(mint_req)

            txn_id = int(time.time())
            nft_metadata_file = lock_and_merge(available_mints, num_mints, mint, output_dir, txn_id)
            nft_names = generate_nft_names_from(nft_metadata_file, mint)
            tx_ins = [f"--tx-in {mint_req.hash}#{mint_req.ix}"]
            tx_outs = get_tx_out_args(input_addr, change, nft_names, profit_addr, total_profit, donation_addr, total_donation, mint)
            mint_build_tmp = cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, 0, nft_metadata_file, mint, nft_names)

            tx_in_count = len(tx_ins)
            tx_out_count = len([tx_out for tx_out in tx_outs if tx_out])
            fee = cardano_cli.calculate_min_fee(mint_build_tmp, tx_in_count, tx_out_count, WITNESS_COUNT)

            tx_outs = get_tx_out_args(input_addr, change - fee, nft_names, profit_addr, total_profit, donation_addr, total_donation, mint)
            mint_build = cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, fee, nft_metadata_file, mint, nft_names)
            mint_signed = cardano_cli.sign_txn([payment_sign_key, mint.sign_key], mint_build)
            cardano_cli.submit_txn(mint_signed)
        time.sleep(WAIT_TIMEOUT)

def ensure_output_dirs_made(output_dir):
    os.makedirs(os.path.join(output_dir, LOCKED_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, METADATA_SUBDIR), exist_ok=True)
    os.makedirs(os.path.join(output_dir, CardanoCli.TXN_DIR), exist_ok=True)

def end_program(signum, frame):
    global _program_is_running
    _program_is_running = False

def set_interrupt_signal(end_program_func):
    signal.signal(signal.SIGINT, end_program_func)

def get_network(mainnet):
    return MAINNET_PARAM if mainnet else TESTNET_PARAM

def get_donation_addr(mainnet):
    return 'addr1qx2skanhkpgdhcyxnczydg3meqcv87z4vep7u2drrr6277v5entql0xseq6a4zs8j524wvwv6k46kpf8pt9ejjk6l9gs4g94mf' if mainnet else 'addr_test1vrce7uwk8vcva5j4dmehrxprwy57x20yaz9cv9vqzjutnnsrgrfey'

def get_donation_amt(do_not_donate):
    return ZERO_ADA if do_not_donate else ONE_ADA

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
    parser.add_argument('--metadata-dir', required=True, help='Local folder where Cardano NFT metadata (e.g., 721s) are stored')
    parser.add_argument('--output-dir', required=True, help='Local folder where vending machine output stored')
    parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    parser.add_argument('--mainnet', action='store_true', help='Run the vending machine in production (default is testnet)')
    parser.add_argument('--no-donation', action='store_true', help='Do not send a 1₳ donation to the dev (no worries!)')
    return parser

if __name__ == "__main__":
    _args = get_parser().parse_args()
    _donation_amt = get_donation_amt(_args.no_donation)
    _donation_addr = get_donation_addr(_args.mainnet)
    _mint = Mint(_args.mint_policy, _args.mint_price, _args.mint_rebate, _donation_amt, _args.metadata_dir, _args.mint_script, _args.mint_sign_key)
    _blockfrost_api = BlockfrostApi(_args.blockfrost_project, mainnet=_args.mainnet)
    _cardano_cli = CardanoCli(mainnet=_args.mainnet)
    set_interrupt_signal(end_program)
    ensure_output_dirs_made(_args.output_dir)
    run_vending_machine(_args.payment_addr, _args.payment_sign_key, _args.profit_addr, _donation_addr, _mint, _args.output_dir, _cardano_cli, _blockfrost_api)
