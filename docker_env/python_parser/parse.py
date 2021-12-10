import ast
import os
import sys
import platform
import json
from visitor import ParserVisitor


def parse_file(filename):
    """Load and parse a file.
    Parameters
    ----------
    filename : string
        Path of parse.py.
    Returns
    -------
    dict
        imports - All imports made by the parsed snippet
        resources   - All resources used by the parsed snippet, traced back to its
                  associated library if possible.
    """

    with open(filename, 'r') as py_file:
        try:
            # Parse python snippet into an AST
            tree = ast.parse(py_file.read())

            # Get imports and resources from AST
            visitor = ParserVisitor()
            visitor.visit(tree)
            return {'imports':list(visitor.import_libraries), 'resources':list(visitor.resources), 'attrs':list(visitor.attrs)}
        except SyntaxError:
            return None


def main():
    """Main function.
    Usage
    -----
    python parse.py <filepath>
    """

    file_path = os.path.abspath(sys.argv[1])
    if os.path.isfile(file_path) and os.path.splitext(file_path)[1] == '.py':
        ret = parse_file(file_path)
        if ret is None:
            print("The snippet can\'t be parsed by Python {}.".format(platform.python_version()))
        else:
            print(json.dumps(ret))
    else:
        print("The snippet is not a Python file.")



if __name__ == '__main__':
    main()