#!/bin/bash

docker build -t python2:parse -f 'python_parser/Python2Dockerfile' python_parser

docker build -t python3:parse -f 'python_parser/Python3Dockerfile' python_parser

docker build -t python2:neo4j -f 'neo4j/Python2Dockerfile' neo4j

docker build -t python3:neo4j -f 'neo4j/Python3Dockerfile' neo4j