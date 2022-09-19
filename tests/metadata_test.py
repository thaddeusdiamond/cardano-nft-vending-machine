import json
import os
import shutil

from test_utils.fs import data_file_path
from test_utils.vending_machine import vm_test_config, VendingMachineTestConfig

from cardano.wt.mint import Mint
from cardano.wt.whitelist.no_whitelist import NoWhitelist

TANGZ_POLICY = '33568ad11f93b3e79ae8dee5ad928ded72adcea719e92108caf1521b'

def test_rejects_if_no_script_file():
    try:
        Mint(TANGZ_POLICY, None, None, None, '/this/path/does/not/exist', None, None)
        assert False, 'Successfully instantiated mint with no script'
    except FileNotFoundError as e:
        assert '/this/path/does/not/exist' in str(e)

def test_rejects_if_no_metadata_directory(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, '/this/dir/does/not/exist', simple_script, None, None)
    try:
        mint.validate()
        assert False, 'Successfully validated mint with no metadata dir'
    except FileNotFoundError as e:
        assert '/this/dir/does/not/exist' in str(e)

def test_accepts_script_with_before_after(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    mint.validate()
    assert mint.initial_slot == 12345678
    assert mint.expiration_slot == 87654321

def test_accepts_script_with_no_expiration(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'noexpiration.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    mint.validate()
    assert mint.initial_slot == None
    assert mint.expiration_slot == None

def test_rejects_if_empty_file(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'empty_bad.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with empty file'
    except ValueError as e:
        assert 'Incorrect # of keys' in str(e)

def test_rejects_if_not_an_object(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'string_bad.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with only JSON string'
    except AttributeError as e:
        assert "'str' object" in str(e)

def test_rejects_if_invalid_json(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'invalid_bad.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with invalid JSON'
    except json.decoder.JSONDecodeError as e:
        pass

def test_rejects_if_not_exactly_721(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', '721_bad.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with wrong 721 spec'
    except ValueError as e:
        assert '721' in str(e)

def test_rejects_if_multiple_721(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', '721_dupe.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with multiple top-level keys'
    except ValueError as e:
        assert 'Incorrect # of keys' in str(e)

def test_rejects_if_not_exactly_one_policy_id(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'policy_extra.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with multiple policy ids'
    except ValueError as e:
        assert 'Too many policy keys (3) found' in str(e)

def test_rejects_if_wrong_policy_id(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint('foobarbazpolicy', None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('success', 'WildTangz 1.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with wrong policy ids'
    except ValueError as e:
        assert 'Encountered asset with policy 33568ad11f93b3e79ae8dee5ad928ded72adcea719e92108caf1521b different from vending machine start value foobarbazpolicy' in str(e)

def test_rejects_if_no_policy_ids(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'policy_empty.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with zero policy ids'
    except ValueError as e:
        assert 'No policy keys found' in str(e)

def test_rejects_if_two_in_policy_no_version(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'policy_bad_version.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with "versions"'
    except ValueError as e:
        assert "Found 2 keys but 1 is not 'version'" in str(e)

def test_rejects_if_nonconforming_policy_id(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'policy_bad_value.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with invalid policy ID'
    except ValueError as e:
        assert "Incorrect looking policy this_is_not_a_real_policy_id" in str(e)

def test_rejects_if_not_exactly_one_asset(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'dupe_bad.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with multiple assets'
    except ValueError as e:
        assert "Incorrect # of assets (2)" in str(e)

def test_rejects_lengthy_metadata(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'lengthy_metadata.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with lengthy metadata'
    except ValueError as e:
        assert "Encountered metadata value >64 chars 'This clothing explanation is way way way " in str(e)

def test_rejects_nested_lengthy_metadata(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        bad_file = data_file_path(request, os.path.join('bad_format', 'nested_lengthy_metadata.json'))
        shutil.copy(bad_file, vm_test_config.metadata_dir)
        mint.validate()
        assert False, 'Successfully validated mint with nested lengthy metadata'
    except ValueError as e:
        assert "Encountered metadata value >64 chars 'This is another really long explanation that should be detected" in str(e)

def test_rejects_if_duplicate_names_in_dir(request, vm_test_config):
    simple_script = data_file_path(request, os.path.join('scripts', 'simple.script'))
    mint = Mint(TANGZ_POLICY, None, None, vm_test_config.metadata_dir, simple_script, None, NoWhitelist())
    try:
        good_file = data_file_path(request, os.path.join('success', 'WildTangz 1.json'))
        shutil.copy(good_file, vm_test_config.metadata_dir)
        shutil.copy(good_file, os.path.join(vm_test_config.metadata_dir, 'dupe.json'))
        mint.validate()
        assert False, 'Successfully validated mint with overlapping asset names'
    except ValueError as e:
        assert "Found duplicate asset name 'WildTangz 1'" in str(e)
