""""
Representation of the current minting process.
"""
class Mint(object):

    def __init__(self, policy, price, rebate, donation, nfts_dir, script, sign_key):
        self.policy = policy
        self.price = price
        self.rebate = rebate
        self.donation = donation
        self.nfts_dir = nfts_dir
        self.script = script
        self.sign_key = sign_key


