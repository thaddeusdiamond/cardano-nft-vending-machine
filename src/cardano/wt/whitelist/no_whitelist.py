import sys

"""
Representation of a non-existent whitelist (e.g., no mint restrictions).
"""
class NoWhitelist(object):

    def available(self, utxo_inputs):
        """
        Always return no limits (e.g., max integer)

        :param utxo_inputs: The UTXOs in the mint request's input transaction
        :return: sys.maxsize (always)
        """
        return sys.maxsize

    def is_whitelisted(self, object):
        """
        For whitelists, this is a bit of a polyglot function to determine
        whether an object (e.g., asset or address) is whitelisted.

        :param object: The generic object to be tested
        :return: True or False (True for base implementation always)
        """
        return True

    def consume(self, utxo_inputs, num_mints):
        """
        No-operation because there is no whitelist to be consumed.

        :param utxo_inputs: The UTXOs in the mint request's input transaction
        :param num_mints: How many mints were successfully processed
        """
        pass

    def validate(self):
        """
        No-operation because a nil whitelist is automatically valid.
        """
        pass
