#!/bin/bash
set -xe

env

NOVADOCKERDIR=$(realpath $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

# Allow the registry container to access keystone and glance
sudo iptables -I INPUT -p tcp -m tcp --src 172.17.0.0/16 --dport 35357 -j ACCEPT
sudo iptables -I INPUT -p tcp -m tcp --src 172.17.0.0/16 --dport 9292 -j ACCEPT

cp $NOVADOCKERDIR/contrib/devstack/extras.d/70-docker.sh $INSTALLDIR/devstack/extras.d/
cp $NOVADOCKERDIR/contrib/devstack/lib/nova_plugins/hypervisor-docker $INSTALLDIR/devstack/lib/nova_plugins/

locate tempest.conf
# Turn off tempest test suites
cat - <<-EOF >> $INSTALLDIR/devstack/tempest/etc/tempest.conf
# The following settings have been turned off for nova-docker
swift=False
ceilometer=False
resize=False
suspend=False
rescue=False
EOF

HOST_IP=$(ip addr | grep -Eo "inet [0-9\.]+" | grep -v 127.0.0.1 | head -n 1 | cut -d " " -f 2)
cat - <<-EOF >> $INSTALLDIR/devstack/localrc
export VIRT_DRIVER=docker
export HOST_IP=$HOST_IP
export KEYSTONE_ADMIN_BIND_HOST=0.0.0.0
export DOCKER_REGISTRY_IMAGE=registry
export DEFAULT_IMAGE_NAME=cirros
export IMAGE_URLS=" "
EOF

