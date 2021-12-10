import docker
import os
import shutil
import json
import neo4j
from neo4j import GraphDatabase
from packaging.version import parse
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
import time
import copy
import pycryptosat
import itertools
import sys


class PythonParser(object):
    def __init__(self):
        self.python2_tag = 'python2:parse'
        self.python3_tag = 'python3:parse'
        
        self.local_dir = os.path.abspath('mount')
        if not os.path.isdir(self.local_dir):
            os.mkdir(self.local_dir)
        
        remote_dir = '/volumes/'
        self.mount = docker.types.Mount(target=remote_dir, source=self.local_dir, type='bind', read_only=False)
        
        self.local_file = os.path.join(self.local_dir, 'snippet.py')
        self.remote_file = os.path.join(remote_dir, 'snippet.py')

        self.client = docker.from_env()


    def parse_pyfile(self, pyfile):
        parse_results = {'Python2': None, 'Python3': None}
        shutil.copyfile(pyfile, self.local_file)

        # Python 2
        container = self.client.containers.run(image=self.python2_tag, detach=True, mounts=[self.mount], command=[self.remote_file])
        container.wait(condition='not-running')['StatusCode']
        run_logs = container.logs(stdout=True, stderr=True).decode().strip()
        container.remove()
        try:
            parse_results['Python2'] = json.loads(run_logs)
            print('Parsing result in Python 2.7.18:\n{}'.format(parse_results['Python2']))
        except json.JSONDecodeError:
            print(run_logs)
        
        # Python3
        container = self.client.containers.run(image=self.python3_tag, detach=True, mounts=[self.mount], command=[self.remote_file])
        container.wait(condition='not-running')['StatusCode']
        run_logs = container.logs(stdout=True, stderr=True).decode().strip()
        container.remove()
        try:
            parse_results['Python3'] = json.loads(run_logs)
            print('Parsing result in Python 3.8.11:\n{}'.format(parse_results['Python3']))
        except json.JSONDecodeError:
            print(run_logs)
        
        os.remove(self.local_file)
        return parse_results
    
    def close(self):
        shutil.rmtree(self.local_dir)
        self.client.close()


class subGraph(object):
    def __init__(self, degree_table={}, in_table={}):
        self.degree_table = degree_table  # {id: set()}
        self.in_table = in_table  # {id: set()}
    
    def copy_graph(self):
        return subGraph(copy.deepcopy(self.degree_table), copy.deepcopy(self.in_table))
    
    def set_graph(self, graph):
        self.degree_table = copy.deepcopy(graph.degree_table)
        self.in_table = copy.deepcopy(graph.in_table)
    
    def clear_graph(self):
        for key in list(self.degree_table.keys()):
            if len(self.degree_table[key]) == 0 and len(self.in_table[key]) == 0:
                self.degree_table.pop(key)
                self.in_table.pop(key)


class pvGraph(object):
    def __init__(self):
        self.degree_table = {}
        self.in_table = {}
        self.node_dict = {} # {pid: (package, version)}
        self.install_set = set()    # The packages that need to be explicitly installed

        self.install_pair = []  # [(package, version)]
    

    def topo_sort(self):
        for key, value in self.in_table.items():
            if len(value) == 0:
                # needs to be explicitly installed
                self.install_set.add(key)

        while len(self.degree_table) > 0:
            has_find = False
            for key, value in list(self.degree_table.items()):
                if len(value) == 0:
                    has_find = True
                    # install pair
                    if key in self.install_set:
                        self.install_pair.append(self.node_dict[key])
                    # delete the connected nodes
                    for in_node in self.in_table[key]:
                        self.degree_table[in_node].remove(key)
                    # delete itself
                    self.degree_table.pop(key)
                    self.in_table.pop(key)
                    
                    break
            
            if not has_find:
                # There exsits a circle!
                for key in self.degree_table:
                    if key in self.install_set:
                        self.install_pair.append(self.node_dict[key])
                return False
        
        return True


