<p align="center">
  <h1 align="center">cardano-nft-vending-machine</h1>
  <p align="center">A simple CNFT mint-and-vend machine Python library that leverages ``cardano-cli``</p>
  <p align="center">
    <a href="https://github.com/thaddeusdiamond/cardano-nft-vending-machine">
      <img src="https://img.shields.io/github/commit-activity/m/thaddeusdiamond/cardano-vending-machine?style=for-the-badge" />
    </a>
    <a href="https://pypi.org/project/cardano-nft-vending-machine">
      <img src="https://img.shields.io/pypi/v/cardano-nft-vending-machine?style=for-the-badge" />
    </a>
    <a href="https://pypi.org/project/cardano-nft-vending-machine">
      <img src="https://img.shields.io/pypi/dw/cardano-nft-vending-machine?style=for-the-badge" />
    </a>
    <img src="https://img.shields.io/pypi/l/cardano-nft-vending-machine?style=for-the-badge" />
    <a href="https://twitter.com/wildtangz">
      <img src="https://img.shields.io/twitter/follow/wildtangz?style=for-the-badge&logo=twitter" />
    </a>
  </p>
</p>

## :warning: **IMPORTANT**
Interactions on the Cardano blockchain involve **REAL CURRENCY AND SHOULD NOT BE TREATED LIGHTLY**.  Some principles:
* Never send money to an address you don't know and can't validate
* Keys should be stored on servers that have as little attack surface (e.g., [iptables blacklists](https://www.cyberciti.biz/tips/linux-iptables-4-block-all-incoming-traffic-but-allow-ssh.html)) as possible
* Open source software should always be audited -- UTSL!
* There are **NO WARRANTIES WHATSOEVER WITH THIS PACKAGE** -- use at your own risk
## Quickstart
This project contains Library bindings that can be installed using the standard [wheel](https://pypi.org/project/wheel/) mechanism.  See the [script quickstart section](#cardano_vending_machinepy) for how to run from CLI.
### Library Usage
The library consists of several Python objects representing the mint process.  The sample below shows how one could run an infinite CNFT vending machine on mainnet for a 10₳ mint (gross of fees and rebates) with their NFT:

    # There are several sample whitelist implementations in cardano.wt.whitelist or you can implement your own
    whitelist = SingleUseWhitelist('/path/to/whitelisted/assets/directory')

    # The Mint object below represents your Mint policy and specifies price, and donation in Lovelace (both can be 0)
    mint = Mint('<POLICY_ID>', 10000000, 1000000, '/path/to/nft/json/metadata', '/path/to/mint/script', '/path/to/mint.skey', whitelist)

    # Blockfrost is used in the code to validate where the UTXO sent to the payment address came from
    blockfrost_api = BlockfrostApi('<BLOCKFROST_PROJ_ID>', mainnet=True)

    # CardanoCli is a wrapper around the cardano-cli command (used as a utility without any interaction with the network)
    cardano_cli = CardanoCli(protocol_params='/path/to/protocol.json')

    # NftVendingMachine vends NFTs and needs to be called repeatedly (with a 25-vend max) so long as the mint period is open
    nft_vending_machine = NftVendingMachine('addr_payment', '/path/to/payment.skey', 'addr_profit', 25, mint, blockfrost_api, cardano_cli, mainnet=True)

    # The following simple loop carries the state of already-completed UTXOs to avoid double spending errors and uses a do-wait-check loop
    already_completed = set()
    while _program_is_running:
        nft_vending_machine.vend('/path/to/output/dir', 'locking_subdir_name', 'metadata_subdir_name', already_completed)
        time.sleep(WAIT_TIMEOUT)

### ``main.py``
There is a sample vending machine script that is included in the ``src/`` directory to show how to invoke the library components.  Use ``-h`` to see detailed help or use a command like below:

        python3 main.py \
                --payment-addr <PAYMENT_ADDR> \
                --payment-sign-key /FULL/PATH/TO/payment.skey \
                --profit-addr <PROFIT_ADDR> \
                [--mint-price <PRICE_LOVELACE> | --free-mint] \
                --mint-script /FULL/PATH/TO/policy.script \
                --mint-sign-key /FULL/PATH/TO/policy.skey \
                --mint-policy $(cat /FULL/PATH/TO/policyID) \
                --blockfrost-project <BLOCKFROST_PROJECT_ID> \
                --metadata-dir metadata/ \
                --output-dir output/ \
                [--single-vend-max <MAX_SINGLE_VEND>] \
                [--vend-randomly] \
                [--no-whitelist | \
                  [--single-use-asset-whitelist <WHITELIST_DIR> | --unlimited-asset-whitelist <WHITELIST_DIR>]] \
                [--donation]
                [--mainnet]
## Installation
This package is available from [PyPI](https://pypi.org/) and can be installed using ``pip3``.  Python <3.8 is currently unsupported at this time.

	pip3 install cardano-nft-vending-machine
## APIs
All API documentation is auto-generated from ``pydoc3``-formatted multi-line strings in the source code.  A mirror of ``master`` is hosted on [Github Pages](https://thaddeusdiamond.github.io/cardano-nft-vending-machine/cardano/).
## Build
Building this project creates a ``.whl`` file for uploading to [PyPI]() or installing locally on a server.  All output is, by default, stored to ``dist/``.  To build, run:

	python3 -m build
## Test
To enhance the output of tests, we recommend installing [pytest-clarity](https://pypi.org/project/pytest-clarity/):

	pip3 install pytest-clarity
Tests are stored in the ``tests`` subdirectory and are run using [pytest](https://docs.pytest.org/en/7.1.x/).  Before invoking the tests you will need to create files at ``tests/secrets/blockfrost-preprod.key`` and ``tests/secrets/blockfrost-preview.key`` with the respective network keys to make sure the test suite can access the test network blockchains (see [blockfrost.io docs](https://docs.blockfrost.io/) for more details).  Then, to invoke the tests:

	python3 -m pytest -vv
By default tests will run on the [preprod Cardano network](https://docs.cardano.org/cardano-testnet/getting-started#late-stagetestingnetworks).  To test against mainnet or the [preview Cardano network](https://docs.cardano.org/cardano-testnet/getting-started#early-stagetestingnetworks) you can use the `TEST_ON_MAINNET` or `TEST_ON_PREVIEW` environment variables as follows:

	TEST_ON_PREVIEW=true python3 -m pytest -vv
Pull requests to ``master`` require 0 failing tests in order to be merged.

## Code Coverage
We use [coverage](https://coverage.readthedocs.io/en/6.4.4/) to measure code coverage from our pytests across the code base.  To run a full test suite with code coverage metrics, invoke:

	python3 -m coverage run --source=src/ --branch -m pytest -vv
Note that you must *separately* generate the report on your CLI using the following:

	python3 -m coverage html
We aim to maintain 80% coverage (lines + branches) if possible.

## Documentation
Documentation is stored in multi-line comments inside the source code and should be generated using the ``pdoc3`` package as follows:

    pdoc3 --html -o docs/ src/cardano   
