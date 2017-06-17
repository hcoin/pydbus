#!/bin/sh
set -e
set -x
TESTS_DIR=$(dirname "$0")
SRC_DIR=`/bin/readlink -f "$TESTS_DIR/.."`
#eval `dbus-launch --sh-syntax`
export $(dbus-launch)
trap 'kill -TERM $DBUS_SESSION_BUS_PID' EXIT

PYTHON=${1:-python}

PYTHONDIR=/root/pydbus
export PYTHONDIR

"$PYTHON" $TESTS_DIR/context.py
"$PYTHON" $TESTS_DIR/identifier.py
"$PYTHON" $TESTS_DIR/publish.py
"$PYTHON" $TESTS_DIR/publish_properties.py
"$PYTHON" $TESTS_DIR/publish_multiface.py
"$PYTHON"  $SRC_DIR/pydbus/_unittest.py

