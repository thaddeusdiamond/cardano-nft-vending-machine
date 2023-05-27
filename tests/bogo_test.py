import json
import os
import pytest
import signal
import sys
import time

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.fs import protocol_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json

from cardano.wt.bonuses.bogo import Bogo
from cardano.wt.mint import Mint
from cardano.wt.utxo import Balance
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DEV_FEE_ADDR = None
DEV_FEE_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10 * 1000000
MINT_PRICES = [Balance(MINT_PRICE, Balance.LOVELACE_POLICY)]
PADDING = 500000
SINGLE_VEND_MAX = 30
VEND_RANDOMLY = True

THRESHOLD = 5
ADDITIONAL = 2

def test_does_not_bonus_below_threshold(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE * (THRESHOLD - 1) + PADDING
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

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist(),
            Bogo(THRESHOLD, ADDITIONAL)
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == (THRESHOLD - 1), f"Test did not create {THRESHOLD - 1} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    created_asset_names = []
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        created_asset_names.append(asset_name)
        asset_name_lens += len(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, (THRESHOLD - 1), asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = ((THRESHOLD - 1) * MINT_PRICE) - rebate_expected - int(profit_txn['fees'])
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

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            created_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

def test_bonuses_single_or_multis(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE * (THRESHOLD * 3 + 1) + (PADDING * 2)
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
    mint_payment = MINT_PRICE * THRESHOLD + PADDING
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

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist(),
            Bogo(THRESHOLD, ADDITIONAL)
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == (THRESHOLD + ADDITIONAL), f"Test did not create {THRESHOLD + ADDITIONAL} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, (THRESHOLD + ADDITIONAL), asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = (THRESHOLD * MINT_PRICE) - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    leftover_utxo = await_payment(buyer.address, payment_txn, blockfrost_api)
    second_payment_txn = send_money(
            [payment],
            lovelace_in(leftover_utxo),
            buyer,
            [leftover_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    second_profit_utxo = await_payment(profit.address, None, blockfrost_api, exclusions=[profit_utxo])

    second_minted_utxo = await_payment(buyer.address, second_profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == (3 * (THRESHOLD + ADDITIONAL) + 1), f"Test did not create {3 * (THRESHOLD + ADDITIONAL) + 1} assets under {policy.id}: {created_assets}"

    created_asset_names = []
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        created_asset_names.append(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    drain_payment = lovelace_in(profit_utxo) + lovelace_in(second_profit_utxo)
    drain_txn = send_money(
            [funder],
            drain_payment,
            profit,
            [profit_utxo, second_profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

    burn_payment = lovelace_in(minted_utxo) + lovelace_in(second_minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            created_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [minted_utxo, second_minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

def test_honors_max_available(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE * THRESHOLD) + PADDING
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

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_names = [f'WildTangz {serial}' for serial in range(1, THRESHOLD + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist(),
            Bogo(THRESHOLD, ADDITIONAL)
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == THRESHOLD, f"Test did not create {THRESHOLD} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, THRESHOLD, asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = (THRESHOLD * MINT_PRICE) - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    created_asset_names = []
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        created_asset_names.append(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

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

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            created_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

def test_does_not_add_to_dev_fee(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE * THRESHOLD) + PADDING
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    developer = Address.new(
            vm_test_config.payees_dir,
            'developer',
            get_network_magic()
    )
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
    payment_txn = send_money(
            [payment],
            lovelace_in(buyer_utxo),
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    dev_fee_amt = int(MINT_PRICE * 0.1)
    mint = Mint(
            MINT_PRICES,
            dev_fee_amt,
            developer.address,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist(),
            Bogo(THRESHOLD, ADDITIONAL)
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == (THRESHOLD + ADDITIONAL), f"Test did not create {THRESHOLD + ADDITIONAL} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, (THRESHOLD + ADDITIONAL), asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = (THRESHOLD * MINT_PRICE) - (dev_fee_amt * THRESHOLD) - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    developer_utxo = await_payment(developer.address, profit_utxo.hash, blockfrost_api)
    developer_expected = dev_fee_amt * THRESHOLD
    developer_actual = lovelace_in(developer_utxo)
    assert developer_actual == developer_expected, f"Developer should have received {developer_expected}, received {developer_actual}"

    created_asset_names = []
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        created_asset_names.append(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

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

    drain_dev = lovelace_in(developer_utxo)
    drain_dev_txn = send_money(
            [funder],
            drain_dev,
            developer,
            [developer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_dev_txn, blockfrost_api)

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            created_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

def test_honors_single_vend_max(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE * (SINGLE_VEND_MAX - 3)) + PADDING
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

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist(),
            Bogo(THRESHOLD, ADDITIONAL)
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == SINGLE_VEND_MAX, f"Test did not create {SINGLE_VEND_MAX} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, SINGLE_VEND_MAX, asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = ((SINGLE_VEND_MAX - 3) * MINT_PRICE) - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    created_asset_names = []
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        created_asset_names.append(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

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

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            created_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [minted_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"
