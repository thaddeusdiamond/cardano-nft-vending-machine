import os
import signal

from test_utils.address import Address
from test_utils.keys import KeyPair
from test_utils.policy import Policy, new_policy_for
from test_utils.vending_machine import vm_test_config

from test_utils.blockfrost import blockfrost_api, get_params_file, get_mainnet_env, get_network_magic, get_preview_env
from test_utils.config import get_funder_address
from test_utils.chain import await_payment, burn_and_reclaim_tada, find_min_utxos_for_txn, lovelace_in, policy_is_empty, send_money
from test_utils.fs import protocol_file_path
from test_utils.metadata import asset_filename, asset_name_hex, create_asset_files, hex_to_asset_name, metadata_json
from test_utils.process import launch_py3_subprocess

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.mint import Mint
from cardano.wt.nft_vending_machine import NftVendingMachine
from cardano.wt.whitelist.no_whitelist import NoWhitelist

DONATION_AMT = 0
EXPIRATION = 87654321
MINT_PRICE = 10000000
SINGLE_VEND_MAX = 10

PADDING = 2000000

PROC_WAIT_TIMEOUT = 60

def test_cli_smoke(request, vm_test_config, blockfrost_api):
    funder = get_funder_address(request)
    funding_utxos = blockfrost_api.get_utxos(funder.address, [])
    print('Funder address currently has: ', sum([lovelace_in(funding_utxo) for funding_utxo in funding_utxos]))
    funding_amt = (MINT_PRICE * SINGLE_VEND_MAX) + PADDING
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
    profit = Address.new(
            vm_test_config.payees_dir,
            'profit',
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

    network_args = []
    if get_mainnet_env():
        network_args.append('--mainnet')
    if get_preview_env():
        network_args.append('--preview')
    proc = launch_py3_subprocess('main.py', request, network_args + [
        '--payment-addr', payment.address,
        '--payment-sign-key', payment.keypair.skey_path,
        '--profit-addr', profit.address,
        '--mint-price', str(MINT_PRICE),
        '--mint-script', policy.script_file_path,
        '--mint-sign-key', policy_keys.skey_path,
        '--mint-policy', policy.id,
        '--blockfrost-project', blockfrost_api.project,
        '--metadata-dir', vm_test_config.metadata_dir,
        '--output-dir', vm_test_config.root_dir,
        '--single-vend-max', str(SINGLE_VEND_MAX),
        '--vend-randomly',
        '--no-whitelist'
    ])
    profit_utxo = await_payment(profit.address, None, blockfrost_api)
    try:
        proc.send_signal(signal.SIGINT)
        assert not proc.wait(PROC_WAIT_TIMEOUT), f"{proc} failed ot end in {PROC_WAIT_TIMEOUT} seconds"
    except subprocess.TimeoutExpired:
        assert False, f"Timed out trying to kill process {proc}"

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
    assert profit_actual == profit_expected, "Expected {profit_expected}, but actual was {profit_actual}"

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
