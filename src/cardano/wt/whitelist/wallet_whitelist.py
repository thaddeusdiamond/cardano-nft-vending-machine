import json
import sys

from pycardano.cip import cip8

from cardano.wt.whitelist.filesystem import FilesystemBasedWhitelist

"""
A whitelist implementation that allows N mints per whitelisted wallet for the
duration of the mint.
"""
class WalletWhitelist(FilesystemBasedWhitelist):

    _MSG_LABEL = '674'
    _SIGNATURE_KEY = 'whitelist_proof'

    def __init__(self, input_dir, consumed_dir, allowable_amount):
        super().__init__(input_dir, consumed_dir)
        self.allowable_amount = allowable_amount

    def required_info(self, mint_utxo, txn_utxos, blockfrost):
        """
        Retrieve the transaction metadata for the specified transaction

        :param mint_utxo: The UTXO representing the mint request itself
        :param txn_utxos: Inputs and outputs of the mint request transaction
        :param blockfrost: API to Blockfrost to retrieve arbitrary txn data
        """
        utxo_inputs = txn_utxos['inputs']
        input_addrs = set([
            utxo_input['address'] for utxo_input in utxo_inputs
            if not (utxo_input['reference'] or utxo_input['collateral'])
        ])
        return {
            'metadata': blockfrost.get_metadata(mint_utxo.hash),
            'input_addrs': input_addrs
        }

    def __get_messages(self, wl_resources):
        return [
            wl_resource['json_metadata'] for wl_resource in wl_resources
            if wl_resource['label'] == WalletWhitelist._MSG_LABEL
        ]

    def _get_signed_message(self, wl_resources):
        messages = self.__get_messages(wl_resources)
        if len(messages) != 1:
            print(f"Wallet whitelist requires exactly 1 MSG (674) label metadata, found {wl_resources}")
            return None
        if not WalletWhitelist._SIGNATURE_KEY in messages[0]:
            print(f"Expected to find '{WalletWhitelist._SIGNATURE_KEY}' in message metadata, found {messages[0]}")
            return None
        signature_msg = messages[0][WalletWhitelist._SIGNATURE_KEY]
        if not type(signature_msg) is list:
            print(f"Encountered unexpected type '{type(signature_msg)}': {messages[0]}")
            return None
        try:
            return json.loads(''.join(signature_msg))
        except Exception as e:
            print(f"Could not parse stringified JSON '{signature_msg}': {e}")
            return None

    def available(self, wl_resources):
        """
        This implementation checks on the filesystem whether the stake key
        that signed the transaction has any payment keys available to mint.

        If multiple stake keys signed or the input does not conform, we return
        0.

        :param wl_resources: The transaction's metadata (used for signatures)
        :return: {self.allowable_amount} if a wallet is on the whitelist, 0 otherwise
        """
        message = self._get_signed_message(wl_resources['metadata'])
        if not message:
            return 0
        try:
            verification = cip8.verify(message)
            stake_key = str(verification["signing_address"])
            addresses = verification["message"].strip().split(',')
            if not self.is_whitelisted(stake_key):
                raise ValueError(f"{stake_key} not on whitelist")
            for input_addr in wl_resources['input_addrs']:
                if not input_addr in addresses:
                    print(f"Found unexpected address {input_addr}, excluding from whitelist")
                    return 0
            return self.allowable_amount
        except Exception as e:
            print(f"Failed to verify {message}: {e}")
            return 0


    def consume(self, wl_resources, num_mints):
        """
        This implementation validates that the number minted did not exceed
        1 (we assume no multi-signature inputs) and removes the wallet and any
        linked stake keys from the whitelist.

        :param wl_resources: The transaction's metadata (used for signatures)
        :param num_mints: How many mints were successfully processed
        """
        if not num_mints:
            return
        if num_mints > self.allowable_amount:
            raise ValueError(f"[MANUALLY DEBUG] THERE WAS AN OVERMINT FOR A WHITELIST ({num_mints}), THE MINT WAS ALREADY PROCESSED, INVESTIGATE {wl_resources}")
        message = self._get_signed_message(wl_resources['metadata'])
        try:
            verification = cip8.verify(message)
            stake_key = str(verification["signing_address"])
            if not self.is_whitelisted(stake_key):
                raise ValueError(f"{stake_key} not on whitelist")
            self._remove_from_whitelist(stake_key)
        except Exception as e:
            raise ValueError(f"[MANUALLY DEBUG] SOMEHOW MINTED OFF WHITELIST ({e}) WITH AN INVALIDLY SIGNED MESSAGE: {wl_resources}")
