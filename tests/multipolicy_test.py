import json
import os
import pytest
import signal
import sys
import time

from test_utils.address import Address
from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.keys import KeyPair
from test_utils.metadata import asset_filename, create_asset_files, create_combined_pack, hex_to_asset_name, metadata_json
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DEV_FEE_ADDR = None
DEV_FEE_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10 * 1000000
PADDING = 1500000
SINGLE_VEND_MAX = 30
VEND_RANDOMLY = False

def test_mints_multiple_policies_in_sequence(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = 2 * (MINT_PRICE + PADDING)
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    funding_request_txn = send_money(
            [buyer],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    payment_one_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_one_utxo = await_payment(payment.address, payment_one_txn, blockfrost_api)
    change_utxo = await_payment(buyer.address, payment_one_txn, blockfrost_api)

    payment_two_txn = send_money(
            [payment],
            lovelace_in(change_utxo),
            buyer,
            [change_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_two_utxo = await_payment(payment.address, payment_two_txn, blockfrost_api)

    policy_one_keys = KeyPair.new(vm_test_config.policy_dir, 'policy1')
    policy_one = new_policy_for(policy_one_keys, vm_test_config.policy_dir, 'policy1.script')
    policy_two_keys = KeyPair.new(vm_test_config.policy_dir, 'policy2')
    policy_two = new_policy_for(policy_two_keys, vm_test_config.policy_dir, 'policy2.script')

    policy_one_names = ["WildTangz 1"]
    create_asset_files(policy_one_names, policy_one, request, vm_test_config.metadata_dir)
    policy_two_names = ["WildTangz 2"]
    create_asset_files(policy_two_names, policy_two, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy_one.script_file_path, policy_two.script_file_path],
            [policy_one_keys.skey_path, policy_two_keys.skey_path],
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
            mainnet=get_mainnet_env()
    )
    nft_vending_machine.validate()

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    profit_one_utxo = await_payment(profit.address, None, blockfrost_api)
    minted_one_utxo = await_payment(buyer.address, profit_one_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy_one.id)
    assert len(created_assets) == 1, f"Test did not create any assets under {policy_one.id}: {created_assets}"
    for asset_name in policy_one_names:
        assert lovelace_in(minted_one_utxo, policy=policy_one, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_one_utxo}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, 1, len(policy_one_names[0]))
    profit_one_txn = blockfrost_api.get_txn(profit_one_utxo.hash)
    profit_one_expected = MINT_PRICE - rebate_expected - int(profit_one_txn['fees'])
    profit_one_actual = lovelace_in(profit_one_utxo)
    assert profit_one_actual == profit_one_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    profit_two_utxo = await_payment(profit.address, None, blockfrost_api, exclusions=[profit_one_utxo])
    minted_two_utxo = await_payment(buyer.address, profit_two_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy_two.id)
    assert len(created_assets) == 1, f"Test did not create any assets under {policy_two.id}: {created_assets}"
    for asset_name in policy_two_names:
        assert lovelace_in(minted_two_utxo, policy=policy_two, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_two_utxo}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, 1, len(policy_two_names[0]))
    profit_two_txn = blockfrost_api.get_txn(profit_two_utxo.hash)
    profit_two_expected = MINT_PRICE - rebate_expected - int(profit_two_txn['fees'])
    profit_two_actual = lovelace_in(profit_two_utxo)
    assert profit_two_actual == profit_two_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    drain_payment = lovelace_in(profit_one_utxo) + lovelace_in(profit_two_utxo)
    drain_txn = send_money(
            [funder],
            drain_payment,
            profit,
            [profit_one_utxo, profit_two_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

    burn_one_txn = burn_and_reclaim_tada(
            policy_one_names,
            policy_one,
            policy_one_keys,
            EXPIRATION,
            funder,
            lovelace_in(minted_one_utxo),
            buyer,
            [minted_one_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_one_txn, blockfrost_api)
    assert policy_is_empty(policy_one, blockfrost_api), f"Burned asset successfully but {policy_one.id} has remaining_assets"

    burn_two_txn = burn_and_reclaim_tada(
            policy_two_names,
            policy_two,
            policy_two_keys,
            EXPIRATION,
            funder,
            lovelace_in(minted_two_utxo),
            buyer,
            [minted_two_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_two_txn, blockfrost_api)
    assert policy_is_empty(policy_two, blockfrost_api), f"Burned asset successfully but {policy_two.id} has remaining_assets"

def test_mints_multiple_policies_in_same_pack_file(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + (PADDING * 2)
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    funding_request_txn = send_money(
            [buyer],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(buyer_utxo)
    payment_txn = send_money(
            [payment],
            mint_payment,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_one_keys = KeyPair.new(vm_test_config.policy_dir, 'policy1')
    policy_one = new_policy_for(policy_one_keys, vm_test_config.policy_dir, 'policy1.script')
    policy_two_keys = KeyPair.new(vm_test_config.policy_dir, 'policy2')
    policy_two = new_policy_for(policy_two_keys, vm_test_config.policy_dir, 'policy2.script')

    policy_one_names = ["WildTangz 1", "WildTangz 2"]
    policy_two_names = ["WildTangz 3"]
    create_combined_pack({
        policy_one.id: policy_one_names,
        policy_two.id: policy_two_names
    }, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy_one.script_file_path, policy_two.script_file_path],
            [policy_one_keys.skey_path, policy_two_keys.skey_path],
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
            mainnet=get_mainnet_env()
    )
    nft_vending_machine.validate()

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)

    asset_name_lens = 0

    created_assets = blockfrost_api.get_assets(policy_one.id)
    assert len(created_assets) == 2, f"Test did not create 2 assets under {policy_one.id}: {created_assets}"
    for asset_name in policy_one_names:
        assert lovelace_in(minted_utxo, policy=policy_one, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
        assert minted_assetid.startswith(policy_one.id), f"Minted asset {minted_assetid} does not belong to policy {policy_one.id}"
        assert asset_name in policy_one_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"
        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    created_assets = blockfrost_api.get_assets(policy_two.id)
    assert len(created_assets) == 1, f"Test did not create 1 assets under {policy_two.id}: {created_assets}"
    for asset_name in policy_two_names:
        assert lovelace_in(minted_utxo, policy=policy_two, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
        assert minted_assetid.startswith(policy_two.id), f"Minted asset {minted_assetid} does not belong to policy {policy_two.id}"
        assert asset_name in policy_two_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"
        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(2, 3, asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    drain_payment = lovelace_in(profit_utxo)
    drain_txn = send_money(
            [funder],
            drain_payment,
            profit,
            [profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

    burn_one_payment = lovelace_in(minted_utxo) - PADDING
    burn_one_txn = burn_and_reclaim_tada(
            policy_one_names,
            policy_one,
            policy_one_keys,
            EXPIRATION,
            funder,
            burn_one_payment,
            buyer,
            [minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_one_txn, blockfrost_api)
    burn_one_utxo = await_payment(buyer.address, burn_one_txn, blockfrost_api)
    assert policy_is_empty(policy_one, blockfrost_api), f"Burned asset successfully but {policy_one.id} has remaining_assets"

    burn_two_payment = lovelace_in(burn_one_utxo)
    burn_two_txn = burn_and_reclaim_tada(
            policy_two_names,
            policy_two,
            policy_two_keys,
            EXPIRATION,
            funder,
            burn_two_payment,
            buyer,
            [burn_one_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_two_txn, blockfrost_api)
    assert policy_is_empty(policy_two, blockfrost_api), f"Burned asset successfully but {policy_two.id} has remaining_assets"