ROOT_TYPE = 'root node'
MODULE_TYPE = 'module node'
PACKAGE_TYPE = 'package node'
VERSION_TYPE = 'version node'
class RequireGraph(object):
    def __init__(self, candidate_libraries, requires_info):
        self.degree_table = {}          # {id: {id: edge_info}}
        self.node_dict = {}             # {id: node}
        self.is_conjunction = {}        # {id: True/False}
        self.node_type = {}             # {id: type}

        self.sorted_degree_table = {}   # {id: [id, ...]}

        # packages and versions (nodes and relationships)
        package_dict = {}
        for record in requires_info:
            # nodes
            for node in record[0]:
                self.node_dict[node.id] = node
                if node.id not in self.degree_table:
                    self.degree_table[node.id] = {}
                    if 'Package' in node.labels:
                        self.node_type[node.id] = PACKAGE_TYPE
                        package_dict[node['name']] = node.id
                        self.is_conjunction[node.id] = False
                    else:
                        self.node_type[node.id] = VERSION_TYPE
                        self.is_conjunction[node.id] = True
            # relationships
            for rel in record[1]:
                # version REQUIRES package: requirement (str)
                self.degree_table[rel.start_node.id][rel.end_node.id] = rel.get('requirement', default=None)

        # virtual root node
        virtual_index = -1
        self.node_dict[virtual_index] = 'root'
        self.node_type[-1] = ROOT_TYPE
        self.degree_table[-1] = {}
        self.is_conjunction[-1] = True

        for top_module, optional_libraries in candidate_libraries.items():
            # virtual module node
            virtual_index -= 1
            self.node_dict[virtual_index] = top_module
            self.node_type[virtual_index] = MODULE_TYPE
            self.degree_table[virtual_index] = {}
            self.is_conjunction[virtual_index] = False
            self.degree_table[-1][virtual_index] = None

            # candidate libraries
            for p_name, vid_set in optional_libraries.items():
                if p_name not in package_dict:
                    # package not in KG
                    self.node_dict[p_name] = None
                    self.node_type[p_name] = PACKAGE_TYPE
                    self.degree_table[p_name] = {}
                    self.is_conjunction[p_name] = False
                    pid = p_name
                else:
                    pid = package_dict[p_name]
                
                if len(vid_set) == 0:
                    # module REQUIRES package: requirement (str, all)
                    self.degree_table[virtual_index][pid] = ''
                else:
                    # module REQUIRES package: requirement (set)
                    self.degree_table[virtual_index][pid] = vid_set
        
        # sort the nodes in degree table
        for nid, neighbor_dict in self.degree_table.items():
            node_type = self.node_type[nid]
            if node_type == ROOT_TYPE:
                # root node: sort the modules by the number of candidate packages
                self.sorted_degree_table[nid] = sorted(list(neighbor_dict), key=lambda item:len(self.degree_table[item]))
            elif node_type == MODULE_TYPE:
                # module node: sort the packages by the number of candidate versions, reverse
                self.sorted_degree_table[nid] = sorted(list(neighbor_dict), key=lambda item:len(self.degree_table[nid][item]), reverse=True)
            elif node_type == PACKAGE_TYPE:
                # package node: sort all versions
                self.sorted_degree_table[nid] = self._sort_versions(list(neighbor_dict))
            else:
                # version node: sort the packages by the number of versions
                self.sorted_degree_table[nid] = sorted(list(neighbor_dict), key=lambda item:len(self.degree_table[item]))
    

    def _sort_versions(self, version_id_list):
        '''
            Sort versions by install status, newest
        '''
        sorted_versions = sorted(version_id_list, key=lambda item:parse(self.node_dict[item]['version']), reverse=True)

        success_list = []
        unseen_list = []
        fail_list = []
        for vid in sorted_versions:
            if self.node_dict[vid]['install_status'] == 'Success':
                success_list.append(vid)
            elif self.node_dict[vid]['install_status'] == 'Unknown':
                unseen_list.append(vid)
            else:
                fail_list.append(vid)
        
        return success_list + unseen_list + fail_list

    def _get_node_name(self, node_id):
        node_info = self.node_dict[node_id]
        if node_info == None:
            return node_id
        
        node_type = self.node_type[node_id]
        if node_type == ROOT_TYPE or node_type == MODULE_TYPE:
            return node_info
        
        if node_type == PACKAGE_TYPE:
            return node_info['name']
        
        return node_info['version']


    def print_graph(self):
        # BFS
        print('{} nodes in the dependency graph.'.format(len(self.node_dict)))
        print('{} packages in dependency graph.'.format(len([nid for nid in self.node_dict if self.node_type[nid] == PACKAGE_TYPE])))

        has_seen = set([-1])
        st = [-1]
        while len(st) > 0:
            node_id = st[0]
            st = st[1:]
            if len(self.degree_table[node_id]) > 0:
                print(self._get_node_name(node_id), end=': ')
                for neighbor_id in self.sorted_degree_table[node_id]:
                    edge_info = self.degree_table[node_id][neighbor_id]
                    if neighbor_id not in has_seen:
                        has_seen.add(neighbor_id)
                        st.append(neighbor_id)
                    print((self._get_node_name(neighbor_id), edge_info), end='\t')
                print('\n')
    

    def _filter_child_id(self, optional_child, spec):
        return [item for item in optional_child if self.node_dict[item]['version'] in spec]
    

    def _get_install_graph(self, graph):
        '''
            Remain the packages that need to be explicitly installed
        '''
        pv_graph = pvGraph()
        
        for nid in graph.degree_table:
            if self.node_type[nid] == PACKAGE_TYPE:
                ## Package node
                if len(graph.degree_table[nid]) == 0:
                    # unknown package
                    if nid not in pv_graph.degree_table:
                        pv_graph.degree_table[nid] = set()
                        pv_graph.in_table[nid] = set()
                    
                    if isinstance(nid, str):
                        pv_graph.node_dict[nid] = (nid, None)
                    else:
                        pv_graph.node_dict[nid] = (self.node_dict[nid]['name'], None)

                    continue
                    
                # get the version of package
                vid_list = list(graph.degree_table[nid])
                if len(vid_list) > 1:
                    vid_list = self._sort_versions(vid_list)
                    print('Mutiple version of a package in SAT solver.')
                vid = vid_list[0]
                # package name and version name
                pv_graph.node_dict[nid] = (self.node_dict[nid]['name'], self.node_dict[vid]['version'])
                if nid not in pv_graph.degree_table:
                    pv_graph.degree_table[nid] = set()
                    pv_graph.in_table[nid] = set()

                for pid in graph.degree_table[vid]:
                    # require relationship
                    if pid not in pv_graph.degree_table:
                        pv_graph.degree_table[pid] = set()
                        pv_graph.in_table[pid] = set()
                    pv_graph.degree_table[nid].add(pid)
                    pv_graph.in_table[pid].add(nid)
                
                # judge if package needs to be explicitly installed
                version_list = self._sort_versions(self.degree_table[nid])
                each_version = None
                all_req = SpecifierSet(prereleases=True)
                has_req = False
                for in_node in graph.in_table[nid]:
                    req = self.degree_table[in_node][nid]
                    if isinstance(req, str):
                        spec = SpecifierSet(req, prereleases=True)
                        # newest version in this requirement
                        optional_versions = self._filter_child_id(version_list, spec)
                        if len(optional_versions) == 0:
                            print('Unexpected error in subgraph.')
                            print(self._get_node_name(nid))
                            print(self._get_node_name(vid))
                            print([self._get_node_name(item) for item in version_list])
                            print(spec)
                            print(self._get_node_name(vid) in spec)
                            continue

                        version = optional_versions[0]
                        if each_version is None:
                            each_version = version
                        elif each_version != version:
                            # needs to be explicitly installed
                            pv_graph.install_set.add(nid)
                            break
                        # union
                        all_req &= spec
                        has_req = True
                
                if nid not in pv_graph.install_set and has_req:
                    if vid != self._filter_child_id(version_list, all_req)[0]:
                        # needs to be explicitly installed in each version of pip
                        pv_graph.install_set.add(nid)

        return pv_graph
    

    def _get_optional_children_id(self, optional_children, subgraph, node_id):
        ret = copy.deepcopy(optional_children)
        if self.node_type[node_id] == PACKAGE_TYPE:
            all_req = SpecifierSet(prereleases=True)
            for nid in subgraph.in_table[node_id]:
                req_info = self.degree_table[nid][node_id]
                if req_info is None:
                    continue
                if isinstance(req_info, set):
                    ret = [item for item in ret if item in req_info]
                elif req_info != '':
                    all_req &= SpecifierSet(req_info, prereleases=True)
                
            ret = [item for item in ret if self.node_dict[item]['version'] in all_req]
            ret = self._sort_versions(ret)

        return ret
    

    # Our heuristic algorithm
    def _heuristic_method(self, subgraph, node_id, father_id=None):
        temp_subgraph = subgraph.copy_graph()

        # save to temp_subgraph
        if node_id not in temp_subgraph.degree_table:
            temp_subgraph.degree_table[node_id] = set()
            temp_subgraph.in_table[node_id] = set()
        if father_id is not None:
            temp_subgraph.degree_table[father_id].add(node_id)
            temp_subgraph.in_table[node_id].add(father_id)

        if self.is_conjunction[node_id]:
            # root or version
            for child in self.sorted_degree_table[node_id]:
                if not self._heuristic_method(temp_subgraph, child, node_id):
                    # Maintain the original state
                    return False
            
            subgraph.set_graph(temp_subgraph)
            return True
        else:
            # module or package
            all_children = None
            # label_children = None
            if self.node_type[node_id] == MODULE_TYPE:
                all_children = self.sorted_degree_table[node_id]
            elif len(self.degree_table[node_id]) == 0:
                # unknown package
                subgraph.set_graph(temp_subgraph)
                return True
            else:
                # all_children = self.sorted_degree_table[node_id]
                # delete all fail versions
                all_children = [item for item in self.sorted_degree_table[node_id] if self.node_dict[item]['install_status'] != 'Fail']
                # label_children = [self.node_dict[item] for item in self.sorted_degree_table[node_id]]

            optional_children = self._get_optional_children_id(all_children, temp_subgraph, node_id)
            if len(optional_children) > 0:
                current_child = None
                for child in self.degree_table[node_id]:
                    if child in temp_subgraph.degree_table and len(temp_subgraph.in_table[child]) > 0:
                        current_child = child
                        break
                
                if current_child is not None:
                    if self.node_type[node_id] == MODULE_TYPE:
                        # virtual module node: move the current_child to first index
                        optional_children.remove(current_child)
                        optional_children.insert(0, current_child)
                    elif current_child in optional_children:
                        # package node: keep the version
                        if current_child not in temp_subgraph.degree_table[node_id]:
                            temp_subgraph.degree_table[node_id].add(current_child)
                            temp_subgraph.in_table[current_child].add(node_id)
                        subgraph.set_graph(temp_subgraph)
                        return True
                    else:
                        # package node: delete the current version
                        temp_subgraph.degree_table[node_id].remove(current_child)
                        temp_subgraph.in_table[current_child].remove(node_id)
                        check_list = [current_child]
                        while len(check_list) > 0:
                            record_list = []
                            for item in check_list:
                                if len(temp_subgraph.in_table[item]) == 0:
                                    for del_child in list(temp_subgraph.degree_table[item]):
                                        temp_subgraph.degree_table[item].remove(del_child)
                                        temp_subgraph.in_table[del_child].remove(item)
                                        record_list.append(del_child)
                                else:
                                    if not self._heuristic_method(temp_subgraph, item):
                                        print('Unexpected fail during deletion!')
                                        print('Suspect result...')
                            
                            check_list = record_list

                index = 0
                child = None
                while index < len(optional_children):
                    child = optional_children[index]
                    if self._heuristic_method(temp_subgraph, child, node_id):
                        subgraph.set_graph(temp_subgraph)
                        return True
                    else:
                        req = self.degree_table[node_id][child]
                        index += 1
                        while index < len(optional_children):
                            child = optional_children[index]
                            if self.degree_table[node_id][child] == req:
                                # skip the versions having the same requirements
                                index += 1
                            else:
                                break
            
            
            # print the conflict package
            # print('Conflict in our heuristic algorithm : ')
            # print('Node type: {}, name: {}'.format(self.node_type[node_id], self._get_node_name(node_id)))
            # print(all_children)
            # print(optional_children)
            # print(label_children)

            for nid in temp_subgraph.in_table[node_id]:
                req = self.degree_table[nid][node_id]
                if isinstance(req, set):
                    versions = self._sort_versions(req)
                    req = [self._get_node_name(item) for item in versions]
                
                parent_node = ''
                if self.node_type[nid] == VERSION_TYPE:
                    parent_node = self._get_node_name(list(temp_subgraph.in_table[nid])[0])
                # print('- {} {}: {}'.format(parent_node, self._get_node_name(nid), req))
            
            return False
    

    def _sat_solver(self):
        # reload SAT solver
        solver = pycryptosat.Solver()

        var_list = list(self.node_dict)
        has_visit = {item: False for item in var_list}
        var_list.insert(0, None)
        cnf_clauses = [[var_list.index(-1)]]
        self._get_cnf_clauses(has_visit, var_list, cnf_clauses, -1)

        # CryptoMiniSat SAT solver
        for clause in cnf_clauses:
            solver.add_clause(clause)

        sat, solution = solver.solve()
        if not sat:
            # unsatisfiable
            return None

        sat_graph = subGraph({}, {})
        keep_nodes = [var_list[index] for index in range(1, len(solution)) if solution[index]]
        for nid in keep_nodes:
            # print('{}:{}'.format(nid, self._get_node_name(nid)))
            # all nodes
            sat_graph.degree_table[nid] = set()
            sat_graph.in_table[nid] = set()

        for nid, children in self.degree_table.items():
            if nid in keep_nodes:
                for child in children:
                    if child in keep_nodes:
                        sat_graph.degree_table[nid].add(child)
                        sat_graph.in_table[child].add(nid)
        
        # print(sat_graph.degree_table)
        
        while True:
            has_delete = False
            for nid, in_set in list(sat_graph.in_table.items()):
                if len(in_set) == 0 and nid != -1:
                    # delete redundant nodes
                    has_delete = True
                    for child in sat_graph.degree_table[nid]:
                        sat_graph.in_table[child].remove(nid)
                    sat_graph.degree_table.pop(nid)
                    sat_graph.in_table.pop(nid)
            
            if not has_delete:
                break

        return sat_graph


    def _get_cnf_clauses(self, has_visit, var_list, clauses, node):
        if has_visit[node]:
            return

        has_visit[node] = True
        var_node = var_list.index(node)
        if self.is_conjunction[node]:
            for nid, req in self.degree_table[node].items():
                # (not x) or y
                clauses.append([-var_node, var_list.index(nid)])
                if self.node_type[nid] == PACKAGE_TYPE:
                    # Version node -> Package node
                    forbidden_child = [item for item in self.degree_table[nid] if self.node_dict[item]['version'] not in SpecifierSet(req, prereleases=True)]
                    for child in forbidden_child:
                        # (not x) or (not y)
                        clauses.append([-var_node, -var_list.index(child)])

        elif len(self.degree_table[node]) > 0:
            # (not x) or x1 or ...
            child_index = [var_list.index(item) for item in self.degree_table[node]]
            temp = [-var_node]
            temp.extend(child_index)
            clauses.append(temp)

            if self.node_type[node] == PACKAGE_TYPE:
                # known package node
                # remove the versions that fails to install
                for nid in self.degree_table[node]:
                    if self.node_dict[nid]['install_status'] == 'Fail':
                        clauses.append([-var_list.index(nid)])
                
                # only one version for a package
                for comb in itertools.combinations(child_index, 2):
                    clauses.append([-comb[0], -comb[1]])
            else:
                # virtual module node
                optional_child = []
                # (not x) or x1 or ...
                for nid in self.degree_table[node]:
                    req = self.degree_table[node][nid]
                    if isinstance(req, set):
                        package_index = var_list.index(nid)
                        index_list = [var_list.index(item) for item in req]
                        # bind candidate versions with candidate packages
                        for version_index in index_list:
                            clauses.append([-version_index, package_index])
                        optional_child.extend(index_list)
                
                if len(optional_child) > 0:
                    # at least one candidate version for a module
                    optional_child.extend([-var_node])
                    clauses.append(optional_child)

        # DFS
        for nid in self.degree_table[node]:
            self._get_cnf_clauses(has_visit, var_list, clauses, nid)
    

    def infer_install_pairs(self):
        has_solution = 1
        install_pairs = None

        # generate subgraph
        subgraph = subGraph({}, {})
        print('Using our heuristic algorithm ...')
        if self._heuristic_method(subgraph, -1):
            # our algorithm
            subgraph.clear_graph()
            pv_graph = self._get_install_graph(subgraph)
        else:
            print('Our method fails. Turn to SAT solver.')
            has_solution = 0
            sat_graph = self._sat_solver()
            if sat_graph is not None:
                pv_graph = self._get_install_graph(sat_graph)
            else:
                print('SAT solver fails. There is no compatible runtime environment.')
                has_solution = -1
                # Best package-version in sorted_degree_table
                subgraph = subGraph({}, {})
                for nid, out_list in self.sorted_degree_table.items():
                    if self.node_type[nid] == MODULE_TYPE:
                    # if isinstance(nid, str) and nid != 'virtual root':
                        # one package
                        pid = out_list[0]
                        if pid not in subgraph.degree_table:
                            subgraph.degree_table[pid] = set()
                            subgraph.in_table[pid] = set()

                        if len(self.degree_table[pid]) == 0:
                            continue

                        # candidate versions
                        req = self.degree_table[nid][pid]
                        # best version 
                        vid = self.sorted_degree_table[pid][0]
                        if isinstance(req, set):
                            for item in self.sorted_degree_table[pid]:
                                if item in req:
                                    vid = item
                                    break

                        if vid not in subgraph.degree_table:
                            subgraph.degree_table[vid] = set()
                            subgraph.in_table[vid] = set()
                        subgraph.degree_table[pid].add(vid)
                        subgraph.in_table[vid].add(pid)                
                
                pv_graph = self._get_install_graph(subgraph)

        # print('Topo sort for installation order.')
        if not pv_graph.topo_sort():
            print("Warning: Exist a circle for topology order!")
            
        install_pairs = pv_graph.install_pair[:]

        return install_pairs, has_solution


