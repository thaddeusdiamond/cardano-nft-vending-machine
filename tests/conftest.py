def pytest_addoption(parser):
    parser.addoption("--available-assets", type=int)
    parser.addoption("--max-nfts", type=int)
    parser.addoption("--mint-price", type=int)
    parser.addoption("--min-nfts", type=int)
    parser.addoption("--num-wallets", type=int)
    parser.addoption("--old-test-dir", type=str)
