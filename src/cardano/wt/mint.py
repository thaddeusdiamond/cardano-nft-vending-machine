import json
import math
import os

from cardano.wt.utxo import Utxo

"""
Representation of the current minting process.
"""
class Mint(object):

    _METADATA_KEY = '721'
    _POLICY_LEN = 56

    class RebateCalculator(object):
        __COIN_SIZE = 0.0               # Will change in next era to slightly lower fees
        __PIDSIZE = 28.0
        __UTXO_SIZE_WITHOUT_VAL = 27.0

        __ADA_ONLY_UTXO_SIZE = __COIN_SIZE + __UTXO_SIZE_WITHOUT_VAL
        __UTXO_BASE_RATIO = math.ceil(Utxo.MIN_UTXO_VALUE / __ADA_ONLY_UTXO_SIZE)

        def calculateRebateFor(num_policies, num_assets, total_name_chars):
            if num_assets < 1:
                return 0
            asset_words = math.ceil(((num_assets * 12.0) + (total_name_chars) + (num_policies * Mint.RebateCalculator.__PIDSIZE)) / 8.0)
            utxo_native_token_multiplier = Mint.RebateCalculator.__UTXO_SIZE_WITHOUT_VAL + (6 + asset_words)
            return int(Mint.RebateCalculator.__UTXO_BASE_RATIO * utxo_native_token_multiplier)

        def __init__(self):
            raise ValueError('Mint rebate calculator is meant to be used as a static class only')

    def __read_validator(validation, key, script):
        with open(script, 'r') as script_file:
            script_json = json.load(script_file)
        if 'scripts' in script_json:
            for validator in script_json['scripts']:
                if validator['type'] == validation:
                    return validator[key]
        return None

    def __init__(self, policy, price, donation, nfts_dir, script, sign_key):
        self.policy = policy
        self.price = price
        self.donation = donation
        self.nfts_dir = nfts_dir
        self.script = script
        self.sign_key = sign_key

        self.initial_slot = Mint.__read_validator('after', 'slot', script)
        self.expiration_slot = Mint.__read_validator('before', 'slot', script)

    def validate(self):
        existing = []
        for filename in os.listdir(self.nfts_dir):
            with open(filename, 'r') as file:
                print(f"Validating {filename}")
                validated_nft = self.__validated_nft(json.load(file), existing)
                existing.append(validated_nft)

    def __validated_nft(self, nft, existing):
        if len(nft.keys()) != 1:
            raise ValueError(f"Incorrect # of keys ({len(nft.keys())}) found in file '{filename}'")
        if not Mint._METADATA_KEY in nft:
            raise ValueError(f"Missing top-level metadata key ({Mint._METADATA_KEY}) in file '{filename}'")
        nft_policy_obj = nft[Mint._METADATA_KEY]
        if len(nft_policy_obj.keys()) != 1:
            raise ValueError(f"Incorrect # of policy keys ({len(nft_policy_arr.keys())}) found in file '{filename}'")
        policy = list(nft_policy_obj.keys())[0]
        if len(policy) != Mint._POLICY_LEN:
            raise ValueError(f"Incorrect looking policy {policy} in file '{filename}'")
        asset_obj = nft_policy_arr[policy]
        if len(asset_obj.keys()) != 1:
            raise ValueError(f"Incorrect # of assets ({len(nft_policy_arr.keys())}) found in file '{filename}'")
        asset_name = list(asset_obj.keys())[0]
        if asset_name in existing:
            raise ValueError(f"Found duplicate asset name '{asset_name}' in file '{filename}'")
        return asset_name
