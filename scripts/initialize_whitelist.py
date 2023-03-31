#!/usr/bin/env python3

import argparse
import os

from cardano.wt.blockfrost import BlockfrostApi

def make_nonexistent_dir(dir):
    try:
        os.mkdir(dir)
    except FileExistsError as e:
        raise ValueError(f"Directory '{dir}' exists, aborting to avoid potential conflicts and overwrites!")

def create_whitelist_file(identifier, linked_ids, whitelist_dir, num_mints_per_wl):
    identifier_path = os.path.join(whitelist_dir, identifier)
    for slot in range(1, num_mints_per_wl + 1):
        identifier_slot_path = f"{identifier_path}_{slot}"
        if os.path.exists(identifier_slot_path):
            raise ValueError(f"Found duplicate identifier in input: {identifier}")
        with open(identifier_slot_path, 'a') as identifier_file:
            linked_ids_contents = '\n'.join([f"{linked_id}_{slot}" for linked_id in linked_ids])
            identifier_file.write(linked_ids_contents)

def get_parser():
    parser = argparse.ArgumentParser(description='Initialize an asset-based whitelist for an existing NFT policy')
    subparsers = parser.add_subparsers(dest="command", help='Select the desired type of whitelist')

    asset_parser = subparsers.add_parser('asset', help='Asset-based whitelist, retrieved using Blockfrost')
    asset_parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    asset_parser.add_argument('--policy-id', required=True, help='Policy ID of the assets to be whitelisted')
    asset_parser.add_argument('--mainnet', action='store_true', help='Run the initializer against mainnet assets (default is False [preprod])')
    asset_parser.add_argument('--preview', action='store_true', help='Run the initializer against preview assets (default is False [preprod])')

    wallet_parser = subparsers.add_parser('wallet', help='Wallet-based whitelist, where input is a file with line-separated entries, each having all possible wallets')
    wallet_parser.add_argument('--wallet-file', required=True, help='Blockfrost project ID to use for retrieving chain data')

    for subparser in [asset_parser, wallet_parser]:
        subparser.add_argument('--consumed-dir', required=True, help='Local folder where consumed whitelist files will go after processing (MUST NOT YET EXIST)')
        subparser.add_argument('--whitelist-dir', required=True, help='Local folder where whitelist files are stored (MUST NOT YET EXIST)')
        subparser.add_argument('--num-mints-per-wl', required=True, type=int, help='How many whitelist slots should be given for each asset')

    return parser

if __name__ == "__main__":
    args = get_parser().parse_args()
    make_nonexistent_dir(args.consumed_dir)
    make_nonexistent_dir(args.whitelist_dir)
    if args.command == 'asset':
        blockfrost_api = BlockfrostApi(args.blockfrost_project, mainnet=args.mainnet, preview=args.preview)
        for asset in blockfrost_api.get_assets(args.policy_id):
            create_whitelist_file(asset['asset'], [], args.whitelist_dir, args.num_mints_per_wl)
    elif args.command == 'wallet':
        for line in open(args.wallet_file, 'r'):
            identifiers = line.strip().split(',')
            for idx in range(len(identifiers)):
                identifier = identifiers[idx]
                other_ids = [other_id for other_id in identifiers if other_id != identifier]
                create_whitelist_file(identifier, other_ids, args.whitelist_dir, args.num_mints_per_wl)
    else:
        raise ValueError(f"Unexpected command {args.command}")
