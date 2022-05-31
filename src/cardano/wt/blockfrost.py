import requests

"""
Repreentation of the Blockfrost web API used in retrieving metadata about txn i/o on the chain.
"""
class BlockfrostApi(object):
    def __init__(self, project, mainnet=False):
        self.project = project
        self.mainnet = mainnet

    def __get_api_base(self):
        return f"https://cardano-{'mainnet' if self.mainnet else 'testnet'}.blockfrost.io/api/v0"

    def __call_api(self, resource):
        return requests.get(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project})

    def get_input_address(self, txn_hash):
        utxo_metadata = self.__call_api(f"txs/{txn_hash}/utxos").json()
        print(utxo_metadata)
        utxo_inputs = set([utxo_input['address'] for utxo_input in utxo_metadata['inputs']])
        if len(utxo_inputs) != 1:
            raise ValueError(f"Txn hash {txn_hash} came from != 1 addresses({utxo_inputs}), aborting...")
        return utxo_inputs.pop()


