import argparse
import binascii
import json
import os
import random

from blockfrost import BlockFrostApi, ApiUrls
from cardano.wt.mint import Mint

JPG_STORE = 'addr1zxgx3far7qygq0k6epa0zcvcvrevmn0ypsnfsue94nsn3tvpw288a4x0xf8pxgcntelxmyclq83s0ykeehchz2wtspks905plm'
MAX_OUTPUTS = 25
MAX_ATTEMPTS = 3

def build_commands(tx_outs, tx_in, tx_out_remaining, build_file, mint_assets, metadata_file, script_file, expiration):
    print(' '.join(['cardano-cli', 'transaction', 'build-raw', '--alonzo-era',
        '--fee', str(0),
        ' '.join(tx_outs),
        f"--mint='{'+'.join(mint_assets)}'",
        '--metadata-json-file', metadata_file,
        '--minting-script-file', script_file,
        '--invalid-hereafter', str(expiration),
        '--out-file', build_file,
        '--tx-in', tx_in,
        '--tx-out', tx_out_remaining,
    ]))

def dump_metadata_file(metadata_path, metadata):
    with open(metadata_path, 'w') as metadata_file:
        json.dump(metadata, metadata_file)

def generate_cardano_cli_cmds(airdrop_owners, airdrop_policy, airdrop_dir, output_dir, script_file, expiration):
    total_airdrop = 0
    tx_outs = []
    mint_assets = []
    iteration = 1
    combined_metadata = {'721': {airdrop_policy: {}}}
    for airdrop in airdrop_owners:
        if total_airdrop == MAX_OUTPUTS:
            build_file = os.path.join(output_dir, f"build.raw_{iteration}")
            metadata_path = os.path.join(output_dir, f"metadata_{iteration}.json")
            dump_metadata_file(metadata_path, combined_metadata)
            build_commands(tx_outs, '<TX_IN_HERE>', '<REMAINDER_HERE>', build_file, mint_assets, metadata_path, script_file, expiration)
            total_airdrop = 0
            tx_outs = []
            mint_assets = []
            combined_metadata['721'][airdrop_policy] = {}
            iteration += 1
        total_airdrop += 1
        with open(os.path.join(airdrop_dir, airdrop), 'r') as airdrop_file:
            airdrop_metadata = json.load(airdrop_file)
            asset_name = next(iter(airdrop_metadata['721'][airdrop_policy].keys()))
            asset_hex_name = binascii.hexlify(asset_name.encode()).decode()
            combined_metadata['721'][airdrop_policy][asset_name] = airdrop_metadata['721'][airdrop_policy][asset_name]
            minted_asset = f"1 {airdrop_policy}.{asset_hex_name}"
            tx_outs.append(f"--tx-out='{airdrop_owners[airdrop]}+1250000+{minted_asset}'")
            mint_assets.append(minted_asset)
    build_file = os.path.join(output_dir, f"build.raw_{iteration}")
    metadata_path = os.path.join(output_dir, f"metadata_{iteration}.json")
    dump_metadata_file(metadata_path, combined_metadata)
    build_commands(tx_outs, '<TX_IN_HERE>', '<REMAINDER_HERE>', build_file, mint_assets, metadata_path, script_file, expiration)

def find_utxo_owner(policy, asset_hex, transaction, blockfrost):
    attempt = 1
    while True:
        try:
            utxos = blockfrost.transaction_utxos(transaction.tx_hash).outputs
            for utxo in utxos:
                for amount in utxo.amount:
                    if amount.unit == f"{policy}{asset_hex}":
                        return utxo.address
            raise ValueError(f"No UTXO found with {asset_hex} in {transaction}")
        except Exception as e:
            if attempt >= MAX_ATTEMPTS:
                raise e
            print(f"Retrying after exception: {e}")
            time.sleep(5)
            attempt += 1

def find_owner_for(policy, asset_hex, blockfrost, snapshot):
    transaction_owner = None
    for transaction in blockfrost.asset_transactions(f"{policy}{asset_hex}", order='desc'):
        transaction_owner = transaction
        if transaction.block_time <= snapshot:
            break
    return find_utxo_owner(policy, asset_hex, transaction_owner, blockfrost)

def confirm_trait_for(policy, asset_hex, required_trait, blockfrost):
    [trait_name, trait_val] = required_trait.split('=')
    print(f"{policy}{asset_hex}")
    asset = blockfrost.asset(f"{policy}{asset_hex}")
    metadata = asset.onchain_metadata
    if getattr(metadata, trait_name) != trait_val:
        raise ValueError(f'Invalid required trait (found {metadata})')

def get_parser():
    parser = argparse.ArgumentParser(prog='Airdrop 1:1 to a set of assets')
    parser.add_argument('--policy', required=True, type=str)
    parser.add_argument('--asset-file', required=True, type=str)
    parser.add_argument('--blockfrost-key', required=True, type=str)
    parser.add_argument('--required-trait', required=False, type=str)
    parser.add_argument('--snapshot', required=True, type=int, help="Use -1 to indicate mint wallet")
    parser.add_argument('--random-seed', required=True, type=int)
    parser.add_argument('--output-dir', type=str)
    parser.add_argument('--airdrop-dir', type=str)
    parser.add_argument('--airdrop-policy', type=str)
    parser.add_argument('--airdrop-prefix', type=str)
    parser.add_argument('--expiration', type=str)
    parser.add_argument('--script-file', type=str)
    return parser

if __name__ == '__main__':
    args = get_parser().parse_args()
    random.seed(args.random_seed)
    blockfrost = BlockFrostApi(project_id=args.blockfrost_key, base_url=ApiUrls.mainnet.value)
    asset_owners = {}
    with open(args.asset_file, 'r') as asset_file:
        for asset in asset_file:
            asset = asset.strip()
            asset_hex = binascii.hexlify(asset.encode()).decode()
            if args.required_trait:
                confirm_trait_for(args.policy, asset_hex, args.required_trait, blockfrost)
            owner = find_owner_for(args.policy, asset_hex, blockfrost, args.snapshot)
            if owner == JPG_STORE:
                print(f"{asset} was listed on JPG at {args.snapshot}")
                continue
            asset_owners[asset] = owner
            print(f"{asset} is owned by {owner} at {args.snapshot}")
    print(asset_owners)

    owners_count = {}
    for asset in asset_owners:
        owner = asset_owners[asset]
        if not owner in owners_count:
            owners_count[owner] = 0
        owners_count[owner] += 1
    print(owners_count)

    #airdrop_owners = {}
    #remaining_files = [f"{args.airdrop_prefix}_{i}.json" for i in range(1, len(asset_owners) + 1)]
    #for asset in asset_owners:
    #    airdrop = random.choice(remaining_files)
    #    airdrop_owners[airdrop] = asset_owners[asset]
    #    remaining_files.remove(airdrop)
    #    print(f"Dropping {airdrop} to {asset_owners[asset]}")
    #print(airdrop_owners)
    #os.mkdir(args.output_dir)
    #generate_cardano_cli_cmds(airdrop_owners, args.airdrop_policy, args.airdrop_dir, args.output_dir, args.script_file, args.expiration)
