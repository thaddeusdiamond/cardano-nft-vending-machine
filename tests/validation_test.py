import os
import sys

from test_utils import data_file_path

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine

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
