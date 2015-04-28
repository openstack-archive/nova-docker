# Copyright (C) 2014 Juniper Networks, Inc
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
from contrail_vrouter_api.vrouter_api import ContrailVRouterApi
from nova.i18n import _
from nova.network import linux_net
from nova import utils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class OpenContrailVIFDriver(object):
    def __init__(self):
        self._vrouter_client = ContrailVRouterApi(doconnect=True)

    def plug(self, instance, vif):
        if_local_name = 'veth%s' % vif['id'][:8]
        if_remote_name = 'ns%s' % vif['id'][:8]

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return
        undo_mgr = utils.UndoManager()

        try:
            utils.execute('ip', 'link', 'add', if_local_name, 'type', 'veth',
                          'peer', 'name', if_remote_name, run_as_root=True)
            undo_mgr.undo_with(lambda: utils.execute(
                'ip', 'link', 'delete', if_local_name, run_as_root=True))

            utils.execute('ip', 'link', 'set', if_remote_name, 'address',
                          vif['address'], run_as_root=True)

        except Exception:
            LOG.exception("Failed to configure network")
            msg = _('Failed to setup the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def attach(self, instance, vif, container_id):
        if_local_name = 'veth%s' % vif['id'][:8]
        if_remote_name = 'ns%s' % vif['id'][:8]

        undo_mgr = utils.UndoManager()
        ipv4_address = '0.0.0.0'
        ipv6_address = None
        if 'subnets' in vif['network']:
            subnets = vif['network']['subnets']
            for subnet in subnets:
                ips = subnet['ips'][0]
                if (ips['version'] == 4):
                    if ips['address'] is not None:
                        ipv4_address = ips['address']
                if (ips['version'] == 6):
                    if ips['address'] is not None:
                        ipv6_address = ips['address']
        params = {
            'ip_address': ipv4_address,
            'vn_id': vif['network']['id'],
            'display_name': instance['display_name'],
            'hostname': instance['hostname'],
            'host': instance['host'],
            'vm_project_id': instance['project_id'],
            'port_type': 'NovaVMPort',
            'ip6_address': ipv6_address,
        }

        try:
            utils.execute('ip', 'link', 'set', if_remote_name, 'netns',
                          container_id, run_as_root=True)

            result = self._vrouter_client.add_port(
                instance['uuid'], vif['id'],
                if_local_name, vif['address'], **params)
            if not result:
                # follow the exception path
                raise RuntimeError('add_port returned %s' % str(result))
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
        except Exception:
            LOG.exception("Failed to attach the network")
            msg = _('Failed to attach the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

        # TODO(NetNS): attempt DHCP client; fallback to manual config if the
        # container doesn't have an working dhcpclient
        utils.execute('ip', 'netns', 'exec', container_id, 'dhclient',
                      if_remote_name, run_as_root=True)

    def unplug(self, instance, vif):
        try:
            self._vrouter_client.delete_port(vif['id'])
        except Exception:
            LOG.exception(_("Delete port failed"), instance=instance)

        if_local_name = 'veth%s' % vif['id'][:8]
        utils.execute('ip', 'link', 'delete', if_local_name, run_as_root=True)
