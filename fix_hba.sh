#!/bin/sh
HBA=/var/lib/postgresql/data/pg_hba.conf
# Replace the last line (host all all all md5) with trust
grep -v "^host all all all" "$HBA" > /tmp/pg_hba_new.conf
echo "host all all all trust" >> /tmp/pg_hba_new.conf
cp /tmp/pg_hba_new.conf "$HBA"
psql -U postgres -c "SELECT pg_reload_conf();"
echo "Done. New last lines:"
grep "^host all all all" "$HBA"
