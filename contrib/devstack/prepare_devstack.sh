#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(realpath $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/extras.d/70-docker.sh $INSTALLDIR/devstack/extras.d/
cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

HOST_IP=$(ip addr | grep -Eo "inet [0-9\.]+" | grep -v 127.0.0.1 | head -n 1 | cut -d " " -f 2)
cat - <<-EOF >> $INSTALLDIR/devstack/localrc
export VIRT_DRIVER=docker
export HOST_IP=$HOST_IP
export KEYSTONE_ADMIN_BIND_HOST=0.0.0.0
export DOCKER_REGISTRY_IMAGE=samalba/docker-registry
export DEFAULT_IMAGE_NAME=cirros
export IMAGE_URLS=" "
EOF

