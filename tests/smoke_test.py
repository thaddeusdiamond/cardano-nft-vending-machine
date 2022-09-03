import binascii
import json
import os
import pytest
import signal
import sys

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy
from test_utils.vending_machine import VendingMachineTestConfig

from test_utils.fs import data_file_path, protocol_file_path, secrets_file_path
from test_utils.chain import await_payment, find_min_utxos_for_txn, lovelace_in, send_money

from cardano.wt.blockfrost import BlockfrostApi
from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DONATION_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10 * 1000000
PADDING = 2 * 1000000
VEND_RANDOMLY = True
SINGLE_VEND_MAX = 30

MAX_RETRIES = 1
MAINNET = os.getenv("TEST_ON_MAINNET", 'False').lower() in ('true', '1', 't')
PREVIEW = os.getenv("TEST_ON_PREVIEW", 'False').lower() in ('true', '1', 't')

def get_params_file():
    return 'preview.json' if PREVIEW else 'preprod.json'

def get_network_magic():
    return BlockfrostApi.PREVIEW_MAGIC if PREVIEW else BlockfrostApi.PREPROD_MAGIC

def get_funder_address(request):
    secrets_dir = os.path.join(os.path.dirname(request.fspath), 'secrets')
    return Address.existing(KeyPair.existing(secrets_dir, 'funder'), get_network_magic())

def new_policy_for(policy_keys, policy_dir, script_name):
    policy_keys = KeyPair.new(policy_dir, 'policy')
    script_file_path = os.path.join(policy_dir, script_name)
    return Policy.new(script_file_path, policy_keys.vkey_path, EXPIRATION)

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

def test_mints_nothing_when_no_payment(request, vm_test_config, blockfrost_api):
    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

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
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            []
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

def test_skips_exclusion_utxos(request, vm_test_config, blockfrost_api):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    cardano_cli = CardanoCli(
            protocol_params=protocol_file_path(request, get_params_file())
    )
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    funding_request_txn = send_money(
            buyer,
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    buyer_utxo = await_payment(
            buyer.address,
            funding_request_txn,
            blockfrost_api
    )
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(buyer_utxo)
    payment_txn = send_money(
            payment,
            mint_payment,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_utxo = await_payment(
            payment.address,
            payment_txn,
            blockfrost_api
    )

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DONATION_AMT,
            vm_test_config.metadata_dir,
            policy.script_file_path,
            policy_keys.skey_path,
            NoWhitelist()
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
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            [payment_utxo]
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    drain_payment = lovelace_in(payment_utxo)
    drain_txn = send_money(
            funder,
            drain_payment,
            payment,
            [payment_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

def test_mints_single_asset(request, vm_test_config, blockfrost_api):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    cardano_cli = CardanoCli(
            protocol_params=protocol_file_path(request, get_params_file())
    )
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    funding_request_txn = send_money(
            buyer,
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    buyer_utxo = await_payment(
            buyer.address,
            funding_request_txn,
            blockfrost_api
    )
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(buyer_utxo)
    payment_txn = send_money(
            payment,
            mint_payment,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_utxo = await_payment(
            payment.address,
            payment_txn,
            blockfrost_api
    )

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DONATION_AMT,
            vm_test_config.metadata_dir,
            policy.script_file_path,
            policy_keys.skey_path,
            NoWhitelist()
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

    asset_name = 'WildTangz 1'
    asset_file = f"{asset_name}.json"
    asset_name_hex = binascii.hexlify(asset_name.encode('utf-8')).decode('utf-8')
    sample_metadata = data_file_path(request, os.path.join('smoketest', asset_file))
    with open(sample_metadata, 'r') as sample_metadata_file:
        sample_metadata_json = json.load(sample_metadata_file)
    with open(os.path.join(vm_test_config.metadata_dir, asset_file), 'w') as sample_metadata_out:
        cip_0025_out = {'721': { policy.id: sample_metadata_json }}
        json.dump(cip_0025_out, sample_metadata_out)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            set()
    )
    profit_utxo = await_payment(
            profit.address,
            None,
            blockfrost_api
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"

    minted_assetid = created_assets[0]['asset']
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert minted_assetid[56:] == asset_name_hex, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    assert minted_asset['onchain_metadata'] == sample_metadata_json[asset_name], f"Mismatch in metadata: {minted_asset}"

    drain_payment = lovelace_in(profit_utxo)
    drain_txn = send_money(
            funder,
            drain_payment,
            profit,
            [profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)
