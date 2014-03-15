#!/bin/bash
#
# Script to kick of test against a devstack deployed nova with the docker driver
#

set -xe

NOVADOCKERDIR=$(realpath $(dirname $0)/../..)

cd $BASE/new/devstack

. openrc admin
nova boot --image $(nova image-list | grep cirros | awk '{print $2}') --flavor m1.small test
sleep 10
nova list
nova list | grep ACTIVE
