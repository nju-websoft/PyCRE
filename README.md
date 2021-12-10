# PyCRE
Conflict-aware Inference of Python Compatible Runtime Environments with Domain Knowledge Graph, ICSE 2022

## Dependencies

This project is developed using Python 3.6.9 on Ubuntu 18.04 LTS.

| Name           | Version |
| -------------- | ------- |
| Docker         | 20.10.8 |
| Docker Compose | 1.23.2  |

## Python Package Knowledge Graph
We have opened our knowledge graphs in [releases](https://github.com/nju-websoft/PyCRE/releases). If you need to create a new knowledge graph, follow the instructions below:

First, you need to install Neo4j 4.1.1 and its required Java version (Java SE 11).

Install extra Python dependencies: 

```
pip install -r build_KG/requirements.txt
```

Automatically acquire knowledge and build KG for specific Python packages: 

```
python build_KG/run.py <packages_file> <neo4j_HOME> <Python_version>
```

Load data from CSV files into an unused Neo4j database and dump the database into a single-file archive:

```
./build_KG/data/Pythonxxx/csv-data/run.sh

NEO4J_HOME/bin/neo4j-admin dump --database=neo4j --to=neo4j.dump
```

## Inference

Move the dump files to the specific folder:

```
mv py2.dump py3.dump docker_env/neo4j
```

Build the docker images and start the deamon service:

```
cd docker_env

./build_images.sh

docker-compose up --detach
```

Install extra Python dependencies:

```
pip install -r bin/requirements.txt
```

Compile [CryptoMiniSat SAT solver](https://github.com/msoos/cryptominisat).

Now, you can use PyCRE to infer a compatible runtime environment to a Python code:

```
python bin/run.py <snippet_path> <dependencies_dir>
```
