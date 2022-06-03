import json
import math
import os
import shutil
import time

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.utxo import Utxo

class NftVendingMachine(object):

    __WITNESS_COUNT = 2

    def __get_donation_addr(mainnet):
        if mainnet:
            return 'addr1qx2skanhkpgdhcyxnczydg3meqcv87z4vep7u2drrr6277v5entql0xseq6a4zs8j524wvwv6k46kpf8pt9ejjk6l9gs4g94mf'
        return 'addr_test1vrce7uwk8vcva5j4dmehrxprwy57x20yaz9cv9vqzjutnnsrgrfey'

    def __init__(self, payment_addr, payment_sign_key, profit_addr, mint, blockfrost_api, cardano_cli, mainnet=False):
        self.payment_addr = payment_addr
        self.payment_sign_key = payment_sign_key
        self.profit_addr = profit_addr
        self.mint = mint
        self.blockfrost_api = blockfrost_api
        self.cardano_cli = cardano_cli
        self.donation_addr = NftVendingMachine.__get_donation_addr(mainnet)

    def __get_tx_out_args(self, input_addr, change, nft_names, total_profit, total_donation):
        user_tokens = filter(None, [input_addr, str(change), CardanoCli.named_asset_str(self.mint.policy, nft_names)])
        user_output = f"--tx-out '{'+'.join(user_tokens)}'"
        profit_output = f"--tx-out '{self.profit_addr}+{total_profit}'" if total_profit else '' 
        donation_output = f"--tx-out '{self.donation_addr}+{total_donation}'" if total_donation else ''
        return [user_output, profit_output, donation_output]

    def __generate_nft_names_from(self, metadata_file):
        with open(metadata_file, 'r') as metadata_filehandle:
            policy_json = json.load(metadata_filehandle)['721'][self.mint.policy]
            names = policy_json.keys()
            return [name.encode('UTF-8').hex() for name in names]

    def __lock_and_merge(self, available_mints, num_mints, output_dir, locked_subdir, metadata_subdir, txn_id):
        combined_nft_metadata = {}
        for i in range(num_mints):
            mint_metadata_filename = available_mints.pop()
            mint_metadata_orig = os.path.join(self.mint.nfts_dir, mint_metadata_filename)
            with open(mint_metadata_orig, 'r') as mint_metadata_handle:
                mint_metadata = json.load(mint_metadata_handle)
                for nft_name, nft_metadata in mint_metadata['721'][self.mint.policy].items():
                    if nft_name in combined_nft_metadata:
                        raise ValueError(f"Duplicate NFT metadata for {nft_name} found")
                    combined_nft_metadata[nft_name] = nft_metadata
            mint_metadata_locked = os.path.join(output_dir, locked_subdir, mint_metadata_filename)
            shutil.move(mint_metadata_orig, mint_metadata_locked)
        combined_output_path = os.path.join(output_dir, metadata_subdir, f"{txn_id}.json")
        with open(combined_output_path, 'w') as combined_metadata_handle:
            json.dump({'721': { self.mint.policy : combined_nft_metadata }}, combined_metadata_handle)
        return combined_output_path

    def __do_vend(self, mint_req, output_dir, locked_subdir, metadata_subdir):
        available_mints = os.listdir(self.mint.nfts_dir)
        if not available_mints:
            print("Metadata directory is empty, please restock the vending machine...")
            return

        input_addr = self.blockfrost_api.get_input_address(mint_req.hash)
        lovelace_bals = [balance for balance in mint_req.balances if balance.policy == Utxo.Balance.LOVELACE_POLICY]
        if len(lovelace_bals) != 1:
            raise ValueError(f"Found too many/few lovelace balances for UTXO {mint_req}")

        lovelace_bal = lovelace_bals.pop()
        num_mints = min(len(available_mints), math.floor((lovelace_bal.lovelace - self.mint.rebate) / self.mint.price))
        total_profit = num_mints * (self.mint.price - self.mint.donation) 
        total_donation = num_mints * self.mint.donation
        change = lovelace_bal.lovelace - (total_profit + total_donation)
        print(f"Beginning to mint {num_mints} NFTs to send to address {input_addr} (change: {change})")

        txn_id = int(time.time())
        nft_metadata_file = self.__lock_and_merge(available_mints, num_mints, output_dir, locked_subdir, metadata_subdir, txn_id)
        nft_names = self.__generate_nft_names_from(nft_metadata_file)
        tx_ins = [f"--tx-in {mint_req.hash}#{mint_req.ix}"]
        tx_outs = self.__get_tx_out_args(input_addr, change, nft_names, total_profit, total_donation)
        mint_build_tmp = self.cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, 0, nft_metadata_file, self.mint, nft_names)

        tx_in_count = len(tx_ins)
        tx_out_count = len([tx_out for tx_out in tx_outs if tx_out])
        fee = self.cardano_cli.calculate_min_fee(mint_build_tmp, tx_in_count, tx_out_count, NftVendingMachine.__WITNESS_COUNT)

        tx_outs = self.__get_tx_out_args(input_addr, change - fee, nft_names, total_profit, total_donation)
        mint_build = self.cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, fee, nft_metadata_file, self.mint, nft_names)
        mint_signed = self.cardano_cli.sign_txn([self.payment_sign_key, self.mint.sign_key], mint_build)
        self.blockfrost_api.submit_txn(mint_signed)

    def vend(self, output_dir, locked_subdir, metadata_subdir, exclusions):
        mint_reqs = self.blockfrost_api.get_utxos(self.payment_addr, exclusions)
        for mint_req in mint_reqs:
            exclusions.add(mint_req)
            try:
                self.__do_vend(mint_req, output_dir, locked_subdir, metadata_subdir)
            except Exception as e:
                print(f"WARNING: Uncaught exception {e} for {mint_req}, adding to exclusions (MANUALLY DEBUG THIS)")
