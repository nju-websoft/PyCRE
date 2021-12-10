#!/usr/bin/env bash

# Exit on failure
set -e

# Create database from backup file
mkdir -p /data/databases/graph.db
neo4j-admin load --force --from=/build-files/database.dump
chown -R neo4j:neo4j /data/

# Start neo4j
/docker-entrypoint.sh neo4j
