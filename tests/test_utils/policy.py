import json
import os
import subprocess
import sys

from test_utils.keys import KeyPair

EXPIRATION = 87654321

def new_policy_for(policy_keys, policy_dir, script_name, expiration=EXPIRATION):
    policy_keys = KeyPair.new(policy_dir, 'policy')
    script_file_path = os.path.join(policy_dir, script_name)
    return Policy.new(script_file_path, policy_keys.vkey_path, expiration)

class Policy(object):

    def new(script_file_path, vkey_path, exp_slot=None):
        policy = Policy(script_file_path, vkey_path, exp_slot)
        policy.initialize()
        return policy

    def __init__(self, script_file_path, vkey_path, exp_slot):
        self.script_file_path = script_file_path
        self.vkey_path = vkey_path
        self.exp_slot = exp_slot

    def initialize(self):
        keyhash = subprocess.check_output([
            'cardano-cli',
            'address',
            'key-hash',
            '--payment-verification-key-file',
            self.vkey_path
        ]).decode(sys.stdout.encoding).strip()
        scripts = [{ "type": "sig", "keyHash": keyhash }]
        if self.exp_slot:
            scripts.append({ "type": "before", "slot": self.exp_slot })
        script = {
          "type": "all",
          "scripts": scripts
        }
        with open(self.script_file_path, 'w') as script_file:
            json.dump(script, script_file)
        self.id = subprocess.check_output([
            'cardano-cli',
            'transaction',
            'policyid',
            '--script-file',
            self.script_file_path
        ]).decode(sys.stdout.encoding).strip()
