# cardano-nft-vending-machine 
### A simple CNFT mint-and-vend machine Python library that leverages ``cardano-cli``
## :warning: **IMPORTANT**
Interactions on the Cardano blockchain involve **REAL CURRENCY AND SHOULD NOT BE TREATED LIGHTLY**.  Some principles:
* Never send money to an address you don't know and can't validate
* Keys should be stored on servers that have as little attack surface (e.g., [iptables blacklists](https://www.cyberciti.biz/tips/linux-iptables-4-block-all-incoming-traffic-but-allow-ssh.html)) as possible
* Open source software should always be audited -- UTSL!
* There are **NO WARRANTIES WHATSOEVER WITH THIS PACKAGE** -- use at your own risk
## Quickstart
This project contains Library bindings that can be installed using the standard [wheel](https://pypi.org/project/wheel/) mechanism.  See the [script quickstart section](#cardano_vending_machinepy) for how to run from CLI.
### Library Usage
The library consists of several Python objects representing the mint process.  The sample below shows how one could run an infinite CNFT vending machine on mainnet for a 10₳ mint where users send an extra 2₳ for the rebate:

    # The Mint object below represents your Mint policy and specifies price, rebate, and donation in Lovelace
    mint = Mint('<POLICY_ID>', 10000000, 2000000, 1000000, '/path/to/nft/json/metadata', '/path/to/mint/script', '/path/to/mint.skey')

    # Blockfrost is used in the code to validate where the UTXO sent to the payment address came from
    blockfrost_api = BlockfrostApi('<BLOCKFROST_PROJ_ID>', mainnet=True)

    # CardanoCli is a wrapper around the cardano-cli command (and uses the CARDANO_NODE_SOCKET_PATH env var)
    cardano_cli = CardanoCli(mainnet=True, protocol_params='/path/to/protocol.json')

    # NftVendingMachine vends NFTs and needs to be called repeatedly so long as the mint period is open 
    nft_vending_machine = NftVendingMachine('addr_payment', '/path/to/payment.skey', 'addr_profit', mint, blockfrost_api, cardano_cli, mainnet=True)

    # The following simple loop carries the state of already-completed UTXOs to avoid double spending errors and uses a do-wait-check loop
    already_completed = set()
    while _program_is_running:
        nft_vending_machine.vend('/path/to/output/dir', 'locking_subdir_name', 'metadata_subdir_name', already_completed)
        time.sleep(WAIT_TIMEOUT)

### ``cardano_vending_machine.py``
There is a sample vending machine script that is included in the ``src/`` directory to show how to invoke the library components.  Use ``-h`` to see detailed help or use a command like below:

        src/cardano/wt/cardano_vending_machine.py \
                --payment-addr <PAYMENT_ADDR> \
                --payment-sign-key /FULL/PATH/TO/payment.skey \
                --profit-addr <PROFIT_ADDR> \
                --mint-price <PRICE_LOVELACE> \
                --mint-rebate <REBATE_LOVELACE>  \
                --mint-script /FULL/PATH/TO/policy.script \
                --mint-sign-key /FULL/PATH/TO/policy.skey \
                --mint-policy $(cat /FULL/PATH/TO/policyID) \
                --blockfrost-project <BLOCKFROST_PROJECT_ID> \
                --metadata-dir metadata/ \
                --output-dir output/
## Installation
This package is available from [PyPI](https://pypi.org/) and can be installed using ``pip3``.  Python <3.8 is currently unsupported at this time.
        
    pip3 install cardano-nft-vending-machine
## APIs
All API documentation is auto-generated from ``pydoc3``-formatted multi-line strings in the source code.  A mirror of ``master`` is hosted on [Github Pages](https://thaddeusdiamond.github.io/cardano-nft-vending-machine/cardano/).
## Build
Building this project creates a ``.whl`` file for uploading to [PyPI]() or installing locally on a server.  All output is, by default, stored to ``dist/``.  To build, run:

	python3 -m build
## Test
Tests are stored in the ``tests`` subdirectory and are run using [pytest](https://docs.pytest.org/en/7.1.x/).  To invoke the tests:

	python3 -m pytest tests
Pull requests to ``master`` require 0 failing tests in order to be merged.
## Documentation
Documentation is stored in multi-line comments inside the source code and should be generated using the ``pdoc3`` package as follows:

    pdoc3 --html -o docs/ src/cardano   
