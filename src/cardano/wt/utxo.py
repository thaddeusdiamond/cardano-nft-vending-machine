import re

"""
Simple UTXO object to strengthen the type of CLI-returned strings
"""
class Utxo(object):

    MIN_UTXO_VALUE = 1000000

    class Balance(object):
        LOVELACE_POLICY = 'lovelace'

        def __init__(self, lovelace, policy):
            self.lovelace = lovelace
            self.policy = policy if policy else Utxo.Balance.LOVELACE_POLICY

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
