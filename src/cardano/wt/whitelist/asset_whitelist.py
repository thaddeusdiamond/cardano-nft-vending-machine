import sys

from cardano.wt.whitelist.filesystem import FilesystemBasedWhitelist

"""
Representation of an asset-based whitelist.
"""
class AssetWhitelist(FilesystemBasedWhitelist):

    def __init__(self, input_dir, consumed_dir):
        super().__init__(input_dir, consumed_dir)

    def required_info(self, mint_utxo, txn_utxos, blockfrost):
        """
        Always return the UTxO outputs fro the mint request transaction

        :param mint_utxo: The UTXO representing the mint request itself
        :param txn_utxos: Inputs and outputs of the mint request transaction
        :param blockfrost: API to Blockfrost to retrieve arbitrary txn data
        """
        return txn_utxos['outputs']

"""
A whitelist implementation that allows up to N mints per whitelisted asset for
the duration of the mint (based on how many whitelist slots were initialized
ahead of time).
"""
class SingleUseWhitelist(AssetWhitelist):

    def __init__(self, input_dir, consumed_dir):
        super().__init__(input_dir, consumed_dir)

    def available(self, wl_resources):
        """
        This implementation checks on the filesystem whether any of the assets
        in the input are whitelisted and how many can be used.

        :param wl_resources: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :return: Number of whitelisted assets found in input transaction
        """
        num_whitelisted = 0
        for utxo_output in wl_resources:
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                asset_id = utxo_amount['unit']
                num_whitelisted += self.num_whitelisted(asset_id)
        return num_whitelisted

    def consume(self, wl_resources, num_mints):
        """
        This implementation validates that the number minted did not exceed the
        total assets in the input transaction and moves the filesystem
        representation of the consumed assets to a staging area for later
        debugging.

        :param wl_resources: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :param num_mints: How many mints were successfully processed
        """
        remaining_to_remove = num_mints
        for utxo_output in wl_resources:
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                if not remaining_to_remove:
                    return
                asset_id = utxo_amount['unit']
                num_removed = min(remaining_to_remove, self.num_whitelisted(asset_id))
                self._remove_from_whitelist(asset_id, num_removed)
                remaining_to_remove -= num_removed
        if remaining_to_remove != 0:
            raise ValueError(f"[MANUALLY DEBUG] THERE WAS AN OVERMINT FOR A WHITELIST ({remaining_to_remove}), THE MINT WAS ALREADY PROCESSED, INVESTIGATE {wl_resources}")


"""
A whitelist implementation that allows unlimited mints per whitelisted asset for
the duration of the mint.
"""
class UnlimitedWhitelist(AssetWhitelist):

    def __init__(self, input_dir, consumed_dir):
        super().__init__(input_dir, consumed_dir)

    def available(self, wl_resources):
        """
        This implementation checks on the filesystem whether any of the assets
        in the input are whitelisted and, if so, returns sys.maxsize.

        :param wl_resources: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :return: sys.maxsize if a whitelisted asset is found, 0 otherwise
        """
        for utxo_output in wl_resources:
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                asset_id = utxo_amount['unit']
                if self.num_whitelisted(asset_id) > 0:
                    return sys.maxsize
        return 0

    def consume(self, wl_resources, num_mints):
        """
        This implementation does not do anything in the interest of efficiency.

        :param wl_resources: The UTXOs in the mint request's input transaction
        :param num_mints: How many mints were successfully processed
        """
        pass
