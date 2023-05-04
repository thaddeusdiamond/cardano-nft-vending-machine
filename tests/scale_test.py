import datetime
import math
import numpy
import os
import pytest
import time

from scipy import stats

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, cardano_cli, find_min_utxos_for_txn, lovelace_in, mint_assets, policy_is_empty, send_money
from test_utils.fs import data_file_path, protocol_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json
from test_utils.process import launch_py3_subprocess

from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.utxo import Utxo
from cardano.wt.whitelist.asset_whitelist import SingleUseWhitelist, UnlimitedWhitelist
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DEV_FEE_ADDR = None
DEV_FEE_AMT = 0
EXPIRATION = 87654321
SINGLE_VEND_MAX = 20
VEND_RANDOMLY = True

PADDING = 500000

METADATA_FILE_PREFIX = "WildTangz"
MAX_FUNDED_ADDYS = 200
MAX_BURNED_UTXOS = 50
MIN_UTXO_PAYMENT = 2000000

VEND_EXECUTION_WAIT = 30
VEND_WAIT_ATTEMPTS_MAX = 10

@pytest.fixture
def scale_params(request):
    request_opts = vars(request.config.option)
    required_params = [
        { "key": "available_assets", "cli": "--available-assets"},
        { "key": "assets_dir", "cli": "--assets-dir"},
        { "key": "max_nfts", "cli": "--max-nfts"},
        { "key": "min_nfts", "cli": "--min-nfts"},
        { "key": "mint_price", "cli": "--mint-price"},
        { "key": "num_wallets", "cli": "--num-wallets"}
    ]
    scale_params = {}
    for required_param in required_params:
        required_param_key = required_param['key']
        if request_opts[required_param_key] is None:
            pytest.skip(reason=f"Running scale test requires parameter {required_param['cli']}")
        scale_params[required_param_key] = request_opts[required_param_key]
    return scale_params

def get_normal_distribution(size):
    numpy.random.seed(seed=12345)
    return stats.truncnorm.rvs(-.5, .5, loc=.5, scale=1, size=size)

