import sys

"""
Representation of a non-existent whitelist (e.g., no mint restrictions).
"""
class NoWhitelist(object):

    def required_info(self, mint_utxo, txn_utxos, blockfrost):
        """
        Always return nothing

        :param mint_utxo: The UTXO representing the mint request itself
        :param txn_utxos: Inputs and outputs of the mint request transaction
        :param blockfrost: API to Blockfrost to retrieve arbitrary txn data
        """
        return None

    def available(self, wl_resources):
        """
        Always return no limits (e.g., max integer)

        :param wl_resources: As returned by required_info()
        :return: sys.maxsize (always)
        """
        return sys.maxsize

    def consume(self, wl_resources, num_mints):
        """
        No-operation because there is no whitelist to be consumed.

        :param wl_resources: As returned by required_info()
        :param num_mints: How many mints were successfully processed
        """
        pass

    def validate(self):
        """
        No-operation because a nil whitelist is automatically valid.
        """
        pass
