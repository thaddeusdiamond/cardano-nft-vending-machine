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

    def __init__(self, price, dev_fee, dev_addr, nfts_dir, scripts, sign_keys, whitelist, bogo=None):
        self.price = price
        self.dev_fee = dev_fee
        self.dev_addr = dev_addr
        self.nfts_dir = nfts_dir
        self.scripts = scripts
        self.sign_keys = sign_keys
        self.whitelist = whitelist
        self.bogo = bogo

        after_slots = list(filter(None, [Mint.__read_validator('after', 'slot', script) for script in self.scripts]))
        self.initial_slot = max(after_slots) if after_slots else None
        before_slots = list(filter(None, [Mint.__read_validator('before', 'slot', script) for script in self.scripts]))
        self.expiration_slot = min(before_slots) if before_slots else None

    def validate(self):
        if self.dev_fee and self.dev_fee < Utxo.MIN_UTXO_VALUE:
            raise ValueError(f"Thank you for offering to pay your dev {self.dev_fee} but the minUTxO on Cardano is {Utxo.MIN_UTXO_VALUE} lovelace")
        if self.dev_fee and not self.dev_addr:
            raise ValueError(f"Thank you for offering to pay your dev {self.dev_fee} but you did not provide a dev address")
        if self.price and self.price < Mint._MIN_PRICE:
            raise ValueError(f"Minimum mint price is {Mint._MIN_PRICE}, you entered {self.price}")
        validated_names = []
        for filename in os.listdir(self.nfts_dir):
            with open(os.path.join(self.nfts_dir, filename), 'r') as file:
                print(f"Validating '{filename}'")
                validated_nfts = self.__validated_nft(json.load(file), validated_names, filename)
                validated_names.extend(validated_nfts)
        self.validated_names = validated_names
        for script in self.scripts:
            if not os.path.exists(script):
                raise ValueError(f"Minting script file '{script}' not found on filesystem")
        for sign_key in self.sign_keys:
            if not os.path.exists(sign_key):
                raise ValueError(f"Signing key file '{sign_key}' not found on filesystem")
        self.policies = list(set([nft_name.split('.')[0] for nft_name in self.validated_names]))
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
        asset_names = []
        for policy in nft_policy_obj:
            if policy == 'version':
                continue
            if len(policy) != Mint._POLICY_LEN:
                raise ValueError(f"Incorrect looking policy {policy} in file '{filename}'")
            asset_obj = nft_policy_obj[policy]
            if len(asset_obj.keys()) == 0:
                raise ValueError(f"Need at least 1 asset for policy '{policy}' in file '{filename}'")
            asset_name = list(asset_obj.keys())[0]
            full_name = f"{policy}.{asset_name}"
            if full_name in existing:
                raise ValueError(f"Found duplicate asset name '{full_name}' in file '{filename}'")
            self.__validate_str_lengths(asset_obj)
            asset_names.append(full_name)
        return asset_names
