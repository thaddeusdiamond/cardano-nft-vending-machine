import binascii
import json
import os

from test_utils.fs import data_file_path

def asset_filename(asset_name):
    return f"{asset_name}.json"

def asset_name_hex(asset_name):
    return binascii.hexlify(asset_name.encode('utf-8')).decode('utf-8')

def create_asset_files(asset_names, policy, request, metadata_dir, test_prefix='smoketest'):
    for asset_name in asset_names:
        asset_file = asset_filename(asset_name)
        sample_metadata_json = metadata_json(request, asset_file, test_prefix)
        with open(os.path.join(metadata_dir, asset_file), 'w') as sample_metadata_out:
            cip_0025_out = {'721': { policy.id: sample_metadata_json }}
            json.dump(cip_0025_out, sample_metadata_out)

def create_combined_pack(policy_asset_map, request, metadata_dir, test_prefix='smoketest'):
    policy_metadata_map = {}
    combined_name = ''
    for policy in policy_asset_map:
        asset_names = policy_asset_map[policy]
        for asset_name in asset_names:
            combined_name += asset_name
            asset_file = asset_filename(asset_name)
            sample_metadata_json = metadata_json(request, asset_file, test_prefix)
            if not policy in policy_metadata_map:
                policy_metadata_map[policy] = {}
            policy_metadata_map[policy][asset_name] = sample_metadata_json[asset_name]
    with open(os.path.join(metadata_dir, asset_filename(combined_name)), 'w') as sample_metadata_out:
        json.dump({'721': policy_metadata_map}, sample_metadata_out)

def hex_to_asset_name(asset_name_hex):
    return binascii.unhexlify(asset_name_hex).decode('utf-8')

def metadata_json(request, asset_file, test_prefix='smoketest'):
    sample_metadata = data_file_path(request, os.path.join(test_prefix, asset_file))
    with open(sample_metadata, 'r') as sample_metadata_file:
        return json.load(sample_metadata_file)
