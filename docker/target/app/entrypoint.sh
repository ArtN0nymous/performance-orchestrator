#!/bin/sh
set -eu
mkdir -p /var/run/sshd /shared/maintenance
chmod 777 /shared/maintenance
ssh-keygen -A
/usr/sbin/sshd
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 app:app
