import os

def data_file_path(request, data_file):
    current_dir = os.path.dirname(request.fspath)
    data_filepath = os.path.join('data', data_file)
    return os.path.join(current_dir, data_filepath)
