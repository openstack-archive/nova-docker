# Copyright 2014 IBM Corp.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from nova.network import model as network_model
from nova import test
from nova.virt import firewall
from novadocker.virt.docker import driver


class DockerFirewallDriverTestCase(test.TestCase):

    REQUIRES_LOCKING = True
    gateway_bridge_4 = network_model.IP(address='10.11.12.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    ips_bridge_4 = [network_model.IP(address='101.168.1.9', type='fixed',
                                     version=4)]

    subnet_bridge_4 = network_model.Subnet(cidr='10.11.1.0/24',
                                           dns=[dns_bridge_4],
                                           gateway=gateway_bridge_4,
                                           ips=ips_bridge_4,
                                           routes=None)

    network_bridge = network_model.Network(id='network-id-xxx-yyy-zzz',
                                           bridge='br100',
                                           label=None,
                                           subnets=[subnet_bridge_4],
                                           bridge_interface='eth0')

    vif_bridge = network_model.VIF(id='920be2f4-2b98-411e-890a-69bcabb2a5a0',
                                   address='00:11:22:33:44:55',
                                   network=network_bridge,
                                   type=network_model.VIF_TYPE_BRIDGE)

    def setUp(self):
        super(DockerFirewallDriverTestCase, self).setUp()
        self.driver = driver.DockerDriver(None)

    @mock.patch.object(firewall.NoopFirewallDriver, 'prepare_instance_filter',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'setup_basic_filtering',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'apply_instance_filter',
                       create=True)
    def test_start_firewall(self, mock_aif, mock_sbf, mock_pif):
        fake_inst = 'fake-inst'
        fake_net_info = mock.ANY
        self.driver._start_firewall(fake_inst, fake_net_info)

        mock_aif.assert_called_once_with(fake_inst, fake_net_info)
        mock_sbf.assert_called_once_with(fake_inst, fake_net_info)
        mock_pif.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'unfilter_instance',
                       create=True)
    def test_stop_firewall(self, mock_ui):
        fake_inst = 'fake-inst'
        fake_net_info = mock.ANY
        self.driver._stop_firewall(fake_inst, fake_net_info)
        mock_ui.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'prepare_instance_filter',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'setup_basic_filtering',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'apply_instance_filter',
                       create=True)
    def test_plug_vifs_bridge(self, mock_aif, mock_sbf, mock_pif):
        fake_net_info = [self.vif_bridge]
        with mock.patch('nova.utils.execute'):
            d = driver.DockerDriver(object)
            fake_inst = {'name': 'fake_instance'}
            d.plug_vifs(fake_inst, fake_net_info)
            mock_aif.assert_called_once_with(fake_inst, fake_net_info)
            mock_sbf.assert_called_once_with(fake_inst, fake_net_info)
            mock_pif.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'unfilter_instance',
                       create=True)
    def test_unplug_vifs_ovs(self, mock_ui):
        iface_id = '920be2f4-2b98-411e-890a-69bcabb2a5a0'
        fake_net_info = [
            {'network': {'bridge': 'br-int',
                         'subnets': [{'gateway': {'address': '10.11.12.1'},
                                      'cidr': '10.11.12.0/24',
                                      'ips': [{'address': '10.11.12.3',
                                               'type': 'fixed', 'version': 4}]
                                      }]},
             'devname': 'tap920be2f4-2b',
             'address': '00:11:22:33:44:55',
             'id': iface_id,
             'type': network_model.VIF_TYPE_OVS}]
        with mock.patch('nova.utils.execute'):
            d = driver.DockerDriver(object)
            fake_inst = {'name': 'fake_instance', 'uuid': 'instance_uuid'}
            d.unplug_vifs(fake_inst, fake_net_info)
            mock_ui.assert_called_once_with(fake_inst, fake_net_info)
