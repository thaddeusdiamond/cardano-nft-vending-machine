import copy
import json
import math
import os
import random
import shutil
import time
import traceback

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.utxo import Utxo, Balance

class BadUtxoError(ValueError):

    def __init__(self, utxo, message):
        super().__init__(message)
        self.utxo = utxo

class NftVendingMachine(object):

    __SINGLE_POLICY = 1
    __ERROR_WAIT = 30

    def as_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def __init__(self, payment_addr, payment_sign_key, profit_addr, vend_randomly, single_vend_max, mint, blockfrost_api, cardano_cli, mainnet=False):
        self.payment_addr = payment_addr
        self.payment_sign_key = payment_sign_key
        self.profit_addr = profit_addr
        self.vend_randomly = vend_randomly
        self.single_vend_max = single_vend_max
        self.mint = mint
        self.blockfrost_api = blockfrost_api
        self.cardano_cli = cardano_cli
        self.mainnet = mainnet
        self.__is_validated = False

    def __get_tx_out_args(self, payees):
        tx_outs = []
        for payee in payees:
            payouts = payees[payee]
            if not payee or not payouts:
                continue
            payout_str = '+'.join([f"{payouts[policy]} {policy}" for policy in payouts if payouts[policy]])
            if payout_str:
                tx_outs.append(f'--tx-out "{payee}+{payout_str}"')
        return tx_outs

    def __get_policy_name_map(self, metadata_file):
        nft_names = {}
        with open(metadata_file, 'r') as metadata_filehandle:
            cip25_metadata = json.load(metadata_filehandle)['721']
            for policy in cip25_metadata:
                if policy == 'version':
                    continue
                nft_names[policy] = list(cip25_metadata[policy].keys())
        return nft_names

    def __lock_and_merge(self, available_mints, num_mints, output_dir, locked_subdir, metadata_subdir, txn_id):
        combined_nft_metadata = {}
        for i in range(num_mints):
            mint_metadata_filename = available_mints.pop(0)
            mint_metadata_orig = os.path.join(self.mint.nfts_dir, mint_metadata_filename)
            with open(mint_metadata_orig, 'r') as mint_metadata_handle:
                mint_metadata = json.load(mint_metadata_handle)
                for policy in mint_metadata['721']:
                    if policy == 'version':
                        continue
                    for nft_name, nft_metadata in mint_metadata['721'][policy].items():
                        if not policy in combined_nft_metadata:
                            combined_nft_metadata[policy] = {}
                        combined_nft_metadata[policy][nft_name] = nft_metadata
            mint_metadata_locked = os.path.join(output_dir, locked_subdir, mint_metadata_filename)
            shutil.move(mint_metadata_orig, mint_metadata_locked)
        combined_output_path = os.path.join(output_dir, metadata_subdir, f"{txn_id}.json")
        with open(combined_output_path, 'w') as combined_metadata_handle:
            json.dump({'721': combined_nft_metadata }, combined_metadata_handle)
        return combined_output_path

    def __calculate_num_mints_requested(self, mint_req):
        num_mints_requested = 0
        for balance in mint_req.balances:
            mint_rate = [price for price in self.mint.prices if self.__normalized_unit(balance.policy) == price.policy]
            if not mint_rate:
                continue
            num_mints_requested += math.floor(balance.lovelace / mint_rate[0].lovelace) if mint_rate[0].lovelace else self.single_vend_max
        return num_mints_requested

    def __normalized_unit(self, policy):
        if policy == Balance.LOVELACE_POLICY:
            return policy
        return f"{policy[0:Mint._POLICY_LEN]}.{policy[Mint._POLICY_LEN:]}"

    def __get_pricing_breakdown(self, input_addr, num_mints, nft_policy_map, mint_req, fee):
        payees = {input_addr: {}, self.profit_addr: {}, self.mint.dev_addr: {}}

        # GET A COPY OF THE UTXOs TO TRACK THE PAYOUTS (PUT LOVELACE BEFORE NATIVE ASSETS)
        print(f"Building pricing breakdown for {num_mints} NFTs being paid from {mint_req}")
        remaining = copy.deepcopy(mint_req.balances)
        remaining.sort(key=lambda balance: balance.policy)
        remaining.reverse()
        remaining_ada = [balance for balance in remaining if balance.policy == Balance.LOVELACE_POLICY][0]

        # PAY THE CREATOR
        remaining_to_payout = num_mints
        for remainder in remaining:
            unit = self.__normalized_unit(remainder.policy)
            if not remaining_to_payout:
                break
            matching_price = [price for price in self.mint.prices if price.policy == unit]
            if not matching_price:
                continue
            if not matching_price[0].lovelace:
                num_paid_for = num_mints
            else:
                num_paid_for = min(remaining_to_payout, math.floor(remainder.lovelace / matching_price[0].lovelace))
            total_paid = (num_paid_for * matching_price[0].lovelace)
            print(f"Paid for {num_paid_for} NFTs using {total_paid} {unit}")
            if not num_paid_for:
                continue
            remaining_to_payout -= num_paid_for
            remainder.lovelace -= total_paid
            if not unit in payees[self.profit_addr]:
                payees[self.profit_addr][unit] = 0
            payees[self.profit_addr][unit] += total_paid
        if not Balance.LOVELACE_POLICY in payees[self.profit_addr]:
            if payees[self.profit_addr]:
                token_types = set([unit[0:Mint._POLICY_LEN] for unit in payees[self.profit_addr].keys()])
                all_tokens = [bytes.fromhex(unit[(Mint._POLICY_LEN + 1):]).decode('UTF-8') for unit in payees[self.profit_addr].keys()]
                total_token_chars = sum([len(token) for token in all_tokens])
                profit_rebate = Mint.RebateCalculator.calculate_rebate_for(len(token_types), len(all_tokens), total_token_chars)
                payees[self.profit_addr][Balance.LOVELACE_POLICY] = profit_rebate
                remaining_ada.lovelace -= profit_rebate
            else:
                payees[self.profit_addr][Balance.LOVELACE_POLICY] = 0
        profit_ada = payees[self.profit_addr][Balance.LOVELACE_POLICY]
        if remaining_to_payout:
            raise ValueError(f"Unable to match UTxO to payment for {num_mints} NFTs")

        # PAY THE USER THE NFTs NEXT
        for policy in nft_policy_map:
            for nft_name in nft_policy_map[policy]:
                hex_name = nft_name.encode('UTF-8').hex()
                asset_name = f"{policy}.{hex_name}"
                if not asset_name in payees[input_addr]:
                    payees[input_addr][asset_name] = 0
                payees[input_addr][asset_name] += 1

        # PAY THE USER'S REBATE AFTER NFTs CALCULATED
        all_names = [name for name_lst in nft_policy_map.values() for name in name_lst]
        total_name_chars = sum([len(name) for name in all_names])
        user_rebate = Mint.RebateCalculator.calculate_rebate_for(len(nft_policy_map.keys()), len(all_names), total_name_chars)
        print(f"Minimum rebate to user is {user_rebate}")

        # DEDUCT REBATES AND FEES FROM PROFIT IF ADA-ONLY MINT, OTHERWISE FROM USER
        payees[input_addr][Balance.LOVELACE_POLICY] = user_rebate
        if profit_ada and len(payees[self.profit_addr]) == 1:
            payees[self.profit_addr][Balance.LOVELACE_POLICY] -= (user_rebate + fee)
        elif user_rebate > remaining_ada.lovelace:
            raise ValueError(f"USER SENT {remaining_ada.lovelace} WHICH CAN'T COVER REBATE OF {user_rebate} (FREE MINT?)")
        else:
            remaining_ada.lovelace -= (user_rebate + fee)

        # PAY THE DEVELOPER (ADA ONLY)
        if self.mint.dev_fee:
            expected_dev_fee = num_mints * self.mint.dev_fee
            if len(payees[self.profit_addr]) == 1:
                actual_dev_fee = min([expected_dev_fee, profit_ada])
                print(f"Paying developer {actual_dev_fee} lovelace")
                dev_fee_diff = expected_dev_fee - actual_dev_fee
                if dev_fee_diff:
                    print(f"SOMETHING IS OFF: Expected dev fee ({expected_dev_fee}) greater than actual ({actual_dev_fee}) by {dev_fee_diff} lovelace")
                payees[self.mint.dev_addr][Balance.LOVELACE_POLICY] = actual_dev_fee
                payees[self.profit_addr][Balance.LOVELACE_POLICY] -= actual_dev_fee
            else:
                print(f"NATIVE TOKEN WARNING: Cannot pay dev fee for native token, need to credit {expected_dev_fee} lovelace ({num_mints} mints)")

        # DRAIN THE REMAINDER TO THE USER
        for remainder in remaining:
            unit = self.__normalized_unit(remainder.policy)
            if not remainder.lovelace:
                continue
            if not unit in payees[input_addr]:
                payees[input_addr][unit] = 0
            payees[input_addr][unit] += remainder.lovelace
            remainder.lovelace = 0
        return payees

    def __do_vend(self, mint_req, output_dir, locked_subdir, metadata_subdir):
        available_mints = sorted(os.listdir(self.mint.nfts_dir))
        if not available_mints:
            print("WARNING: Metadata directory is empty, please restock the vending machine...")
        elif self.vend_randomly:
            random.shuffle(available_mints)

        num_mints_requested = self.__calculate_num_mints_requested(mint_req)

        utxos = self.blockfrost_api.get_tx_utxos(mint_req.hash)
        utxo_inputs = utxos['inputs']
        utxo_outputs = utxos['outputs']
        input_addrs = set([utxo_input['address'] for utxo_input in utxo_inputs if not utxo_input['reference']])
        if len(input_addrs) < 1:
            raise BadUtxoError(mint_req, f"Txn hash {txn_hash} has no valid addresses ({utxo_inputs}), aborting...")
        input_addr = input_addrs.pop()

        wl_resources = self.mint.whitelist.required_info(mint_req, utxos, self.blockfrost_api)
        wl_availability = self.mint.whitelist.available(wl_resources)
        num_mints = min(self.single_vend_max, len(available_mints), num_mints_requested, wl_availability)

        bonuses = 0
        if self.mint.bogo:
            eligible_bonuses = self.mint.bogo.determine_bonuses(num_mints_requested)
            num_mints_plus_bonus = min(self.single_vend_max, len(available_mints), (num_mints + eligible_bonuses))
            print(f"Bonus of {eligible_bonuses} NFTs determined based on {num_mints_requested} (can mint {num_mints_plus_bonus} in total)")
            bonuses = num_mints_plus_bonus - num_mints
            num_mints += bonuses

        print(f"Beginning to mint {num_mints} NFTs to send to address {input_addr}")
        txn_id = int(time.time())
        nft_metadata_file = self.__lock_and_merge(available_mints, num_mints, output_dir, locked_subdir, metadata_subdir, txn_id)
        nft_policy_map = self.__get_policy_name_map(nft_metadata_file)

        fee = 0
        pricing_breakdown = self.__get_pricing_breakdown(input_addr, (num_mints - bonuses), nft_policy_map, mint_req, fee)
        print(f"Anticipated pricing breakdown: {pricing_breakdown}")

        tx_ins = [f"--tx-in {mint_req.hash}#{mint_req.ix}"]
        tx_outs = self.__get_tx_out_args(pricing_breakdown)
        mint_build_tmp = self.cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, 0, nft_metadata_file, self.mint, nft_policy_map, self.script_map)

        tx_in_count = len(tx_ins)
        tx_out_count = len([tx_out for tx_out in tx_outs if tx_out])
        signers = [self.payment_sign_key]
        if num_mints:
            signers.extend(self.mint.sign_keys)
        fee = self.cardano_cli.calculate_min_fee(mint_build_tmp, tx_in_count, tx_out_count, len(signers))

        pricing_breakdown = self.__get_pricing_breakdown(input_addr, (num_mints - bonuses), nft_policy_map, mint_req, fee)
        print(f"Final pricing breakdown: {pricing_breakdown}")

        tx_outs = self.__get_tx_out_args(pricing_breakdown)
        mint_build = self.cardano_cli.build_raw_mint_txn(output_dir, txn_id, tx_ins, tx_outs, fee, nft_metadata_file, self.mint, nft_policy_map, self.script_map)
        mint_signed = self.cardano_cli.sign_txn(signers, mint_build)
        self.mint.whitelist.consume(wl_resources, num_mints)
        self.blockfrost_api.submit_txn(mint_signed)

    def vend(self, output_dir, locked_subdir, metadata_subdir, exclusions):
        if not self.__is_validated:
            raise ValueError('Attempting to vend from non-validated vending machine')
        mint_reqs = self.blockfrost_api.get_utxos(self.payment_addr, exclusions)
        for mint_req in mint_reqs:
            exclusions.add(mint_req)
            try:
                self.__do_vend(mint_req, output_dir, locked_subdir, metadata_subdir)
            except BadUtxoError as e:
                print(f"UNRECOVERABLE UTXO ERROR\n{e.utxo}\n^--- REQUIRES INVESTIGATION")
                print(traceback.format_exc())
            except Exception as e:
                print(f"ERROR: Uncaught exception for {mint_req}, added to exclusions (RETRY WILL NOT BE ATTEMPTED)")
                print(traceback.format_exc())
                time.sleep(NftVendingMachine.__ERROR_WAIT)

    def validate(self):
        self.mint.validate()
        if self.payment_addr == self.profit_addr:
            raise ValueError(f"Payment address and profit address ({self.payment_addr}) cannot be the same!")
        self.max_rebate = self.__max_rebate_for(self.mint.validated_names)
        for price in self.mint.prices:
            if price.lovelace and price.policy == Balance.LOVELACE_POLICY and price.lovelace < (self.max_rebate + self.mint.dev_fee + Utxo.MIN_UTXO_VALUE):
                raise ValueError(f"Price of {price.lovelace} lovelace with dev fee of {self.mint.dev_fee} could lead to a minUTxO error due to rebates")
        if not os.path.exists(self.payment_sign_key):
            raise ValueError(f"Payment signing key file '{self.payment_sign_key}' not found on filesystem")
        expected_payment_addr = self.cardano_cli.build_addr(self.payment_sign_key, self.mainnet)
        if not expected_payment_addr == self.payment_addr:
            raise ValueError(f"Could not match {self.payment_addr} to signature at '{self.payment_sign_key}' (expected {expected_payment_addr})")
        self.script_map = {}
        for policy in self.mint.policies:
            self.script_map[policy] = self.__validate_script_file(policy)
            if not self.script_map[policy]:
                raise ValueError(f"No matching script file found for policy {policy}")
        self.__is_validated = True

    def __validate_script_file(self, policy):
        for script in self.mint.scripts:
            if self.cardano_cli.policy_id(script) == policy:
                return script
        return None

    def __max_rebate_for(self, nft_names):
        max_len = 0 if not nft_names else max([len(nft_name.split('.')[1]) for nft_name in nft_names])
        all_policies = [nft_name.split('.')[0] for nft_name in nft_names]
        return Mint.RebateCalculator.calculate_rebate_for(
            len(set(all_policies)),
            self.single_vend_max,
            max_len * self.single_vend_max
        )
