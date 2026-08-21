#!/bin/bash
# `wait -n` below is a bashism (dash, Debian's default /bin/sh, doesn't support
# it) -- hence bash explicitly, not sh.
# Runs all three production schedulers (see schedulers/restart.sh for the
# equivalent nohup-based setup used outside Docker) as foreground children of
# PID 1, so `docker stop`/compose's SIGTERM reaches them and so the container
# exits (letting `restart: unless-stopped` bring it back) if any of them dies,
# instead of silently degrading to two-out-of-three schedulers running.
set -e

python schedulers/initial_calculations.py &
python schedulers/updated_calculations.py &
python schedulers/forecast_calculations.py &

wait -n
exit $?
