from package_info.pypi_crawler import get_distributions
from version_info.acquire_versions import VersionFinder
from installation_info.install_libraries import DynamicInstaller
from transfer_csv.knowledge2csv import CsvTransformer
from packaging.utils import canonicalize_name
import sys
import os
import json


def main():
    """
    Completely automated knowledge acquisition process
    -----
    python run.py <python_version> <neo4j_home> <packages_file>
    -----
    packages_file (Optional): specified Python packages.
    """

    python_version = sys.argv[1]

    data_dir = os.path.abspath('data/')
    if not os.path.isdir(data_dir):
        os.mkdir(data_dir)
    
    python_dir = os.path.join(data_dir, 'Python{}'.format(python_version))
    if not os.path.isdir(python_dir):
        os.mkdir(python_dir)
    
    neo4j_home = sys.argv[2]

    p_list = []
    if len(sys.argv) <= 3:
        # Get all packages from PyPI
        p_list = get_distributions()
    else:
        with open(sys.argv[3], 'r') as f:
            p_list = [line.strip() for line in f.readlines() if line.strip()!='']
    
    print('----- Get {} packages.'.format(len(p_list)))
    
    # Normalize and de-duplicate package names
    packages_set = set(canonicalize_name(p) for p in p_list)
    print('----- Get {} normalized and distinct packages.'.format(len(packages_set)))
    
    # Save packages
    p_file = os.path.join(python_dir, 'packages.txt')
    with open(p_file, 'w') as f:
        f.write('\n'.join(packages_set))
    print('----- Saved to {}.'.format(p_file))
    
    # Obtain all available versions for the packages
    print('----- Start to get versions ...')
    pv_file = 'packages_versions.json'
    version_finder = VersionFinder(python_version)
    exit_code, run_logs = version_finder.versions4packages(p_file, pv_file)
    version_finder.close()
    print('Exit code: {}'.format(exit_code))
    print(run_logs)
    
    pv_path = os.path.join(python_dir, pv_file)
    if os.path.exists(pv_path):
        with open(pv_path, 'r') as f:
            pv_dict = json.load(f)
    else:
        pv_dict = {}
    
    p_num = v_num = 0
    for _,value in pv_dict.items():
        p_num += 1
        v_num += len(value)
    print('----- Get {} available versions for {} packages.'.format(v_num, p_num))
    print('----- Saved to {}.'.format(pv_path))
    
    # Install
    install_dir = os.path.join(python_dir, 'libraries-data')
    if not os.path.isdir(install_dir):
        os.mkdir(install_dir)
    
    print('----- Install all distributions ... (saved to {}) -----'.format(install_dir))
    installer = DynamicInstaller(python_version)
    for package in sorted(pv_dict):
        installer.install_and_analyze(package, pv_dict[package], install_dir)
    installer.close()

    # Transfer to csv files
    csv_dir = os.path.join(python_dir, 'csv-data')

    print('----- Transfer to csv files ... (saved to {}) -----'.format(csv_dir))
    transformer = CsvTransformer(csv_dir, neo4j_home)
    unknown_packages = transformer.generate_csv(install_dir)
    print('----- Get {} unknown packages -----'.format(len(unknown_packages)))

    unknown_p_file = os.path.join(python_dir, 'unknown_packages.txt')
    with open(unknown_p_file, 'w') as f:
        f.write('\n'.join(unknown_packages))
    print('----- Unknown packages are saved to {}.'.format(unknown_p_file))


    # Obtain all available versions for the unknown packages
    print('----- Start to get versions for unknown packages ...')
    unknown_pv_file = 'unknown_packages_versions.json'
    version_finder = VersionFinder(python_version)
    exit_code, run_logs = version_finder.versions4packages(unknown_p_file, unknown_pv_file)
    version_finder.close()
    print('Exit code: {}'.format(exit_code))
    print(run_logs)
    unknown_pv_path = os.path.join(python_dir, unknown_pv_file)
    print('----- Saved to {}.'.format(unknown_pv_path))

    # Supplements: add to csv files
    transformer.add_packages_and_versions(unknown_pv_path)


if __name__ == '__main__':
    main()