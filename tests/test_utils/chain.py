import time

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.utxo import Utxo

from test_utils.metadata import asset_name_hex

BURN_RETRIES = 3
BURN_WAIT = 30

WAIT_RETRIES = 3
WAIT_BACKOFF = 30

def await_payment(address, tx_hash, blockfrost_api):
    for i in range(WAIT_RETRIES):
        for utxo in blockfrost_api.get_utxos(address, []):
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

def burn_and_reclaim_tada(asset_names, policy, policy_keys, expiration, receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir):
    burn_names = '+'.join(['.'.join([f"-1 {policy.id}", asset_name_hex(asset_name)]) for asset_name in asset_names])
    burn_args = [
        f"--mint='{burn_names}'",
        f"--minting-script-file {policy.script_file_path}"
    ]
    if expiration:
        burn_args.append(f"--invalid-hereafter {expiration}")
    send_money(receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, additional_args=burn_args, additional_signers=[policy_keys.skey_path])

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

def send_money(receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir, additional_args=[], additional_signers=[]):
    txn_id = int(time.time())
    tx_in_args = [f"--tx-in {utxo.hash}#{utxo.ix}" for utxo in utxo_inputs]

    utxo_inputs_total = sum([lovelace_in(utxo) for utxo in utxo_inputs])
    remainder = utxo_inputs_total - requested

    tx_out_args = [f"--tx-out {receiver.address}+{requested}"]
    if remainder > 0:
        tx_out_args.append(f"--tx-out {sender.address}+{remainder}")

    raw_build_file = cardano_cli.build_raw_txn(
        output_dir,
        txn_id,
        tx_in_args,
        tx_out_args,
        0,
        None,
        additional_args
    )

    signers = additional_signers
    signers.append(sender.keypair.skey_path)

    min_fee = cardano_cli.calculate_min_fee(
        raw_build_file,
        len(tx_in_args),
        len(tx_out_args),
        len(signers)
    )
    tx_out_args[0] = f"--tx-out {receiver.address}+{requested - min_fee}"

    build_file = cardano_cli.build_raw_txn(
        output_dir,
        txn_id,
        tx_in_args,
        tx_out_args,
        min_fee,
        None,
        additional_args
    )
    signed_file = cardano_cli.sign_txn(signers, build_file)
    return blockfrost_api.submit_txn(signed_file)