def test_concurrent_wallet_usage(request, vm_test_config, blockfrost_api, cardano_cli, scale_params):
    print(scale_params)
    available_assets = scale_params['available_assets']
    assets_dir = scale_params['assets_dir']
    max_nfts = scale_params['max_nfts']
    min_nfts = scale_params['min_nfts']
    mint_price = scale_params['mint_price']
    num_wallets = scale_params['num_wallets']

    ### LOAD METADATA
    policy_keys = KeyPair.new(vm_test_config.policy_dir, 'policy')
    policy = new_policy_for(policy_keys, vm_test_config.policy_dir, 'policy.script', expiration=EXPIRATION)
    asset_names = [f"{METADATA_FILE_PREFIX} {i}" for i in range(1, available_assets + 1)]
    create_asset_files(asset_names, policy, request, vm_test_config.metadata_dir, test_prefix=f"../../{assets_dir}")

    ### VENDING MACHINE CONFIGURATION
    payment = Address.new(
            vm_test_config.payees_dir,
            'payment',
            get_network_magic()
    )
    mint = Mint(
            mint_price,
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

    ### INITIAL FUNDING TRANSACTIONS
    funder = get_funder_address(request)
    all_wallets = []
    funding_amt = (mint_price * max_nfts) + PADDING
    quantity_mapping = [0 for _ in range(max_nfts + 1)]
    normal_distribution = get_normal_distribution(num_wallets)
    total_iterations = math.ceil(num_wallets / MAX_FUNDED_ADDYS)
    for iteration in range(total_iterations):
        funding_utxos = blockfrost_api.get_utxos(funder.address, [])
        print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
        buyers = []
        start_idx = (iteration * MAX_FUNDED_ADDYS)
        for buyer_idx in range(start_idx, start_idx + MAX_FUNDED_ADDYS):
            if buyer_idx >= num_wallets:
                break
            buyer_obj = Address.new(vm_test_config.buyers_dir, f"buyer_{buyer_idx}", get_network_magic())
            quantity = int(round(normal_distribution[buyer_idx] * (max_nfts - min_nfts)) + min_nfts)
            buyer = {
                "buyer": buyer_obj,
                "quantity": quantity
            }
            quantity_mapping[quantity] += 1
            buyers.append(buyer)
        funding_inputs = find_min_utxos_for_txn(funding_amt * MAX_FUNDED_ADDYS, funding_utxos, funder.address)
        funding_request_txn = send_money(
                [buyer['buyer'] for buyer in buyers],
                funding_amt,
                funder,
                funding_inputs,
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir
        )
        for buyer in buyers:
            buyer['funding_hash'] = funding_request_txn
        all_wallets += buyers
        await_payment(buyers[0]['buyer'].address, funding_request_txn, blockfrost_api)
    for idx in range(len(quantity_mapping)):
        print(f"{quantity_mapping[idx]} buyers will purchase {idx} NFTs")

    ### SEND IN THE PAYMENTS
    for wallet in all_wallets:
        wallet_addr = wallet['buyer'].address
        funding_utxo = await_payment(wallet_addr, wallet['funding_hash'], blockfrost_api)
        mint_payment_avail = min(lovelace_in(funding_utxo), (wallet['quantity'] * mint_price) + PADDING)
        mint_payment = max(mint_payment_avail, MIN_UTXO_PAYMENT)
        payment_txn = send_money(
                [payment],
                mint_payment,
                wallet['buyer'],
                [funding_utxo],
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir
        )
        if wallet_addr == all_wallets[-1]['buyer'].address:
            await_payment(payment.address, payment_txn, blockfrost_api)

    ### DO THE VEND!
    start_time = time.time()
    print(f">>> BEGINNING THE VEND ---> {datetime.datetime.now().isoformat()}")
    nft_vending_machine.vend(
            vm_test_config.root_dir,
            vm_test_config.locked_dir,
            vm_test_config.txn_metadata_dir,
            set()
    )
    end_time = time.time()
    runtime = end_time - start_time
    print(f">>> THE VEND IS COMPLETE ---> {datetime.datetime.now().isoformat()}")
    print(f"^------ Vend completed in {runtime:,.2f}s")

    ### VALIDATE THAT THE VEND WAS DONE CORRECTLY
    created_assets = blockfrost_api.get_assets(policy.id)
    attempted_to_mint = sum([(idx * quantity_mapping[idx]) for idx in range(len(quantity_mapping))])
    expected_num_assets = min(attempted_to_mint, available_assets)
    assert len(created_assets) == expected_num_assets, f"Test did not create {expected_num_assets} asset under {policy.id}: {created_assets}"

    for created_asset in created_assets:
        minted_assetid = created_asset['asset']
        assert hex_to_asset_name(minted_assetid[56:]) in asset_names, f"Minted asset {minted_assetid} not found in {asset_names}"

    ### FINAL DRAIN TRANSACTIONS
    total_iterations = math.ceil(num_wallets / MAX_BURNED_UTXOS)
    for iteration in range(total_iterations):
        funding_utxos = blockfrost_api.get_utxos(funder.address, [])
        funding_total = sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos])
        print(f"Funder address currently has: {funding_total}")
        drain_assets = []
        drain_utxos = []
        drain_signers = []
        drain_amt = 0
        start_idx = iteration * MAX_BURNED_UTXOS
        for wallet_idx in range(start_idx, start_idx + MAX_BURNED_UTXOS):
            if wallet_idx >= num_wallets:
                break
            wallet = all_wallets[wallet_idx]
            buyer_utxos = blockfrost_api.get_utxos(wallet['buyer'].address, [])
            minted_assets = 0
            for buyer_utxo in buyer_utxos:
                for balance in buyer_utxo.balances:
                    if balance.policy == Utxo.Balance.LOVELACE_POLICY:
                        drain_amt += balance.lovelace
                    else:
                        minted_assets += 1
                        drain_assets.append(hex_to_asset_name(balance.policy[56:]))
            assert minted_assets <= wallet['quantity'], f"Requested {wallet['quantity']} from {wallet['buyer'].address} but received {minted_assets}"
            drain_utxos += buyer_utxos
            drain_signers.append(wallet['buyer'].keypair)
        burn_and_reclaim_tada(
                drain_assets,
                policy,
                policy_keys,
                EXPIRATION,
                funder,
                drain_amt,
                [],
                drain_utxos,
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir,
                additional_keys=drain_signers
        )

    all_payment_utxos = list(blockfrost_api.get_utxos(payment.address, []))
    curr_idx = 0
    while curr_idx < len(all_payment_utxos):
        payment_utxos = all_payment_utxos[curr_idx:(curr_idx + 200)]
        drain_payment = sum([lovelace_in(payment_utxo) for payment_utxo in payment_utxos])
        drain_txn = send_money(
                [funder],
                drain_payment,
                payment,
                payment_utxos,
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir
        )
        curr_idx += 200

    all_profit_utxos = list(blockfrost_api.get_utxos(profit.address, []))
    curr_idx = 0
    while curr_idx < len(all_profit_utxos):
        profit_utxos = all_profit_utxos[curr_idx:(curr_idx + 200)]
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
        curr_idx += 200

