import json
import os
import shutil
import sys

from test_utils.fs import data_file_path
from test_utils.vending_machine import vm_test_config

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.utxo import Utxo
from cardano.wt.whitelist.no_whitelist import NoWhitelist

TANGZ_POLICY = '33568ad11f93b3e79ae8dee5ad928ded72adcea719e92108caf1521b'

def test_does_not_vend_without_validation():
    try:
        vending_machine = NftVendingMachine(None, None, None, False, sys.maxsize, None, None, None, mainnet=False)
        vending_machine.vend(None, None, None, [])
        assert False, "Successfully vended without validation"
    except ValueError as e:
        assert 'Attempting to vend from non-validated vending machine' in str(e)

def test_does_not_allow_same_payment_profit():
    try:
        vending_machine = NftVendingMachine('addr123', None, 'addr123', False, sys.maxsize, None, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with same profit and payment addr"
    except ValueError as e:
        assert 'addr123' in str(e)

def test_cascades_validation_to_mint():
    class FakeMinter(object):
        def __init__(self):
            self.is_validated = False
            self.validated_names = []
            self.price = 0
        def validate(self):
            self.is_validated = True
    mint = FakeMinter()
    vending_machine = NftVendingMachine('addr123', None, 'addr456', False, sys.maxsize, mint, None, None, mainnet=False)
    vending_machine.validate()
    assert mint.is_validated, "Did not cascade validation to minter"

def test_does_not_allow_prices_below_threshold_unless_free(request):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(None, 4999999, None, None, simple_script, None, None)
        vending_machine = NftVendingMachine('addr123', None, 'addr456', False, sys.maxsize, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with price below threshold of 5₳"
    except ValueError as e:
        assert '4999999' in str(e)

def test_does_not_allow_donation_below_min_utxo(request):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(None, 4999999, Utxo.MIN_UTXO_VALUE - 1, None, simple_script, None, None)
        vending_machine = NftVendingMachine('addr123', None, 'addr456', False, sys.maxsize, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with donation below threshold of 1₳"
    except ValueError as e:
        assert f"{Utxo.MIN_UTXO_VALUE - 1}" in str(e)

def test_does_not_allow_donation_rebate_min_utxo_to_exceed_price(request, vm_test_config):
    sample_price = 5000000
    sample_donation = 1000000
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(TANGZ_POLICY, sample_price, sample_donation, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
        for i in range(1, 30):
            filename = f"WildTangz {i}.json"
            data_file = data_file_path(request, os.path.join('smoketest', filename))
            with open(data_file, 'r') as data_fileobj:
                data_json = json.load(data_fileobj)
                with open(os.path.join(vm_test_config.metadata_dir, filename), 'w') as out_file:
                    json.dump({'721': {'33568ad11f93b3e79ae8dee5ad928ded72adcea719e92108caf1521b': data_json}}, out_file)
        vending_machine = NftVendingMachine('addr123', None, 'addr456', False, 30, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, 'Successfully validated mint with overlapping asset names'
    except ValueError as e:
        assert f"Price of {sample_price} with donation of {sample_donation} could lead to a minUTxO error due to rebates" in str(e)
