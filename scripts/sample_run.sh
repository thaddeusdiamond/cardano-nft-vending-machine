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

# NOTE: Here is where you move the JSONs representing your NFTs and save them
cp $SET_YOUR_METADATA_DIRECTORY/* metadata/

# In one terminal, now run the cardano-nft-vending-machine code (backend)
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
