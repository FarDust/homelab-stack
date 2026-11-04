#!/bin/sh
set -eu

find /lego -type f -exec chgrp 3000 {} + -exec chmod a+r {} +
find /lego -type f -path '/lego/supabase-db.*/privkey.pem' \
  -exec chown 0:102 {} + \
  -exec chmod 0640 {} +
