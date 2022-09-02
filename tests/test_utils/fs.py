import os

def filepath_for_test(request, prefix, relative_path):
    current_dir = os.path.dirname(request.fspath)
    filepath = os.path.join(prefix, relative_path)
    return os.path.join(current_dir, filepath)

def data_file_path(request, data_file):
    return filepath_for_test(request, 'data', data_file)

def protocol_file_path(request, protocol_file):
    return data_file_path(request, os.path.join('protocol', protocol_file))

def secrets_file_path(request, secrets_file):
    return filepath_for_test(request, 'secrets', secrets_file)
