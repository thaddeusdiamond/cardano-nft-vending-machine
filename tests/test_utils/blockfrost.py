import os
import pytest

from test_utils.fs import secrets_file_path

from cardano.wt.blockfrost import BlockfrostApi

BLOCKFROST_RETRIES = 3

def get_mainnet_env():
    return os.getenv("TEST_ON_MAINNET", 'False').lower() in ('true', '1', 't')

def get_preview_env():
    return os.getenv("TEST_ON_PREVIEW", 'False').lower() in ('true', '1', 't')

def get_params_file():
    return 'preview.json' if get_preview_env() else 'preprod.json'

def get_network_magic():
    return BlockfrostApi.PREVIEW_MAGIC if get_preview_env() else BlockfrostApi.PREPROD_MAGIC

@pytest.fixture
def blockfrost_api(request):
    blockfrost_key = None
    blockfrost_keyfile_path = 'blockfrost-preview.key' if get_preview_env() else 'blockfrost-preprod.key'
    with open(secrets_file_path(request, blockfrost_keyfile_path)) as blockfrost_keyfile:
        blockfrost_key = blockfrost_keyfile.read().strip()
    return BlockfrostApi(
        blockfrost_key,
        mainnet=get_mainnet_env(),
        preview=get_preview_env(),
        max_get_retries=BLOCKFROST_RETRIES
    )
