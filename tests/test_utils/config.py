import os

from test_utils.address import Address
from test_utils.keys import KeyPair

from test_utils.blockfrost import get_network_magic

FUNDER_NAME = os.environ['FUNDER'] if 'FUNDER' in os.environ else 'funder'

def get_funder_address(request):
    secrets_dir = os.path.join(os.path.dirname(request.fspath), 'secrets')
    print(f"Using funder '{FUNDER_NAME}'")
    return Address.existing(KeyPair.existing(secrets_dir, FUNDER_NAME), get_network_magic())
