# Copyright (C) 2013 VMware, Inc
# Copyright 2011 OpenStack Foundation
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


from oslo_concurrency import processutils
from oslo_log import log as logging

from nova import exception
from nova.network import linux_net
from nova.network import manager
from nova.network import model as network_model
from nova import utils
from novadocker.i18n import _
from novadocker.virt.docker import network
from oslo_config import cfg
import random

# We need config opts from manager, but pep8 complains, this silences it.
assert manager

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.conf.netconf')
CONF.import_opt('vlan_interface', 'nova.manager')
CONF.import_opt('flat_interface', 'nova.manager')
CONF.import_opt('network_device_mtu', 'nova.objects.network')

LOG = logging.getLogger(__name__)


class DockerGenericVIFDriver(object):

    def plug(self, instance, vif):
        vif_type = vif['type']

        LOG.debug('plug vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        if vif_type == network_model.VIF_TYPE_BRIDGE:
            self.plug_bridge(instance, vif)
        elif vif_type == network_model.VIF_TYPE_OVS:
            if self.ovs_hybrid_required(vif):
                self.plug_ovs_hybrid(instance, vif)
            else:
                self.plug_ovs(instance, vif)
        elif vif_type == network_model.VIF_TYPE_MIDONET:
            self.plug_midonet(instance, vif)
        elif vif_type == network_model.VIF_TYPE_IOVISOR:
            self.plug_iovisor(instance, vif)
        elif vif_type == 'hyperv':
            self.plug_windows(instance, vif)
        else:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)

    def plug_windows(self, instance, vif):
        pass

    def plug_iovisor(self, instance, vif):
        """Plug docker vif into IOvisor

        Creates a port on IOvisor and onboards the interface
        """
        if_local_name = 'tap%s' % vif['id'][:11]
        if_remote_name = 'ns%s' % vif['id'][:11]

        iface_id = vif['id']
        net_id = vif['network']['id']
        tenant_id = instance['project_id']

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return
        undo_mgr = utils.UndoManager()

        try:
            utils.execute('ip', 'link', 'add', 'name', if_local_name, 'type',
                          'veth', 'peer', 'name', if_remote_name,
                          run_as_root=True)
            utils.execute('ifc_ctl', 'gateway', 'add_port', if_local_name,
                          run_as_root=True)
            utils.execute('ifc_ctl', 'gateway', 'ifup', if_local_name,
                          'access_vm',
                          vif['network']['label'] + "_" + iface_id,
                          vif['address'], 'pgtag2=%s' % net_id,
                          'pgtag1=%s' % tenant_id, run_as_root=True)
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)

        except Exception:
            LOG.exception("Failed to configure network on IOvisor")
            msg = _('Failed to setup the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def plug_ovs(self, instance, vif):
        if_local_name = 'tap%s' % vif['id'][:11]
        if_remote_name = 'ns%s' % vif['id'][:11]
        bridge = vif['network']['bridge']

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return
        undo_mgr = utils.UndoManager()

        try:
            utils.execute('ip', 'link', 'add', 'name', if_local_name, 'type',
                          'veth', 'peer', 'name', if_remote_name,
                          run_as_root=True)
            linux_net.create_ovs_vif_port(bridge, if_local_name,
                                          network.get_ovs_interfaceid(vif),
                                          vif['address'],
                                          instance['uuid'])
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
        except Exception:
            LOG.exception("Failed to configure network")
            msg = _('Failed to setup the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def plug_midonet(self, instance, vif):
        """Plug into MidoNet's network port

        This accomplishes binding of the vif to a MidoNet virtual port
        """
        if_local_name = 'tap%s' % vif['id'][:11]
        if_remote_name = 'ns%s' % vif['id'][:11]
        port_id = network.get_ovs_interfaceid(vif)

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return

        undo_mgr = utils.UndoManager()
        try:
            utils.execute('ip', 'link', 'add', 'name', if_local_name, 'type',
                          'veth', 'peer', 'name', if_remote_name,
                          run_as_root=True)
            undo_mgr.undo_with(lambda: utils.execute(
                'ip', 'link', 'delete', if_local_name, run_as_root=True))
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
            utils.execute('mm-ctl', '--bind-port', port_id, if_local_name,
                          run_as_root=True)
        except Exception:
            LOG.exception("Failed to configure network")
            msg = _('Failed to setup the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def plug_ovs_hybrid(self, instance, vif):
        """Plug using hybrid strategy

        Create a per-VIF linux bridge, then link that bridge to the OVS
        integration bridge via a veth device, setting up the other end
        of the veth device just like a normal OVS port.  Then boot the
        VIF on the linux bridge. and connect the tap port to linux bridge
        """

        if_local_name = 'tap%s' % vif['id'][:11]
        if_remote_name = 'ns%s' % vif['id'][:11]
        iface_id = self.get_ovs_interfaceid(vif)
        br_name = self.get_br_name(vif['id'])
        v1_name, v2_name = self.get_veth_pair_names(vif['id'])

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return
        undo_mgr = utils.UndoManager()

        try:
            if not linux_net.device_exists(br_name):
                utils.execute('brctl', 'addbr', br_name, run_as_root=True)
                # Incase of failure undo the Steps
                # Deleting/Undoing the interface will delete all
                # associated resources
                undo_mgr.undo_with(lambda: utils.execute(
                    'brctl', 'delbr', br_name, run_as_root=True))
                # LOG.exception('Throw Test exception with bridgename %s'
                # % br_name)

                utils.execute('brctl', 'setfd', br_name, 0, run_as_root=True)
                utils.execute('brctl', 'stp', br_name, 'off', run_as_root=True)
                utils.execute('tee',
                              ('/sys/class/net/%s/bridge/multicast_snooping' %
                               br_name),
                              process_input='0',
                              run_as_root=True,
                              check_exit_code=[0, 1])

            if not linux_net.device_exists(v2_name):
                linux_net._create_veth_pair(v1_name, v2_name)
                undo_mgr.undo_with(lambda: utils.execute(
                    'ip', 'link', 'delete', v1_name, run_as_root=True))

                utils.execute('ip', 'link', 'set', br_name, 'up',
                              run_as_root=True)
                undo_mgr.undo_with(lambda: utils.execute('ip', 'link', 'set',
                                                         br_name, 'down',
                                                         run_as_root=True))

                # Deleting/Undoing the interface will delete all
                # associated resources (remove from the bridge, its
                # pair, etc...)
                utils.execute('brctl', 'addif', br_name, v1_name,
                              run_as_root=True)

                linux_net.create_ovs_vif_port(self.get_bridge_name(vif),
                                              v2_name,
                                              iface_id, vif['address'],
                                              instance['uuid'])
                undo_mgr.undo_with(
                    lambda: utils.execute('ovs-vsctl', 'del-port',
                                          self.get_bridge_name(vif),
                                          v2_name, run_as_root=True))

            utils.execute('ip', 'link', 'add', 'name', if_local_name, 'type',
                          'veth', 'peer', 'name', if_remote_name,
                          run_as_root=True)
            undo_mgr.undo_with(
                lambda: utils.execute('ip', 'link', 'delete', if_local_name,
                                      run_as_root=True))

            # Deleting/Undoing the interface will delete all
            # associated resources (remove from the bridge, its pair, etc...)
            utils.execute('brctl', 'addif', br_name, if_local_name,
                          run_as_root=True)
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
        except Exception:
            msg = "Failed to configure Network." \
                " Rolling back the network interfaces %s %s %s %s " % (
                    br_name, if_local_name, v1_name, v2_name)
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    # We are creating our own mac's now because the linux bridge interface
    # takes on the lowest mac that is assigned to it.  By using FE range
    # mac's we prevent the interruption and possible loss of networking
    # from changing mac addresses.
    def _fe_random_mac(self):
        mac = [0xfe, 0xed,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(map(lambda x: "%02x" % x, mac))

    def plug_bridge(self, instance, vif):
        if_local_name = 'tap%s' % vif['id'][:11]
        if_remote_name = 'ns%s' % vif['id'][:11]
        bridge = vif['network']['bridge']
        gateway = network.find_gateway(instance, vif['network'])

        net = vif['network']
        if net.get_meta('should_create_vlan', False):
            vlan = net.get_meta('vlan'),
            iface = (CONF.vlan_interface or
                     vif['network'].get_meta('bridge_interface'))
            linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                vlan,
                bridge,
                iface,
                net_attrs=vif,
                mtu=vif.get('mtu'))
            iface = 'vlan%s' % vlan
        else:
            iface = (CONF.flat_interface or
                     vif['network'].get_meta('bridge_interface'))
            LOG.debug('Ensuring bridge for %s - %s' % (iface, bridge))
            linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                bridge,
                iface,
                net_attrs=vif,
                gateway=gateway)

        # Device already exists so return.
        if linux_net.device_exists(if_local_name):
            return
        undo_mgr = utils.UndoManager()

        try:
            utils.execute('ip', 'link', 'add', 'name', if_local_name, 'type',
                          'veth', 'peer', 'name', if_remote_name,
                          run_as_root=True)
            undo_mgr.undo_with(lambda: utils.execute(
                'ip', 'link', 'delete', if_local_name, run_as_root=True))
            # NOTE(samalba): Deleting the interface will delete all
            # associated resources (remove from the bridge, its pair, etc...)
            utils.execute('ip', 'link', 'set', if_local_name, 'address',
                          self._fe_random_mac(), run_as_root=True)
            utils.execute('brctl', 'addif', bridge, if_local_name,
                          run_as_root=True)
            utils.execute('ip', 'link', 'set', if_local_name, 'up',
                          run_as_root=True)
        except Exception:
            LOG.exception("Failed to configure network")
            msg = _('Failed to setup the network, rolling back')
            undo_mgr.rollback_and_reraise(msg=msg, instance=instance)

    def unplug(self, instance, vif):
        vif_type = vif['type']

        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))

        if vif_type == network_model.VIF_TYPE_BRIDGE:
            self.unplug_bridge(instance, vif)
        elif vif_type == network_model.VIF_TYPE_OVS:
            if self.ovs_hybrid_required(vif):
                self.unplug_ovs_hybrid(instance, vif)
            else:
                self.unplug_ovs(instance, vif)
        elif vif_type == network_model.VIF_TYPE_MIDONET:
            self.unplug_midonet(instance, vif)
        elif vif_type == network_model.VIF_TYPE_IOVISOR:
            self.unplug_iovisor(instance, vif)
        elif vif_type == 'hyperv':
            self.unplug_windows(instance, vif)
        else:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)

    def unplug_windows(self, instance, vif):
        pass

    def unplug_iovisor(self, instance, vif):
        """Unplug vif from IOvisor

        Offboard an interface and deletes port from IOvisor
        """
        if_local_name = 'tap%s' % vif['id'][:11]
        iface_id = vif['id']
        try:
            utils.execute('ifc_ctl', 'gateway', 'ifdown',
                          if_local_name, 'access_vm',
                          vif['network']['label'] + "_" + iface_id,
                          vif['address'], run_as_root=True)
            utils.execute('ifc_ctl', 'gateway', 'del_port', if_local_name,
                          run_as_root=True)
            linux_net.delete_net_dev(if_local_name)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_ovs(self, instance, vif):
        """Unplug the VIF by deleting the port from the bridge."""
        try:
            linux_net.delete_ovs_vif_port(vif['network']['bridge'],
                                          vif['devname'])
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_midonet(self, instance, vif):
        """Unplug into MidoNet's network port

        This accomplishes unbinding of the vif from its MidoNet virtual port
        """
        try:
            utils.execute('mm-ctl', '--unbind-port',
                          network.get_ovs_interfaceid(vif), run_as_root=True)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_ovs_hybrid(self, instance, vif):
        """UnPlug using hybrid strategy

        Unhook port from OVS, unhook port from bridge, delete
        bridge, and delete both veth devices.
        """
        try:
            br_name = self.get_br_name(vif['id'])
            v1_name, v2_name = self.get_veth_pair_names(vif['id'])

            if linux_net.device_exists(br_name):
                utils.execute('brctl', 'delif', br_name, v1_name,
                              run_as_root=True)
                utils.execute('ip', 'link', 'set', br_name, 'down',
                              run_as_root=True)
                utils.execute('brctl', 'delbr', br_name,
                              run_as_root=True)

            linux_net.delete_ovs_vif_port(self.get_bridge_name(vif),
                                          v2_name)
        except processutils.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif"), instance=instance)

    def unplug_bridge(self, instance, vif):
        # NOTE(arosen): nothing has to be done in the linuxbridge case
        # as when the veth is deleted it automatically is removed from
        # the bridge.
        pass

    def attach(self, instance, vif, container_id):
        vif_type = vif['type']
        if_remote_name = 'ns%s' % vif['id'][:11]
        gateway = network.find_gateway(instance, vif['network'])
        ip = network.find_fixed_ip(instance, vif['network'])

        LOG.debug('attach vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        try:
            utils.execute('ip', 'link', 'set', if_remote_name, 'netns',
                          container_id, run_as_root=True)
            utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'link',
                          'set', if_remote_name, 'address', vif['address'],
                          run_as_root=True)
            utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'addr',
                          'add', ip, 'dev', if_remote_name, run_as_root=True)
            utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'link',
                          'set', if_remote_name, 'up', run_as_root=True)

            # Setup MTU on if_remote_name is required if it is a non
            # default value
            mtu = CONF.network_device_mtu
            if vif.get('mtu') is not None:
                mtu = vif.get('mtu')
            if mtu is not None:
                utils.execute('ip', 'netns', 'exec', container_id, 'ip',
                              'link', 'set', if_remote_name, 'mtu', mtu,
                              run_as_root=True)

            if gateway is not None:
                utils.execute('ip', 'netns', 'exec', container_id,
                              'ip', 'route', 'replace', 'default', 'via',
                              gateway, 'dev', if_remote_name, run_as_root=True)

            # Disable TSO, for now no config option
            utils.execute('ip', 'netns', 'exec', container_id, 'ethtool',
                          '--offload', if_remote_name, 'tso', 'off',
                          run_as_root=True)

        except Exception:
            LOG.exception("Failed to attach vif")

    def get_bridge_name(self, vif):
        return vif['network']['bridge']

    def get_ovs_interfaceid(self, vif):
        return vif.get('ovs_interfaceid') or vif['id']

    def get_br_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def ovs_hybrid_required(self, vif):
        ovs_hybrid_required = self.get_firewall_required(vif) or \
            self.get_hybrid_plug_enabled(vif)
        return ovs_hybrid_required

    def get_firewall_required(self, vif):
        if vif.get('details'):
            enabled = vif['details'].get('port_filter', False)
            if enabled:
                return False
            if CONF.firewall_driver != "nova.virt.firewall.NoopFirewallDriver":
                return True
        return False

    def get_hybrid_plug_enabled(self, vif):
        if vif.get('details'):
            return vif['details'].get('ovs_hybrid_plug', False)
        return False
