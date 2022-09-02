import os
import subprocess
import sys

from test_utils.keys import KeyPair

class Address(object):

    def new(directory, prefix, network_magic):
        address = Address(directory, prefix, network_magic)
        address.initialize()
        return address

    def __init__(self, directory, prefix, network_magic):
        self.keypair = KeyPair.new(directory, prefix)
        self.network_magic = network_magic

    def initialize(self):
        self.address = subprocess.check_output([
            'cardano-cli',
            'address',
            'build',
            '--payment-verification-key-file',
            self.keypair.vkey_path,
            '--testnet-magic',
            self.network_magic
        ]).decode(sys.stdout.encoding)
