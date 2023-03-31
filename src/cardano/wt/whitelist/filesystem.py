import glob
import os
import shutil

"""
Representation of a whitelist that lives on a filesystem where the name of the
file is the whitelist identifier (e.g., address, stake key).  Note that the
contents of the file can be empty, or they can be a one-per-line set of linked
identifiers that need to be removed from the whitelist when this whitelist spot
is consumed.
"""
class FilesystemBasedWhitelist(object):

    def __init__(self, input_dir, consumed_dir):
        self.input_dir = input_dir
        self.consumed_dir = consumed_dir

    def __matching_files_for(self, identifier):
        root_identifier_path = os.path.join(self.input_dir, identifier)
        return glob.glob(f"{root_identifier_path}_[0-9]*")

    def _remove_from_whitelist(self, identifier, num_removed):
        try:
            identifier_locations = self.__matching_files_for(identifier)
            print(f"Removing {num_removed} WL slot(s) of {len(identifier_locations)} remaining for '{identifier}'")
            if len(identifier_locations) < num_removed:
                raise ValueError(f"Attempting to remove too many items ({num_removed}) from the whitelist: {identifier_locations}")
            for idx in range(0, num_removed):
                identifier_location = identifier_locations[idx]
                linked_id_paths = []
                with open(identifier_location, 'r') as linked_ids:
                    for linked_id in linked_ids:
                        linked_id_path = os.path.join(self.input_dir, linked_id)
                        if not os.path.exists(linked_id_path):
                            print(f"Linked ID {linked_id} was not on whitelist, skipping...")
                            continue
                        linked_id_paths.append(linked_id_path)
                shutil.move(identifier_location, self.consumed_dir)
                for linked_id_path in linked_id_paths:
                    shutil.move(linked_id_path, self.consumed_dir)
        except Exception as e:
            print(f"[CATASTROPHIC] FILESYSTEM ERROR IN WHITELIST, THIS IS BAD! {e}")

    def num_whitelisted(self, identifier):
        return len(self.__matching_files_for(identifier))

    def validate(self):
        if not os.path.exists(self.input_dir):
            raise ValueError(f"Could not find whitelist directory {self.input_dir} on filesystem!")
        if not os.path.exists(self.consumed_dir):
            raise ValueError(f"Output directory {self.consumed_dir} does not exist on filesystem!")
