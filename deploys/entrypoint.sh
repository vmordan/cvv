#!/bin/bash
set -e

# Start PostgreSQL
echo "Starting PostgreSQL..."
max=5
for i in $(seq 1 $max); do
	echo "Starting PostgreSQL (attempt $i/$max)..."
	service postgresql restart && break
	echo "Postgres failed to start, retrying..."
	sleep 3
done

# Start CVV Web UI
echo "[CVV] Starting CVV Web Interface..."
cd /cvv
./start.sh --host 0.0.0.0 --port 8989

