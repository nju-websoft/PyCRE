import json
import os
import sys
import importlib
import signal
import traceback
import pkgutil
import shlex
import subprocess


def handle_timeout(signum, frame):
    raise Exception('#Import timeout#')

class ModuleImporter(object):
    def __init__(self):
        self.modules_list = []
        self.attrs_dict = {}
        # the modules that fails to be imported
        self.import_info = {}
        
        # Register the signal function handler
        signal.signal(signal.SIGALRM, handle_timeout)

    def _judge_import(self, name, is_top_module):
        '''
        Return
            list: import successfully and has '__path__'
            []: import successfully but does not have '__path__'
            None: can't import successfully
        '''
        module_path = None
        # Define a timeout for import
        signal.alarm(10)
        try:
            module = importlib.import_module(name)
        except Exception as e:
            self.import_info[name] = traceback.format_exc()
        else:
            self.modules_list.append(name)
            self.attrs_dict[name] = [attr for attr in dir(module) if not attr.startswith('_')]

            if is_top_module:
                try:
                    module_path = module.__path__
                except Exception:
                    module_path = []
        finally:
            signal.alarm(0)
            return module_path
    

    def _recursion_submodules(self, top_module):
        module_path = self._judge_import(top_module, True)
        # import success
        if module_path is not None:
            if isinstance(module_path, str):
                module_path = module_path.strip()
                if module_path == '':
                    module_path = []
                else:
                    module_path = [module_path]
        
            if isinstance(module_path, list):
                # have '__path__'
                if len(module_path) > 0:
                    for _, name, _ in pkgutil.walk_packages(module_path, top_module+'.', onerror=lambda x: None):
                        if '._' not in name:
                            self._judge_import(name, False)
    

    def import_modules(self, top_modules):
        for top_module in top_modules:
            self._recursion_submodules(top_module)


def main():
    package = sys.argv[1]
    version = sys.argv[2]

    info_dict = {}

    # pip show -f package
    show_command = 'timeout 30 python -W ignore:DEPRECATION -m pip show -f {}'.format(package)
    try:
        show_log = subprocess.check_output(shlex.split(show_command), stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError:
        # fail to pip show
        print('Fail to execute \"pip show {}\"'.format(package))
        exit(-1)
    
    # Get all files in the distrubution
    location_path = None
    all_files = []
    is_file = False
    for line in show_log.split('\n'):
        line = line.strip()
        if is_file:
            all_files.append(line)
        elif line == 'Files:':
            is_file = True
        elif line.startswith('Location:'):
            location_path = line[len('Location:'):].strip()
    
    if location_path is None or len(all_files)==0:
        print('Unexpected output for \"pip show {}\":'.format(package))
        print(show_log)
        exit(-1)

    # find METADATA
    meta_path = None
    for item in all_files:
        _, full_name = os.path.split(item)
        if full_name == 'METADATA':
            meta_path = os.path.join(location_path, item)
            break
    
    # Requires-Dist
    require_list = []
    if meta_path is not None and os.path.isfile(meta_path):
        with open(meta_path, 'r') as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith('Requires-Dist:'):
                    require_list.append(line[len('Requires-Dist:'):].strip())
    
    info_dict['Requires'] = require_list
    
    # find top_level.txt
    top_path = None
    for item in all_files:
        _, full_name = os.path.split(item)
        if full_name == 'top_level.txt':
            top_path = os.path.join(location_path, item)
            break
    
    # top modules
    top_modules = []
    if top_path is not None and os.path.isfile(top_path):
        with open(top_path, 'r') as f:
            top_modules = [item.strip() for item in f.readlines() if item.strip()!='']
    else:
        format_exts = ['.py', '.pyc', '.pyo', '.pyd', '.so', '.dll']
        # files in this distribution
        for path in all_files:
            if path.startswith('.'):
                # not in site-packages
                continue
        
            full_path, ext = os.path.splitext(path)
            if ext not in format_exts or '.' in full_path:
                # not a module file
                continue

            dir_path = os.path.split(path)[0]
            filename = full_path.split('/')[-1]
            # judge if it is a top module
            if dir_path == '':
                top_modules.add(filename)
            elif filename == '__init__' and '/' not in dir_path:
                top_modules.add(dir_path)
    
    top_modules = [m for m in top_modules if not m.startswith('_')]
    
    # Get all submodules and attributes
    importer = ModuleImporter()
    importer.import_modules(top_modules)
    info_dict['Modules'] = importer.modules_list
    info_dict['Attrs'] = importer.attrs_dict

    with open('/volumes/data.json', 'w') as f:
        json.dump(info_dict, f)
    
    with open('/volumes/import_fail.json', 'w') as f:
        json.dump(importer.import_info, f)


if __name__ == '__main__':
    label_file = '/volumes/LABEL'
    if not os.path.exists(label_file):
        f = open(label_file, 'w')
        f.close()
        main()