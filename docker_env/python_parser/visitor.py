import ast
import imp
import sys
import importlib


# Up the recursion limit
sys.setrecursionlimit(10000)


class ParserVisitor(ast.NodeVisitor):
    def __init__(self):
        self.import_libraries = set()   # imported modules that aren't in standard library
        self.import_names = []          # used name
        self.mappings = {}              # {used_name: full_name}
        self.resources = set()          # uncertain resources: from ... import xxx
        self.attrs = set()              # the attributes of those modules used in the code

    def is_standard_library(self, name):
        """Determine if a module name refers to a module in the python standard library.
        Parameters
        ----------
        name : string
            Name of the module to check.
        Returns
        -------
        bool
            True if the module is in the standard library.
        """

        # Name must be defined.
        if name is None:
            raise Exception('Name cannot be none')

        # Attempt to use python import tools to discover facts about the module.
        # If we get an import error, it was definitely not part of the standard library, so return false.
        # If we do find the module, check to make sure it's not not a builtin or part of python extras or site-packages.
        
        # get top_module name
        try:
            importlib.import_module(name)
            
            name = name.split('.')[0]
            path = imp.find_module(name)[1]
            return bool(imp.is_builtin(name) or ('site-packages' not in path and 'Extras' not in path))
        except ImportError:
            return False

    def visit_Import(self, node):
        # Import(alias* names)
        # alias = (identifier name, identifier? asname)
        for alias in node.names:
            if alias.name and not self.is_standard_library(alias.name):
                self.import_libraries.add(alias.name)
                if alias.asname is not None:
                    self.mappings[alias.asname] = alias.name
                    self.import_names.insert(0, alias.asname)
                else:
                    self.import_names.insert(0, alias.name)

        # Call generic visit to visit all child nodes
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        # ImportFrom(identifier? module, alias* names, int? level)
        # level > 0 means relative import: local relative module can't be installed
        if node.module and node.level == 0 and not self.is_standard_library(node.module):
            self.import_libraries.add(node.module)
            for alias in node.names:
                if alias.name != '*':
                    possible_module = '{}.{}'.format(node.module, alias.name)
                    self.resources.add(possible_module)

                    if alias.asname is not None:
                        self.mappings[alias.asname] = possible_module
                        self.import_names.insert(0, alias.asname)
                    else:
                        self.mappings[alias.name] = possible_module
                        self.import_names.insert(0, alias.name)

        # Call generic visit to visit all child nodes
        self.generic_visit(node)

    '''
    # Interpreted language is hard to know which variable is a module object
    def visit_Assign(self, node):
        # Assign(expr* targets, expr value)
        If the value of an assignment matches an imported name,
        then treat the targets of the assignment as aliases.
        # Check if the target in self.aliases but value is not a module or aliases
        pass
    '''
    
    def visit_Attribute(self, node):
        # Attribute(expr value, identifier attr, expr_context ctx)
        # xx.xx must be an attribute
        attr_name = self.get_variable_name(node)
        if attr_name != '':
            for name in self.import_names:
                if attr_name.startswith('{}.'.format(name)):
                    # should add it to self.attrs
                    if name in self.mappings:
                        resource_name = '{}{}'.format(self.mappings[name], attr_name[len(name):])
                    else:
                        resource_name = attr_name
                    
                    # check if already exists
                    has_exist = False
                    for exist_res in self.attrs:
                        if exist_res.startswith('{}.'.format(resource_name)):
                            has_exist = True
                            break
                    
                    if not has_exist:
                        self.attrs.add(resource_name)
                    break
        
        # Call generic visit to visit all child nodes
        self.generic_visit(node)
    

    def get_variable_name(self, node):
        """Get full name of variable node(Name or Attribute)."""

        # Get type
        t = type(node)

        if t is ast.Name:
            return node.id
        elif t is ast.Attribute:
            value = self.get_variable_name(node.value)
            if value == '':
                return value
            else:
                return '{}.{}'.format(value, node.attr)
        else:
            return ''