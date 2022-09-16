
<p align="center">
  <h1 align="center">cardano-nft-vending-machine</h1>
  <p align="center">A simple CNFT mint-and-vend machine Python library that leverages cardano-cli and Blockfrost.io</p>
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
* Open source software should always be audited independently -- UTSL!
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

        python3 main.py [validate | run] \
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
                --single-vend-max <MAX_SINGLE_VEND> \
                [--vend-randomly] \
                [--no-whitelist | \
                  [--single-use-asset-whitelist <WHITELIST_DIR> | --unlimited-asset-whitelist <WHITELIST_DIR>]] \
                [--donation]
                [--mainnet]
## Installation
This package is available from [PyPI](https://pypi.org/) and can be installed using ``pip3``.  Python <3.8 is currently unsupported at this time.

	pip3 install cardano-nft-vending-machine
### Scripts
In the `scripts/` directory there are several scripts that can be used to help operationalize the vending machine.
#### initialize_asset_wl.py
This file should be used exactly once to initialize an asset-based whitelist for an existing NFT policy with *ALL* of the assets that are currently minted.  Note that the `CONSUMED_DIR` folder is created but left empty so that the vending machine (e.g., started with `main.py`) can use it during running.

	usage: initialize_asset_wl.py [-h] --blockfrost-project BLOCKFROST_PROJECT --consumed-dir CONSUMED_DIR [--mainnet] --policy-id POLICY_ID [--preview] --whitelist-dir WHITELIST_DIR
	Initialize an asset-based whitelist for an existing NFT policy
	optional arguments:
	-h, --help
		show this help message and exit
	--blockfrost-project BLOCKFROST_PROJECT
		Blockfrost project ID to use for retrieving chain data
	--consumed-dir CONSUMED_DIR
		Local folder where consumed whitelist files will go after processing (MUST NOT YET EXIST)
	--mainnet
		Run the initializer against mainnet assets (default is False [preprod])
	--policy-id POLICY_ID
		Policy ID of the assets to be whitelisted
	--preview
		Run the initializer against preview assets (default is False [preprod])
	--whitelist-dir WHITELIST_DIR
		Local folder where whitelist files are stored (MUST NOT YET EXIST)

#### upload_wl_usage.py

This file should be run continuously during a whitelist mint to upload changes in the assets used for consumption by external parties.  Note that if there are any performance issues (e.g., IOPS throughput) with the local vending machine filesystem it is recommended you not use this file.  It is kept separate from the main vending machine operation to avoid any synchronization or performance issues as it is not critical.

	usage: upload_wl_usage.py [-h] --old-wl-file OLD_WL_FILE --out-file OUT_FILE --whitelist-dir WHITELIST_DIR [--credentials CREDENTIALS] [--upload-method UPLOAD_METHOD]
	Determine if a set of whitelist assets have been recently used in the vending machine
	optional arguments:
	-h, --help  show this help message and exit
	--old-wl-file OLD_WL_FILE
		Most recent run of this program that was uploaded to cloud storage
	--out-file OUT_FILE
		Where to store the new used whitelist information if any changes (can be same as --old-wl-file)
	--whitelist-dir WHITELIST_DIR
		Local folder where consumed whitelist files have gone after processing by vending machine
	--credentials CREDENTIALS
		JSON-formatted application-specific credentials
	--upload-method UPLOAD_METHOD
		Mechanism for uploading changes in whitelist files (e.g., CloudFlare)

## APIs
All API documentation is auto-generated from ``pydoc3``-formatted multi-line strings in the source code.  A mirror of ``master`` is hosted on [Github Pages](https://thaddeusdiamond.github.io/cardano-nft-vending-machine/cardano/).
## Build
Building this project creates a ``.whl`` file for uploading to [PyPI]() or installing locally on a server.  All output is, by default, stored to ``dist/``.  To build, run:

	python3 -m build
## Test
To enhance the output of tests, we recommend installing [pytest-clarity](https://pypi.org/project/pytest-clarity/):

	pip3 install pytest-clarity
Tests are stored in the ``tests`` subdirectory and are run using [pytest](https://docs.pytest.org/en/7.1.x/).  But before invoking the tests you need to create secrets for [blockfrost.io](https://blockfrost.io) and fund a test address (the "funder") as below.

### Blockfrost Key Files
There are two supported test Cardano networks on Blockfrost as of the time of this writing: preprod and preview.  More information on these two supported test networks can be found on the [Cardano.org testnet documentation](https://docs.cardano.org/cardano-testnet/getting-started).

For running the testing suite on preprod you will need to create a file at ``tests/secrets/blockfrost-preprod.key`` that contains *just your blockfrost key* for preprod. If you want to run on preview, simply do that same for your preview key at ``tests/secrets/blockfrost-preview.key``.  For more information, see the [full blockfrost.io documentation](https://docs.blockfrost.io/).

### Funder Key Files
The test suite assumes that there is a "funder" address that is able to pay tADA out (and then receive the entire sum at the end of a successful test less chain fees).  To create a new funder address, run:

	cardano-cli address key-gen \
		--signing-key-file tests/secrets/funder.skey \
		--verification-key-file tests/secrets/funder.vkey

The result will be two files (the signing key and verification/public key) of a "funder" address.  This address can be determined at the CLI using:

	cardano-cli address build \
            --payment-verification-key-file tests/secrets/funder.vkey \
            --testnet-magic <PREPROD_OR_PREVIEW_MAGIC>

Before running any tests ensure the funder has adequate tADA by using the [testnets faucet](https://docs.cardano.org/cardano-testnet/tools/faucet) for whichever test network you will be running the test suite against.

### Running the Tests
Finally, to run the tests:

	python3 -m pytest -vv [-s] [-k TEST_SINGLE_PATTERN]
By default tests will run on the [preprod Cardano network](https://docs.cardano.org/cardano-testnet/getting-started#late-stagetestingnetworks).  To test against mainnet or the [preview Cardano network](https://docs.cardano.org/cardano-testnet/getting-started#early-stagetestingnetworks) you can use the `TEST_ON_MAINNET` or `TEST_ON_PREVIEW` environment variables as follows:

	TEST_ON_PREVIEW=true python3 -m pytest -vv
Pull requests to ``master`` require 0 failing tests in order to be merged.

### Scale Testing
The file `tests/scale_test.py` contains mechanisms for testing the vending machine at scale which are, by default, skipped during a test run.  To manually invoke these tests, you need to pass several specific parameters.  For example, running:

	python3 -m pytest -vv -s -k test_concurrent_wallet_usage \
		--available-assets 100
		--max-nfts 4
		--min-nfts 0
		--mint-price 5000000
		--num-wallets 100

Would run a simulation where 100 wallets would randomly attempt to purchase between 0 and 4 assets (according to a normal distribution), during a 5A mint.  The code would ensure that each recipient received less than or equal to their stated asset count and that in total no more than 100 assets were minted.

Note that currently we have only loaded 100 sample files into `tests/data/scale` but could increase this in the future as needed.  The key here is the concurrent wallet/UTxO creation, not necessarily the asset scale.  Whitelist scale testing is not supported at the moment.

### Code Coverage
We use [coverage](https://coverage.readthedocs.io/en/6.4.4/) to measure code coverage from our pytests across the code base.  To run a full test suite with code coverage metrics, invoke:

	python3 -m coverage run --source=src/ --branch -m pytest -vv
Note that you must *separately* generate the report on your CLI using the following:

	python3 -m coverage html
We aim to maintain 85%+ coverage (lines + branches) if possible.

## Documentation
Documentation is stored in multi-line comments inside the source code and should be generated using the ``pdoc3`` package as follows:

    pdoc3 --html -o docs/ src/cardano
