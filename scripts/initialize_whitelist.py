#!/usr/bin/env python3

import argparse
import binascii
import os

from blockfrost import BlockFrostApi, ApiUrls
from pycardano import address, network

ADA_HANDLE_POLICY = 'f0ff48bbb7bbe9d59a40f1ce90e9e9d0ff5002ec48f232b49ca0fb9a'

def make_nonexistent_dir(dir):
    try:
        os.mkdir(dir)
    except FileExistsError as e:
        raise ValueError(f"Directory '{dir}' exists, aborting to avoid potential conflicts and overwrites!")

def get_network_flag(mainnet):
    return network.Network.MAINNET if mainnet else network.Network.TESTNET

def create_whitelist_file(identifier, linked_ids, whitelist_dir, prefix, num_mints_per_wl):
    identifier_path = os.path.join(whitelist_dir, identifier)
    for slot in range(1, num_mints_per_wl + 1):
        identifier_slot_path = f"{identifier_path}_{prefix if prefix else ''}{slot}"
        if os.path.exists(identifier_slot_path):
            raise ValueError(f"Found duplicate identifier in input: {identifier}")
        with open(identifier_slot_path, 'a') as identifier_file:
            linked_ids_contents = '\n'.join([f"{linked_id}_{prefix if prefix else ''}{slot}" for linked_id in linked_ids])
            identifier_file.write(linked_ids_contents)

def get_stake_key(identifier, blockfrost_api, mainnet):
    addr_id = None
    if identifier[0] == '$':
        handle_name_hex = binascii.hexlify(identifier.lower()[1:].encode()).decode()
        handle_hex = f"{ADA_HANDLE_POLICY}{handle_name_hex}"
        print(f"Attempting to retrieve handle {identifier}")
        addr_id = blockfrost_api.asset_addresses(handle_hex)[0].address
    elif identifier.startswith('addr') or identifier.startswith('stake'):
        print(f"Decoding from address/stake {identifier}")
        addr_id = identifier

    if not addr_id:
        raise ValueError(f"Unexpected identifier format: {identifier}")

    addr = address.Address.decode(addr_id)
    if not addr.staking_part:
        unstaked_addr = address.Address(payment_part=addr.payment_part, staking_part=None, network=get_network_flag(mainnet))
        print(f"Retrieved unstaked address key {unstaked_addr}")
        return str(unstaked_addr)
    else:
        stake = address.Address(payment_part=None, staking_part=addr.staking_part, network=get_network_flag(mainnet))
        print(f"Retrieved stake key {stake}")
        return str(stake)

def get_parser():
    parser = argparse.ArgumentParser(description='Initialize an asset-based whitelist for an existing NFT policy')
    subparsers = parser.add_subparsers(dest="command", help='Select the desired type of whitelist')

    asset_parser = subparsers.add_parser('asset', help='Asset-based whitelist, retrieved using Blockfrost')
    asset_parser.add_argument('--policy-id', required=True, help='Policy ID of the assets to be whitelisted')

    wallet_parser = subparsers.add_parser('wallet', help='Wallet-based whitelist, where input is a file with line-separated entries, each having all possible wallets')
    wallet_parser.add_argument('--wallet-file', required=True, help='File containing one address/handle per line')

    for subparser in [asset_parser, wallet_parser]:
        subparser.add_argument('--mainnet', action='store_true', help='Run the initializer against mainnet assets (default is False [preprod])')
        subparser.add_argument('--preview', action='store_true', help='Run the initializer against preview assets (default is False [preprod])')
        subparser.add_argument('--blockfrost-project', required=True, help='Blockfrost project ID to use for retrieving chain data')
        subparser.add_argument('--consumed-dir', required=True, help='Local folder where consumed whitelist files will go after processing (MUST NOT YET EXIST)')
        subparser.add_argument('--whitelist-dir', required=True, help='Local folder where whitelist files are stored (MUST NOT YET EXIST)')
        subparser.add_argument('--num-mints-per-wl', required=True, type=int, help='How many whitelist slots should be given for each asset')
        subparser.add_argument('--prefix', required=False, help='Optional (needs to be integer) prefix for whitelist file IDs')

    return parser

if __name__ == "__main__":
    args = get_parser().parse_args()
    make_nonexistent_dir(args.consumed_dir)
    make_nonexistent_dir(args.whitelist_dir)
    base_api = ApiUrls.mainnet if args.mainnet else (ApiUrls.preview if args.preview else ApiUrls.preprod)
    blockfrost_api = BlockFrostApi(project_id=args.blockfrost_project, base_url=base_api.value)
    if args.command == 'asset':
        for asset in blockfrost_api.assets_policy(args.policy_id):
            create_whitelist_file(asset.asset, [], args.whitelist_dir, args.prefix, args.num_mints_per_wl)
    elif args.command == 'wallet':
        for line in open(args.wallet_file, 'r'):
            identifiers = None
            num_mints = args.num_mints_per_wl
            if ':' in line:
                ids_num = line.strip().split(':')
                num_mints = int(ids_num[1])
                identifiers = ids_num[0].split(',')
            else:
                identifiers = line.strip().split(',')
            for idx in range(len(identifiers)):
                raw_id = identifiers[idx]
                stake_id = get_stake_key(raw_id, blockfrost_api, args.mainnet)
                other_ids = [get_stake_key(other_id, blockfrost_api, args.mainnet) for other_id in identifiers if other_id != raw_id]
                create_whitelist_file(stake_id, other_ids, args.whitelist_dir, args.prefix, num_mints)
    else:
        raise ValueError(f"Unexpected command {args.command}")
