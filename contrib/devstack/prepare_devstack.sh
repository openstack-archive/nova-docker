#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(readlink -f $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

cat - <<-EOF >> $INSTALLDIR/devstack/localrc
GITDIR['nova-docker']=$DEST/nova-docker
enable_plugin nova-docker https://git.openstack.org/openstack/nova-docker
EOF