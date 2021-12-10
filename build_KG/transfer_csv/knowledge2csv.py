from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name
from packaging.version import parse
import os
import json


class CsvTransformer(object):
    def __init__(self, res_dir, neo4j_home):
        # global info for nodes
        self.packageInfo_dict = {}      # {name: id}
        self.attributeInfo_dict = {}    # {name: id}
        self.version_require = {}       # {vid: requires}

        # generate unique ID
        self.package_id = 0
        self.version_id = 0
        self.module_id = 0
        self.attribute_id = 0

        # labels
        self.label_package = 'Package'
        self.label_version = 'Version'
        self.label_module = 'Module'
        self.label_attribute = 'Attribute'
        self.label_hasVersion = 'HAS_VERSION'
        self.label_hasModule = 'HAS_MODULE'
        self.label_hasAttribute = 'HAS_ATTRIBUTE'
        self.label_require = 'REQUIRES'

        # all csv files for nodes and relationships
        if not os.path.isdir(res_dir):
            os.mkdir(res_dir)
        
        node_dir = os.path.join(res_dir, 'nodes')
        rel_dir = os.path.join(res_dir, 'relationships')
        if not os.path.isdir(node_dir):
            os.mkdir(node_dir)
        if not os.path.isdir(rel_dir):
            os.mkdir(rel_dir)
        
        # shell script: load csv files to neo4j database
        with open(os.path.join(res_dir, 'run.sh'), 'w') as f:
            f.write('#!/bin/bash\n')
            f.write('{}/bin/neo4j-admin import \\\n'.format(os.path.abspath(neo4j_home)))
            f.write('--nodes nodes/packages_header.csv,nodes/packages.csv \\\n')
            f.write('--nodes nodes/versions_header.csv,nodes/versions.csv \\\n')
            f.write('--nodes nodes/modules_header.csv,nodes/modules.csv \\\n')
            f.write('--nodes nodes/attributes_header.csv,nodes/attributes.csv \\\n')
            f.write('--relationships relationships/hasVersion_header.csv,relationships/hasVersion.csv \\\n')
            f.write('--relationships relationships/version2Module_header.csv,relationships/version2Module.csv \\\n')
            f.write('--relationships relationships/module2Module_header.csv,relationships/module2Module.csv \\\n')
            f.write('--relationships relationships/hasAttribute_header.csv,relationships/hasAttribute.csv \\\n')
            f.write('--relationships relationships/requires_header.csv,relationships/requires.csv')
        
        # csv header
        with open(os.path.join(node_dir, 'packages_header.csv'), 'w') as f:
            f.write(':ID(Package-ID),name,:LABEL')
        with open(os.path.join(node_dir, 'versions_header.csv'), 'w') as f:
            f.write(':ID(Version-ID),version,install_status,:LABEL')
        with open(os.path.join(node_dir, 'modules_header.csv'), 'w') as f:
            f.write(':ID(Module-ID),name,import_status,:LABEL')
        with open(os.path.join(node_dir, 'attributes_header.csv'), 'w') as f:
            f.write(':ID(Attribute-ID),name,:LABEL')
        
        with open(os.path.join(rel_dir, 'hasVersion_header.csv'), 'w') as f:
            f.write(':START_ID(Package-ID),:END_ID(Version-ID),:TYPE')
        with open(os.path.join(rel_dir, 'version2Module_header.csv'), 'w') as f:
            f.write(':START_ID(Version-ID),:END_ID(Module-ID),:TYPE')
        with open(os.path.join(rel_dir, 'module2Module_header.csv'), 'w') as f:
            f.write(':START_ID(Module-ID),:END_ID(Module-ID),:TYPE')
        with open(os.path.join(rel_dir, 'hasAttribute_header.csv'), 'w') as f:
            f.write(':START_ID(Module-ID),:END_ID(Attribute-ID),:TYPE')
        with open(os.path.join(rel_dir, 'requires_header.csv'), 'w') as f:
            f.write(':START_ID(Version-ID),requirement,:END_ID(Package-ID),:TYPE')

        self.csv_package = os.path.join(node_dir, 'packages.csv')
        self.csv_version = os.path.join(node_dir, 'versions.csv')
        self.csv_module = os.path.join(node_dir, 'modules.csv')
        self.csv_attribute = os.path.join(node_dir, 'attributes.csv')
        
        self.csv_hasVersion = os.path.join(rel_dir, 'hasVersion.csv')
        self.csv_version2Module = os.path.join(rel_dir, 'version2Module.csv')
        self.csv_module2Module = os.path.join(rel_dir, 'module2Module.csv')
        self.csv_hasAttribute = os.path.join(rel_dir, 'hasAttribute.csv')
        self.csv_require = os.path.join(rel_dir, 'requires.csv')


    def add_packages_and_versions(self, pv_file):
        pv_data = {}
        with open(pv_file, 'r') as f:
            pv_data = json.load(f)
        
        # files writer
        node_version = open(self.csv_version, 'a')
        rel_version = open(self.csv_hasVersion, 'a')
        
        p_num = 0
        v_num = 0
        for package, version_list in pv_data.items():
            if package not in self.packageInfo_dict:
                print('Error: Package {} is not in supplements'.format(package))
                continue

            p_num += 1
            v_num += len(version_list)
            
            pid = self.packageInfo_dict[package]
            version_list.sort(key=lambda x:parse(x))
            for version in version_list:
                node_version.write('{},{},{},{}\n'.format(self.version_id, version, 'Unknown', self.label_version))
                rel_version.write('{},{},{}\n'.format(pid, self.version_id, self.label_hasVersion))
                self.version_id += 1
        
        node_version.close()
        rel_version.close()
        print('Supplements: {} packages and {} versions'.format(p_num, v_num))

    
    def generate_csv(self, data_dir):
        """
        Return: the packages that need versions
        """        
        # files writer
        node_package = open(self.csv_package, 'w')
        node_version = open(self.csv_version, 'w')
        node_module = open(self.csv_module, 'w')
        node_attr = open(self.csv_attribute, 'w')
        rel_version = open(self.csv_hasVersion, 'w')
        rel_version2module = open(self.csv_version2Module, 'w')
        rel_module2module = open(self.csv_module2Module, 'w')
        rel_attr = open(self.csv_hasAttribute, 'w')
        rel_require = open(self.csv_require, 'w')

        # packages and versions
        for package in os.listdir(data_dir):
            print(package)
            if package in self.packageInfo_dict:
                print('Warning: Repetitive package : {}'.format(package))
                continue
            
            self.packageInfo_dict[package] = self.package_id
            node_package.write('{},{},{}\n'.format(self.package_id, package, self.label_package))

            p_dir = os.path.join(data_dir, package)
            version_list = os.listdir(p_dir)
            version_list.remove('exit_status.json')

            version_list.sort(key=lambda x:parse(x))
            for version in version_list:
                rel_version.write('{},{},{}\n'.format(self.package_id, self.version_id, self.label_hasVersion))
                v_dir = os.path.join(p_dir, version)
                install_status = 'Fail'
                if os.path.exists(os.path.join(v_dir, 'LABEL')):
                    install_status = 'Success'
                else:
                    install_outfile = os.path.join(v_dir, 'install.txt')
                    if os.path.exists(install_outfile):
                        with open(os.path.join(v_dir, 'install.txt'), 'r') as f:
                            for line in f.readlines():
                                if 'ERROR: Could not find a version that satisfies the requirement {}=={} (from versions: none)'.format(package, version) in line:
                                    # print('{} {}'.format(package, version))
                                    # Due to networkError
                                    install_status = 'Unknown'
                                    break
                node_version.write('{},{},{},{}\n'.format(self.version_id, version, install_status, self.label_version))
                
                data_path = os.path.join(v_dir, 'data.json')
                if not os.path.exists(data_path):
                    self.version_id += 1
                    continue

                import_path = os.path.join(v_dir, 'import_fail.json')
                if not os.path.exists(import_path):
                    self.version_id += 1
                    continue
                
                try:
                    with open(data_path) as f:
                        data_json = json.load(f)
                    with open(import_path) as f:
                        import_json = json.load(f)
                except json.decoder.JSONDecodeError:
                    print('Error: invalid json file ({} {})'.format(package, version))
                    self.version_id += 1
                    continue
                
                if data_json['Requires'] is not None and len(data_json['Requires']) > 0:
                    self.version_require[self.version_id] = data_json['Requires']
                # modules
                module_dict = {}
                module_list = data_json['Modules'] + list(import_json)
                module_list.sort(key=lambda x:len(x.split('.')))
                for module in module_list:
                    module_dict[module] = self.module_id
                    import_status = True
                    if module in import_json:
                        import_status = False
                    node_module.write('{},{},{},{}\n'.format(self.module_id, module, import_status, self.label_module))
                    
                    module_info = module.split('.')
                    if len(module_info) == 1:
                        rel_version2module.write('{},{},{}\n'.format(self.version_id, self.module_id, self.label_hasModule))
                    else:
                        index = 0
                        has_prefix = False
                        for i in range(1, len(module_info)):
                            index += len(module_info[-i])+1
                            prefix_module = module[:-index]
                            if prefix_module in module_dict:
                                has_prefix = True
                                rel_module2module.write('{},{},{}\n'.format(module_dict[prefix_module], self.module_id, self.label_hasModule))
                                if i != 1:
                                    print('Warning: module \"{}\" --> \"{}\" ({} {})'.format(prefix_module, module, package, version))
                                break
                        
                        if not has_prefix:
                            print('Warning: module \"{}\" has no parent module ({} {})'.format(module, package, version))
                            rel_version2module.write('{},{},{}\n'.format(self.version_id, self.module_id, self.label_hasModule))
                    # attrs
                    if module in data_json['Attrs']:
                        for attr in data_json['Attrs'][module]:
                            if attr not in self.attributeInfo_dict:
                                self.attributeInfo_dict[attr] = self.attribute_id
                                node_attr.write('{},{},{}\n'.format(self.attribute_id, attr, self.label_attribute))
                                self.attribute_id += 1
                            rel_attr.write('{},{},{}\n'.format(self.module_id, self.attributeInfo_dict[attr], self.label_hasAttribute))
                            
                    self.module_id += 1
                
                self.version_id += 1
            
            self.package_id += 1
        
        # require
        print('Handle on requirements ...')
        unknown_packages = []
        for vid, requires in self.version_require.items():
            for item in requires:
                # ignore extra requirements
                if len(item.split(';')) > 1:
                    continue

                try:
                    req = Requirement(item)

                    require_package = canonicalize_name(req.name)
                    if require_package not in self.packageInfo_dict:
                        unknown_packages.append(require_package)
                        self.packageInfo_dict[require_package] = self.package_id
                        node_package.write('{},{},{}\n'.format(self.package_id, require_package, self.label_package))
                        self.package_id += 1
                    rel_require.write('{},\"{}\",{},{}\n'.format(vid, str(req.specifier).replace('\"', '\''), self.packageInfo_dict[require_package], self.label_require))
                except InvalidRequirement:
                    print('Warning: InvalidRequirement \"{}\"'.format(item))

        # close
        node_package.close()
        node_version.close()
        node_module.close()
        node_attr.close()
        rel_version.close()
        rel_version2module.close()
        rel_module2module.close()
        rel_attr.close()
        rel_require.close()

        return unknown_packages


def main():
    pass


if __name__ == '__main__':
    main()