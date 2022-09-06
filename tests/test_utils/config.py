import os

from test_utils.address import Address
from test_utils.keys import KeyPair

from test_utils.blockfrost import get_network_magic

def get_funder_address(request):
    secrets_dir = os.path.join(os.path.dirname(request.fspath), 'secrets')
    return Address.existing(KeyPair.existing(secrets_dir, 'funder'), get_network_magic())
