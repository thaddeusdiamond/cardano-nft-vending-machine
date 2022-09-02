import os
import tempfile

from test_utils import data_file_path

CARDANO_VM_TEST = 'cardano-vm-test-'

class VendingMachineTestConfig(object):

    def __create_test_dir(self, dir_name):
        dir_path = os.path.join(self.root_dir, dir_name)
        os.mkdir(dir_path)
        return dir_path

    def __init__(self):
        self.root_dir = tempfile.mkdtemp(prefix=CARDANO_VM_TEST)
        self.metadata_dir = self.__create_test_dir('metadata')
        self.locked_dir = self.__create_test_dir('locked')
        self.output_dir = self.__create_test_dir('output')
        self.policy_dir = self.__create_test_dir('policy')
        self.payees_dir = self.__create_test_dir('payees')

    def copy_datafile_to_metadata(self, data_file, request):
        shutil.copy(data_file_path(request, data_file), self.metadata_dir)
