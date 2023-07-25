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

DEFAULT_DB_NAME=$1
ADMIN_USER=${2:-admin}
ADMIN_PASS=${3:-admin}
CV_DIR=$(pwd)

if [ -z ${DEFAULT_DB_NAME} ];
then
    echo "Usage: $0 <database name> [<user> <password>]"
    exit 1
fi

echo "Create ${DEFAULT_DB_NAME} database"
sudo sed -i '/^local/c\local all all trust' /etc/postgresql/*/main/pg_hba.conf
sudo service postgresql restart || { echo 'Cannot restart postgresql' ; exit 1; }
is_exist_out=$(psql -U postgres -c "SELECT datname FROM pg_catalog.pg_database WHERE datname='${DEFAULT_DB_NAME}'")
if [[ $is_exist_out == *"(1 row)"* ]]; then
  echo "Drop database ${DEFAULT_DB_NAME}"
  dropdb -U postgres ${DEFAULT_DB_NAME}
fi
createdb -U postgres -T template0 -E utf8 -O postgres ${DEFAULT_DB_NAME} || { echo 'Cannot create new database' ; exit 1; }

echo "Set up CV web-interface"
echo $'{\n\t\"ENGINE\": \"django.db.backends.postgresql_psycopg2\",\n\t\"NAME\": \"'${DEFAULT_DB_NAME}$'\",\n\t\"USER\": \"postgres\"\n}' > ${CV_DIR}/web/web/db.json
echo -e 'from web.development import *\nPERFORM_AUTO_SAVE=False' > ${CV_DIR}/web/web/settings.py
python3 ${CV_DIR}/web/manage.py compilemessages || { echo 'Cannot compile messages' ; exit 1; }
python3 ${CV_DIR}/web/manage.py makemigrations jobs marks reports service tools users || { echo 'Cannot create migrations for database' ; exit 1; }
python3 ${CV_DIR}/web/manage.py migrate || { echo 'Cannot update database' ; exit 1; }
echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('${ADMIN_USER}', '', '${ADMIN_PASS}')" | python3 ${CV_DIR}/web/manage.py shell
echo "from django.contrib.auth.models import User; from web.populate import Population, extend_user; user = User.objects.first(); extend_user(user, 2); Population(user=user)" | python3 ${CV_DIR}/web/manage.py shell

echo "Launch web-interface by command: './start.sh --host <host> --port <port> &'"
