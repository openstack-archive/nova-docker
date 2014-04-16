#!/bin/bash
set -xe

SCRIPTDIR=$(realpath $(dirname $0))

export INSTALLDIR=$BASE/new
bash -xe $SCRIPTDIR/prepare_devstack.sh

export DEVSTACK_GATE_VIRT_DRIVER=docker
export KEEP_LOCALRC=1


# The registry container needs the service endpoints to be the real IP's so it can talk to keystone/glance
# devstack-gate is currently hardcoding it to 127.0.0.1
HOST_IP=$(ip addr | grep -Eo "inet [0-9\.]+" | grep -v 127.0.0.1 | head -n 1 | cut -d " " -f 2)
sed -i -e "s/SERVICE_HOST=127.0.0.1/SERVICE_HOST=$HOST_IP/g" $INSTALLDIR/devstack-gate/devstack-vm-gate.sh

$INSTALLDIR/devstack-gate/devstack-vm-gate.sh
