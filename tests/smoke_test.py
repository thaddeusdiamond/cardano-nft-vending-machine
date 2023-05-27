import pytest

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.fs import protocol_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json

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
DONT_VEND_RANDOMLY = False

MIN_UTXO_ON_REFUND = 1600000
MIN_UTXO_RETAINER = 1500000

def test_mints_nothing_when_no_payment(request, vm_test_config, blockfrost_api, cardano_cli):
    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    mint = Mint(
            MINT_PRICES,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
            NoWhitelist()
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
            mainnet=get_mainnet_env()
    )
    nft_vending_machine.validate()
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            []
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

def test_skips_exclusion_utxos(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
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
    mint = Mint(
            MINT_PRICES,
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
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            [payment_utxo]
    )

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    drain_payment = lovelace_in(payment_utxo)
    drain_txn = send_money(
            [funder],
            drain_payment,
            payment,
            [payment_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

def test_blacklists_min_utxo_errors(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MIN_UTXO_ON_REFUND
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
    mint = Mint(
            MINT_PRICES,
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

    assert payment_utxo in exclusions, f"Exclusions did not have {payment_utxo}"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    # Have to end the test here because there is no way to drain... ADA is locked

@pytest.mark.parametrize("vend_randomly", [DONT_VEND_RANDOMLY, VEND_RANDOMLY])
@pytest.mark.parametrize("expiration", [EXPIRATION, None])
@pytest.mark.parametrize("asset_name", ['WildTangz 1', 'WildTangz Sw₳gbito'])
def test_mints_single_asset(request, vm_test_config, blockfrost_api, cardano_cli, expiration, asset_name, vend_randomly):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
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
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=expiration)
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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
            vend_randomly,
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
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"

    minted_assetid = created_assets[0]['asset']
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert minted_assetid[56:] == asset_name_hex(asset_name), f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
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
            [asset_name],
            policy,
            policy_keys,
            expiration,
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

def test_mints_restocked_nfts(request, vm_test_config, blockfrost_api, cardano_cli):
    restock_attempts = 3

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE + PADDING) * restock_attempts + MIN_UTXO_RETAINER
    funding_inputs = find_min_utxos_for_txn(funding_amt, funding_utxos, funder.address)

    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    most_recent_buyer_txn = send_money(
            [buyer],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)

    minted_asset_names = []
    asset_name = "WildTangz 1"
    minted_asset_names.append(asset_name)
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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

    for idx in range(1, restock_attempts + 1):
        buyer_utxo = await_payment(buyer.address, most_recent_buyer_txn, blockfrost_api)
        mint_payment = lovelace_in(buyer_utxo) - MIN_UTXO_RETAINER
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

        if idx != 1:
            asset_name = f"WildTangz {idx}"
            minted_asset_names.append(asset_name)
            create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

        nft_vending_machine.vend(
                vm_test_config.root_dir,
                vm_test_config.locked_dir,
                vm_test_config.txn_metadata_dir,
                set()
        )

        profit_utxo = await_payment(profit.address, None, blockfrost_api)
        profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
        profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_name)) - int(profit_txn['fees'])
        profit_actual = lovelace_in(profit_utxo)
        assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

        minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
        created_assets = blockfrost_api.get_assets(policy.id)
        assert len(created_assets) == idx, f"Test did not create {idx} asset under {policy.id}: {created_assets}"
        min_refund = MINT_PRICE * (restock_attempts - idx)
        assert lovelace_in(minted_utxo) > min_refund, f"Buyer should have received a refund greater than {min_refund} in {minted_utxo}"
        assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"

        for created_asset in created_assets:
            minted_assetid = created_asset['asset']
            assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
            minted_asset_name = hex_to_asset_name(minted_assetid[56:])
            assert minted_asset_name in minted_asset_names, f"Minted asset {minted_asset_name} not in the minter set {minted_asset_names}"

            minted_asset = blockfrost_api.get_asset(minted_assetid)
            assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
            expected_metadata = metadata_json(request, asset_filename(minted_asset_name))[minted_asset_name]
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
        most_recent_buyer_txn = profit_utxo.hash

    burn_utxos = blockfrost_api.get_utxos(buyer.address, [])
    burn_payment = sum([lovelace_in(burn_utxo) for burn_utxo in burn_utxos])
    burn_txn = burn_and_reclaim_tada(
            minted_asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer,
            burn_utxos,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

def test_mints_multiple_assets(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE * SINGLE_VEND_MAX + PADDING
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
    profit_expected = (SINGLE_VEND_MAX * MINT_PRICE) - rebate_expected - int(profit_txn['fees'])
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

def test_refunds_overages_correctly(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE * (SINGLE_VEND_MAX + 1) + PADDING
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

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX * 2)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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

    minted_asset_names = [hex_to_asset_name(created_asset['asset'][56:]) for created_asset in created_assets]
    total_name_chars = sum([len(name) for name in minted_asset_names])
    expected_rebate = Mint.RebateCalculator.calculate_rebate_for(1, len(created_assets), total_name_chars)
    overage = lovelace_in(payment_utxo) - (SINGLE_VEND_MAX * MINT_PRICE)
    assert lovelace_in(minted_utxo) == overage + expected_rebate, f"User did not receive a correct refund of {overage + expected_rebate}"

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            minted_asset_names,
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

def test_marks_too_little_as_a_refund_correctly(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = int(MINT_PRICE / 2)
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

    asset_name = 'WildTangz 1'
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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

    assert payment_utxo in exclusions, f"Exclusions did not have {payment_utxo}"

    try:
        profit_utxo = await_payment(profit.address, None, blockfrost_api)
        assert False, 'Found profit when only refund expected: {profit_utxo}'
    except ValueError:
        pass

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    minter_utxo = await_payment(buyer.address, None, blockfrost_api)
    drain_payment = lovelace_in(minter_utxo)
    assert drain_payment < funding_amt, f"Refund not processed for {minter_utxo}"
    drain_txn = send_money(
            [funder],
            drain_payment,
            buyer,
            [minter_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

def test_refunds_when_metadata_empty(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE * 2 + PADDING
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
    mint = Mint(
            MINT_PRICES,
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

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        profit_utxo = await_payment(profit.address, None, blockfrost_api)
        assert False, 'Found profit when only refund expected: {profit_utxo}'
    except ValueError:
        pass

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    minter_utxo = await_payment(buyer.address, None, blockfrost_api)
    drain_payment = lovelace_in(minter_utxo)
    drain_txn = send_money(
            [funder],
            drain_payment,
            buyer,
            [minter_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

def test_can_handle_multiple_input_addresses(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = int((MINT_PRICE + PADDING) / 2)
    funding_inputs = find_min_utxos_for_txn(funding_amt * 2, funding_utxos, funder.address)

    buyer_one = Address.new(
            vm_test_config.buyers_dir,
            'buyer1',
            get_network_magic()
    )
    buyer_two = Address.new(
            vm_test_config.buyers_dir,
            'buyer2',
            get_network_magic()
    )
    funding_request_txn = send_money(
            [buyer_one, buyer_two],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    buyer_one_utxo = await_payment(buyer_one.address, funding_request_txn, blockfrost_api)
    buyer_two_utxo = await_payment(buyer_two.address, funding_request_txn, blockfrost_api)
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(buyer_one_utxo) + lovelace_in(buyer_two_utxo)
    payment_txn = send_money(
            [payment],
            mint_payment,
            buyer_one,
            [buyer_one_utxo, buyer_two_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_keys=[buyer_two.keypair]
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script')

    asset_name = 'WildTangz 1'
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    profit_utxo = await_payment(profit.address, None, blockfrost_api)

    recipient = None
    try:
        minter_utxo = await_payment(buyer_one.address, profit_utxo.hash, blockfrost_api)
        recipient = buyer_one
    except ValueError:
        pass

    try:
        minter_utxo = await_payment(buyer_two.address, profit_utxo.hash, blockfrost_api)
        if recipient:
            assert False, 'Found NFTs at buyer one and buyer two addresses!'
        recipient = buyer_two
    except ValueError:
        pass

    if not recipient:
        assert False, 'Neither input address received the NFT back!'

    qty_minted = lovelace_in(minter_utxo, policy=policy, asset_name=asset_name)
    assert qty_minted == 1, 'Found {qty_minted} {asset_name} NFTs at {recipient}'

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

    burn_payment = lovelace_in(minter_utxo)
    burn_txn = burn_and_reclaim_tada(
            [asset_name],
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            recipient,
            [minter_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

def test_sends_asset_to_non_reference_input(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer1 = Address.new(
            vm_test_config.buyers_dir,
            'buyer1',
            get_network_magic()
    )
    buyer2 = Address.new(
            vm_test_config.buyers_dir,
            'buyer2',
            get_network_magic()
    )

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_inputs = find_min_utxos_for_txn((MINT_PRICE + PADDING) * 2, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer1, buyer2],
            MINT_PRICE + PADDING,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer1_utxo = await_payment(buyer1.address, funding_request_txn, blockfrost_api)
    buyer2_utxo = await_payment(buyer2.address, funding_request_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint_payment = lovelace_in(buyer1_utxo)
    payment_txn = send_money(
            [payment],
            mint_payment,
            buyer1,
            [buyer1_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            ref_inputs=[buyer2_utxo]
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)

    asset_name = "WildTangz 1"
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer1.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"

    burn_payment = lovelace_in(minted_utxo) + lovelace_in(buyer2_utxo) + lovelace_in(profit_utxo)
    burn_txn = burn_and_reclaim_tada(
            [asset_name],
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            buyer1,
            [minted_utxo, buyer2_utxo, profit_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_keys=[buyer2.keypair, profit.keypair]
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

def test_processes_utxos_in_blockchain_order(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    num_buyers = 5
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(funding_amt * num_buyers, funding_utxos, funder.address)

    buyers = list()
    for buyer_idx in range(num_buyers):
        buyers.append(Address.new(
                vm_test_config.buyers_dir,
                f"buyer{buyer_idx}",
                get_network_magic()
        ))
    funding_request_txn = send_money(
            buyers,
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )

    for buyer_idx in range(num_buyers):
        buyer = buyers[buyer_idx]
        buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
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
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)

    asset_names = [f'WildTangz {serial}' for serial in range(1, num_buyers + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    mint = Mint(
            MINT_PRICES,
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
            DONT_VEND_RANDOMLY,
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

    most_recent_buyer_txn_time = -1
    most_recent_buyer_txn_index = -1
    minted_utxos = []
    for buyer_idx in range(num_buyers):
        buyer = buyers[buyer_idx]
        minted_utxo = await_payment(buyer.address, None, blockfrost_api)
        minted_utxos.append(minted_utxo)
        minted_txn = blockfrost_api.get_txn(minted_utxo.hash)
        minted_txn_time = minted_txn['block_time']
        minted_txn_index = minted_txn['index']
        if minted_txn_time == most_recent_buyer_txn_time:
            assert minted_txn_index > most_recent_buyer_txn_index, f"Mint transaction for buyer{buyer_idx} came in same block time but earlier index than prior"
        else:
            assert minted_txn_time > most_recent_buyer_txn_time, f"Mint transaction for buyer{buyer_idx} came in earlier block time than prior mint"
        most_recent_buyer_txn_time = minted_txn_time
        most_recent_buyer_txn_index = minted_txn_index

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == num_buyers, f"Test did not create {num_buyers} asset under {policy.id}: {created_assets}"

    profit_utxos = blockfrost_api.get_utxos(profit.address, [])
    drain_payment = sum([lovelace_in(profit_utxo) for profit_utxo in profit_utxos])
    drain_txn = send_money(
            [funder],
            drain_payment,
            profit,
            profit_utxos,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, drain_txn, blockfrost_api)

    burn_payment = sum([lovelace_in(minted_utxo) for minted_utxo in minted_utxos])
    burn_txn = burn_and_reclaim_tada(
            asset_names,
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            burn_payment,
            [],
            minted_utxos,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            additional_keys=[buyer.keypair for buyer in buyers]
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"
