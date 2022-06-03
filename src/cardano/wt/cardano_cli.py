import json
import os
import subprocess

from deprecated import deprecated

from cardano.wt.utxo import Utxo

"""
cardano-cli *nix script representation in Python
"""
class CardanoCli(object):

    _WITNESS_COUNT = 1

    _MAINNET_PARAM = '--mainnet'
    _TESTNET_PARAM = '--testnet-magic 1097911063'

    TXN_DIR = 'txn'

    def __init__(self, mainnet=False, protocol_params=None):
        self.mainnet = mainnet
        self.protocol_params = protocol_params

    def __run_script(self, cardano_args, add_network=True):
        cmd = f'cardano-cli {cardano_args} {self.__get_network_flag() if add_network else ""}'
        print(cmd)
        cli_cmd = subprocess.Popen(cmd,  shell=True, text=True, stdout=subprocess.PIPE)
        (out, err) = cli_cmd.communicate()
        print(f'[STDOUT] {out}')
        print(f'[STDERR] {err}')
        return out

    def __get_network_flag(self):
       return self._MAINNET_PARAM if self.mainnet else self._TESTNET_PARAM

    def named_asset_str(nft_policy, nft_names):
        return '+'.join(['.'.join([f"1 {nft_policy}", nft_name]) for nft_name in nft_names])

    @deprecated(version='0.2.0', reason='This requires a working cardano node, use BlockfrostApi class instead.')
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

    def build_raw_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, addl_args):
        raw_build_file = os.path.join(output_dir, CardanoCli.TXN_DIR, f"txn_{txn_id}.raw.build")
        self.__run_script(
            f'transaction build-raw --fee {fee} --alonzo-era {" ".join(tx_out_args)} {" ".join(tx_in_args)} \
                --metadata-json-file {metadata_json_file} --out-file {raw_build_file} {" ".join(addl_args)}',
            add_network=False
        )
        return raw_build_file
    
    def build_raw_mint_txn(self, output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint, nft_names): 
        named_asset_str = CardanoCli.named_asset_str(mint.policy, nft_names)
        mint_args = [f"--mint='{named_asset_str}'", f"--minting-script-file {mint.script}"] if nft_names else []
        if mint.initial_slot:
            mint_args.append(f"--invalid-before {mint.initial_slot}")
        if mint.expiration_slot:
            mint_args.append(f"--invalid-hereafter {mint.expiration_slot}")
        return self.build_raw_txn(output_dir, txn_id, tx_in_args, tx_out_args, fee, metadata_json_file, mint_args)
   
    def calculate_min_fee(self, raw_build_file, tx_in_count, tx_out_count, witness_count):
        lovelace_fee_str = self.__run_script(
            f'transaction calculate-min-fee --tx-body-file {raw_build_file} --tx-in-count {tx_in_count} \
              --tx-out-count {tx_out_count} --witness-count {witness_count} --protocol-params-file {self.protocol_params}',
            add_network=False
        )
        return int(lovelace_fee_str.split(' ')[0])

    def sign_txn(self, signing_files, build_file):
        signed_file = f"{build_file}.signed"
        signing_key_args = ' '.join([f"--signing-key-file {signing_file}" for signing_file in signing_files])
        self.__run_script(
            f'transaction sign {signing_key_args} --tx-body-file {build_file} --out-file {signed_file}',
            add_network=False
        )
        return signed_file

    @deprecated(version='0.2.0', reason='This requires a working cardano node, use BlockfrostApi class instead.')
    def submit_txn(self, signed_file):
        self.__run_script(f'transaction submit --tx-file {signed_file}')
        pass

    def _write_metadata_file(self, txn_id, metadata):
        metadata_json_file = f'metadata/metadata_{txn_id}.json'
        with open(metadata_json_file, 'w') as metadata_json_file_out:
            metadata_json_file_out.write(json.dumps(metadata))
        return metadata_json_file


