import json
import os
import shutil
import sys

from test_utils.fs import data_file_path
from test_utils.vending_machine import vm_test_config

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.utxo import Utxo, Balance
from cardano.wt.whitelist.no_whitelist import NoWhitelist

MINT_PRICE = [Balance(5000000, Balance.LOVELACE_POLICY)]
FAKE_TOKEN = 'a' * 56 + '.' + 'aaa'

def test_does_not_vend_without_validation():
    try:
        vending_machine = NftVendingMachine(None, None, None, False, sys.maxsize, None, None, None, mainnet=False)
        vending_machine.vend(None, None, None, [])
        assert False, "Successfully vended without validation"
    except ValueError as e:
        assert 'Attempting to vend from non-validated vending machine' in str(e)

def test_does_not_allow_same_payment_profit(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('sign_keys', 'dummy.skey'))
        mint = Mint(MINT_PRICE, 0, None, vm_test_config.metadata_dir, [simple_script], [sign_key], NoWhitelist())
        vending_machine = NftVendingMachine('addr123', None, 'addr123', False, sys.maxsize, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with same profit and payment addr"
    except ValueError as e:
        assert 'Payment address and profit address (addr123) cannot be the same!' in str(e)

def test_does_not_allow_prices_below_threshold_unless_free(request):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('sign_keys', 'dummy.skey'))
        too_low_mint = [Balance(4999999, Balance.LOVELACE_POLICY)]
        mint = Mint(too_low_mint, None, None, None, [simple_script], [sign_key], None)
        vending_machine = NftVendingMachine('addr123', sign_key, 'addr456', False, sys.maxsize, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with price below threshold of 5₳"
    except ValueError as e:
        assert '4999999' in str(e)

def test_does_not_allow_dev_fee_below_min_utxo(request):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(MINT_PRICE, Utxo.MIN_UTXO_VALUE - 1,  None, None, [simple_script], None, None)
        vending_machine = NftVendingMachine('addr123', None, 'addr456', False, sys.maxsize, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated vending machine with donation below threshold of 1₳"
    except ValueError as e:
        assert f"{Utxo.MIN_UTXO_VALUE - 1}" in str(e)

def test_does_not_allow_nonexistent_script_file(request):
    try:
        simple_script = '/path/does/not/exist'
        mint = Mint(MINT_PRICE, 0, None, None, [simple_script], None, None)
        mint.validate()
        assert False, "Successfully validated mint with nonexistent script file"
    except FileNotFoundError as e:
        assert f"No such file or directory: '{simple_script}'" in str(e)

def test_does_not_allow_nonexistent_sign_key(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = '/path/does/not/exist'
        mint = Mint(MINT_PRICE, 0, None, vm_test_config.metadata_dir, [simple_script], [sign_key], None)
        mint.validate()
        assert False, "Successfully validated mint with nonexistent sign key file"
    except ValueError as e:
        assert f"Signing key file '{sign_key}'" in str(e)

def test_does_not_allow_dev_fee_rebate_min_utxo_to_exceed_price(request, vm_test_config):
    sample_price = [Balance(5000000, Balance.LOVELACE_POLICY)]
    sample_donation = 1000000
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('protocol', 'preprod.json'))
        mint = Mint(sample_price, sample_donation, 'addr123', vm_test_config.metadata_dir, [simple_script], [sign_key], NoWhitelist())
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
        assert f"Price of {sample_price[0]} with dev fee of {sample_donation} could lead to a minUTxO error due to rebates" in str(e)

def test_does_not_allow_nonexistent_payment_signing_key(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('sign_keys', 'dummy.skey'))
        bad_sign_key = '/path/does/not/exist'
        mint = Mint(MINT_PRICE, 0, None, vm_test_config.metadata_dir, [simple_script], [sign_key], NoWhitelist())
        vending_machine = NftVendingMachine('addr123', bad_sign_key, 'addr456', False, 30, mint, None, None, mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated mint with nonexistent sign key file"
    except ValueError as e:
        assert f"Payment signing key file '{bad_sign_key}' not found" in str(e)

def test_does_not_allow_payment_addr_without_matching_signing_key(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('sign_keys', 'dummy.skey'))
        mint = Mint(MINT_PRICE, 0, None, vm_test_config.metadata_dir, [simple_script], [sign_key], NoWhitelist())
        vending_machine = NftVendingMachine('addr123', sign_key, 'addr456', False, 30, mint, None, CardanoCli(), mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated mint with nonexistent sign key file"
    except ValueError as e:
        assert f"Could not match addr123 to signature at '{sign_key}' (expected addr_test1vplgrtqgphv0hpx2v6zyzwxxmyh0q4vjrzeuv7qvtk3ev2cmmgd54)" in str(e)

def test_does_not_allow_policies_with_no_matching_script(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        sign_key = data_file_path(request, os.path.join('sign_keys', 'dummy.skey'))
        good_file = data_file_path(request, os.path.join('success', 'WildTangz 1.json'))
        shutil.copy(good_file, vm_test_config.metadata_dir)
        mint = Mint(MINT_PRICE, 0, None, vm_test_config.metadata_dir, [simple_script], [sign_key], NoWhitelist())
        vending_machine = NftVendingMachine('addr_test1vplgrtqgphv0hpx2v6zyzwxxmyh0q4vjrzeuv7qvtk3ev2cmmgd54', sign_key, 'addr456', False, 5, mint, None, CardanoCli(), mainnet=False)
        vending_machine.validate()
        assert False, "Successfully validated mint with nonexistent sign key file"
    except ValueError as e:
        assert f"No matching script file found for policy 33568ad11f93b3e79ae8dee5ad928ded72adcea719e92108caf1521b" in str(e)

def test_does_not_allow_mint_with_duplicate_policy_prices(request, vm_test_config):
    try:
        dupe_price = [Balance(5000000, FAKE_TOKEN), Balance(10000000, FAKE_TOKEN)]
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(dupe_price, None, None, None, [simple_script], None, NoWhitelist())
        mint.validate()
        assert False, f"Successfully validated mint with duplicated price policy '{FAKE_TOKEN}'"
    except ValueError as e:
        assert f"Duplicate price detected for policy '{FAKE_TOKEN}'", aborting in str(e)

def test_does_not_allow_mint_with_short_policy_id(request, vm_test_config):
    try:
        invalid_price = [Balance(5000000, 'invalid_policy_id')]
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(invalid_price, None, None, None, [simple_script], None, NoWhitelist())
        mint.validate()
        assert False, f"Successfully validated mint with invalid price policy 'invalid_policy_id'"
    except ValueError as e:
        assert "Price unit 'invalid_policy_id' does not look like a valid unit name" in str(e)

def test_does_not_allow_mint_with_invalid_policy_id(request, vm_test_config):
    try:
        unit = 'a' * 57
        invalid_price = [Balance(5000000, unit)]
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(invalid_price, None, None, None, [simple_script], None, NoWhitelist())
        mint.validate()
        assert False, f"Successfully validated mint with invalid price policy 'invalid_policy_id'"
    except ValueError as e:
        assert f"Price unit '{unit}' does not look like a valid unit name" in str(e)

def test_does_not_allow_mint_with_nonada_freemint(request, vm_test_config):
    try:
        nonada_freemint = [Balance(0, FAKE_TOKEN)]
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint(nonada_freemint, None, None, None, [simple_script], None, NoWhitelist())
        mint.validate()
        assert False, f"Successfully validated mint with duplicated price policy '{FAKE_TOKEN}'"
    except ValueError as e:
        assert f"Detected invalid zero price for non-ADA policy '{FAKE_TOKEN}'" in str(e)

def test_does_not_allow_mint_with_no_prices(request, vm_test_config):
    try:
        simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
        mint = Mint([], None, None, None, [simple_script], None, NoWhitelist())
        mint.validate()
        assert False, f"Successfully validated mint with no prices"
    except ValueError as e:
        assert 'Must specify at least one valid mint price, even if 0 ADA for free mint' in str(e)
