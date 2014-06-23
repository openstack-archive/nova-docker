# coding=utf-8

# Copyright (c) 2012 NTT DOCOMO, INC.
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

import re

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import utils
from nova.virt import volumeutils
from novadocker.virt.docker import client as docker_client

opts = [
    cfg.BoolOpt('use_unsafe_iscsi',
        default=False,
        help='Do not set this out of dev/test environments. '
                      'If a node does not have a fixed PXE IP address, '
                      'volumes are exported with globally opened ACL'),
    cfg.StrOpt('iscsi_iqn_prefix',
        default='iqn.2010-10.org.openstack.docker',
        help='The iSCSI IQN prefix used in docker volume '
             'connections.'),
    ]

docker_group = cfg.OptGroup(name='docker',
                            title='Docker Options')

CONF = cfg.CONF
CONF.register_group(docker_group)
CONF.register_opts(opts, docker_group)

CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('use_ipv6', 'nova.netconf')
CONF.import_opt('volume_drivers', 'nova.virt.libvirt.driver', group='libvirt')

LOG = logging.getLogger(__name__)


def _create_iscsi_export_tgtadm(path, tid, iqn):
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'target',
                  '--op', 'new',
                  '--tid', tid,
                  '--targetname', iqn,
                  run_as_root=True)
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'logicalunit',
                  '--op', 'new',
                  '--tid', tid,
                  '--lun', '1',
                  '--backing-store', path,
                  run_as_root=True)


def _allow_iscsi_tgtadm(tid, address):
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'target',
                  '--op', 'bind',
                  '--tid', tid,
                  '--initiator-address', address,
                  run_as_root=True)


def _delete_iscsi_export_tgtadm(tid):
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'logicalunit',
                      '--op', 'delete',
                      '--tid', tid,
                      '--lun', '1',
                      run_as_root=True)
    except processutils.ProcessExecutionError:
        pass
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'target',
                      '--op', 'delete',
                      '--tid', tid,
                      run_as_root=True)
    except processutils.ProcessExecutionError:
        pass
    # Check if the tid is deleted, that is, check the tid no longer exists.
    # If the tid dose not exist, tgtadm returns with exit_code 22.
    # utils.execute() can check the exit_code if check_exit_code parameter is
    # passed. But, regardless of whether check_exit_code contains 0 or not,
    # if the exit_code is 0, the function dose not report errors. So we have to
    # catch a ProcessExecutionError and test its exit_code is 22.
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'target',
                      '--op', 'show',
                      '--tid', tid,
                      run_as_root=True)
    except processutils.ProcessExecutionError as e:
        if e.exit_code == 22:
            # OK, the tid is deleted
            return
        raise
    raise exception.NovaException(_(
            'docker driver was unable to delete tid %s') % tid)


def _show_tgtadm():
    out, _ = utils.execute('tgtadm', '--lld', 'iscsi',
                           '--mode', 'target',
                           '--op', 'show',
                           run_as_root=True)
    return out


def _list_backingstore_path():
    out = _show_tgtadm()
    l = []
    for line in out.split('\n'):
        m = re.search(r'Backing store path: (.*)$', line)
        if m:
            if '/' in m.group(1):
                l.append(m.group(1))
    return l


def _get_next_tid():
    out = _show_tgtadm()
    last_tid = 0
    for line in out.split('\n'):
        m = re.search(r'^Target (\d+):', line)
        if m:
            tid = int(m.group(1))
            if last_tid < tid:
                last_tid = tid
    return last_tid + 1


def _find_tid(iqn):
    out = _show_tgtadm()
    pattern = r'^Target (\d+): *' + re.escape(iqn)
    for line in out.split('\n'):
        m = re.search(pattern, line)
        if m:
            return int(m.group(1))
    return None


def _get_iqn(instance_name, mountpoint):
    mp = mountpoint.replace('/', '-').strip('-')
    iqn = '%s:%s-%s' % (CONF.docker.iscsi_iqn_prefix,
                        instance_name,
                        mp)
    return iqn


