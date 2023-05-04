import json
import os
import subprocess
import tempfile

from deprecated import deprecated

from cardano.wt import network
from cardano.wt.utxo import Utxo

"""
cardano-cli *nix script representation in Python
"""
class CardanoCli(object):

    TXN_DIR = 'txn'

    def __init__(self, protocol_params=None):
        self.protocol_params = protocol_params

    def __run_script(self, cardano_args):
        cmd = f'cardano-cli {cardano_args}'
        print(cmd)
        cli_cmd = subprocess.Popen(cmd,  shell=True, text=True, stdout=subprocess.PIPE)
        (out, err) = cli_cmd.communicate()
        print(f'[STDOUT] {out}')
        print(f'[STDERR] {err}')
        return out

    def named_assets_str(nft_policy_map):
        named_assets = []
        for policy in nft_policy_map:
            for nft_name in nft_policy_map[policy]:
                hex_name = nft_name.encode('UTF-8').hex()
                named_assets.append(f"{policy}.{hex_name}")
        return '+'.join([f"1 {named_asset}" for named_asset in named_assets])

    def build_raw_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, addl_args, era='--alonzo-era'):
        raw_build_file = os.path.join(output_dir, CardanoCli.TXN_DIR, f"txn_{txn_id}.raw.build")
        metadata_file_args = f"--metadata-json-file {metadata_json_file}" if metadata_json_file else ''
        self.__run_script(
            f'transaction build-raw --fee {fee} {era} {" ".join(tx_out_args)} {" ".join(tx_in_args)} \
                {metadata_file_args} --out-file {raw_build_file} {" ".join(addl_args)}'
        )
        return raw_build_file

    def build_raw_mint_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint, nft_policy_map, scripts_map):
        mint_args = []
        if nft_policy_map:
            named_asset_str = CardanoCli.named_assets_str(nft_policy_map)
            mint_args.append(f"--mint=\"{named_asset_str}\"")
            mint_args.extend([f"--minting-script-file {scripts_map[script]}" for script in scripts_map if script in nft_policy_map])
        if mint.initial_slot:
            mint_args.append(f"--invalid-before {mint.initial_slot}")
        if mint.expiration_slot:
            mint_args.append(f"--invalid-hereafter {mint.expiration_slot}")
        return self.build_raw_txn(output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint_args)

    def calculate_min_fee(self, raw_build_file, tx_in_count, tx_out_count, witness_count):
        lovelace_fee_str = self.__run_script(
            f'transaction calculate-min-fee --tx-body-file {raw_build_file} --tx-in-count {tx_in_count} \
              --tx-out-count {tx_out_count} --witness-count {witness_count} --protocol-params-file {self.protocol_params}'
        )
        return int(lovelace_fee_str.split(' ')[0])

    def sign_txn(self, signing_files, build_file):
        signed_file = f"{build_file}.signed"
        signing_key_args = ' '.join([f"--signing-key-file {signing_file}" for signing_file in signing_files])
        self.__run_script(
            f'transaction sign {signing_key_args} --tx-body-file {build_file} --out-file {signed_file}'
        )
        return signed_file

    def build_addr(self, payment_sign_key, mainnet=False):
        with tempfile.NamedTemporaryFile() as verification_file:
            self.__run_script(
                f"key verification-key --signing-key-file {payment_sign_key} --verification-key-file {verification_file.name}"
            )
            network_flag = "--mainnet" if mainnet else f"--testnet-magic {network.PREPROD_MAGIC}"
            address = self.__run_script(
                f"address build --payment-verification-key-file {verification_file.name} {network_flag}"
            )
            return address.strip()

    def policy_id(self, script_file):
        return self.__run_script(f"transaction policyid --script-file {script_file}").strip()
