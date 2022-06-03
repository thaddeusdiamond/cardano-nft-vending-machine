import json
import requests

from http import HTTPStatus

from cardano.wt.utxo import Utxo

"""
Repreentation of the Blockfrost web API used in retrieving metadata about txn i/o on the chain.
"""
class BlockfrostApi(object):
    def __init__(self, project, mainnet=False):
        self.project = project
        self.mainnet = mainnet

    def __get_api_base(self):
        return f"https://cardano-{'mainnet' if self.mainnet else 'testnet'}.blockfrost.io/api/v0"

    def __call_get_api(self, resource):
        api_resp = requests.get(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project})
        print(f"Blockfrost API: {resource} ({api_resp.status_code})")
        api_resp.raise_for_status()
        print(api_resp.json())
        return api_resp.json()

    def __call_post_api(self, content_type, resource, data):
        api_resp = requests.post(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project, 'Content-Type': content_type}, data=data)
        print(f"Blockfrost API: {resource} ({api_resp.status_code})")
        print(api_resp.text)
        api_resp.raise_for_status()
        return api_resp.json()


    def get_input_address(self, txn_hash):
        utxo_metadata = self.__call_get_api(f"txs/{txn_hash}/utxos")
        utxo_inputs = set([utxo_input['address'] for utxo_input in utxo_metadata['inputs']])
        if len(utxo_inputs) != 1:
            raise ValueError(f"Txn hash {txn_hash} came from != 1 addresses({utxo_inputs}), aborting...")
        return utxo_inputs.pop()

    def get_utxos(self, address, exclusions):
        try:
            utxo_data = self.__call_get_api(f"addresses/{address}/utxos")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == HTTPStatus.NOT_FOUND:
                return []
            raise e
        available_utxos = set()
        #print('EXCLUSIONS\t', [f'{utxo.hash}#{utxo.ix}' for utxo in exclusions])
        for raw_utxo in utxo_data:
            balances = [Utxo.Balance(int(balance['quantity']), balance['unit']) for balance in raw_utxo['amount']]
            utxo = Utxo(raw_utxo['tx_hash'], raw_utxo['output_index'], balances)
            if utxo in exclusions:
                print(f'Skipping {utxo.hash}#{utxo.ix}')
                continue
            available_utxos.add(utxo)
        return available_utxos

    def get_protocol_parameters(self):
        return self.__call_get_api('epochs/latest/parameters')

    def submit_txn(self, signed_file):
        with open(signed_file, 'r') as signed_filehandle:
            tx_cbor = json.load(signed_filehandle)['cborHex']
        self.__call_post_api('application/cbor', '/tx/submit', bytes.fromhex(tx_cbor))
