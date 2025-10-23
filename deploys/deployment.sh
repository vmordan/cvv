#!/bin/bash
#
# CVV is a continuous verification visualizer.
# Copyright (c) 2019-2023 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

#!/bin/bash

DEFAULT_DB_NAME="$1"
ADMIN_USER="${2:-admin}"
ADMIN_PASS="${3:-admin}"
CV_DIR="$(pwd)"

if [ -z "$DEFAULT_DB_NAME" ]; then
	    echo "Usage: $0 <database name> [<user> <password>]"
	        exit 1
fi

set -e  # stop on error
set -o pipefail

echo "Creating database: $DEFAULT_DB_NAME"

# Ensure we can edit PostgreSQL config and restart the service
PG_HBA_PATH=$(ls /etc/postgresql/*/main/pg_hba.conf | head -n 1)
if [ -z "$PG_HBA_PATH" ]; then
	    echo "PostgreSQL pg_hba.conf not found!"
	        exit 1
fi

# Update pg_hba.conf to "trust" for local connections
sed -i 's/^local .*/local   all             all                                     trust/' "$PG_HBA_PATH"
service postgresql restart || { echo "Cannot restart postgresql"; exit 1; }

# Drop DB if exists
DB_EXISTS=$(psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DEFAULT_DB_NAME}'")
if [ "$DB_EXISTS" = "1" ]; then
	    echo "Dropping existing database: $DEFAULT_DB_NAME"
	        dropdb -U postgres "$DEFAULT_DB_NAME"
fi

# Create DB
createdb -U postgres -T template0 -E UTF8 -O postgres "$DEFAULT_DB_NAME" || { echo "Cannot create new database"; exit 1; }

echo "Setting up CV web-interface"

cat > "${CV_DIR}/web/web/db.json" <<EOF
{
    "ENGINE": "django.db.backends.postgresql_psycopg2",
    "NAME": "${DEFAULT_DB_NAME}",
    "USER": "postgres"
}
EOF

cat > "${CV_DIR}/web/web/settings.py" <<EOF
from web.development import *
PERFORM_AUTO_SAVE = False
EOF

python3 "${CV_DIR}/web/manage.py" compilemessages || { echo "Cannot compile messages"; exit 1; }
python3 "${CV_DIR}/web/manage.py" makemigrations jobs marks reports service tools users || { echo "Cannot create migrations"; exit 1; }
python3 "${CV_DIR}/web/manage.py" migrate || { echo "Cannot update database"; exit 1; }

# Create superuser if not exists
python3 "${CV_DIR}/web/manage.py" shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username="${ADMIN_USER}").exists():
    User.objects.create_superuser("${ADMIN_USER}", "", "${ADMIN_PASS}")
EOF

# Extend user
python3 "${CV_DIR}/web/manage.py" shell <<EOF
from django.contrib.auth.models import User
from web.populate import Population, extend_user
user = User.objects.first()
extend_user(user, 2)
Population(user=user)
EOF

echo "Launch web interface using:"
echo "./start.sh --host <host> --port <port> &"
