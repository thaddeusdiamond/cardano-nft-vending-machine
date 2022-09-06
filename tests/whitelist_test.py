import os

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_params_file, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, find_min_utxos_for_txn, lovelace_in, mint_assets, policy_is_empty, send_money
from test_utils.fs import data_file_path, protocol_file_path
from test_utils.metadata import asset_name_hex, create_asset_files
from test_utils.process import launch_py3_subprocess

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.asset_whitelist import SingleUseWhitelist

DONATION_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10000000
SINGLE_VEND_MAX = 10
VEND_RANDOMLY = True
WL_EXPIRATION = 76543210

WL_REBATE = 5000000
PADDING = 2000000

def test_validate_requires_whitelist_dir_created(request, vm_test_config):
    whitelist = SingleUseWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(None, MINT_PRICE, DONATION_AMT, vm_test_config.metadata_dir, simple_script, None, whitelist)
    try:
        mint.validate()
        assert False, "Successfully validated mint without a whitelist directory"
    except ValueError as e:
        assert f"Could not find whitelist directory {vm_test_config.whitelist_dir}" in str(e)

def test_validate_requires_consumed_dir_created(request, vm_test_config):
    os.mkdir(vm_test_config.whitelist_dir)
    whitelist = SingleUseWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(None, MINT_PRICE, DONATION_AMT, vm_test_config.metadata_dir, simple_script, None, whitelist)
    try:
        mint.validate()
        assert False, "Successfully validated mint without a whitelist directory"
    except ValueError as e:
        assert f"{vm_test_config.consumed_dir} does not exist" in str(e)

def test_rejects_if_no_asset_sent_to_self(request, vm_test_config, blockfrost_api):
    cardano_cli = CardanoCli(
            protocol_params=protocol_file_path(request, get_params_file())
    )
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_inputs = find_min_utxos_for_txn(WL_REBATE, funding_utxos, funder.address)
    wl_funding_request_txn = send_money(
            [buyer],
            WL_REBATE,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    wl_buyer_utxo = await_payment(buyer.address, wl_funding_request_txn, blockfrost_api)

    wl_policy_keys = KeyPair.new(vm_test_config.policy_dir, 'wl_policy')
    wl_policy = new_policy_for(wl_policy_keys, vm_test_config.policy_dir, 'wl_policy.script', expiration=WL_EXPIRATION)

    wl_pass = "WildTangz WL 1"
    wl_pass_onchain = f"{wl_policy.id}{asset_name_hex(wl_pass)}"
    wl_selfpayment = lovelace_in(wl_buyer_utxo)
    wl_txn = mint_assets([wl_pass], wl_policy, wl_policy_keys, WL_EXPIRATION, buyer, wl_selfpayment, buyer, [wl_buyer_utxo], cardano_cli, blockfrost_api, vm_test_config.root_dir)
    wl_mint_utxo = await_payment(buyer.address, wl_txn, blockfrost_api)

    wl_initializer_args = [
        '--blockfrost-project', blockfrost_api.project,
        '--consumed-dir', vm_test_config.consumed_dir,
        '--whitelist-dir', vm_test_config.whitelist_dir,
        '--policy-id', wl_policy.id
    ]
    if get_preview_env():
        wl_initializer_args.append('--preview')
    if get_mainnet_env():
        wl_initializer_args.append('--mainnet')

    launch_py3_subprocess(os.path.join('scripts', 'initialize_asset_wl.py'), request, wl_initializer_args).wait()
    whitelist = SingleUseWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.is_whitelisted(wl_pass_onchain), f"{wl_pass_onchain} should be on the whitelist"

    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
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
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DONATION_AMT,
            vm_test_config.metadata_dir,
            policy.script_file_path,
            policy_keys.skey_path,
            whitelist
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

    asset_name = "WildTangz 1"
    create_asset_files([asset_name], policy, request, vm_test_config.metadata_dir)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    created_assets = blockfrost_api.get_assets(policy.id)
    assert not created_assets, f"Somehow the test created assets under {policy.id}: {created_assets}"

    assert whitelist.is_whitelisted(wl_pass_onchain), f"{wl_pass_onchain} should have remained on the whitelist"

    burn_payment = lovelace_in(wl_mint_utxo)
    burn_txn = burn_and_reclaim_tada(
            [wl_pass],
            wl_policy,
            wl_policy_keys,
            WL_EXPIRATION,
            funder,
            burn_payment,
            buyer,
            [wl_mint_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, burn_txn, blockfrost_api)

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
