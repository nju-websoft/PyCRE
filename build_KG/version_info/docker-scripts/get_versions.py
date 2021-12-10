import shlex
import subprocess
import re
import os
import json


def main():
    packages_file = os.environ['packages_file']
    versions_file = os.environ['versions_file']

    # Regex expression
    re_versions = re.compile(r'\(from versions:(.+?)\)\n')

    pv_dict = {}
    with open(packages_file, 'r') as f:
        for line in f.readlines():
            package = line.strip()
            if package == '':
                continue
            
            cmd = 'pip install {}==1234567890'.format(package)
            try:
                out_log = subprocess.check_output(shlex.split(cmd), stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                versions_info = re_versions.findall(e.output.decode())
                if len(versions_info) == 1:
                    # Normal output
                    versions_str = versions_info[0].strip()
                    if versions_str != 'none':
                        pv_dict[package] = [version.strip() for version in versions_str.split(',')]
                else:
                    # Unexpected output
                    print('Unexpected output when get versions of {}:'.format(package))
                    print(e.output)
            else:
                # Unexpected success
                print('Unexpected success when get versions of {}:'.format(package))
                print(out_log)
    
    # save
    with open(versions_file, 'w') as f:
        json.dump(pv_dict, f)


if __name__ == '__main__':
    main()