class QueryApplication(object):
    def __init__(self):
        self.parser = PythonParser()
        py2_driver = GraphDatabase.driver("bolt://localhost:7687", auth=('neo4j', 'neo4j'))
        py3_driver = GraphDatabase.driver("bolt://localhost:7697", auth=('neo4j', 'neo4j'))
        self.neo4j_driver = {'Python2':py2_driver, 'Python3':py3_driver}
    
    
    @staticmethod
    def _get_module_info_by_name(tx, module_name):
        result = tx.run("MATCH (m:Module {name:$module_name}) "
                        "RETURN m;", module_name=module_name)
        ret = []
        for record in result:
            ret.append((record[0].id, record[0]['import_status']))
        return ret
    
    @staticmethod
    def _get_submodules_by_module(tx, module_name, max_hop, query_modules):
        result = tx.run("MATCH (m:Module {name:$module_name}) "
                        "CALL apoc.neighbors.tohop(m, \"HAS_MODULE>\", $max_hop) "
                        "YIELD node "
                        "RETURN id(m), node;", module_name=module_name, max_hop=max_hop)

        for record in result:
            if record[1]['import_status'] == 'True':
                query_modules[record[0]].append(record[1]['name'])

    
    @staticmethod
    def _get_attributes_by_module_list(tx, module_id_list, submodule_list, ret):
        result = tx.run("MATCH (m:Module)-[:HAS_MODULE*0..]->(s:Module)-[:HAS_ATTRIBUTE]->(a:Attribute) "
                        "WHERE id(m) in $module_id_list AND s.name in $submodule_list "
                        "RETURN id(m), s.name, a.name", module_id_list=module_id_list, submodule_list=submodule_list)
        
        for record in result:
            ret[record[0]].append('{}.{}'.format(record[1], record[2]))
    
    @staticmethod
    def _get_packages_and_versions_by_module_list(tx, module_id_list):
        result = tx.run("MATCH (p:Package)-[:HAS_VERSION]->(v:Version)-[:HAS_MODULE]->(m:Module) "
                        "WHERE id(m) in $module_id_list "
                        "RETURN p.name,id(v);", module_id_list=module_id_list)
        
        ret = {}    # {package: version_id_set}
        for record in result:
            p = record[0]
            vid = record[1]
            if p not in ret:
                ret[p] = set()
            ret[p].add(vid)
        
        return ret
    
    @staticmethod
    def _get_require_subgraph(tx, package_list):
        result = tx.run("WITH $package_list AS package_list "
                        "MATCH (startNode:Package) WHERE startNode.name in package_list "
                        "WITH startNode "
                        "CALL apoc.path.subgraphAll(startNode, { "
                            "relationshipFilter:\"REQUIRES>|HAS_VERSION>\" "
                        "}) "
                        "YIELD nodes, relationships "
                        "RETURN nodes, relationships", package_list=package_list).values()

        return result

    
    def _calculate_match_degree(self, tree_set, name_set):
        if len(tree_set) == 0 or len(name_set) == 0:
            return 0.0
        
        ret = 0.0
        for name in name_set:
            if name in tree_set:
                ret += 1
            else:
                split_info = name.split('.')
                length = len(split_info)
                prefix_name = name
                i = 1
                while i < length:
                    prefix_name = prefix_name[:-(len(split_info[-i])+1)]
                    if prefix_name in tree_set:
                        break
                    i += 1
            
                ret += 1 - i/length
    
        return ret


    def infer_CRE(self, snippet_path, res_dir):
        ret = {'python':None, 'install_pairs':None, 'parse':0, 'match':0, 'solving':0, 'has_solution':1}
        print('Start to infer compatible runtime environment for {} ...'.format(snippet_path))

        stime = time.time()
        parse_results = self.parser.parse_pyfile(snippet_path)
        ret['parse'] = round(time.time() - stime, 2)

        python_version = []
        if parse_results['Python3'] is not None:
            if parse_results['Python2'] is not None:
                py2_third_modules = len(parse_results['Python2']['imports'])
                py3_third_modules = len(parse_results['Python3']['imports'])
                if py2_third_modules < py3_third_modules:
                    python_version.append('Python2')
                elif py2_third_modules == py3_third_modules:
                    python_version.append('Python2')
                    python_version.append('Python3')
                else:
                    python_version.append('Python3')
            else:
                python_version.append('Python3')
        elif parse_results['Python2'] is not None:
            python_version.append('Python2')
        
        if len(python_version) == 0:
            print('{} can not be parsed.'.format(snippet_path))
            return ret
        
        print('Optional Python version: {}'.format(python_version))
        py_info = {}
        for py_version in python_version:
            print('--------------------------')
            print('Inference in {} :'.format(py_version))
            py_info[py_version] = {'candidates':{}, 'module_score':0, 'attr_score':0}

            if len(parse_results[py_version]['imports']) == 0:
                print('No third modules.')
                continue
            
            driver = self.neo4j_driver[py_version]
            
            # code -> forest
            forest = {}
            possible_modules = parse_results[py_version]['imports'] + parse_results[py_version]['resources']
            for item in possible_modules:
                split_item = item.split('.')
                top_module = split_item[0]
                if top_module not in forest:
                    forest[top_module] = {'modules':[], 'attrs':[], 'max_hop':0}
                forest[top_module]['modules'].append(item)
                depth = len(split_item) - 1
                if depth > forest[top_module]['max_hop']:
                    forest[top_module]['max_hop'] = depth
            
            possible_attrs = parse_results[py_version]['attrs'] + parse_results[py_version]['resources']
            for item in possible_attrs:
                split_item = item.split('.')
                top_module = split_item[0]
                if top_module not in forest:
                    print('Unexpected error parse result for attribute \"{}\"'.format(item))
                else:
                    forest[top_module]['attrs'].append(item)
                    depth = len(split_item) - 1
                    if depth > forest[top_module]['max_hop']:
                        forest[top_module]['max_hop'] = depth
            
            # Query KG
            stime = time.time()

            candidate_libraries = {}   # {top_module: {package_id: version_id_set}}
            for top_module, parse_info in forest.items():
                print('--- Query module \"{}\" in KG'.format(top_module))
                # query top module
                with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
                    query_top_modules = session.read_transaction(self._get_module_info_by_name, top_module)
                
                if len(query_top_modules) == 0:
                    print('There is not module \"{}\" in KG'.format(top_module))
                    homonymic_package = canonicalize_name(top_module)
                    print('Try to install package \"{}\"'.format(homonymic_package))
                    candidate_libraries[top_module] = {canonicalize_name(homonymic_package): set()}
                    continue

                # handle ImportError
                # query modules
                query_modules = {}
                for item in query_top_modules:
                    if item[1] == 'True':
                        query_modules[item[0]] = [top_module]
                    else:
                        query_modules[item[0]] = []

                with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
                    session.read_transaction(self._get_submodules_by_module, top_module, parse_info['max_hop'], query_modules)
                
                # transform list to set
                for module_id in query_modules:
                    query_modules[module_id] = set(query_modules[module_id])

                # {module_id: score}
                score_dict = {}
                max_query = 0
                for module_id, submodule_set in query_modules.items():
                    score = self._calculate_match_degree(submodule_set, parse_info['modules'])
                    score_dict[module_id] = score
                    if score > max_query:
                        max_query = score
                
                if max_query > 0:
                    py_info[py_version]['module_score'] += max_query / len(parse_info['modules'])

                # handle attributes
                query_attrs = {}
                need_query_modules = set()
                for module_id, score in score_dict.items():
                    if score == max_query:
                        query_set = set()
                        for attr in possible_attrs:
                            split_attr = attr.split('.')
                            prefix_attr = attr
                            i = 1
                            while i < len(split_attr):
                                prefix_attr = prefix_attr[:-(len(split_attr[-i])+1)]
                                if prefix_attr in query_modules[module_id]:
                                    break
                                i += 1
                            query_set.add(prefix_attr)
                        query_attrs[module_id] = list(query_set)
                        need_query_modules |= query_set
                
                if len(query_attrs) > 0 and len(need_query_modules) > 0:
                    module_id_list = list(query_attrs)
                    with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
                        session.read_transaction(self._get_attributes_by_module_list, module_id_list, list(need_query_modules), query_attrs)
                
                # transform list to set
                for module_id in query_attrs:
                    query_attrs[module_id] = set(query_attrs[module_id])

                score_dict = {}
                max_query = 0

                # for module_id, attr_set in candidate_attr_dict.items():
                for module_id, attr_set in query_attrs.items():
                    score = self._calculate_match_degree(attr_set, parse_info['attrs'])
                    score_dict[module_id] = score
                    if score > max_query:
                        max_query = score
                
                if max_query > 0:
                    py_info[py_version]['attr_score'] += max_query / len(parse_info['attrs'])
                
                best_module_list = [key for key,value in score_dict.items() if value==max_query]
                with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
                    trans_res = session.read_transaction(self._get_packages_and_versions_by_module_list, best_module_list)                
                candidate_libraries[top_module] = trans_res

                print('Candidate packages for top module \"{}\": {}'.format(top_module, list(trans_res)))
            
            ret['match'] += round(time.time()-stime, 2)
            print('matching degree of modules: {}\nmatching degree of attrs: {}'.format(py_info[py_version]['module_score'], py_info[py_version]['attr_score']))
            py_info[py_version]['candidates'] = candidate_libraries

        sorted_py = sorted(py_info, key=lambda x:py_info[x]['module_score'], reverse=True)
        max_value = py_info[sorted_py[0]]['module_score']
        sorted_py = [item for item in sorted_py if py_info[item]['module_score']==max_value]
        sorted_py = sorted(sorted_py, key=lambda x:py_info[x]['attr_score'], reverse=True)
        max_value = py_info[sorted_py[0]]['attr_score']
        sorted_py = [item for item in sorted_py if py_info[item]['attr_score']==max_value]

        if len(sorted_py) == 1:
            py_version = sorted_py[0]
        elif len(sorted_py) > 1:
            py_version = 'Python3'
        else:
            print('Unexpected error when inferring Python vesion.')
            return ret
        
        if py_version == 'Python3':
            ret['python'] = '3.8.11'
        else:
            ret['python'] = '2.7.18'
        print('Select {}.'.format(py_version))
        
        # Query requireGraph and dependency solving
        print('----- Dependency solving ...')
        packages_set = set()
        for _, item in py_info[py_version]['candidates'].items():
            packages_set.update(list(item))
        
        if len(packages_set) > 0:
            stime = time.time()

            driver = self.neo4j_driver[py_version]
            print('Search dependencies for packages: {}'.format(','.join(packages_set)))
            with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
                requires_info = session.read_transaction(self._get_require_subgraph, list(packages_set))
                
            require_graph = RequireGraph(py_info[py_version]['candidates'], requires_info)
            # require_graph.print_graph()
            install_pairs, has_solution = require_graph.infer_install_pairs()

            ret['install_pairs'] = install_pairs
            ret['has_solution'] = has_solution
            ret['solving'] = round(time.time()-stime, 2)
        else:
            ret['install_pairs'] = []
        
        requirement_path = os.path.join(res_dir, 'requirements.txt')
        dockerfile_path = os.path.join(res_dir, 'Dockerfile')
        self._generate_requirement(requirement_path, ret['install_pairs'])
        self._generate_dockerfile(dockerfile_path, snippet_path, ret['python'])
        return ret
    

    def _generate_requirement(self, file_path, pv_pairs):
        with open(file_path, 'w') as f:
            for item in pv_pairs:
                if item[1] is None:
                    f.write('{}\n'.format(item[0]))
                else:
                    f.write('{}=={}\n'.format(item[0], item[1]))
    

    def _generate_dockerfile(self, dockerfile_path, snippet_path, python_version):
        if python_version is not None:
            with open(dockerfile_path, 'w') as f:
                f.write('FROM python:{}\n\n'.format(python_version))
                f.write('RUN pip install --no-cache-dir --upgrade pip\n')
                f.write('COPY requirements.txt /\n')
                f.write('RUN pip install -r /requirements.txt\n\n')
                f.write('COPY {} /snippets/snippet.py\n'.format(snippet_path))
                f.write('CMD python /snippets/snippet.py')

    
    def close(self):
        self.parser.close()
        for driver in self.neo4j_driver.values():
            driver.close()


