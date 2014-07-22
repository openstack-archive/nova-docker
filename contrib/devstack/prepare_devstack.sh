#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(realpath $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/extras.d/70-docker.sh $INSTALLDIR/devstack/extras.d/
cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

cat - <<-EOF >> $INSTALLDIR/devstack/localrc
export VIRT_DRIVER=docker
export DEFAULT_IMAGE_NAME=cirros
export IMAGE_URLS=" "
EOF

