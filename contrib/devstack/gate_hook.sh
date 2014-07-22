#!/bin/bash
set -xe

SCRIPTDIR=$(readlink -f $(dirname $0))

# TODO : This should be removed once PATH contains sbin
#        https://review.openstack.org/#/c/91655/
export PATH=$PATH:/usr/local/sbin:/usr/sbin
sudo useradd -U -s /bin/bash -d /opt/stack/new -m stack || true
sudo useradd -U -s /bin/bash -m tempest || true

export INSTALLDIR=$BASE/new
bash -xe $SCRIPTDIR/prepare_devstack.sh

export DEVSTACK_GATE_VIRT_DRIVER=docker
export KEEP_LOCALRC=1

export ENABLED_SERVICES+=-tr-api,-tr-cond,-tr-mgr,-trove,-ceilometer-acentral,-ceilometer-acompute,-ceilometer-alarm-evaluator,-ceilometer-alarm-notifier,-ceilometer-anotification,-ceilometer-api,-ceilometer-collector,-s-account,-s-container,-s-object,-s-proxy,-sahara

export DEVSTACK_GATE_TEMPEST_REGEX='^(?!.*?(volume|resize|suspend|swift|rescue|cinder|migrate)).*'

export DEVSTACK_GATE_TEMPEST=1
export DEVSTACK_GATE_TEMPEST_FULL=0

$INSTALLDIR/devstack-gate/devstack-vm-gate.sh