'''
def infer_dataset():
    gists_dir = os.path.abspath(sys.argv[1])
    results_dir = os.path.abspath(sys.argv[2])

    if not os.path.isdir(results_dir):
        os.mkdir(results_dir)

    time_dict = {}
    time_file = os.path.join(results_dir, 'time.txt')

    count = 0
    querier = QueryApplication()
    for child_dir in sorted(os.listdir(gists_dir)):
        count += 1

        res_dir = os.path.join(results_dir, child_dir)
        if not os.path.isdir(res_dir):
            os.mkdir(res_dir)
        else:
            continue
        
        print('{}:{}'.format(count, child_dir))
        
        snippet_path = os.path.join(os.path.join(gists_dir, child_dir), 'snippet.py')
        req_path = os.path.join(res_dir, 'requirements.txt')

        stime = time.time()
        infer_result = querier.infer_CRE(snippet_path, req_path)
        with open(os.path.join(res_dir, 'result.json'), 'w') as f:
            json.dump(infer_result, f)
        
        time_dict[child_dir] = format(time.time() - stime, '.2f')
        with open(time_file, 'a') as f:
            f.write('{} {}\n'.format(child_dir, time_dict[child_dir]))


    json_file = os.path.join(results_dir, 'time.json')
    with open(json_file, 'w') as f:
        json.dump(time_dict, f)

    querier.close()
'''


def main():
    snippet_path = os.path.abspath(sys.argv[1])
    res_dir = os.path.abspath(sys.argv[2])

    querier = QueryApplication()
    infer_result = querier.infer_CRE(snippet_path, res_dir)

    querier.close()


if __name__ == '__main__':
    main()
