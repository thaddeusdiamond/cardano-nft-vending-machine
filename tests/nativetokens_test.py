import pytest

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, mint_assets, policy_is_empty, send_money
from test_utils.fs import protocol_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json

from cardano.wt.mint import Mint
from cardano.wt.utxo import Balance
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DEV_FEE_ADDR = None
DEV_FEE_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 100
PADDING = 500000
SINGLE_VEND_MAX = 5
VEND_RANDOMLY = True
DONT_VEND_RANDOMLY = False

NATIVETOKEN_QTY = SINGLE_VEND_MAX * MINT_PRICE
MIN_ADA = 5000000

def test_works_when_no_ada_prices(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MIN_ADA + PADDING
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

    nativetoken_keys = KeyPair.new(vm_test_config.policy_dir, 'nativetoken')
    nativetoken_policy = new_policy_for(nativetoken_keys, vm_test_config.policy_dir, 'nativetoken.script', expiration=EXPIRATION)
    nativetoken = "Token"
    nativetoken_onchain = f"{nativetoken_policy.id}{asset_name_hex(nativetoken)}"
    nativetoken_unit = f"{nativetoken_policy.id}.{asset_name_hex(nativetoken)}"
    nativetoken_selfpayment = lovelace_in(buyer_utxo)
    nativetoken_txn = mint_assets(
        [nativetoken],
        nativetoken_policy,
        nativetoken_keys,
        EXPIRATION,
        buyer,
        nativetoken_selfpayment,
        buyer,
        [buyer_utxo],
        cardano_cli,
        blockfrost_api,
        vm_test_config.root_dir,
        quantity=NATIVETOKEN_QTY
    )
    nativetoken_mint_utxo = await_payment(buyer.address, nativetoken_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(nativetoken_mint_utxo)
    payment_txn = send_money(
            [payment],
            mint_payment,
            buyer,
            [nativetoken_mint_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_outputs=f"{NATIVETOKEN_QTY} {nativetoken_unit}"
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')
    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)
    mint = Mint(
            [Balance(MINT_PRICE, nativetoken_unit)],
            0,
            None,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
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
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == SINGLE_VEND_MAX, f"Test did not create {SINGLE_VEND_MAX} assets under {policy.id}: {created_assets}"
    for asset_name in asset_names:
        assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        asset_name_lens += len(asset_name)
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, SINGLE_VEND_MAX, asset_name_lens)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = Mint.RebateCalculator.calculate_rebate_for(1, 1, len(nativetoken))
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"
    profit_tokens_actual = lovelace_in(profit_utxo, policy=nativetoken_policy, asset_name=nativetoken)
    profit_tokens_expected = MINT_PRICE * SINGLE_VEND_MAX
    assert profit_tokens_expected == profit_tokens_actual, f"Expected {profit_tokens_expected} of {nativetoken_policy.id}, but actual was {profit_tokens_actual}"

    drain_payment = lovelace_in(profit_utxo)
    drain_txn = burn_and_reclaim_tada(
            [nativetoken],
            nativetoken_policy,
            nativetoken_keys,
            EXPIRATION,
            funder,
            drain_payment,
            profit,
            [profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            quantity=NATIVETOKEN_QTY
    )
    await_payment(funder.address, drain_txn, blockfrost_api)
    assert policy_is_empty(nativetoken_policy, blockfrost_api), f"Burned asset successfully but {nativetoken_policy.id} has remaining_assets"

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            asset_names,
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

def test_refunds_nativetokens_if_ada_only_price(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = int(MIN_ADA / 2) + PADDING
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)
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

    token_policy_keys = KeyPair.new(vm_test_config.policy_dir, 'token_policy')
    token_policy = new_policy_for(token_policy_keys, vm_test_config.policy_dir, 'token_policy.script', expiration=EXPIRATION)

    token = "WildTangz WL 1"
    token_onchain = f"{token_policy.id}{asset_name_hex(token)}"
    token_selfpayment = lovelace_in(buyer_utxo)
    token_txn = mint_assets([token], token_policy, token_policy_keys, EXPIRATION, buyer, token_selfpayment, buyer, [buyer_utxo], cardano_cli, blockfrost_api, vm_test_config.root_dir)
    token_utxo = await_payment(buyer.address, token_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(token_utxo)
    payment_txn = send_money(
            [payment],
            mint_payment,
            buyer,
            [token_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_outputs=f"1 {token_policy.id}.{asset_name_hex(token)}"
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)

    asset_name = "WildTangz 1"
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            [Balance(MIN_ADA, Balance.LOVELACE_POLICY)],
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
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

    exclusions = set()
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            exclusions
    )
    assert payment_utxo in exclusions, f"Expected {payment_utxo} in exclusions {exclusions}"

    refund_utxo = await_payment(buyer.address, None, blockfrost_api, exclusions=[token_utxo])
    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    burn_payment = lovelace_in(refund_utxo)
    burn_txn = burn_and_reclaim_tada(
            [token],
            token_policy,
            token_policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

def test_accepts_ada_dev_fee_then_native_tokens_with_both_prices(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MIN_ADA * SINGLE_VEND_MAX) + MIN_ADA + (2 * PADDING)
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

    nativetoken_keys = KeyPair.new(vm_test_config.policy_dir, 'nativetoken')
    nativetoken_policy = new_policy_for(nativetoken_keys, vm_test_config.policy_dir, 'nativetoken.script', expiration=EXPIRATION)
    nativetoken = "Token"
    nativetoken_onchain = f"{nativetoken_policy.id}{asset_name_hex(nativetoken)}"
    nativetoken_unit = f"{nativetoken_policy.id}.{asset_name_hex(nativetoken)}"
    nativetoken_selfpayment = lovelace_in(buyer_utxo)
    nativetoken_txn = mint_assets(
        [nativetoken],
        nativetoken_policy,
        nativetoken_keys,
        EXPIRATION,
        buyer,
        nativetoken_selfpayment,
        buyer,
        [buyer_utxo],
        cardano_cli,
        blockfrost_api,
        vm_test_config.root_dir,
        quantity=NATIVETOKEN_QTY
    )
    nativetoken_mint_utxo = await_payment(buyer.address, nativetoken_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')
    asset_names = [f'WildTangz {serial}' for serial in range(1, (SINGLE_VEND_MAX * 2) + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)
    mint = Mint(
            [Balance(MINT_PRICE, nativetoken_unit), Balance(MIN_ADA, Balance.LOVELACE_POLICY)],
            0,
            None,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
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

    payment_txn = send_money(
            [payment],
            MIN_ADA,
            buyer,
            [nativetoken_mint_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_outputs=f"{NATIVETOKEN_QTY} {nativetoken_unit}"
    )
    leftover_utxo = await_payment(buyer.address, payment_txn, blockfrost_api)
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    exclusions = set()
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            exclusions
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
    profit_expected = Mint.RebateCalculator.calculate_rebate_for(1, 1, len(nativetoken))
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"
    profit_tokens_actual = lovelace_in(profit_utxo, policy=nativetoken_policy, asset_name=nativetoken)
    profit_tokens_expected = MINT_PRICE * SINGLE_VEND_MAX
    assert profit_tokens_expected == profit_tokens_actual, f"Expected {profit_tokens_expected} of {nativetoken_policy.id}, but actual was {profit_tokens_actual}"

    ada_payment_txn = send_money(
            [payment],
            lovelace_in(leftover_utxo),
            buyer,
            [leftover_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    ada_payment_utxo = await_payment(payment.address, ada_payment_txn, blockfrost_api)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            exclusions
    )
    second_profit_utxo = await_payment(profit.address, None, blockfrost_api, exclusions=[profit_utxo])
    second_minted_utxo = await_payment(buyer.address, second_profit_utxo.hash, blockfrost_api)

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == (SINGLE_VEND_MAX * 2), f"Test did not create additional {SINGLE_VEND_MAX} assets under {policy.id}: {created_assets}"

    asset_name_lens = 0
    for minted_asset in created_assets:
        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        try:
            assert lovelace_in(second_minted_utxo, policy=policy, asset_name=asset_name) == 1, f"{asset_name} not minted with correct qty"
            asset_name_lens += len(asset_name)
        except ValueError:
            assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"{asset_name} not minted with correct qty"

        minted_assetid = minted_asset['asset']
        asset_name = hex_to_asset_name(minted_assetid[56:])
        assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
        assert asset_name in asset_names, f"Minted asset {minted_assetid} has unexpected name {asset_name}"

        minted_asset = blockfrost_api.get_asset(minted_assetid)
        assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
        expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
        assert int(minted_asset['quantity']) == 1, f"Minted more than 1 quantity of {minted_asset}"
        assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, SINGLE_VEND_MAX, asset_name_lens)
    second_profit_txn = blockfrost_api.get_txn(second_profit_utxo.hash)
    second_profit_expected = (MIN_ADA * SINGLE_VEND_MAX) - rebate_expected - int(second_profit_txn['fees'])
    second_profit_actual = lovelace_in(second_profit_utxo)
    assert second_profit_actual == second_profit_expected, f"Expected {second_profit_expected}, but actual was {second_profit_actual}"

    drain_payment = lovelace_in(profit_utxo) + lovelace_in(second_profit_utxo)
    drain_txn = burn_and_reclaim_tada(
            [nativetoken],
            nativetoken_policy,
            nativetoken_keys,
            EXPIRATION,
            funder,
            drain_payment,
            profit,
            [profit_utxo, second_profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            quantity=NATIVETOKEN_QTY
    )
    await_payment(funder.address, drain_txn, blockfrost_api)
    assert policy_is_empty(nativetoken_policy, blockfrost_api), f"Burned asset successfully but {nativetoken_policy.id} has remaining_assets"

    burn_payment = lovelace_in(minted_utxo) + lovelace_in(second_minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            asset_names,
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

@pytest.mark.skip('Potentially supported, but untested behavior')
def test_accepts_mixed_ada_nativetokens():
    assert False, "Test not implemented yet"

@pytest.mark.skip('Potentially supported, but untested behavior')
def test_partial_refunds_prioritize_ada_payments():
    assert False, "Test not implemented yet"
