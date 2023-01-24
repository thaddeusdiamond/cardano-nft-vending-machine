import os
import subprocess
import sys

from test_utils.keys import KeyPair, StakeKeyPair

class Address(object):

    def new(directory, prefix, network_magic):
        keypair = KeyPair.new(directory, prefix)
        return Address.existing(keypair, network_magic)

    def new_staked(directory, prefix, network_magic):
        payment_keypair = KeyPair.new(directory, prefix)
        stake_keypair = StakeKeyPair.new(directory, prefix)
        return Address.existing(payment_keypair, network_magic, stake_keypair=stake_keypair)

    def existing(keypair, network_magic, stake_keypair=None):
        address = Address(keypair, network_magic, stake_keypair)
        address.initialize()
        return address

    def __init__(self, keypair, network_magic, stake_keypair):
        self.keypair = keypair
        self.network_magic = network_magic
        self.stake_keypair = stake_keypair

    def initialize(self):
        address_args = [
            'cardano-cli',
            'address',
            'build',
            '--payment-verification-key-file',
            self.keypair.vkey_path,
            '--testnet-magic',
            self.network_magic
        ]
        if self.stake_keypair:
            address_args.extend(['--stake-verification-key-file', self.stake_keypair.vkey_path])
        self.address = subprocess.check_output(address_args).decode(sys.stdout.encoding).strip()
        self.stake_address = None
        if self.stake_keypair:
            stake_args = [
                'cardano-cli',
                'stake-address',
                'build',
                '--stake-verification-key-file',
                self.stake_keypair.vkey_path,
                '--testnet-magic',
                self.network_magic
            ]
            self.stake_address = subprocess.check_output(stake_args).decode(sys.stdout.encoding).strip()
