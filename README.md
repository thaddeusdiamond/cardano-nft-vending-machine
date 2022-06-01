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
[TODO: Complete this section]
### ``cardano_vending_machine.py``
There is a sample vending machine script that is included in the ``src/`` directory to show how to invoke the library components.  Use ``-h`` to see detailed help or use a command like below:

    CARDANO_NODE_SOCKET_PATH=/home/cnode/sockets/node.socket_test \
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
[TODO: Complete this section]
## Build
Building this project creates a ``.whl`` file for uploading to [PyPI]() or installing locally on a server.  All output is, by default, stored to ``dist/``.  To build, run:

	python3 -m build
## Test
Tests are stored in the ``tests`` subdirectory and are run using [pytest](https://docs.pytest.org/en/7.1.x/).  To invoke the tests:

	python3 -m pytest tests
Pull requests to ``master`` require 0 failing tests in order to be merged.
