#!/bin/sh
psql -U postgres -c "ALTER SYSTEM SET log_connections = on;"
psql -U postgres -c "ALTER SYSTEM SET log_hostname = off;"
psql -U postgres -c "SELECT pg_reload_conf();"
