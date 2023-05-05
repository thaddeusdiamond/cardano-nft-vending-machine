import json
import os
import pytest

from pycardano.cip import cip8
from pycardano.key import SigningKey, StakeSigningKey
from pycardano.network import Network

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_blockfrost_key, get_mainnet_env, get_network_magic
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.fs import data_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json
from test_utils.process import launch_py3_subprocess

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.wallet_whitelist import WalletWhitelist

DEV_FEE_ADDR = None
DEV_FEE_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10000000
NFT_REBATE_MAX = 2000000
PADDING = 500000
SINGLE_VEND_MAX = 10
VEND_RANDOMLY = False

DUMMY_SIGN_KEY = os.path.abspath(__file__)

def initialize_whitelist(request, vm_test_config, whitelist_dir, consumed_dir, buyers, num_mints_per_wl=1, linked_wallets=None):
    temporary_file = os.path.join(vm_test_config.root_dir, 'whitelist_file')
    with open(temporary_file, 'w') as temporary_file_handle:
        lines = []
        for idx in range(len(buyers)):
            buyer = buyers[idx]
            addresses = [buyer.stake_address if buyer.stake_address else buyer.address]
            if linked_wallets and linked_wallets[idx]:
                linked_addresses = [linked_address.stake_address if linked_address.stake_address else linked_address.address for linked_address in linked_wallets[idx]]
                addresses.extend(linked_addresses)
            lines.append(','.join(addresses))
        temporary_file_handle.write('\n'.join(lines))
    wl_initializer_args = [
        'wallet',
        '--wallet-file', temporary_file,
        '--blockfrost-project', get_blockfrost_key(request),
        '--consumed-dir', consumed_dir,
        '--whitelist-dir', whitelist_dir,
        '--num-mints-per-wl', str(num_mints_per_wl)
    ]
    print(f"scripts/initialize_whitelist.py {request} {' '.join(wl_initializer_args)}")
    launch_py3_subprocess(os.path.join('scripts', 'initialize_whitelist.py'), request, wl_initializer_args).wait()

def chunked_str(str_val):
    return [str_val[i:(i + 64)] for i in range(0, len(str_val), 64)]

def get_pycardano_network():
    return Network.MAINNET if get_mainnet_env() else Network.TESTNET

def test_validate_requires_whitelist_dir_created(request, vm_test_config):
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(None, MINT_PRICE, DEV_FEE_AMT, DEV_FEE_ADDR, vm_test_config.metadata_dir, simple_script, DUMMY_SIGN_KEY, whitelist)
    try:
        mint.validate()
        assert False, "Successfully validated mint without a whitelist directory"
    except ValueError as e:
        assert f"Could not find whitelist directory {vm_test_config.whitelist_dir}" in str(e)

def test_validate_requires_consumed_dir_created(request, vm_test_config):
    os.mkdir(vm_test_config.whitelist_dir)
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(None, MINT_PRICE, DEV_FEE_AMT, DEV_FEE_ADDR, vm_test_config.metadata_dir, simple_script, DUMMY_SIGN_KEY, whitelist)
    try:
        mint.validate()
        assert False, "Successfully validated mint without a whitelist directory"
    except ValueError as e:
        assert f"{vm_test_config.consumed_dir} does not exist" in str(e)

