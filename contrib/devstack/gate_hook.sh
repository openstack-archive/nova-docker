#!/bin/bash
set -xe

SCRIPTDIR=$(realpath $(dirname $0))

# TODO : This should be removed once PATH contains sbin
#        https://review.openstack.org/#/c/91655/
export PATH=$PATH:/usr/local/sbin:/usr/sbin
sudo useradd -U -s /bin/bash -d /opt/stack/new -m stack || true
sudo useradd -U -s /bin/bash -m tempest || true

export INSTALLDIR=$BASE/new
bash -xe $SCRIPTDIR/prepare_devstack.sh

export DEVSTACK_GATE_VIRT_DRIVER=docker
export KEEP_LOCALRC=1


# The registry container needs the service endpoints to be the real IP's so it can talk to keystone/glance
# devstack-gate is currently hardcoding it to 127.0.0.1
HOST_IP=$(ip addr | grep -Eo "inet [0-9\.]+" | grep -v 127.0.0.1 | head -n 1 | cut -d " " -f 2)
sed -i -e "s/SERVICE_HOST=127.0.0.1/SERVICE_HOST=$HOST_IP/g" $INSTALLDIR/devstack-gate/devstack-vm-gate.sh

#temporary ls to check for config
ls -al /opt/stack/new/devstack/tempest/etc/
export PYTHONUNBUFFERED=true
export DEVSTACK_GATE_TIMEOUT=60
export DEVSTACK_GATE_TEMPEST=1
export DEVSTACK_GATE_TEMPEST_FULL=1
export PROJECTS="stackforge/nova-docker $PROJECTS"

$INSTALLDIR/devstack-gate/devstack-vm-gate.sh
