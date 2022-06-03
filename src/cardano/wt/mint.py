import json

"""
Representation of the current minting process.
"""
class Mint(object):

    def __read_validator(validation, key, script):
        with open(script, 'r') as script_file:
            script_json = json.load(script_file)
        if 'scripts' in script_json:
            for validator in script_json['scripts']:
                if validator['type'] == validation:
                    return validator[key]
        return None

    def __init__(self, policy, price, rebate, donation, nfts_dir, script, sign_key):
        self.policy = policy
        self.price = price
        self.rebate = rebate
        self.donation = donation
        self.nfts_dir = nfts_dir
        self.script = script
        self.sign_key = sign_key

        self.initial_slot = Mint.__read_validator('after', 'slot', script)
        self.expiration_slot = Mint.__read_validator('before', 'slot', script)
