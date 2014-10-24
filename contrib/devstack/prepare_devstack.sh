#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(readlink -f $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVADOCKERDIR/contrib/devstack/extras.d/70-docker.sh $INSTALLDIR/devstack/extras.d/
cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

# We won't need this hack once global requirements is updated in
# this review : https://review.openstack.org/#/c/128746/
if [ -f /usr/local/bin/pip ]; then
    sudo PIP_DOWNLOAD_CACHE=/var/cache/pip http_proxy= https_proxy= no_proxy= /usr/local/bin/pip install docker-py
fi
if [ -f /usr/bin/pip ]; then
    sudo PIP_DOWNLOAD_CACHE=/var/cache/pip http_proxy= https_proxy= no_proxy= /usr/bin/pip install docker-py
fi

cat - <<-EOF >> $INSTALLDIR/devstack/localrc
export VIRT_DRIVER=docker
export DEFAULT_IMAGE_NAME=cirros
export NON_STANDARD_REQS=1
export IMAGE_URLS=" "
EOF

