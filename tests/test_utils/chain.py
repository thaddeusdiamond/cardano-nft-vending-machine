import time

from cardano.wt.cardano_cli import CardanoCli
from cardano.wt.utxo import Utxo

WAIT_RETRIES = 3
WAIT_BACKOFF = 30

def await_payment(address, tx_hash, blockfrost_api):
    for i in range(WAIT_RETRIES):
        for utxo in blockfrost_api.get_utxos(address, []):
            if utxo.hash == tx_hash:
                return utxo
        time.sleep(WAIT_BACKOFF)
    raise ValueError(f"Failed to find {tx_hash} at {address}")

def find_min_utxos_for_txn(requested, utxos, address):
    used_utxos = []
    used = 0
    for utxo in utxos:
        used += lovelace_in(utxo)
        used_utxos.append(utxo)
        if used >= requested:
            return used_utxos
    raise ValueError(f"Funding address {address} does not have enough funds to complete the test")

def lovelace_in(utxo):
    for balance in utxo.balances:
        if balance.policy == Utxo.Balance.LOVELACE_POLICY:
            return balance.lovelace
    raise ValueError(f"No lovelace found in {utxo}")

def send_money(receiver, requested, sender, utxo_inputs, cardano_cli, blockfrost_api, output_dir):
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
        []
    )

    min_fee = cardano_cli.calculate_min_fee(
        raw_build_file,
        len(tx_in_args),
        len(tx_out_args),
        CardanoCli._WITNESS_COUNT
    )
    tx_out_args[0] = f"--tx-out {receiver.address}+{requested - min_fee}"

    build_file = cardano_cli.build_raw_txn(
        output_dir,
        txn_id,
        tx_in_args,
        tx_out_args,
        min_fee,
        None,
        []
    )
    signed_file = cardano_cli.sign_txn([sender.keypair.skey_path], build_file)
    return blockfrost_api.submit_txn(signed_file)
