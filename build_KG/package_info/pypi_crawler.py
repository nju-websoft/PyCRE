'''
Reference from https://wiki.python.org/moin/PyPISimple
'''

from bs4 import BeautifulSoup
from urllib.request import urlopen
import sys
import os


def get_distributions(simple_index='https://pypi.org/simple/'):
    """
    Get all available packages from PyPI.
    """
    with urlopen(simple_index) as f:
        soup = BeautifulSoup(f.read(), features='html.parser')

    return [a.text for a in soup.find_all('a')]


def main():
    """
    python pypi_crawler.py <filename>
    """
    out_file = sys.argv[1]
    
    packages_list = get_distributions()
    print('Get {} packages from PyPI.'.format(len(packages_list)))
    
    with open(out_file, 'w') as fw:
        for package in packages_list:
            fw.write(package+'\n')

    print('Successfully save all packages to {}!'.format(os.path.abspath(out_file)))
    

if __name__ == '__main__':
    main()
