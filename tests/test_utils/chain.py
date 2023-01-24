import json
import os
import pytest
import time

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.utxo import Utxo

from test_utils.blockfrost import get_preview_env
from test_utils.fs import protocol_file_path
from test_utils.metadata import asset_name_hex

BURN_RETRIES = 7
BURN_WAIT = 30

WAIT_RETRIES = 7
WAIT_BACKOFF = 30

def await_payment(address, tx_hash, blockfrost_api, exclusions=[]):
    for i in range(WAIT_RETRIES):
        for utxo in blockfrost_api.get_utxos(address, exclusions):
            if not tx_hash or utxo.hash == tx_hash:
                return utxo
        time.sleep(WAIT_BACKOFF)
    raise ValueError(f"Failed to find {tx_hash} at {address}")

def assets_are_empty(remaining_assets):
    if not remaining_assets:
        return True
    for asset in remaining_assets:
        if int(asset['quantity']) > 0:
            return False
    return True

def burn_and_reclaim_tada(asset_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, era='--alonzo-era', additional_keys=[]):
    burn_units = [f"{policy.id}{asset_name_hex(asset_name)}" for asset_name in asset_names]
    burn_names = '+'.join(['.'.join([f"-1 {policy.id}", asset_name_hex(asset_name)]) for asset_name in asset_names])
    return mint_assets_directly(burn_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, burned=burn_units, era=era, additional_keys=additional_keys)

def calculate_remainder_str(lovelace_requested, num_receivers, utxo_inputs, burned, additional_outputs):
    total_qty = {}
    for utxo in utxo_inputs:
        for balance in utxo.balances:
            if not balance.policy in total_qty:
                total_qty[balance.policy] = 0
            total_qty[balance.policy] += balance.lovelace
    total_qty[Utxo.Balance.LOVELACE_POLICY] -= lovelace_requested * num_receivers
    for asset_name in burned:
        total_qty[asset_name] -= 1
    for qty_asset_name in filter(None, additional_outputs.split('+')):
        hex_asset_name = ''.join(qty_asset_name.split(' ')[1].split('.'))
        if hex_asset_name in total_qty:
            total_qty[hex_asset_name] -= 1
    units_qtys = []
    for (unit, qty) in total_qty.items():
        if qty:
            units_qtys.append(f"{qty} {cardano_cli_name(unit)}")
    return '+'.join(units_qtys) if units_qtys else None

def cardano_cli_name(unit):
    return f"{unit[0:56]}.{unit[56:]}" if unit != Utxo.Balance.LOVELACE_POLICY else ''

def get_params_file():
    return 'preview.json' if get_preview_env() else 'preprod.json'

def mint_assets(asset_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir):
    mint_names = '+'.join(['.'.join([f"1 {policy.id}", asset_name_hex(asset_name)]) for asset_name in asset_names])
    return mint_assets_directly(mint_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, outputs=mint_names)

def mint_assets_directly(mint_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, outputs='', burned=[], era='--alonzo-era', additional_keys=[]):
    mint_args = []
    if mint_names:
        mint_args += [
            f"--mint='{mint_names}'",
            f"--minting-script-file {policy.script_file_path}"
        ]
        if expiration:
            mint_args.append(f"--invalid-hereafter {expiration}")
    return send_money(
        [receiver],
        requested,
        sender,
        utxo_inputs,
        cardano_cli,
        blockfrost_api,
        output_dir,
        additional_args=mint_args,
        additional_keys=[policy_keys] + additional_keys,
        additional_outputs=outputs,
        burned=burned,
        era=era
    )

def find_min_utxos_for_txn(requested, utxos, address):
    used_utxos = []
    used = 0
    for utxo in utxos:
        used += lovelace_in(utxo)
        used_utxos.append(utxo)
        if used == requested or used > requested + Utxo.MIN_UTXO_VALUE:
            return used_utxos
    raise ValueError(f"Funding address {address} does not have enough funds to complete the test")

def lovelace_in(utxo, policy=None, asset_name=None):
    if policy:
        unit_name = f"{policy.id}{asset_name_hex(asset_name)}"
    else:
        unit_name = Utxo.Balance.LOVELACE_POLICY
    for balance in utxo.balances:
        if balance.policy == unit_name:
            return balance.lovelace
    raise ValueError(f"No lovelace found for {asset_name} ({unit_name}) in {utxo}")

def policy_is_empty(policy, blockfrost_api):
    for i in range(BURN_RETRIES):
        remaining_assets = blockfrost_api.get_assets(policy.id)
        if assets_are_empty(remaining_assets):
            return True
        time.sleep(BURN_WAIT)
    return False

def send_money(receivers, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, additional_args=[], additional_keys=[], additional_outputs='', ref_inputs=[], burned=[], era='--alonzo-era', metadata=None):
    txn_id = int(time.time())
    tx_in_args = [f"--tx-in {utxo.hash}#{utxo.ix}" for utxo in utxo_inputs]
    remainder = calculate_remainder_str(requested, len(receivers), utxo_inputs, burned, additional_outputs)
    era = '--babbage-era' if ref_inputs else era

    tx_out_args = []
    for receiver in receivers:
        tx_out_args.append(f"--tx-out '{receiver.address}+{requested}'")
    if remainder:
        tx_out_args.append(f"--tx-out '{sender.address}+{remainder}'")
    if additional_outputs:
        tx_out_args[0] = f"--tx-out '{receivers[0].address}+{requested}+{additional_outputs}'"

    additional_args_clone = additional_args.copy()
    additional_args_clone += [f"--read-only-tx-in-reference {ref_input.hash}#{ref_input.ix}" for ref_input in ref_inputs]

    metadata_file = None
    if metadata:
        metadata_file = os.path.join(output_dir, CardanoCli.TXN_DIR, f"{txn_id}.json")
        with open(metadata_file, 'w') as metadata_handle:
            json.dump(metadata, metadata_handle)

    raw_build_file = cardano_cli.build_raw_txn(
        output_dir,
        txn_id,
        tx_in_args,
        tx_out_args,
        0,
        metadata_file,
        additional_args_clone,
        era=era
    )

    signers = additional_keys.copy()
    if sender:
        signers.append(sender.keypair)

    min_fee = cardano_cli.calculate_min_fee(
        raw_build_file,
        len(tx_in_args),
        len(tx_out_args),
        len(signers)
    )
    net_lovelace = requested - min_fee
    tx_out_args[0] = f"--tx-out {receivers[0].address}+{net_lovelace}"
    if additional_outputs:
        tx_out_args[0] = f"--tx-out '{receivers[0].address}+{net_lovelace}+{additional_outputs}'"

    build_file = cardano_cli.build_raw_txn(
        output_dir,
        txn_id,
        tx_in_args,
        tx_out_args,
        min_fee,
        metadata_file,
        additional_args_clone,
        era=era
    )
    signing_files = [keypair.skey_path for keypair in signers]
    signed_file = cardano_cli.sign_txn(signing_files, build_file)
    return blockfrost_api.submit_txn(signed_file)

@pytest.fixture
def cardano_cli(request):
    return CardanoCli(protocol_params=protocol_file_path(request, get_params_file()))
