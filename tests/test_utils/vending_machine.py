import os
import pytest
import tempfile

from test_utils.fs import data_file_path

from cardano.wt.cardano_cli import CardanoCli

CARDANO_VM_TEST = 'cardano-vm-test-'

class VendingMachineTestConfig(object):

    def __create_test_dir(self, dir_name):
        dir_path = os.path.join(self.root_dir, dir_name)
        os.mkdir(dir_path)
        return dir_path

    def __init__(self):
        self.root_dir = tempfile.mkdtemp(prefix=CARDANO_VM_TEST)
        self.buyers_dir = self.__create_test_dir('buyers')
        self.metadata_dir = self.__create_test_dir('metadata')
        self.locked_dir = self.__create_test_dir('locked')
        self.policy_dir = self.__create_test_dir('policy')
        self.payees_dir = self.__create_test_dir('payees')
        self.txn_dir = self.__create_test_dir(CardanoCli.TXN_DIR)
        self.txn_metadata_dir = self.__create_test_dir('in_proc')

        self.consumed_dir = os.path.join(self.root_dir, 'consumed')
        self.whitelist_dir = os.path.join(self.root_dir, 'whitelist')

    def copy_datafile_to_metadata(self, data_file, request):
        shutil.copy(data_file_path(request, data_file), self.metadata_dir)

@pytest.fixture
def vm_test_config():
    return VendingMachineTestConfig()
