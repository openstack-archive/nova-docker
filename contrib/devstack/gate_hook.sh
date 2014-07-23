#!/bin/bash
set -xe

SCRIPTDIR=$(realpath $(dirname $0))

# TODO : This should be removed once PATH contains sbin
#        https://review.openstack.org/#/c/91655/
export PATH=$PATH:/usr/local/sbin:/usr/sbin
sudo useradd -U -s /bin/bash -d /opt/stack/new -m stack || true
sudo useradd -U -s /bin/bash -m tempest || true

exit 1

# Accept all ssh connections, not just those on the IN_public_allow zone
sudo iptables -I INPUT -p tcp -m tcp --dport 22 -j ACCEPT
sudo systemctl stop firewalld

export INSTALLDIR=$BASE/new
bash -xe $SCRIPTDIR/prepare_devstack.sh

export DEVSTACK_GATE_VIRT_DRIVER=docker
export KEEP_LOCALRC=1

# Turn off tempest test suites
cat <<EOF >> $INSTALLDIR/tempest/etc/tempest.conf.sample
# The following settings have been turned off for nova-docker
[compute-feature-enabled]
resize=False
suspend=False
rescue=False

[service_available]
swift=False
ceilometer=False
cinder=False
EOF

export DEVSTACK_GATE_TEMPEST=0
export DEVSTACK_GATE_TEMPEST_FULL=0

$INSTALLDIR/devstack-gate/devstack-vm-gate.sh
