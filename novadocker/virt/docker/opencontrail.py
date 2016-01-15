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

from nova.network import linux_net
from nova import utils

from oslo_log import log as logging

from novadocker.i18n import _


LOG = logging.getLogger(__name__)


class OpenContrailVIFDriver(object):
    def get_ipv4_network(self, vif):
        ipv4_address = '0.0.0.0'
        ipv4_netmask = '0.0.0.0'
        ipv4_gateway = '0.0.0.0'
        if 'subnets' in vif['network']:
            subnets = vif['network']['subnets']
            for subnet in subnets:
                ips = subnet['ips'][0]
                if (ips['version'] == 4):
                    if ips['address'] is not None:
                        ipv4_address = ips['address']
                        ipv4_netmask = subnet['cidr'].split('/')[1]
                        ipv4_gateway = subnet['gateway']['address']
        return (ipv4_address, ipv4_netmask, ipv4_gateway)

    def get_ipv6_network(self, vif):
        ipv6_address = None
        ipv6_netmask = None
        ipv6_gateway = None
        if 'subnets' in vif['network']:
            subnets = vif['network']['subnets']
            for subnet in subnets:
                ips = subnet['ips'][0]
                if (ips['version'] == 6):
                    if ips['address'] is not None:
                        ipv6_address = ips['address']
                        ipv6_netmask = subnet['cidr'].split('/')[1]
                        ipv6_gateway = subnet['gateway']['address']
        return (ipv6_address, ipv6_netmask, ipv6_gateway)

    def get_ifnames(self, vif):
        if_local_name = 'veth%s' % vif['id'][:8]
        if_remote_name = 'ns%s' % vif['id'][:8]
        return (if_local_name, if_remote_name)

    def add_port(self, instance, vif):
        (if_local_name, _) = self.get_ifnames(vif)
        (ipv4_address, _, _) = self.get_ipv4_network(vif)
        (ipv6_address, _, _) = self.get_ipv6_network(vif)
        ptype = 'NovaVMPort'

        cmd_args = ("--oper=add --uuid=%s --instance_uuid=%s --vn_uuid=%s "
                    "--vm_project_uuid=%s --ip_address=%s --ipv6_address=%s"
                    " --vm_name=%s --mac=%s --tap_name=%s --port_type=%s "
                    "--tx_vlan_id=%d --rx_vlan_id=%d" % (
                        vif['id'], instance.uuid, vif['network']['id'],
                        instance.project_id, ipv4_address, ipv6_address,
                        instance.display_name, vif['address'],
                        if_local_name, ptype, -1, -1))

        utils.execute('vrouter-port-control', cmd_args, run_as_root=True)

    def plug(self, instance, vif):
        """Plug into Contrail's network port

        Bind the vif to a Contrail virtual port.
        """
        vif_type = vif['type']

        LOG.debug('Plug vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        (if_local_name, if_remote_name) = self.get_ifnames(vif)

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
        """Plug into Contrail's network port

        Bind the vif to a Contrail virtual port.
        """
        vif_type = vif['type']

        LOG.debug('Attach vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        (if_local_name, if_remote_name) = self.get_ifnames(vif)

        undo_mgr = utils.UndoManager()
        undo_mgr.undo_with(lambda: utils.execute(
            'ip', 'link', 'delete', if_local_name, run_as_root=True))
        try:
            utils.execute('ip', 'link', 'set', if_remote_name, 'netns',
                          container_id, run_as_root=True)

            self.add_port(instance, vif)
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
        except Exception:
            LOG.exception("Failed to attach the network")
            msg = _('Failed to attach the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

        try:
            utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'link',
                          'set', if_remote_name, 'address', vif['address'],
                          run_as_root=True)
            (ipv6_address,
             ipv6_netmask,
             ipv6_gateway) = self.get_ipv6_network(vif)
            if ipv6_address:
                ip = ipv6_address + "/" + ipv6_netmask
                gateway = ipv6_gateway
                utils.execute('ip', 'netns', 'exec', container_id, 'ifconfig',
                              if_remote_name, 'inet6', 'add', ip,
                              run_as_root=True)
                utils.execute('ip', 'netns', 'exec', container_id, 'ip', '-6',
                              'route', 'replace', 'default', 'via', gateway,
                              'dev', if_remote_name, run_as_root=True)
            (ipv4_address,
             ipv4_netmask,
             ipv4_gateway) = self.get_ipv4_network(vif)
            if ipv4_address != '0.0.0.0':
                ip = ipv4_address + "/" + ipv4_netmask
                gateway = ipv4_gateway
                utils.execute('ip', 'netns', 'exec', container_id, 'ifconfig',
                              if_remote_name, ip, run_as_root=True)
                utils.execute('ip', 'netns', 'exec', container_id, 'ip',
                              'route', 'replace', 'default', 'via', gateway,
                              'dev', if_remote_name, run_as_root=True)
            utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'link',
                          'set', if_remote_name, 'up', run_as_root=True)
        except Exception:
            LOG.exception(_("Failed to attach vif"), instance=instance)

    def unplug(self, instance, vif):
        """Unplug Contrail's network port

        Unbind the vif from a Contrail virtual port.
        """
        vif_type = vif['type']
        if_local_name = 'veth%s' % vif['id'][:8]

        LOG.debug('Unplug vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        cmd_args = ("--oper=delete --uuid=%s" % (vif['id']))
        try:
            utils.execute('vrouter-port-control', cmd_args, run_as_root=True)
            if linux_net.device_exists(if_local_name):
                utils.execute('ip', 'link', 'delete', if_local_name,
                              run_as_root=True)
        except Exception:
            LOG.exception(_("Delete port failed"), instance=instance)
