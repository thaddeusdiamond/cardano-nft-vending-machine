# The below code requires the following tools:
#    * bash
#    * cardano-cli (no node required!)
#    * python3
#    * npm/node
#    * webpack
#    * static-server

# Configure your secret variables
export SET_YOUR_BLOCKFROST_PROJ_HERE="UPDATED_BLOCKFROST_VALUE"
export SET_YOUR_POLICY_EXPIRATION_HERE="UPDATED_POLICY_EXPIRATION"
export SET_YOUR_MINT_PRICE="UPDATED_MINT_PRICE"
export SET_YOUR_SINGLE_VEND_MAX="UPDATED_SINGLE_VEND_MAXIMUM"
export SET_YOUR_METADATA_DIRECTORY="UPDATED/METADATA/DIRECTORY/PATH"

# Use this flag to switch between legacy testnet, preprod, and preview envs
export NETWORK_MAGIC=

# Make the directory where vending machine backend and frontend code will be
mkdir sample_run/
cd sample_run/

# Generate the addresses for the vending machine and your profit vault
# NOTE: We recommend using a hardware (e.g., Ledger) wallet for production use
mkdir keys/
cardano-cli address key-gen \
  --verification-key-file keys/vending_machine.vkey \
  --signing-key-file keys/vending_machine.skey
cardano-cli address build \
  --payment-verification-key-file keys/vending_machine.vkey \
  --out-file keys/vending_machine.addr \
  --testnet-magic $NETWORK_MAGIC
cardano-cli address key-gen \
  --verification-key-file keys/profit_vault.vkey \
  --signing-key-file keys/profit_vault.skey
cardano-cli address build \
  --payment-verification-key-file keys/profit_vault.vkey \
  --out-file keys/profit_vault.addr \
  --testnet-magic $NETWORK_MAGIC

# Create the policy that will be used to mint this NFT
mkdir policies/
cardano-cli address key-gen \
  --verification-key-file policies/nftpolicy.vkey \
  --signing-key-file policies/nftpolicy.skey
cat <<EOF > policies/nftpolicy.script
{
  "type": "all",
  "scripts":
  [
   {
     "type": "before",
     "slot": $SET_YOUR_POLICY_EXPIRATION_HERE
   },
   {
     "type": "sig",
     "keyHash": "$(cardano-cli address key-hash --payment-verification-key-file policies/nftpolicy.vkey)"
   }
  ]
}
EOF
cardano-cli transaction policyid \
  --script-file policies/nftpolicy.script > policies/nftpolicyID

# Create a directory to place your NFT metadata in (each one stored in JSON)
mkdir metadata/

# [OPTIONAL] Create a whitelist directory for any whitelists you will be running
venv/bin/python3 cardano-nft-vending-machine/scripts/initialize_asset_wl.py \
  --blockfrost-project $SET_YOUR_BLOCKFROST_PROJ_HERE \
  --consumed-dir output/wl_consumed \
  --policy-id $(cat policies/nftpolicyID) \
  --whitelist-dir whitelist/ \
  --mainnet

# In one terminal, now run the cardano-nft-vending-machine code (backend)
# NOTE: We recommend running this before copying any metadata over to ensure
#       that if your address leaked there are no mints before the drop is live
git clone https://github.com/thaddeusdiamond/cardano-nft-vending-machine.git
python3 -m venv venv
venv/bin/pip3.8 install --upgrade pip
venv/bin/pip3.8 install cardano-nft-vending-machine
venv/bin/python3 cardano-nft-vending-machine/main.py \
  --payment-addr $(cat keys/vending_machine.addr) \
  --payment-sign-key keys/vending_machine.skey \
  --profit-addr $(cat keys/profit_vault.addr) \
  --mint-price $SET_YOUR_MINT_PRICE \
  --mint-script policies/nftpolicy.script \
  --mint-sign-key policies/nftpolicy.skey \
  --mint-policy $(cat policies/nftpolicyID) \
  --blockfrost-project $SET_YOUR_BLOCKFROST_PROJ_HERE \
  --metadata-dir metadata/ \
  --output-dir output \
  --single-vend-limit $SET_YOUR_SINGLE_VEND_MAX \
  --vend-randomly \
  --no-whitelist

# In a second terminal, when you are ready copy your metadata files into the
# vending machine and your drop will be live!
cp $SET_YOUR_METADATA_DIRECTORY/* metadata/

# [OPTIONAL] In another terminal, launch a script to update Cloudflare or other
#            service provider when the whitelist is used.
venv/bin/python3 cardano-nft-vending-machine/scripts/upload_wl_usage.py \
  --old-wl-file output/wl_upload_store/used_wl_assets.json \
  --out-file output/wl_upload_store/used_wl_assets.json \
  --whitelist-dir output/wl_consumed \
  --upload-method cloudflare \
  --credentials '{"project_name": "PROJECT_NAME", "account_id": "ACCOUNT_ID", "api_token": "API_TOKEN", "branch": "BRANCH"}'