def test_rejects_if_no_metadata(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_no_msg_in_metadata(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata={}
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_msg_empty_metadata(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata={'674':{}}
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_msg_stakesign_empty(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata={'674':{'whitelist_proof': {}}}
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_address_signed_but_not_whitelisted(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = StakeSigningKey.load(buyer.keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    wl_buyer = Address.new(
            vm_test_config.buyers_dir,
            'wl_buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [wl_buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(wl_buyer.address) == 1, f"{wl_buyer.address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
            vm_test_config.metadata_dir,
            [policy.script_file_path],
            [policy_keys.skey_path],
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

    assert whitelist.num_whitelisted(buyer.address) == 0, f"{buyer.address} should NOT be on the whitelist"
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    assert whitelist.num_whitelisted(buyer.address) == 0, f"{buyer.address} should NOT be on the whitelist"

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(wl_buyer.address) == 1, f"{wl_buyer.address} should have remained on the whitelist"

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

def test_rejects_if_stake_signed_but_not_whitelisted(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    wl_buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'wl_buyer',
            get_network_magic()
    )

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [wl_buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(wl_buyer.stake_address) == 1, f"{wl_buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(wl_buyer.stake_address) == 1, f"{wl_buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_wrong_message_signed(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign('hello, world!', buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_rejects_if_wrong_payment_address_signed(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    other_buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'other_buyer',
            get_network_magic()
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(other_buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_successfully_mints_signed_stake_key_once(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE + PADDING) * 2
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
    payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)
    second_utxo = await_payment(buyer.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_names[1])) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    second_payment_txn = send_money(
            [payment],
            lovelace_in(second_utxo),
            buyer,
            [second_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1 and int(created_assets[0]['quantity']) == 1, f"Test should NOT create second asset under {policy.id}: {created_assets}"

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
            [asset_names[0]],
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
    burn_utxo = await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

    refund_utxo = await_payment(buyer.address, None, blockfrost_api)
    refund_payment = lovelace_in(refund_utxo)
    assert refund_payment > (MINT_PRICE - PADDING), f"Expecting refund greater than {MINT_PRICE} instead found {refund_payment}"
    refund_txn = send_money(
            [funder],
            refund_payment,
            buyer,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, refund_txn, blockfrost_api)

def test_rejects_if_stringified_msg_not_a_list(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=False, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': stringified_msg[0:64]}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
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
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"

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

def test_supports_whitelisted_unstaked_addresses(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    buyer_skey = SigningKey.load(buyer.keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.address) == 1, f"{buyer.address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE + PADDING) * 2
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
    payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)
    second_utxo = await_payment(buyer.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    expected_asset_name = asset_names.pop(0)
    asset_names.append(expected_asset_name)
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    assert whitelist.num_whitelisted(buyer.address) == 1, f"{buyer.address} should be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.address) == 0, f"{buyer.address} should NOT be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(expected_asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    second_payment_txn = send_money(
            [payment],
            lovelace_in(second_utxo),
            buyer,
            [second_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    assert whitelist.num_whitelisted(buyer.address) == 0, f"{buyer.address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.address) == 0, f"{buyer.address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1 and int(created_assets[0]['quantity']) == 1, f"Test should NOT create second asset under {policy.id}: {created_assets}"

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
            [expected_asset_name],
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
    burn_utxo = await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

    refund_utxo = await_payment(buyer.address, None, blockfrost_api)
    refund_payment = lovelace_in(refund_utxo)
    assert refund_payment > (MINT_PRICE - PADDING), f"Expecting refund greater than {MINT_PRICE} instead found {refund_payment}"
    refund_txn = send_money(
            [funder],
            refund_payment,
            buyer,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, refund_txn, blockfrost_api)

def test_rejects_if_any_payment_addresses_not_included(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )

    other_buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'other_buyer',
            get_network_magic()
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(other_buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer, other_buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(other_buyer.stake_address) == 1, f"{other_buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(2 * funding_amt, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer, other_buyer],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    other_buyer_utxo = await_payment(other_buyer.address, funding_request_txn, blockfrost_api)

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
            [buyer_utxo, other_buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata,
            additional_keys=[other_buyer.keypair]
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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
            vm_test_config.txn_metadata_dir,
            set()
    )

    try:
        await_payment(profit.address, None, blockfrost_api)
        assert False, f"{profit.address} was paid, but should not have been"
    except:
        pass

    assert policy_is_empty(policy, blockfrost_api), f"Somehow the test created assets under {policy.id}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should have remained on the whitelist"
    assert whitelist.num_whitelisted(other_buyer.stake_address) == 1, f"{other_buyer.stake_address} should have remained on the whitelist"

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

def test_avoids_duplicates_with_diff_payment_key(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    otherkey = Address.existing(
            KeyPair.new(vm_test_config.buyers_dir, 'other_buyer'),
            get_network_magic(),
            stake_keypair=buyer.stake_keypair
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer])
    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(2 * funding_amt, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer, otherkey],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    buyer_lovelace = lovelace_in(buyer_utxo)
    assert buyer_lovelace >= (MINT_PRICE + (PADDING / 2)), f"Initialization error, too little lovelace {buyer_lovelace}"
    otherkey_utxo = await_payment(otherkey.address, funding_request_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    payment_txn = send_money(
            [payment],
            buyer_lovelace,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    expected_asset_name = asset_names.pop(0)
    asset_names.append(expected_asset_name)
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(otherkey.stake_address) == 1, f"{otherkey.stake_address} should be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(otherkey.stake_address) == 0, f"{otherkey.stake_address} should NOT be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(expected_asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    otherkey_skey = StakeSigningKey.load(otherkey.stake_keypair.skey_path)
    second_signed_msg = cip8.sign(otherkey.address, otherkey_skey, attach_cose_key=True, network=get_pycardano_network())
    second_stringified_msg = json.dumps(second_signed_msg)
    second_metadata = {'674': {'whitelist_proof': chunked_str(second_stringified_msg)}}

    second_payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            otherkey,
            [otherkey_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(otherkey.stake_address) == 0, f"{otherkey.stake_address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(otherkey.stake_address) == 0, f"{otherkey.stake_address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1 and int(created_assets[0]['quantity']) == 1, f"Test should NOT create second asset under {policy.id}: {created_assets}"

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
            [expected_asset_name],
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
    burn_utxo = await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

    refund_utxo = await_payment(otherkey.address, None, blockfrost_api)
    refund_payment = lovelace_in(refund_utxo)
    assert refund_payment > (MINT_PRICE - PADDING), f"Expecting refund greater than {MINT_PRICE} instead found {refund_payment}"
    refund_txn = send_money(
            [funder],
            refund_payment,
            otherkey,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, refund_txn, blockfrost_api)

def test_avoids_duplicates_with_linked_stake_keys(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    linked_wallet = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer_linked',
            get_network_magic()
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer], num_mints_per_wl=1, linked_wallets=[[linked_wallet]])

    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(2 * funding_amt, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer, linked_wallet],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    buyer_lovelace = lovelace_in(buyer_utxo)
    assert buyer_lovelace >= (MINT_PRICE + (PADDING / 2)), f"Initialization error, too little lovelace {buyer_lovelace}"
    linked_wallet_utxo = await_payment(linked_wallet.address, funding_request_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    payment_txn = send_money(
            [payment],
            buyer_lovelace,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    expected_asset_name = asset_names.pop(0)
    asset_names.append(expected_asset_name)
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 1, f"{linked_wallet.stake_address} should be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(expected_asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    linked_wallet_skey = StakeSigningKey.load(linked_wallet.stake_keypair.skey_path)
    second_signed_msg = cip8.sign(linked_wallet.address, linked_wallet_skey, attach_cose_key=True, network=get_pycardano_network())
    second_stringified_msg = json.dumps(second_signed_msg)
    second_metadata = {'674': {'whitelist_proof': chunked_str(second_stringified_msg)}}

    second_payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            linked_wallet,
            [linked_wallet_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1 and int(created_assets[0]['quantity']) == 1, f"Test should NOT create second asset under {policy.id}: {created_assets}"

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
            [expected_asset_name],
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
    burn_utxo = await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

    refund_utxo = await_payment(linked_wallet.address, None, blockfrost_api)
    refund_payment = lovelace_in(refund_utxo)
    assert refund_payment > (MINT_PRICE - PADDING), f"Expecting refund greater than {MINT_PRICE} instead found {refund_payment}"
    refund_txn = send_money(
            [funder],
            refund_payment,
            linked_wallet,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, refund_txn, blockfrost_api)

def test_skips_non_whitelisted_linked_stake_keys(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    linked_wallet = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer_linked',
            get_network_magic()
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer], linked_wallets=[[linked_wallet]])
    os.remove(os.path.join(vm_test_config.whitelist_dir, f"{linked_wallet.stake_address}_1"))

    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(2 * funding_amt, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer, linked_wallet],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    buyer_lovelace = lovelace_in(buyer_utxo)
    assert buyer_lovelace >= (MINT_PRICE + (PADDING / 2)), f"Initialization error, too little lovelace {buyer_lovelace}"
    linked_wallet_utxo = await_payment(linked_wallet.address, funding_request_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    payment_txn = send_money(
            [payment],
            buyer_lovelace,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    expected_asset_name = asset_names.pop(0)
    asset_names.append(expected_asset_name)
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(expected_asset_name)) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    linked_wallet_skey = StakeSigningKey.load(linked_wallet.stake_keypair.skey_path)
    second_signed_msg = cip8.sign(linked_wallet.address, linked_wallet_skey, attach_cose_key=True, network=get_pycardano_network())
    second_stringified_msg = json.dumps(second_signed_msg)
    second_metadata = {'674': {'whitelist_proof': chunked_str(second_stringified_msg)}}

    second_payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            linked_wallet,
            [linked_wallet_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=second_metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1 and int(created_assets[0]['quantity']) == 1, f"Test should NOT create second asset under {policy.id}: {created_assets}"

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
            [expected_asset_name],
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
    burn_utxo = await_payment(funder.address, burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"

    refund_utxo = await_payment(linked_wallet.address, None, blockfrost_api)
    refund_payment = lovelace_in(refund_utxo)
    assert refund_payment > (MINT_PRICE - PADDING), f"Expecting refund greater than {MINT_PRICE} instead found {refund_payment}"
    refund_txn = send_money(
            [funder],
            refund_payment,
            linked_wallet,
            [refund_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, refund_txn, blockfrost_api)

def test_should_allow_multiple_txns_for_multiple_slots(request, vm_test_config, blockfrost_api, cardano_cli):
    buyer = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer',
            get_network_magic()
    )
    linked_wallet = Address.new_staked(
            vm_test_config.buyers_dir,
            'buyer_linked',
            get_network_magic()
    )

    buyer_skey = StakeSigningKey.load(buyer.stake_keypair.skey_path)
    signed_msg = cip8.sign(buyer.address, buyer_skey, attach_cose_key=True, network=get_pycardano_network())
    stringified_msg = json.dumps(signed_msg)
    metadata = {'674': {'whitelist_proof': chunked_str(stringified_msg)}}

    initialize_whitelist(request, vm_test_config, vm_test_config.whitelist_dir, vm_test_config.consumed_dir, [buyer], num_mints_per_wl=2, linked_wallets=[[linked_wallet]])

    whitelist = WalletWhitelist(vm_test_config.whitelist_dir, vm_test_config.consumed_dir)
    assert whitelist.num_whitelisted(buyer.stake_address) == 2, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 2, f"{buyer.stake_address} should be on the whitelist"

    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = MINT_PRICE + PADDING
    funding_inputs = find_min_utxos_for_txn(2 * funding_amt, funding_utxos, funder.address)
    funding_request_txn = send_money(
            [buyer, linked_wallet],
            funding_amt,
            funder,
            funding_inputs,
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    buyer_utxo = await_payment(buyer.address, funding_request_txn, blockfrost_api)
    buyer_lovelace = lovelace_in(buyer_utxo)
    assert buyer_lovelace >= (MINT_PRICE + (PADDING / 2)), f"Initialization error, too little lovelace {buyer_lovelace}"
    linked_wallet_utxo = await_payment(linked_wallet.address, funding_request_txn, blockfrost_api)

    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    payment_txn = send_money(
            [payment],
            buyer_lovelace,
            buyer,
            [buyer_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=metadata
    )
    payment_utxo = await_payment(payment.address, payment_txn, blockfrost_api)

    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    mint = Mint(
            policy.id,
            MINT_PRICE,
            DEV_FEE_AMT,
            DEV_FEE_ADDR,
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

    asset_names = ["WildTangz 1", "WildTangz 2"]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )

    assert whitelist.num_whitelisted(buyer.stake_address) == 1, f"{buyer.stake_address} should be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 1, f"{linked_wallet.stake_address} should be on the whitelist"

    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    profit_txn = blockfrost_api.get_txn(profit_utxo.hash)
    profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_names[1])) - int(profit_txn['fees'])
    profit_actual = lovelace_in(profit_utxo)
    assert profit_actual == profit_expected, f"Expected {profit_expected}, but actual was {profit_actual}"

    minted_utxo = await_payment(buyer.address, profit_utxo.hash, blockfrost_api)
    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 1, f"Test did not create 1 asset under {policy.id}: {created_assets}"
    assert lovelace_in(minted_utxo) < NFT_REBATE_MAX, f"Buyer requested one and should have received minUTxO back"

    minted_assetid = created_assets[0]['asset']
    asset_name = hex_to_asset_name(minted_assetid[56:])
    assert lovelace_in(minted_utxo, policy=policy, asset_name=asset_name) == 1, f"Buyer does not have {asset_name} in {minted_utxo}"
    assert minted_assetid.startswith(policy.id), f"Minted asset {minted_assetid} does not belong to policy {policy.id}"
    assert asset_name in asset_names, f"Minted asset {minted_assetid} does not have hex name {asset_name}"

    minted_asset = blockfrost_api.get_asset(minted_assetid)
    assert minted_asset, f"Could not retrieve {minted_assetid} from the blockchain"
    expected_metadata = metadata_json(request, asset_filename(asset_name))[asset_name]
    assert minted_asset['onchain_metadata'] == expected_metadata, f"Mismatch in metadata: {minted_asset}"

    linked_wallet_skey = StakeSigningKey.load(linked_wallet.stake_keypair.skey_path)
    second_signed_msg = cip8.sign(linked_wallet.address, linked_wallet_skey, attach_cose_key=True, network=get_pycardano_network())
    second_stringified_msg = json.dumps(second_signed_msg)
    second_metadata = {'674': {'whitelist_proof': chunked_str(second_stringified_msg)}}

    second_payment_txn = send_money(
            [payment],
            MINT_PRICE + PADDING,
            linked_wallet,
            [linked_wallet_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir,
            metadata=second_metadata
    )
    second_payment_utxo = await_payment(payment.address, second_payment_txn, blockfrost_api)

    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    second_profit_utxo = await_payment(profit.address, None, blockfrost_api, exclusions=[profit_utxo])
    second_profit_txn = blockfrost_api.get_txn(second_profit_utxo.hash)
    second_profit_expected = MINT_PRICE - Mint.RebateCalculator.calculate_rebate_for(1, 1, len(asset_names[0])) - int(second_profit_txn['fees'])
    second_profit_actual = lovelace_in(second_profit_utxo)
    assert second_profit_actual == second_profit_expected, f"Expected {second_profit_expected}, but actual was {second_profit_actual}"

    assert whitelist.num_whitelisted(buyer.stake_address) == 0, f"{buyer.stake_address} should NOT be on the whitelist"
    assert whitelist.num_whitelisted(linked_wallet.stake_address) == 0, f"{linked_wallet.stake_address} should NOT be on the whitelist"

    created_assets = blockfrost_api.get_assets(policy.id)
    assert len(created_assets) == 2 and int(created_assets[0]['quantity']) == 1, f"Test should create second asset under {policy.id}: {created_assets}"

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

    burn_payment = lovelace_in(minted_utxo)
    burn_txn = burn_and_reclaim_tada(
            [asset_names[0]],
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

    second_mint_utxo = await_payment(linked_wallet.address, None, blockfrost_api)
    second_burn_payment = lovelace_in(second_mint_utxo)
    second_burn_txn = burn_and_reclaim_tada(
            [asset_names[1]],
            policy,
            policy_keys,
            EXPIRATION,
            funder,
            second_burn_payment,
            linked_wallet,
            [second_mint_utxo],
            cardano_cli,
            blockfrost_api,
            vm_test_config.root_dir
    )
    await_payment(funder.address, second_burn_txn, blockfrost_api)

    assert policy_is_empty(policy, blockfrost_api), f"Burned asset successfully but {policy.id} has remaining_assets"
