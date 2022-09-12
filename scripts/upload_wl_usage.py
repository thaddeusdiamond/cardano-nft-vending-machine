#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys

WHITELIST_KEY = 'used_assets'

def upload_to_cloudflare(out_file, cloudflare_args):
    env_copy = os.environ.copy()
    env_copy['CLOUDFLARE_ACCOUNT_ID'] = cloudflare_args['account_id']
    env_copy['CLOUDFLARE_API_TOKEN'] = cloudflare_args['api_token']
    subprocess.check_output([
        'wrangler',
        'pages',
        'publish',
        '--branch',
        cloudflare_args['branch'],
        '--project-name',
        cloudflare_args['project_name'],
        os.path.dirname(out_file)
    ], env=env_copy).decode(sys.stdout.encoding).strip()

def write_to_local(whitelist, out_file):
    with open(out_file, 'w') as whitelist_file:
        json.dump(whitelist, whitelist_file)

def load_new_whitelist(whitelist_dir):
    if not os.path.exists(whitelist_dir):
        return {WHITELIST_KEY: []}
    whitelist_files = os.listdir(whitelist_dir)
    return {WHITELIST_KEY: whitelist_files}

def load_existing_whitelist(old_wl_file):
    if not os.path.exists(old_wl_file):
        return None
    with open(old_wl_file, 'r') as old_wl_filehandle:
        return json.load(old_wl_filehandle)

def get_parser():
    parser = argparse.ArgumentParser(description='Determine if a set of whitelist assets have been recently used in the vending machine')
    parser.add_argument('--old-wl-file', required=True, help='Most recent run of this program that was uploaded to cloud storage')
    parser.add_argument('--out-file', required=True, help='Where to store the new used whitelist information if any changes (can be same as --old-wl-file)')
    parser.add_argument('--whitelist-dir', required=True, help='Local folder where consumed whitelist files have gone after processing by vending machine')

    parser.add_argument('--credentials', help='JSON-formatted application-specific credentials')
    parser.add_argument('--upload-method', help='Mechanism for uploading changes in whitelist files (e.g., CloudFlare)')

    return parser

if __name__ == "__main__":
    args = get_parser().parse_args()
    existing_whitelist = load_existing_whitelist(args.old_wl_file)
    new_whitelist = load_new_whitelist(args.whitelist_dir)
    if new_whitelist != existing_whitelist:
        write_to_local(new_whitelist, args.out_file)
        if not args.upload_method:
            sys.exit(0)
        upload_method = args.upload_method.lower()
        upload_args = json.loads(args.credentials)
        if upload_method == "cloudflare":
            upload_to_cloudflare(args.out_file, upload_args)
        else:
            raise ValueError(f"Unexpected upload method '{upload_method}'")
