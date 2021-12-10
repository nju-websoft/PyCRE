import json
import docker
import sys
import os
import time


class DynamicInstaller(object):
    def __init__(self, python_version):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.dockerfile_dir = os.path.join(self.current_dir, 'docker-scripts')
        self.dockerfile_path = os.path.join(self.dockerfile_dir, 'Dockerfile')

        self._generate_dockerfile(self.dockerfile_path, python_version)
        
        self.pip_source = '-i https://pypi.tuna.tsinghua.edu.cn/simple'
        # build image
        self.image_tag = 'python:install'
        self.client = docker.from_env()
        self.client.images.build(path=self.dockerfile_dir, tag=self.image_tag, dockerfile='Dockerfile', forcerm=True)

        # output files
        self.log_file = 'log.txt'
        self.install_file = 'install.txt'
        self.module_file = 'data.json'
        self.fail_file = 'import_fail.json'

        # target volume for mounts
        self.target_dir = '/volumes/'
        self.target_install_path = os.path.join(self.target_dir, self.install_file)
    
    def close(self):
        self.client.images.remove(image=self.image_tag)
        self.client.close()
    
    
    def _generate_dockerfile(self, file_path, python_version):
        with open(file_path, 'w') as f:
            f.write('FROM python:{}\n'.format(python_version))
            f.write('RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \\\n')
            f.write('\t&& pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \n')
            f.write('COPY python{}_analyze.py /scripts/dynamic_analyze.py'.format(python_version[0]))
    
    
    def install_and_analyze(self, package, version_list, save_dir):
        """
        Install and analyze package by 'pip install <package>==<version>'
        """
        package_dir = os.path.join(save_dir, package)
        exit_file = os.path.join(package_dir, 'exit_status.json')
        v_dict = {}
        if not os.path.isdir(package_dir):
            os.mkdir(package_dir)
        elif os.path.exists(exit_file):
            # Exsiting results
            with open(exit_file, 'r') as f:
                v_dict = json.load(f)

        for version in version_list:
            version_dir = os.path.join(package_dir, version)
            if not os.path.isdir(version_dir):
                # print('{}:{}'.format(package, version))
                os.mkdir(version_dir)

                # Use bind mounts
                mount = docker.types.Mount(target=self.target_dir, source=version_dir, type='bind', read_only=False)

                install_command = 'stdbuf -i0 -o0 -e0 timeout 600 python -W ignore:DEPRECATION -m pip install --no-compile {}=={} --disable-pip-version-check {} > {} 2>&1'.format(package, version, self.pip_source, self.target_install_path)
                exec_command = 'timeout 300 python scripts/dynamic_analyze.py {} {}'.format(package, version)
                complete_command = ['/bin/sh', '-c', '{} && {}'.format(install_command, exec_command)]

                # used to avoid repetitive execution and indicate whether the installation was successful
                label_file = os.path.join(version_dir, 'LABEL')
                if os.path.exists(label_file):
                    os.remove(label_file)
                
                # run the container
                container = self.client.containers.run(image=self.image_tag, command=complete_command, detach=True, network_mode='host', mounts=[mount])
                try:
                    exit_code = container.wait(timeout=960, condition='not-running')['StatusCode']
                    v_dict[version] = str(exit_code)
                except Exception:
                    v_dict[version] = 'Timeout'
                    time.sleep(100)
                    if container.status == 'running':
                        container.kill()
                        time.sleep(100)
                finally:
                    # get output from container
                    try:
                        run_logs = container.logs(stdout=True, stderr=True).decode(encoding='UTF-8', errors='ignore').strip()
                        with open(os.path.join(version_dir, 'log.txt'), 'w') as f:
                            f.write(run_logs)
                    except docker.errors.APIError:
                        pass
                    
                    container.remove(v=True, force=True)
        
        with open(exit_file, 'w') as f:
            json.dump(v_dict, f)
                

def main():
    pv_file = sys.argv[1]
    python_version = sys.argv[2]

    with open(os.path.join(pv_file), 'r') as f:
        pv_dict = json.load(f)

    install_dir = os.path.join(os.environ['HOME'], 'Python{}-libraries-data'.format(python_version[0]))
    if not os.path.isdir(install_dir):
        os.mkdir(install_dir)
    
    installer = DynamicInstaller(python_version)
    for package in sorted(pv_dict):
        installer.install_and_analyze(package, pv_dict[package], install_dir)

    installer.close()


if __name__ == '__main__':
    main()