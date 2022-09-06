#!/usr/bin/env python3

import argparse
import os

from cardano.wt.blockfrost import BlockfrostApi

def make_nonexistent_dir(dir):
    try:
        os.mkdir(dir)
    except FileExistsError as e:
        raise ValueError(f"Directory '{dir}' exists, aborting to avoid potential conflicts and overwrites!")

def create_whitelist(policy_id, whitelist_dir, blockfrost_api):
    make_nonexistent_dir(whitelist_dir)
    for asset in blockfrost_api.get_assets(policy_id):
        asset_path = os.path.join(whitelist_dir, asset['asset'])
        open(asset_path, 'a').close()

def get_parser():
    parser = argparse.ArgumentParser(description='Initialize an asset-based whitelist for an existing NFT policy')
    parser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
    parser.add_argument('--consumed-dir', required=True, help='Local folder where consumed whitelist files will go after processing (MUST NOT YET EXIST)')
    parser.add_argument('--mainnet', action='store_true', help='Run the initializer against mainnet assets (default is False [preprod])')
    parser.add_argument('--policy-id', required=True, help='Policy ID of the assets to be whitelisted')
    parser.add_argument('--preview', action='store_true', help='Run the initializer against preview assets (default is False [preprod])')
    parser.add_argument('--whitelist-dir', required=True, help='Local folder where whitelist files are stored (MUST NOT YET EXIST)')
    return parser

if __name__ == "__main__":
    args = get_parser().parse_args()
    blockfrost_api = BlockfrostApi(args.blockfrost_project, mainnet=args.mainnet, preview=args.preview)
    make_nonexistent_dir(args.consumed_dir)
    create_whitelist(args.policy_id, args.whitelist_dir, blockfrost_api)
