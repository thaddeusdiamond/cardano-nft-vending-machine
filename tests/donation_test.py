from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.fs import protocol_file_path
from test_utils.metadata import create_asset_files

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DONATION_AMT = 2000000
EXPIRATION = 87654321
MINT_PRICE = 10000000
SINGLE_VEND_MAX = 10
VEND_RANDOMLY = True

PADDING = 500000

def test_donation_works(request, vm_test_config, blockfrost_api, cardano_cli):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE * SINGLE_VEND_MAX) + PADDING
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
            mainnet=get_mainnet_env()
    )
    nft_vending_machine.validate()

    asset_names = [f'WildTangz {serial}' for serial in range(1, SINGLE_VEND_MAX + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            set()
    )
    profit_utxo = await_payment(profit.address, None, blockfrost_api)

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == SINGLE_VEND_MAX, f"Test did not create {SINGLE_VEND_MAX} assets under {policy.id}: {created_assets}"
    for asset_name in asset_names:
        assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"

    rebate_expected = Mint.RebateCalculator.calculate_rebate_for(1, SINGLE_VEND_MAX, sum([len(asset_name) for asset_name in asset_names]))
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = (SINGLE_VEND_MAX * MINT_PRICE) - DONATION_AMT - rebate_expected - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected} profit, but actual was {profit_actual}"

    donation_utxo = await_payment(NftVendingMachine._get_donation_addr(get_mainnet_env()), profit_utxo.hash, blockfrost_api)
    donation_actual = lovelace_in(donation_utxo)
    assert donation_actual == DONATION_AMT, f"Expected {DONATION_AMT} donation, but actual was {donation_actual}"

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