def test_do_the_drain(request, vm_test_config, blockfrost_api, cardano_cli, scale_params):
    print(scale_params)
    available_assets = scale_params['available_assets']
    max_nfts = scale_params['max_nfts']
    min_nfts = scale_params['min_nfts']
    mint_price = scale_params['mint_price']
    num_wallets = scale_params['num_wallets']
    old_test_dir = vars(request.config.option)['old_test_dir']
    if not old_test_dir:
        pytest.skip('Must provide an old test directory to do the draining')

    policy_keys = KeyPair.existing(old_test_dir, 'policy/policy')
    policy = new_policy_for(policy_keys, os.path.join(old_test_dir, 'policy'), 'policy.script', EXPIRATION)

    funder = get_funder_address(request)
    total_iterations = math.ceil(num_wallets / MAX_BURNED_UTXOS)
    for iteration in range(total_iterations):
        funding_utxos = blockfrost_api.get_utxos(funder.address, [])
        funding_total = sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos])
        print(f"Funder address currently has: {funding_total}")
        drain_assets = []
        drain_utxos = []
        drain_signers = []
        drain_amt = 0
        start_idx = iteration * MAX_BURNED_UTXOS
        for wallet_idx in range(start_idx, start_idx + MAX_BURNED_UTXOS):
            if wallet_idx >= num_wallets:
                break
            buyer_keypair = KeyPair.existing(old_test_dir, f"buyers/buyer_{wallet_idx}")
            buyer = Address.existing(buyer_keypair, get_network_magic())
            buyer_utxos = blockfrost_api.get_utxos(buyer.address, [])
            minted_assets = 0
            for buyer_utxo in buyer_utxos:
                for balance in buyer_utxo.balances:
                    if balance.policy == Utxo.Balance.LOVELACE_POLICY:
                        drain_amt += balance.lovelace
                    else:
                        minted_assets += 1
                        drain_assets.append(hex_to_asset_name(balance.policy[56:]))
            drain_utxos += buyer_utxos
            drain_signers.append(buyer.keypair)
        if not drain_utxos:
            continue
        burn_and_reclaim_tada(
                drain_assets,
                policy,
                policy_keys,
                EXPIRATION,
                funder,
                drain_amt,
                [],
                drain_utxos,
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir,
                additional_keys=drain_signers
        )

    payment_keypair = KeyPair.existing(old_test_dir, 'payees/payment')
    payment = Address.existing(payment_keypair, get_network_magic())
    all_payment_utxos = list(blockfrost_api.get_utxos(payment.address, []))
    curr_idx = 0
    while curr_idx < len(all_payment_utxos):
        payment_utxos = all_payment_utxos[curr_idx:(curr_idx + 200)]
        drain_payment = sum([lovelace_in(payment_utxo) for payment_utxo in payment_utxos])
        drain_txn = send_money(
                [funder],
                drain_payment,
                payment,
                payment_utxos,
                cardano_cli,
                blockfrost_api,
                vm_test_config.root_dir
        )
        curr_idx += 200

    profit_keypair = KeyPair.existing(old_test_dir, 'payees/profit')
    profit = Address.existing(profit_keypair, get_network_magic())
    all_profit_utxos = list(blockfrost_api.get_utxos(profit.address, []))
    curr_idx = 0
    while curr_idx < len(all_profit_utxos):
        profit_utxos = all_profit_utxos[curr_idx:(curr_idx + 200)]
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
        curr_idx += 200
