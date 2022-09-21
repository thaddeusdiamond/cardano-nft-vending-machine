import json
import math
import os

from cardano.wt.utxo import Utxo

"""
Representation of the current minting process.
"""
class Mint(object):

    _METADATA_KEY = '721'
    _METADATA_MAXLEN = 64
    _MIN_PRICE = 5000000
    _POLICY_LEN = 56

    class RebateCalculator(object):
        __COIN_SIZE = 0.0               # Will change in next era to slightly lower fees
        __PIDSIZE = 28.0
        __UTXO_SIZE_WITHOUT_VAL = 27.0

        __ADA_ONLY_UTXO_SIZE = __COIN_SIZE + __UTXO_SIZE_WITHOUT_VAL
        __UTXO_BASE_RATIO = math.floor(Utxo.MIN_UTXO_VALUE / __ADA_ONLY_UTXO_SIZE)

        def calculate_rebate_for(num_policies, num_assets, total_name_chars):
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

    def __init__(self, policy, price, donation, nfts_dir, script, sign_key, whitelist):
        self.policy = policy
        self.price = price
        self.donation = donation
        self.nfts_dir = nfts_dir
        self.script = script
        self.sign_key = sign_key
        self.whitelist = whitelist

        self.initial_slot = Mint.__read_validator('after', 'slot', script)
        self.expiration_slot = Mint.__read_validator('before', 'slot', script)

    def validate(self):
        if self.donation and self.donation < Utxo.MIN_UTXO_VALUE:
            raise ValueError(f"Thank you for offering to donate {self.donation} but the minUTxO on Cardano is {Utxo.MIN_UTXO_VALUE} lovelace")
        if self.price and self.price < Mint._MIN_PRICE:
            raise ValueError(f"Minimum mint price is {Mint._MIN_PRICE}, you entered {self.price}")
        validated_names = []
        for filename in os.listdir(self.nfts_dir):
            with open(os.path.join(self.nfts_dir, filename), 'r') as file:
                print(f"Validating '{filename}'")
                validated_nft = self.__validated_nft(json.load(file), validated_names, filename)
                validated_names.append(validated_nft)
        self.validated_names = validated_names
        print(f"Validating whitelist of type {self.whitelist.__class__}")
        self.whitelist.validate()

    def __validate_str_lengths(self, metadata):
        if type(metadata) is dict:
            for key, value in metadata.items():
                self.__validate_str_lengths(value)
        if type(metadata) is list:
            for value in metadata:
                self.__validate_str_lengths(value)
        if type(metadata) is str and len(metadata) > Mint._METADATA_MAXLEN:
            raise ValueError(f"Encountered metadata value >{Mint._METADATA_MAXLEN} chars '{metadata}'")

    def __validated_nft(self, nft, existing, filename):
        if len(nft.keys()) != 1:
            raise ValueError(f"Incorrect # of keys ({len(nft.keys())}) found in file '{filename}'")
        if not Mint._METADATA_KEY in nft:
            raise ValueError(f"Missing top-level metadata key ({Mint._METADATA_KEY}) in file '{filename}'")
        nft_policy_obj = nft[Mint._METADATA_KEY]
        if len(nft_policy_obj.keys()) == 0:
            raise ValueError(f"No policy keys found in file '{filename}'")
        if len(nft_policy_obj.keys()) > 2:
            raise ValueError(f"Too many policy keys ({len(nft_policy_obj.keys())}) found in file '{filename}'")
        if len(nft_policy_obj.keys()) == 2 and not 'version' in nft_policy_obj.keys():
            raise ValueError(f"Found 2 keys but 1 is not 'version' (file '{filename}') [see CIP-0025]")
        policy = sorted(list(nft_policy_obj.keys()))[0]
        if len(policy) != Mint._POLICY_LEN:
            raise ValueError(f"Incorrect looking policy {policy} in file '{filename}'")
        if policy != self.policy:
            raise ValueError(f"Encountered asset with policy {policy} different from vending machine start value {self.policy}")
        asset_obj = nft_policy_obj[policy]
        if len(asset_obj.keys()) != 1:
            raise ValueError(f"Incorrect # of assets ({len(asset_obj.keys())}) found in file '{filename}'")
        asset_name = list(asset_obj.keys())[0]
        if asset_name in existing:
            raise ValueError(f"Found duplicate asset name '{asset_name}' in file '{filename}'")
        self.__validate_str_lengths(asset_obj)
        return asset_name
