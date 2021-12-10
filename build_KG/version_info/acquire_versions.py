import docker
import json
import sys
import os
from packaging.utils import canonicalize_version


class VersionFinder(object):
    def __init__(self, python_version):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.dockerfile_dir = os.path.join(self.current_dir, 'docker-scripts')
        self.dockerfile_path = os.path.join(self.dockerfile_dir, 'Dockerfile')

        self._generate_dockerfile(python_version)
        
        self.image_tag = 'python{}:version'.format(python_version[0])
        # build image
        self.client = docker.from_env()
        self.client.images.build(path=self.dockerfile_dir, tag=self.image_tag, dockerfile='Dockerfile', forcerm=True)

    
    def close(self):
        self.client.images.remove(image=self.image_tag)
        self.client.close()
    
    
    def _generate_dockerfile(self, python_version):
        with open(self.dockerfile_path, 'w') as f:
            f.write('FROM python:{}\n'.format(python_version))
            f.write('RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \\\n')
            f.write('\t&& pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \n')
            f.write('COPY get_versions.py /scripts/\n')
            f.write('CMD python /scripts/get_versions.py')
    
    
    def versions4packages(self, packages_path, versions_file):
        data_dir, packages_file = os.path.split(os.path.abspath(packages_path))
        # Mount
        target_dir = '/volumes/'
        mount = docker.types.Mount(target=target_dir, source=data_dir, type='bind', read_only=False)
        # run container
        path_env = {}
        path_env['packages_file'] = os.path.join(target_dir, packages_file)
        path_env['versions_file'] = os.path.join(target_dir, versions_file)

        container = self.client.containers.run(image=self.image_tag, detach=True, network_mode='host', mounts=[mount], environment=path_env)
        exit_code = container.wait(condition='not-running')['StatusCode']

        run_logs = container.logs(stdout=True, stderr=True).decode().strip()
        container.remove()

        # Normalize and de-duplicate versions
        pv_path = os.path.join(data_dir, versions_file)
        if os.path.exists(pv_path):
            with open(pv_path, 'r') as f:
                pv_dict = json.load(f)
            
            for key,value in pv_dict.items():
                new_value = []
                exist_versions = set()
                for item in value:
                    normalized_item = canonicalize_version(item)
                    if normalized_item not in exist_versions:
                        new_value.append(item)
                        exist_versions.add(normalized_item)
                        
                pv_dict[key] = new_value

            with open(pv_path, 'w') as f:
                json.dump(pv_dict, f)

        return exit_code, run_logs


def main():
    """
    python get_versions.py <packages_file> <python_version> <versions.json>
    """
    packages_path = sys.argv[1]
    python_version = sys.argv[2]
    versions_file = sys.argv[3]

    version_finder = VersionFinder(python_version)
    version_finder.versions4packages(packages_path, versions_file)
    version_finder.close()

    data_dir = os.path.split(os.path.abspath(packages_path))[0]
    with open(os.path.join(data_dir, versions_file), 'r') as f:
        pv_dict = json.load(f)

    p_num = v_num = 0
    for _,value in pv_dict.items():
        p_num += 1
        v_num += len(value)
    
    print('Get {} available versions for {} packages.'.format(v_num, p_num))


if __name__ == '__main__':
    main()