Continuous Verification Visualizer (CVV)
========================================

Continuous Verification Visualizer (CVV) is a web-interface for visualization of 
continuous verification results.

Requirements
------------
1. Ubuntu 16.04-22.04
2. Additional tools:
```shell
sudo apt install python3-dev postgresql python3-pip libpq-dev gettext
```
3. Python modules:
```shell
sudo pip3 install --upgrade setuptools
sudo pip3 install --upgrade pip
sudo pip3 install requests ujson graphviz django psycopg2 pluggy py attrs six more-itertools ply pytest atomicwrites pycparser psycopg2 sympy pytz
```

Deployment
----------

1. Execute basic script, which creates data base and default user (login=admin, password=admin):
```shell
deploys/deployment.sh <database name>
```

2. Start CV server with command:
```shell
./start.sh --host <host> --port <port>
```
or
```shell
nohup ./start.sh --host <host> --port <port> &
```
as a background process.

3. Set up user accounts via "Admin tools" (create additional users, change default passwords, etc.).
4. Create reports tree structure if needed via copying and editing root report.
5. Upload required reports.
6. Stop background server with command:
```shell
./stop.sh
```
