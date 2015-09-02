# Copyright 2014 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os

from oslo_concurrency import processutils
from oslo_log import log

from nova import exception
from nova import utils

from novadocker.i18n import _

LOG = log.getLogger(__name__)


def teardown_network(container_id):
    if os.name == 'nt':
        return

    try:
        output, err = utils.execute('ip', '-o', 'netns', 'list')
        for line in output.split('\n'):
            if container_id == line.strip():
                utils.execute('ip', 'netns', 'delete', container_id,
                              run_as_root=True)
                break
    except processutils.ProcessExecutionError:
        LOG.warning(_('Cannot remove network namespace, netns id: %s'),
                    container_id)


def find_fixed_ip(instance, network_info):
    for subnet in network_info['subnets']:
        netmask = subnet['cidr'].split('/')[1]
        for ip in subnet['ips']:
            if ip['type'] == 'fixed' and ip['address']:
                return ip['address'] + "/" + netmask
    raise exception.InstanceDeployFailure(_('Cannot find fixed ip'),
                                          instance_id=instance['uuid'])


def find_gateway(instance, network_info):
    for subnet in network_info['subnets']:
        return subnet['gateway']['address']
    raise exception.InstanceDeployFailure(_('Cannot find gateway'),
                                          instance_id=instance['uuid'])


# NOTE(arosen) - this method should be removed after it's moved into the
# linux_net code in nova.
def get_ovs_interfaceid(vif):
    return vif.get('ovs_interfaceid') or vif['id']
