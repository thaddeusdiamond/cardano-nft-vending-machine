import os
import shutil
import sys

"""
Representation of an asset-based whitelist (with common methods for
filesystem handling).
"""
class AssetWhitelist(object):

    def __init__(self, input_dir, consumed_dir):
        self.input_dir = input_dir
        self.consumed_dir = consumed_dir

    def __fs_location(self, asset_id):
        return os.path.join(self.input_dir, asset_id)

    def _remove_from_whitelist(self, asset_id):
        consumed_location = os.path.join(self.consumed_dir, asset_id)
        shutil.move(self.__fs_location(asset_id), consumed_location)

    def is_whitelisted(self, asset_id):
        return os.path.exists(self.__fs_location(asset_id))

    def validate(self):
        if not os.path.exists(self.input_dir):
            raise ValueError(f"Could not find whitelist directory {self.input_dir} on filesystem!")
        if not os.path.exists(self.consumed_dir):
            raise ValueError(f"Output directory {self.consumed_dir} does not exist on filesystem!")

"""
A whitelist implementation that allows 1 mint per whitelisted asset for the
duration of the mint.
"""
class SingleUseWhitelist(AssetWhitelist):

    def __init__(self, input_dir, consumed_dir):
        super().__init__(input_dir, consumed_dir)

    def available(self, utxo_outputs):
        """
        This implementation checks on the filesystem whether any of the assets
        in the input are whitelisted and how many can be used.

        :param utxo_outputs: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :return: Number of whitelisted assets found in input transaction
        """
        num_whitelisted = 0
        for utxo_output in utxo_outputs:
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                asset_id = utxo_amount['unit']
                if self.is_whitelisted(asset_id):
                    num_whitelisted += 1
        return num_whitelisted

    def consume(self, utxo_outputs, num_mints):
        """
        This implementation validates that the number minted did not exceed the
        total assets in the input transaction and moves the filesystem
        representation of the consumed assets to a staging area for later
        debugging.

        :param utxo_outputs: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :param num_mints: How many mints were successfully processed
        """
        remaining_to_remove = num_mints
        for utxo_output in utxo_outputs:
            if not remaining_to_remove:
                break
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                asset_id = utxo_amount['unit']
                if not self.is_whitelisted(asset_id):
                    continue
                self._remove_from_whitelist(asset_id)
                remaining_to_remove -= 1
        if remaining_to_remove != 0:
            raise ValueError(f"[MANUALLY DEBUG] THERE WAS AN OVERMINT FOR A WHITELIST ({remaining_to_remove}), THE MINT WAS ALREADY PROCESSED, INVESTIGATE {utxo_outputs}")


"""
A whitelist implementation that allows unlimited mints per whitelisted asset for the
duration of the mint.
"""
class UnlimitedWhitelist(AssetWhitelist):

    def __init__(self, input_dir, consumed_dir):
        super().__init__(input_dir, consumed_dir)

    def available(self, utxo_outputs):
        """
        This implementation checks on the filesystem whether any of the assets
        in the input are whitelisted and, if so, returns sys.maxsize.

        :param utxo_outputs: The UTXOs spent in the mint request's input txn
            NOTE: Explicitly skips reference inputs
        :return: sys.maxsize if a whitelisted asset is found, 0 otherwise
        """
        for utxo_output in utxo_outputs:
            utxo_amounts = utxo_output['amount']
            for utxo_amount in utxo_amounts:
                asset_id = utxo_amount['unit']
                if self.is_whitelisted(asset_id):
                    return sys.maxsize
        return 0

    def consume(self, utxo_outputs, num_mints):
        """
        This implementation does not do anything in the interest of efficiency.

        :param utxo_outputs: The UTXOs in the mint request's input transaction
        :param num_mints: How many mints were successfully processed
        """
        pass
