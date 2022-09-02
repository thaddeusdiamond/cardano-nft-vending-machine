import json
import os
import pytest
import signal
import sys
import time

from test_utils import protocol_file_path, secrets_file_path
from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy
from test_utils.vending_machine import VendingMachineTestConfig

from cardano.wt.blockfrost import BlockfrostApi
from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DONATION_AMT = 0
EXPIRATION = 87654321
MAINNET = False
MAX_RETRIES = 1
MINT_PRICE = 10 * 1000000
PREVIEW = True
VEND_RANDOMLY = True
SINGLE_VEND_MAX = 30

@pytest.fixture
def vm_test_config():
    return VendingMachineTestConfig()

@pytest.fixture
def blockfrost_api(request):
    blockfrost_key = None
    blockfrost_keyfile_path = 'blockfrost-preview.key' if PREVIEW else 'blockfrost-preprod.key'
    with open(secrets_file_path(request, blockfrost_keyfile_path)) as blockfrost_keyfile:
        blockfrost_key = blockfrost_keyfile.read().strip()
    return BlockfrostApi(blockfrost_key, mainnet=MAINNET, preview=PREVIEW, max_get_retries=MAX_RETRIES)

def get_params_file():
    return 'preview.json' if PREVIEW else 'preprod.json'

def get_network_magic():
    return BlockfrostApi.PREVIEW_MAGIC if PREVIEW else BlockfrostApi.PREPROD_MAGIC

def test_mints_nothing_when_no_payment(request, vm_test_config, blockfrost_api):
    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    script_file_path = os.path.join(vm_test_config.policy_dir, 'policy.script')
    policy = Policy.new(script_file_path, policy_keys.vkey_path, EXPIRATION)

    mint = Mint(
            policy.id,
            MINT_PRICE,
            DONATION_AMT,
            vm_test_config.metadata_dir,
            policy.script_file_path,
            policy_keys.skey_path,
            NoWhitelist()
    )
    cardano_cli = CardanoCli(
            mainnet=MAINNET,
            protocol_params=protocol_file_path(request, get_params_file())
    )

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    profit = Address.new(
            vm_test_config.payees_dir,
            'profit',
            get_network_magic()
    )

    nft_vending_machine = NftVendingMachine(
            payment.address,
            payment.keypair.skey_path,
            profit.address,
            VEND_RANDOMLY,
            SINGLE_VEND_MAX,
            mint,
            blockfrost_api,
            cardano_cli,
            mainnet=MAINNET
    )
    nft_vending_machine.validate()
    nft_vending_machine.vend(
            vm_test_config.output_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            []
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"
