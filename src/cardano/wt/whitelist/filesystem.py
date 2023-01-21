import os
import shutil

"""
Representation of a whitelist that lives on a filesystem where the name of the
file is the whitelist identifier (e.g., address, stake key).
"""
class FilesystemBasedWhitelist(object):

    def __init__(self, input_dir, consumed_dir):
        self.input_dir = input_dir
        self.consumed_dir = consumed_dir

    def __fs_location(self, identifier):
        return os.path.join(self.input_dir, identifier)

    def _remove_from_whitelist(self, identifier):
        consumed_location = os.path.join(self.consumed_dir, identifier)
        shutil.move(self.__fs_location(identifier), consumed_location)

    def is_whitelisted(self, identifier):
        return os.path.exists(self.__fs_location(identifier))

    def validate(self):
        if not os.path.exists(self.input_dir):
            raise ValueError(f"Could not find whitelist directory {self.input_dir} on filesystem!")
        if not os.path.exists(self.consumed_dir):
            raise ValueError(f"Output directory {self.consumed_dir} does not exist on filesystem!")
