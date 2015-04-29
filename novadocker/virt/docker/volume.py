# Copyright (c) 2013 dotCloud, Inc.
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

import glob
import os
import time

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils

from nova import exception
from nova.i18n import _
from nova.i18n import _LW
from nova import paths
from nova import utils


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume'),
    cfg.IntOpt('num_iser_scan_tries',
               default=5,
               help='Number of times to rescan iSER target to find volume'),
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt UUID of the secret for the rbd_user'
                    'volumes'),
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the NFS volume is mounted on the'
                    ' compute node'),
    cfg.StrOpt('nfs_mount_options',
               help='Mount options passed to the NFS client. See section '
                    'of the nfs man page for details'),
    cfg.StrOpt('smbfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the SMBFS shares are mounted on the '
                    'compute node'),
    cfg.StrOpt('smbfs_mount_options',
               default='',
               help='Mount options passed to the SMBFS client. See '
                    'mount.cifs man page for details. Note that the '
                    'libvirt-qemu uid and gid must be specified.'),
    cfg.IntOpt('num_aoe_discover_tries',
               default=3,
               help='Number of times to rediscover AoE target to find volume'),
    cfg.StrOpt('glusterfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the glusterfs volume is mounted on the '
                    'compute node'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI volume'),
    cfg.BoolOpt('iser_use_multipath',
                default=False,
                help='Use multipath connection of the iSER volume'),
    cfg.StrOpt('scality_sofs_config',
               help='Path or URL to Scality SOFS configuration file'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted'),
    cfg.ListOpt('qemu_allowed_storage_drivers',
                default=[],
                help='Protocols listed here will be accessed directly '
                     'from QEMU. Currently supported protocols: [gluster]'),
    cfg.StrOpt('quobyte_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the Quobyte volume is mounted on the '
                    'compute node'),
    cfg.StrOpt('quobyte_client_cfg',
               help='Path to a Quobyte Client configuration file.'),
    cfg.StrOpt('iscsi_iface',
               deprecated_name='iscsi_transport',
               help='The iSCSI transport iface to use to connect to target in '
                    'case offload support is desired. Supported transports '
                    'are be2iscsi, bnx2i, cxgb3i, cxgb4i, qla4xxx and ocs. '
                    'Default format is transport_name.hwaddress and can be '
                    'generated manually or via iscsiadm -m iface'),
    # iser is also supported, but use LibvirtISERVolumeDriver
    # instead
]

CONF = cfg.CONF
CONF.register_opts(volume_opts, 'libvirt')


class DockerBaseVolumeDriver(object):
    """Base class for volume drivers."""

    def __init__(self, connection, is_block_dev):
        self.connection = connection
        self.is_block_dev = is_block_dev

    def _get_secret_uuid(self, conf, password=None):
        secret = self.connection._host.find_secret(conf.source_protocol,
                                                   conf.source_name)
        if secret is None:
            secret = self.connection._host.create_secret(conf.source_protocol,
                                                         conf.source_name,
                                                         password)
        return secret.UUIDString()

    def _delete_secret_by_name(self, connection_info):
        source_protocol = connection_info['driver_volume_type']
        netdisk_properties = connection_info['data']
        if source_protocol == 'rbd':
            return
        elif source_protocol == 'iscsi':
            usage_type = 'iscsi'
            usage_name = ("%(target_iqn)s/%(target_lun)s" %
                          netdisk_properties)
            self.connection._host.delete_secret(usage_type, usage_name)

    def connect_volume(self, connection_info, disk_info):
        """Connect the volume. Returns xml for libvirt."""
        pass

    def disconnect_volume(self, connection_info, disk_dev):
        """Disconnect the volume."""
        pass


class DockerISCSIVolumeDriver(DockerBaseVolumeDriver):
    """Driver to attach Network volumes to libvirt."""
    supported_transports = ['be2iscsi', 'bnx2i', 'cxgb3i',
                            'cxgb4i', 'qla4xxx', 'ocs']

    def __init__(self, connection):
        super(DockerISCSIVolumeDriver, self).__init__(connection,
                                                      is_block_dev=True)
        self.num_scan_tries = CONF.libvirt.num_iscsi_scan_tries
        self.use_multipath = CONF.libvirt.iscsi_use_multipath
        if CONF.libvirt.iscsi_iface:
            self.transport = CONF.libvirt.iscsi_iface
        else:
            self.transport = 'default'

    def _get_transport(self):
        if self._validate_transport(self.transport):
            return self.transport
        else:
            return 'default'

    def _validate_transport(self, transport_iface):
        """Check that given iscsi_iface uses only supported transports

        Accepted transport names for provided iface param are
        be2iscsi, bnx2i, cxgb3i, cxgb4i, qla4xxx and ocs. iSER uses it's
        own separate driver. Note the difference between transport and
        iface; unlike iscsi_tcp/iser, this is not one and the same for
        offloaded transports, where the default format is
        transport_name.hwaddress
        """
        # We can support iser here as well, but currently reject it as the
        # separate iser driver has not yet been deprecated.
        if transport_iface == 'default':
            return True
        # Will return (6) if iscsi_iface file was not found, or (2) if iscsid
        # could not be contacted
        out = self._run_iscsiadm_bare(['-m',
                                       'iface',
                                       '-I',
                                       transport_iface],
                                      check_exit_code=[0, 2, 6])[0] or ""
        LOG.debug("iscsiadm %(iface)s configuration: stdout=%(out)s",
                  {'iface': transport_iface, 'out': out})
        for data in [line.split() for line in out.splitlines()]:
            if data[0] == 'iface.transport_name':
                if data[2] in self.supported_transports:
                    return True

        LOG.warn(_LW("No useable transport found for iscsi iface %s. "
                     "Falling back to default transport"),
                 transport_iface)
        return False

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        msg = ('iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s' %
               {'command': iscsi_command, 'out': out, 'err': err})
        # NOTE(bpokorny): iscsi_command can contain passwords so we need to
        # sanitize the password in the message.
        LOG.debug(strutils.mask_password(msg))
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value,
                         **kwargs):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command, **kwargs)

    def _get_target_portals_from_iscsiadm_output(self, output):
        # return both portals and iqns
        #
        # as we are parsing a command line utility, allow for the
        # possibility that additional debug data is spewed in the
        # stream, and only grab actual ip / iqn lines.
        targets = []
        for data in [line.split() for line in output.splitlines()]:
            if len(data) == 2 and data[1].startswith('iqn.'):
                targets.append(data)
        return targets

    @utils.synchronized('connect_volume')
    def connect_volume(self, connection_info, disk_info):
        """Attach the volume to instance_name."""
        iscsi_properties = connection_info['data']

        # multipath installed, discovering other targets if available
        # multipath should be configured on the nova-compute node,
        # in order to fit storage vendor
        out = None
        if self.use_multipath:
            out = self._run_iscsiadm_discover(iscsi_properties)

            # There are two types of iSCSI multipath devices.  One which shares
            # the same iqn between multiple portals, and the other which use
            # different iqns on different portals.  Try to identify the type by
            # checking the iscsiadm output if the iqn is used by multiple
            # portals.  If it is, it's the former, so use the supplied iqn.
            # Otherwise, it's the latter, so try the ip,iqn combinations to
            # find the targets which constitutes the multipath device.
            ips_iqns = self._get_target_portals_from_iscsiadm_output(out)
            same_portal = False
            all_portals = set()
            match_portals = set()
            for ip, iqn in ips_iqns:
                all_portals.add(ip)
                if iqn == iscsi_properties['target_iqn']:
                    match_portals.add(ip)
            if len(all_portals) == len(match_portals):
                same_portal = True

            for ip, iqn in ips_iqns:
                props = iscsi_properties.copy()
                props['target_portal'] = ip.split(",")[0]
                if not same_portal:
                    props['target_iqn'] = iqn
                self._connect_to_iscsi_portal(props)

            self._rescan_iscsi()
        else:
            self._connect_to_iscsi_portal(iscsi_properties)

            # Detect new/resized LUNs for existing sessions
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

        host_device = self._get_host_device(iscsi_properties)

        # The /dev/disk/by-path/... node is not always present immediately
        # TODO(justinsb): This retry-with-delay is a pattern, move to utils?
        tries = 0
        disk_dev = disk_info['dev']

        # Check host_device only when transport is used, since otherwise it is
        # directly derived from properties. Only needed for unit tests
        while ((self._get_transport() != "default" and not host_device)
               or not os.path.exists(host_device)):
            if tries >= self.num_scan_tries:
                raise exception.NovaException(_("iSCSI device not found at %s")
                                              % (host_device))

            LOG.warn(_LW("ISCSI volume not yet found at: %(disk_dev)s. "
                         "Will rescan & retry.  Try number: %(tries)s"),
                     {'disk_dev': disk_dev, 'tries': tries})

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

            # For offloaded open-iscsi transports, host_device cannot be
            # guessed unlike iscsi_tcp where it can be obtained from
            # properties, so try and get it again.
            if not host_device and self._get_transport() != "default":
                host_device = self._get_host_device(iscsi_properties)

            tries = tries + 1
            if not host_device or not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug("Found iSCSI node %(disk_dev)s "
                      "(after %(tries)s rescans)",
                      {'disk_dev': disk_dev,
                       'tries': tries})

        if self.use_multipath:
            # we use the multipath device instead of the single path device
            self._rescan_multipath()

            multipath_device = self._get_multipath_device_name(host_device)

            if multipath_device is not None:
                host_device = multipath_device
                connection_info['data']['multipath_id'] = \
                    multipath_device.split('/')[-1]

        connection_info['data']['device_path'] = host_device

    def _run_iscsiadm_discover(self, iscsi_properties):
        def run_iscsiadm_update_discoverydb():
            return utils.execute(
                'iscsiadm',
                '-m', 'discoverydb',
                '-t', 'sendtargets',
                '-p', iscsi_properties['target_portal'],
                '--op', 'update',
                '-n', "discovery.sendtargets.auth.authmethod",
                '-v', iscsi_properties['discovery_auth_method'],
                '-n', "discovery.sendtargets.auth.username",
                '-v', iscsi_properties['discovery_auth_username'],
                '-n', "discovery.sendtargets.auth.password",
                '-v', iscsi_properties['discovery_auth_password'],
                run_as_root=True)

        out = None
        if iscsi_properties.get('discovery_auth_method'):
            try:
                run_iscsiadm_update_discoverydb()
            except processutils.ProcessExecutionError as exc:
                # iscsiadm returns 6 for "db record not found"
                if exc.exit_code == 6:
                    (out, err) = utils.execute(
                        'iscsiadm',
                        '-m', 'discoverydb',
                        '-t', 'sendtargets',
                        '-p', iscsi_properties['target_portal'],
                        '--op', 'new',
                        run_as_root=True)
                    run_iscsiadm_update_discoverydb()
                else:
                    raise

            out = self._run_iscsiadm_bare(
                ['-m',
                 'discoverydb',
                 '-t',
                 'sendtargets',
                 '-p',
                 iscsi_properties['target_portal'],
                 '--discover'],
                check_exit_code=[0, 255])[0] or ""
        else:
            out = self._run_iscsiadm_bare(
                ['-m',
                 'discovery',
                 '-t',
                 'sendtargets',
                 '-p',
                 iscsi_properties['target_portal']],
                check_exit_code=[0, 255])[0] or ""
        return out

    @utils.synchronized('connect_volume')
    def disconnect_volume(self, connection_info, disk_dev):
        """Detach the volume from instance_name."""
        iscsi_properties = connection_info['data']
        host_device = self._get_host_device(iscsi_properties)
        multipath_device = None
        if self.use_multipath:
            if 'multipath_id' in iscsi_properties:
                multipath_device = ('/dev/mapper/%s' %
                                    iscsi_properties['multipath_id'])
            else:
                multipath_device = self._get_multipath_device_name(host_device)

        super(DockerISCSIVolumeDriver,
              self).disconnect_volume(connection_info, disk_dev)

        if self.use_multipath and multipath_device:
            return self._disconnect_volume_multipath_iscsi(iscsi_properties,
                                                           multipath_device)

        # NOTE(vish): Only disconnect from the target if no luns from the
        #             target are in use.
        device_byname = ("ip-%s-iscsi-%s-lun-" %
                         (iscsi_properties['target_portal'],
                          iscsi_properties['target_iqn']))
        devices = self.connection._get_all_block_devices()
        devices = [dev for dev in devices if (device_byname in dev
                                              and
                                              dev.startswith(
                                                  '/dev/disk/by-path/'))]
        if not devices:
            self._disconnect_from_iscsi_portal(iscsi_properties)
        elif host_device not in devices:
            # Delete device if LUN is not in use by another instance
            self._delete_device(host_device)

    def _delete_device(self, device_path):
        device_name = os.path.basename(os.path.realpath(device_path))
        delete_control = '/sys/block/' + device_name + '/device/delete'
        if os.path.exists(delete_control):
            # Copy '1' from stdin to the device delete control file
            utils.execute('cp', '/dev/stdin', delete_control,
                          process_input='1', run_as_root=True)
        else:
            LOG.warn(_LW("Unable to delete volume device %s"), device_name)

    def _remove_multipath_device_descriptor(self, disk_descriptor):
        disk_descriptor = disk_descriptor.replace('/dev/mapper/', '')
        try:
            self._run_multipath(['-f', disk_descriptor],
                                check_exit_code=[0, 1])
        except processutils.ProcessExecutionError as exc:
            # Because not all cinder drivers need to remove the dev mapper,
            # here just logs a warning to avoid affecting those drivers in
            # exceptional cases.
            LOG.warn(_LW('Failed to remove multipath device descriptor '
                         '%(dev_mapper)s. Exception message: %(msg)s')
                     % {'dev_mapper': disk_descriptor,
                        'msg': exc.message})

    def _disconnect_volume_multipath_iscsi(self, iscsi_properties,
                                           multipath_device):
        self._rescan_iscsi()
        self._rescan_multipath()
        block_devices = self.connection._get_all_block_devices()
        devices = []
        for dev in block_devices:
            if "/mapper/" in dev:
                devices.append(dev)
            else:
                mpdev = self._get_multipath_device_name(dev)
                if mpdev:
                    devices.append(mpdev)

        # Do a discovery to find all targets.
        # Targets for multiple paths for the same multipath device
        # may not be the same.
        out = self._run_iscsiadm_discover(iscsi_properties)

        # Extract targets for the current multipath device.
        ips_iqns = []
        entries = self._get_iscsi_devices()
        for ip, iqn in self._get_target_portals_from_iscsiadm_output(out):
            ip_iqn = "%s-iscsi-%s" % (ip.split(",")[0], iqn)
            for entry in entries:
                entry_ip_iqn = entry.split("-lun-")[0]
                if entry_ip_iqn[:3] == "ip-":
                    entry_ip_iqn = entry_ip_iqn[3:]
                elif entry_ip_iqn[:4] == "pci-":
                    # Look at an offset of len('pci-0000:00:00.0')
                    offset = entry_ip_iqn.find("ip-", 16, 21)
                    entry_ip_iqn = entry_ip_iqn[(offset + 3):]
                if (ip_iqn != entry_ip_iqn):
                    continue
                entry_real_path = os.path.realpath("/dev/disk/by-path/%s" %
                                                   entry)
                entry_mpdev = self._get_multipath_device_name(entry_real_path)
                if entry_mpdev == multipath_device:
                    ips_iqns.append([ip, iqn])
                    break

        if not devices:
            # disconnect if no other multipath devices
            self._disconnect_mpath(iscsi_properties, ips_iqns)
            return

        # Get a target for all other multipath devices
        other_iqns = [self._get_multipath_iqn(device)
                      for device in devices]
        # Get all the targets for the current multipath device
        current_iqns = [iqn for ip, iqn in ips_iqns]

        in_use = False
        for current in current_iqns:
            if current in other_iqns:
                in_use = True
                break

        # If no other multipath device attached has the same iqn
        # as the current device
        if not in_use:
            # disconnect if no other multipath devices with same iqn
            self._disconnect_mpath(iscsi_properties, ips_iqns)
            return
        elif multipath_device not in devices:
            # delete the devices associated w/ the unused multipath
            self._delete_mpath(iscsi_properties, multipath_device, ips_iqns)

        # else do not disconnect iscsi portals,
        # as they are used for other luns,
        # just remove multipath mapping device descriptor
        self._remove_multipath_device_descriptor(multipath_device)
        return

    def _connect_to_iscsi_portal(self, iscsi_properties):
        # NOTE(vish): If we are on the same host as nova volume, the
        #             discovery makes the target so we don't need to
        #             run --op new. Therefore, we check to see if the
        #             target exists, and if we get 255 (Not Found), then
        #             we run --op new. This will also happen if another
        #             volume is using the same target.
        try:
            self._run_iscsiadm(iscsi_properties, ())
        except processutils.ProcessExecutionError as exc:
            # iscsiadm returns 21 for "No records found" after version 2.0-871
            if exc.exit_code in [21, 255]:
                self._reconnect(iscsi_properties)
            else:
                raise

        if iscsi_properties.get('auth_method'):
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.authmethod",
                                  iscsi_properties['auth_method'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.username",
                                  iscsi_properties['auth_username'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.password",
                                  iscsi_properties['auth_password'])

        # duplicate logins crash iscsiadm after load,
        # so we scan active sessions to see if the node is logged in.
        out = self._run_iscsiadm_bare(["-m", "session"],
                                      run_as_root=True,
                                      check_exit_code=[0, 1, 21])[0] or ""

        portals = [{'portal': p.split(" ")[2], 'iqn': p.split(" ")[3]}
                   for p in out.splitlines() if p.startswith("tcp:")]

        stripped_portal = iscsi_properties['target_portal'].split(",")[0]
        if len(portals) == 0 or len(
                [s for s in portals if
                 stripped_portal == s['portal'].split(",")[0] and
                 s['iqn'] == iscsi_properties['target_iqn']]) == 0:
            try:
                self._run_iscsiadm(iscsi_properties,
                                   ("--login",),
                                   check_exit_code=[0, 255])
            except processutils.ProcessExecutionError as err:
                # as this might be one of many paths,
                # only set successful logins to startup automatically
                if err.exit_code in [15]:
                    self._iscsiadm_update(iscsi_properties,
                                          "node.startup",
                                          "automatic")
                    return

            self._iscsiadm_update(iscsi_properties,
                                  "node.startup",
                                  "automatic")

    def _disconnect_from_iscsi_portal(self, iscsi_properties):
        self._iscsiadm_update(iscsi_properties, "node.startup", "manual",
                              check_exit_code=[0, 21, 255])
        self._run_iscsiadm(iscsi_properties, ("--logout",),
                           check_exit_code=[0, 21, 255])
        self._run_iscsiadm(iscsi_properties, ('--op', 'delete'),
                           check_exit_code=[0, 21, 255])

    def _get_multipath_device_name(self, single_path_device):
        device = os.path.realpath(single_path_device)

        out = self._run_multipath(['-ll',
                                   device],
                                  check_exit_code=[0, 1])[0]
        mpath_line = [line for line in out.splitlines()
                      if "scsi_id" not in line]  # ignore udev errors
        if len(mpath_line) > 0 and len(mpath_line[0]) > 0:
            return "/dev/mapper/%s" % mpath_line[0].split(" ")[0]

        return None

    def _get_iscsi_devices(self):
        try:
            devices = list(os.walk('/dev/disk/by-path'))[0][-1]
        except IndexError:
            return []
        iscsi_devs = []
        for entry in devices:
            if (entry.startswith("ip-") or
                    (entry.startswith('pci-') and 'ip-' in entry)):
                iscsi_devs.append(entry)

        return iscsi_devs

    def _delete_mpath(self, iscsi_properties, multipath_device, ips_iqns):
        entries = self._get_iscsi_devices()
        # Loop through ips_iqns to construct all paths
        iqn_luns = []
        for ip, iqn in ips_iqns:
            iqn_lun = '%s-lun-%s' % (iqn,
                                     iscsi_properties.get('target_lun', 0))
            iqn_luns.append(iqn_lun)
        for dev in ['/dev/disk/by-path/%s' % dev for dev in entries]:
            for iqn_lun in iqn_luns:
                if iqn_lun in dev:
                    self._delete_device(dev)

        self._rescan_multipath()

    def _disconnect_mpath(self, iscsi_properties, ips_iqns):
        for ip, iqn in ips_iqns:
            props = iscsi_properties.copy()
            props['target_portal'] = ip
            props['target_iqn'] = iqn
            self._disconnect_from_iscsi_portal(props)

        self._rescan_multipath()

    def _get_multipath_iqn(self, multipath_device):
        entries = self._get_iscsi_devices()
        for entry in entries:
            entry_real_path = os.path.realpath("/dev/disk/by-path/%s" % entry)
            entry_multipath = self._get_multipath_device_name(entry_real_path)
            if entry_multipath == multipath_device:
                return entry.split("iscsi-")[1].split("-lun")[0]
        return None

    def _run_iscsiadm_bare(self, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('iscsiadm',
                                   *iscsi_command,
                                   run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %(command)s: stdout=%(out)s stderr=%(err)s",
                  {'command': iscsi_command, 'out': out, 'err': err})
        return (out, err)

    def _run_multipath(self, multipath_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = utils.execute('multipath',
                                   *multipath_command,
                                   run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("multipath %(command)s: stdout=%(out)s stderr=%(err)s",
                  {'command': multipath_command, 'out': out, 'err': err})
        return (out, err)

    def _rescan_iscsi(self):
        self._run_iscsiadm_bare(('-m', 'node', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])
        self._run_iscsiadm_bare(('-m', 'session', '--rescan'),
                                check_exit_code=[0, 1, 21, 255])

    def _rescan_multipath(self):
        self._run_multipath(['-r'], check_exit_code=[0, 1, 21])

    def _get_host_device(self, transport_properties):
        """Find device path in devtemfs."""
        device = ("ip-%s-iscsi-%s-lun-%s" %
                  (transport_properties['target_portal'],
                   transport_properties['target_iqn'],
                   transport_properties.get('target_lun', 0)))
        if self._get_transport() == "default":
            return ("/dev/disk/by-path/%s" % device)
        else:
            host_device = None
            look_for_device = glob.glob('/dev/disk/by-path/*%s' % device)
            if look_for_device:
                host_device = look_for_device[0]
            return host_device

    def _reconnect(self, iscsi_properties):
        # Note: iscsiadm does not support changing iface.iscsi_ifacename
        # via --op update, so we do this at creation time
        self._run_iscsiadm(iscsi_properties,
                           ('--interface', self._get_transport(),
                            '--op', 'new'))
