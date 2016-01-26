#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(readlink -f $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

cat - <<-EOF >> $INSTALLDIR/devstack/localrc
RECLONE=True
git_clone https://github.com/dims/devstack-plugin-docker /opt/stack/docker-service master
RECLONE=False
enable_plugin docker-service https://github.com/dims/devstack-plugin-docker
EOF

