import json
import requests
import time

from http import HTTPStatus

from cardano.wt.utxo import Utxo

"""
Repreentation of the Blockfrost web API used in retrieving metadata about txn i/o on the chain.
"""
class BlockfrostApi(object):

    _API_CALLS_PER_SEC = 10
    _BACKOFF_SEC = 5
    _BURST_TXN_PER_SEC = 10
    _MAX_RETRIES = 9
    _MAX_BURST = 500
    _UTXO_LIST_LIMIT = 100

    def __init__(self, project, mainnet=False):
        self.project = project
        self.mainnet = mainnet
        self.built_up_burst = BlockfrostApi._MAX_BURST
        self.bursting = False
        self.curr_sec = int(time.time())
        self.curr_calls = 0

    def __account_for_rate_limit(self):
        this_time = time.time()
        this_sec = int(this_time)
        if self.curr_sec == this_sec:
            self.curr_calls += 1
        else:
            if self.bursting:
                self.built_up_burst = 0
            else:
                self.built_up_burst = max(BlockfrostApi._MAX_BURST, self.built_up_burst + BlockfrostApi._BURST_TXN_PER_SEC)
            self.bursting = False
            self.curr_sec = this_sec
            self.curr_calls = 1
        if self.curr_calls == BlockfrostApi._API_CALLS_PER_SEC:
            print("Blockfrost API: ENTERING BURST, EXCEEDED ALLOWABLE API CALLS")
            self.bursting = True
        if self.bursting and (self.curr_calls > BlockfrostApi._MAX_BURST):
            print("Blockfrost API: BEYOND BURST CAPABILITIES, MAY RESULT IN FATAL ERROR")
            time.sleep(1.0  / BlockfrostApi._API_CALLS_PER_SEC)

    def __get_api_base(self):
        return f"https://cardano-{'mainnet' if self.mainnet else 'testnet'}.blockfrost.io/api/v0"

    def __call_get_api(self, resource, max_retries=0):
        self.__account_for_rate_limit()
        retries = 0
        while True:
            try:
                pi_resp = requests.get(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project})
                print(f"Blockfrost API: {resource} ({api_resp.status_code})")
                api_resp.raise_for_status()
                print(api_resp.json())
                return api_resp.json()
            except requests.exceptions.HTTPError as e:
                if retries < max_retries:
                    retries += 1
                    time.sleep(BlockfrostApi._BACKOFF_SEC)
                else:
                    raise e

    def __call_post_api(self, content_type, resource, data):
        self.__account_for_rate_limit()
        api_resp = requests.post(f"{self.__get_api_base()}/{resource}", headers={'project_id': self.project, 'Content-Type': content_type}, data=data)
        print(f"Blockfrost API: {resource} ({api_resp.status_code})")
        print(api_resp.text)
        api_resp.raise_for_status()
        return api_resp.json()

    def get_input_address(self, txn_hash):
        utxo_metadata = self.__call_get_api(f"txs/{txn_hash}/utxos", max_retries=BlockfrostApi._MAX_RETRIES)
        utxo_inputs = set([utxo_input['address'] for utxo_input in utxo_metadata['inputs']])
        if len(utxo_inputs) < 1:
            raise ValueError(f"Txn hash {txn_hash} has no valid addresses({utxo_inputs}), aborting...")
        return utxo_inputs.pop()

    def get_utxos(self, address, exclusions):
        available_utxos = set()
        current_page = 0
        while True:
            current_page += 1
            try:
                utxo_data = self.__call_get_api(f"addresses/{address}/utxos?count={BlockfrostApi._UTXO_LIST_LIMIT}&page={current_page}")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == HTTPStatus.NOT_FOUND:
                    return []
                raise e
            #print('EXCLUSIONS\t', [f'{utxo.hash}#{utxo.ix}' for utxo in exclusions])
            for raw_utxo in utxo_data:
                balances = [Utxo.Balance(int(balance['quantity']), balance['unit']) for balance in raw_utxo['amount']]
                utxo = Utxo(raw_utxo['tx_hash'], raw_utxo['output_index'], balances)
                if utxo in exclusions:
                    print(f'Skipping {utxo.hash}#{utxo.ix}')
                    continue
                available_utxos.add(utxo)
            if len(utxo_data) < BlockfrostApi._UTXO_LIST_LIMIT:
                break
        return available_utxos

    def get_protocol_parameters(self):
        return self.__call_get_api('epochs/latest/parameters')

    def submit_txn(self, signed_file):
        with open(signed_file, 'r') as signed_filehandle:
            tx_cbor = json.load(signed_filehandle)['cborHex']
        self.__call_post_api('application/cbor', '/tx/submit', bytes.fromhex(tx_cbor))
