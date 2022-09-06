import os
import subprocess

def launch_py3_subprocess(script_path, request, args):
    root_dir = os.path.dirname(os.path.dirname(request.fspath))
    script_loc = os.path.join(root_dir, script_path)
    proc_env = os.environ.copy()
    curr_pythonpath = proc_env['PYTHONPATH'] if 'PYTHONPATH' in proc_env else ''
    proc_env["PYTHONPATH"] = f"{os.path.join(root_dir, 'src')}:{curr_pythonpath}"
    args_copy = args.copy()
    args_copy.insert(0, script_loc)
    args_copy.insert(0, 'python3')
    return subprocess.Popen(args_copy, env=proc_env)
