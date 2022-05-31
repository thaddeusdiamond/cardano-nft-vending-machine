#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import requests
import shutil
import signal
import subprocess
import time

"""
Simple UTXO object to strengthen the type of CLI-returned strings
"""
class Utxo(object):

    class Balance(object):
        LOVELACE_POLICY = 'lovelace'

        def __init__(self, lovelace, policy):
            self.lovelace = lovelace
            self.policy = policy if policy else Balance.LOVELACE_POLICY

        def __repr__(self):
            return f"{self.lovelace} {self.policy}"


    def __init__(self, hash, ix, balances):
        self.hash = hash
        self.ix = ix
        self.balances = balances

    def __eq__(self, other):
        return isinstance(other, Utxo) and (self.hash == other.hash and self.ix == other.ix)

    def __hash__(self):
        return hash((self.hash, self.ix))

    def __repr__(self):
        return f"{self.hash}#{self.ix} {self.balances}"

    def from_cli(cli_str):
        utxo_data = re.split('\s+', cli_str)
        balance_strs = [balance.strip() for balance in ' '.join(utxo_data[2:]).split('+')]
        balances = []
        for balance_str in balance_strs:
            try:
                balances.append(Utxo.Balance(int(balance_str.split(' ')[0]), balance_str.split(' ')[1]))
            except ValueError:
                continue
        return Utxo(utxo_data[0], utxo_data[1], balances)

""""
Representation of the current minting process.
"""
class Mint(object):

    def __init__(self, policy, price, rebate, donation, nfts_dir, script, sign_key):
        self.policy = policy
        self.price = price
        self.rebate = rebate
        self.donation = donation
        self.nfts_dir = nfts_dir
        self.script = script
        self.sign_key = sign_key

"""
cardano-cli *nix script representation in Python
"""
class CardanoCli(object):

    _PPARAMS_FILE = 'protocol.json'
    _WITNESS_COUNT = 1

    _MAINNET_PARAM = '--mainnet'
    _TESTNET_PARAM = '--testnet-magic 1097911063'

    TXN_DIR = 'txn'

    def __init__(self, mainnet=False):
        self.__mainnet = mainnet

    def __run_script(self, cardano_args, add_network=True):
        cmd = f'cardano-cli {cardano_args} {self.__get_network_flag() if add_network else ""}'
        print(cmd)
        cli_cmd = subprocess.Popen(cmd,  shell=True, text=True, stdout=subprocess.PIPE)
        (out, err) = cli_cmd.communicate()
        print(f'[STDOUT] {out}')
        print(f'[STDERR] {err}')
        return out

    def __get_network_flag(self):
       return self._MAINNET_PARAM if self.__mainnet else self._TESTNET_PARAM

    def get_utxos(self, address, exclusions):
        output = self.__run_script(f'query utxo --address {address}') 
        out_lines = output.strip().split('\n')
        available_utxos = set()
        #print('EXCLUSIONS\t', [f'{utxo.hash}#{utxo.ix}' for utxo in exclusions])
        for out_line in out_lines[2:]:
            utxo = Utxo.from_cli(out_line)
            if utxo in exclusions:
                print(f'Skipping {utxo.hash}#{utxo.ix}')
                continue
            available_utxos.add(utxo)
        return available_utxos

    def build_txn(self, output_dir, txn_id, change_addr, tx_in_args, tx_out_args, metadata_json_file, witness_override, addl_args): 
        build_file = os.path.join(output_dir, CardanoCli.TXN_DIR, f"txn_{txn_id}.build")
        self.__run_script(
            f'transaction build --alonzo-era {" ".join(tx_in_args)} {" ".join(tx_out_args)} --change-address {change_addr} \
                --metadata-json-file {metadata_json_file} --witness-override {witness_override} --out-file {build_file} {" ".join(addl_args)}'
        )
        return build_file

    def build_mint_txn(self, output_dir, txn_id, change_addr, tx_in_args, tx_out_args, metadata_json_file, witness_override, mint, nft_names): 
        mint_args = [f"--mint='{nfts_as_cli(nft_names, mint)}'", f"--minting-script-file {mint.script}"] if nft_names else []
        return self.build_txn(output_dir, txn_id, change_addr, tx_in_args, tx_out_args, metadata_json_file, witness_override, mint_args)

    def build_raw_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, addl_args):
        raw_build_file = os.path.join(output_dir, CardanoCli.TXN_DIR, f"txn_{txn_id}.raw.build")
        self.__run_script(
            f'transaction build-raw --fee {fee} --alonzo-era {" ".join(tx_out_args)} {" ".join(tx_in_args)} \
                --metadata-json-file {metadata_json_file} --out-file {raw_build_file} {" ".join(addl_args)}',
            add_network=False
        )
        return raw_build_file
    
    def build_raw_mint_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint, nft_names): 
        mint_args = [f"--mint='{nfts_as_cli(nft_names, mint)}'", f"--minting-script-file {mint.script}"] if nft_names else []
        return self.build_raw_txn(output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint_args)
   
    def calculate_min_fee(self, raw_build_file, tx_in_count, tx_out_count, witness_count):
        lovelace_fee_str = self.__run_script(
            f'transaction calculate-min-fee --tx-body-file {raw_build_file} --tx-in-count {tx_in_count} \
              --tx-out-count {tx_out_count} --witness-count {witness_count} --protocol-params-file {self._PPARAMS_FILE}' 
        )
        return int(lovelace_fee_str.split(' ')[0])

    def sign_txn(self, signing_files, build_file):
        signed_file = f"{build_file}.signed"
        signing_key_args = ' '.join([f"--signing-key-file {signing_file}" for signing_file in signing_files])
        self.__run_script(f'transaction sign {signing_key_args} --tx-body-file {build_file} --out-file {signed_file}')
        return signed_file

    def submit_txn(self, signed_file):
        self.__run_script(f'transaction submit --tx-file {signed_file}')
        pass

    def _write_metadata_file(self, txn_id, metadata):
        metadata_json_file = f'metadata/metadata_{txn_id}.json'
        with open(metadata_json_file, 'w') as metadata_json_file_out:
            metadata_json_file_out.write(json.dumps(metadata))
        return metadata_json_file

"""
Repreentation of the Blockfrost web API used in retrieving metadata about txn i/o on the chain.
"""
class BlockfrostApi(object):
    def __init__(self, project, mainnet=False):
        self.project = project
        self.mainnet = mainnet

    def __get_api_base(self):
        return "https://cardano-{'mainnet' if self.mainnet else 'testnet'}.blockfrost.io/api/v0"

    def __call_api(self, resource):
        return requests.get(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project})

    def get_input_address(self, txn_hash):
        utxo_metadata = self.__call_api(f"txs/{txn_hash}/utxos").json()
        print(utxo_metadata)
        utxo_inputs = set([utxo_input['address'] for utxo_input in utxo_metadata['inputs']])
        if len(utxo_inputs) != 1:
            raise ValueError(f"Txn hash {txn_hash} came from != 1 addresses({utxo_inputs}), aborting...")
        return utxo_inputs.pop()

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
