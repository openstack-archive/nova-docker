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

export DEVSTACK_GATE_TEMPEST_REGEX='^(?!.*?(boto|volume|resize|suspend|rescue|cinder|migrate|object_storage)).*'

export DEVSTACK_GATE_TEMPEST=1
export DEVSTACK_GATE_TEMPEST_FULL=0
export DEVSTACK_GATE_TROVE=0

source $INSTALLDIR/devstack-gate/functions.sh
source $INSTALLDIR/devstack/functions-common
if is_ubuntu; then
  apt_get update
  install_package --force-yes linux-image-extra-`uname -r`
fi

trap exit_trap EXIT
function exit_trap {
    local r=$?
    if [[ "$r" -eq "0" ]]; then
        echo "All tests run successfully"
    else
        echo "ERROR! some tests failed, please see detailed output"
    fi
    echo "Collecting docker-specific logs"
    bash -x $SCRIPTDIR/copy_logs_hook.sh
}

$INSTALLDIR/devstack-gate/devstack-vm-gate.sh
