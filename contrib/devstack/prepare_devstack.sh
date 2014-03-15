#!/bin/bash
set -xe

NOVADOCKERDIR=$(realpath $(dirname $0)/../..)
BASE=${BASE:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/extras.d/70-docker.sh $BASE/new/devstack/extras.d/
cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $BASE/new/devstack/lib/nova_plugins/

cd $BASE/new/devstack
patch -p0 < $NOVADOCKERDIR/contrib/devstack/stackrc.diff


# The registry container needs the service endpoints to be the real IP's so it can talk to keystone/glance
HOST_IP=$(ip addr | grep -Eo "inet [0-9\.]+" | grep -v 127.0.0.1 | head -n 1 | cut -d " " -f 2)
echo export HOST_IP=$HOST_IP >> $BASE/new/devstack/localrc
echo export KEYSTONE_ADMIN_BIND_HOST=0.0.0.0 >> $BASE/new/devstack/localrc
echo export DOCKER_REGISTRY_IMAGE=samalba/docker-registry >> $BASE/new/devstack/localrc
sed -i -e "s/SERVICE_HOST=127.0.0.1/SERVICE_HOST=$HOST_IP/g" $BASE/new/devstack-gate/devstack-vm-gate.sh