class VolumeDriver(object):

    def __init__(self, virtapi):
        super(VolumeDriver, self).__init__()
        self.virtapi = virtapi
        self._initiator = None

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = volumeutils.get_iscsi_initiator()
            if not self._initiator:
                LOG.warn(_('Could not determine iscsi initiator name'),
                         instance=instance)
        return {
            'ip': CONF.my_ip,
            'initiator': self._initiator,
            'host': CONF.host,
        }

    def attach_volume(self, connection_info, instance, mountpoint):
        raise NotImplementedError()

    def detach_volume(self, connection_info, instance, mountpoint):
        raise NotImplementedError()


"""The VolumeDriver delegates to nova.virt.libvirt.volume."""
class DockerVolumeDriver(VolumeDriver):

    def __init__(self, virtapi):
        super(DockerVolumeDriver, self).__init__(virtapi)
        self.volume_drivers = {}
        self.docker = docker_client.DockerHTTPClient()
        for driver_str in CONF.libvirt.volume_drivers:
            driver_type, _sep, driver = driver_str.partition('=')
            driver_class = importutils.import_class(driver)
            self.volume_drivers[driver_type] = driver_class(self)

    def _volume_driver_method(self, method_name, connection_info,
                              *args, **kwargs):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        method = getattr(driver, method_name)
        return method(connection_info, *args, **kwargs)

    def attach_volume(self, connection_info, instance, mountpoint):
        host_ip = CONF.my_ip
        if not host_ip:
            if not CONF.docker.use_unsafe_iscsi:
                raise exception.NovaException(_(
                    'No fixed PXE IP is associated to %s') % instance['uuid'])

        mount_device = mountpoint.rpartition("/")[2]
        disk_info = {'dev': mount_device,
                     'bus': 'docker',
                     'type': 'docker',
                    }
        conf = self._connect_volume(connection_info, disk_info)
        self._publish_iscsi(instance, mountpoint, host_ip,
                            conf.source_path)

    def _connect_volume(self, connection_info, disk_info):
        return self._volume_driver_method('connect_volume',
                                          connection_info,
                                          disk_info)

    def _publish_iscsi(self, instance, mountpoint, host_ip, device_path):
        iqn = _get_iqn(instance['name'], mountpoint)
        tid = _get_next_tid()
        _create_iscsi_export_tgtadm(device_path, tid, iqn)

        if host_ip:
            _allow_iscsi_tgtadm(tid, host_ip)
        else:
            # NOTE(NTTdocomo): Since nova-compute does not know the
            # instance's initiator ip, it allows any initiators
            # to connect to the volume. This means other bare-metal
            # instances that are not attached the volume can connect
            # to the volume. Do not set CONF.docker.use_unsafe_iscsi
            # out of dev/test environments.
            # TODO(NTTdocomo): support CHAP
            _allow_iscsi_tgtadm(tid, 'ALL')

    def detach_volume(self, connection_info, instance, mountpoint):
        mount_device = mountpoint.rpartition("/")[2]
        try:
            self._depublish_iscsi(instance, mountpoint)
        finally:
            self._disconnect_volume(connection_info, mount_device)

    def _disconnect_volume(self, connection_info, disk_dev):
        return self._volume_driver_method('disconnect_volume',
                                          connection_info,
                                          disk_dev)

    def _depublish_iscsi(self, instance, mountpoint):
        iqn = _get_iqn(instance['name'], mountpoint)
        tid = _find_tid(iqn)
        if tid is not None:
            _delete_iscsi_export_tgtadm(tid)
        else:
            LOG.warn(_('detach volume could not find tid for %s'), iqn,
                     instance=instance)

    def get_all_block_devices(self):
        """Return all block devices in use on this node."""
        return _list_backingstore_path()

    def get_hypervisor_version(self):
        """A dummy method for LibvirtBaseVolumeDriver.connect_volume."""
        return 1
