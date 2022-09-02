import os
import subprocess

class KeyPair(object):

    def new(directory, prefix):
        keypair = KeyPair(directory, prefix)
        keypair.initialize()
        return keypair

    def existing(directory, prefix):
        return KeyPair(directory, prefix)

    def __init__(self, directory, prefix):
        self.skey_path = os.path.join(directory, f"{prefix}.skey")
        self.vkey_path = os.path.join(directory, f"{prefix}.vkey")

    def initialize(self):
        subprocess.check_output([
            'cardano-cli',
            'address',
            'key-gen',
            '--signing-key-file',
            self.skey_path,
            '--verification-key-file',
            self.vkey_path
        ])
