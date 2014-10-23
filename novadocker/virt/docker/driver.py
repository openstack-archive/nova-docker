# Copyright (c) 2013 dotCloud, Inc.
# Copyright 2014 IBM Corp.
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

"""
A Docker Hypervisor which allows running Linux Containers instead of VMs.
"""

import os
import socket
import time
import uuid

from docker import errors
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import importutils
from oslo.utils import units

from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova import exception
from nova.i18n import _
from nova.image import glance
from nova.openstack.common import fileutils
from nova.openstack.common import log
from nova import utils
from nova.virt import driver
from nova.virt import firewall
from nova.virt import images
from novadocker.virt.docker import client as docker_client
from novadocker.virt.docker import hostinfo
from novadocker.virt.docker import network
from novadocker.virt import hostutils

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('instances_path', 'nova.compute.manager')

docker_opts = [
    cfg.StrOpt('host_url',
               default='unix:///var/run/docker.sock',
               help='tcp://host:port to bind/connect to or '
                    'unix://path/to/socket to use'),
    cfg.BoolOpt('api_insecure',
                default=False,
                help='If set, ignore any SSL validation issues'),
    cfg.StrOpt('ca_file',
               help='Location of CA certificates file for '
                    'securing docker api requests (tlscacert).'),
    cfg.StrOpt('cert_file',
               help='Location of TLS certificate file for '
                    'securing docker api requests (tlscert).'),
    cfg.StrOpt('key_file',
               help='Location of TLS private key file for '
                    'securing docker api requests (tlskey).'),
    cfg.StrOpt('vif_driver',
               default='novadocker.virt.docker.vifs.DockerGenericVIFDriver'),
    cfg.StrOpt('snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where docker driver will temporarily store '
                    'snapshots.')
]

CONF.register_opts(docker_opts, 'docker')

LOG = log.getLogger(__name__)


class DockerDriver(driver.ComputeDriver):
    """Docker hypervisor driver."""

    def __init__(self, virtapi):
        super(DockerDriver, self).__init__(virtapi)
        self._docker = None
        vif_class = importutils.import_class(CONF.docker.vif_driver)
        self.vif_driver = vif_class()
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

    @property
    def docker(self):
        if self._docker is None:
            self._docker = docker_client.DockerHTTPClient(CONF.docker.host_url)
        return self._docker

    def init_host(self, host):
        if self._is_daemon_running() is False:
            raise exception.NovaException(
                _('Docker daemon is not running or is not reachable'
                  ' (check the rights on /var/run/docker.sock)'))

    def _is_daemon_running(self):
        return self.docker.ping()

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def refresh_security_group_rules(self, security_group_id):
        """Refresh security group rules from data store.

        Invoked when security group rules are updated.

        :param security_group_id: The security group id.

        """
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        """Refresh security group members from data store.

        Invoked when instances are added/removed to a security group.

        :param security_group_id: The security group id.

        """
        self.firewall_driver.refresh_security_group_members(security_group_id)

    def refresh_provider_fw_rules(self):
        """Triggers a firewall update based on database changes."""
        self.firewall_driver.refresh_provider_fw_rules()

    def refresh_instance_security_rules(self, instance):
        """Refresh security group rules from data store.

        Gets called when an instance gets added to or removed from
        the security group the instance is a member of or if the
        group gains or loses a rule.

        :param instance: The instance object.

        """
        self.firewall_driver.refresh_instance_security_rules(instance)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        """Set up filtering rules.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)

    def unfilter_instance(self, instance, network_info):
        """Stop filtering instance.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        self.firewall_driver.unfilter_instance(instance, network_info)

    def list_instances(self, inspect=False):
        res = []
        for container in self.docker.containers(all=True):
            info = self.docker.inspect_container(container['id'])
            if not info:
                continue
            if inspect:
                res.append(info)
            else:
                res.append(info['Config'].get('Hostname'))
        return res

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for vif in network_info:
            self.vif_driver.plug(instance, vif)
        self._start_firewall(instance, network_info)

    def _attach_vifs(self, instance, network_info):
        """Plug VIFs into container."""
        if not network_info:
            return
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        netns_path = '/var/run/netns'
        if not os.path.exists(netns_path):
            utils.execute(
                'mkdir', '-p', netns_path, run_as_root=True)
        nspid = self._find_container_pid(container_id)
        if not nspid:
            msg = _('Cannot find any PID under container "{0}"')
            raise RuntimeError(msg.format(container_id))
        netns_path = os.path.join(netns_path, container_id)
        utils.execute(
            'ln', '-sf', '/proc/{0}/ns/net'.format(nspid),
            '/var/run/netns/{0}'.format(container_id),
            run_as_root=True)

        for vif in network_info:
            self.vif_driver.attach(instance, vif, container_id)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)
        self._stop_firewall(instance, network_info)

    def _encode_utf8(self, value):
        return unicode(value).encode('utf-8')

    def _find_container_by_name(self, name):
        try:
            for info in self.list_instances(inspect=True):
                if info['Config'].get('Hostname') == name:
                    return info
        except errors.APIError as e:
            if e.response.status_code != 404:
                raise
        return {}

    def _get_container_id(self, instance):
        return self._find_container_by_name(instance['name']).get('id')

    def get_info(self, instance):
        container = self._find_container_by_name(instance['name'])
        if not container:
            raise exception.InstanceNotFound(instance_id=instance['name'])
        running = container['State'].get('Running')
        mem = container['Config'].get('Memory', 0)

        # NOTE(ewindisch): cgroups/lxc defaults to 1024 multiplier.
        #                  see: _get_cpu_shares for further explaination
        num_cpu = container['Config'].get('CpuShares', 0) / 1024

        # FIXME(ewindisch): Improve use of statistics:
        #                   For 'mem', we should expose memory.stat.rss, and
        #                   for cpu_time we should expose cpuacct.stat.system,
        #                   but these aren't yet exposed by Docker.
        #
        #                   Also see:
        #                    docker/docs/sources/articles/runmetrics.md
        info = {
            'max_mem': mem,
            'mem': mem,
            'num_cpu': num_cpu,
            'cpu_time': 0
        }
        info['state'] = (power_state.RUNNING if running
                         else power_state.SHUTDOWN)
        return info

    def get_host_stats(self, refresh=False):
        hostname = socket.gethostname()
        stats = self.get_available_resource(hostname)
        stats['host_hostname'] = stats['hypervisor_hostname']
        stats['host_name_label'] = stats['hypervisor_hostname']
        return stats

    def get_available_nodes(self, refresh=False):
        hostname = socket.gethostname()
        return [hostname]

    def get_available_resource(self, nodename):
        if not hasattr(self, '_nodename'):
            self._nodename = nodename
        if nodename != self._nodename:
            LOG.error(_('Hostname has changed from %(old)s to %(new)s. '
                        'A restart is required to take effect.'
                        ), {'old': self._nodename,
                            'new': nodename})

        memory = hostinfo.get_memory_usage()
        disk = hostinfo.get_disk_usage()
        stats = {
            'vcpus': 1,
            'vcpus_used': 0,
            'memory_mb': memory['total'] / units.Mi,
            'memory_mb_used': memory['used'] / units.Mi,
            'local_gb': disk['total'] / units.Gi,
            'local_gb_used': disk['used'] / units.Gi,
            'disk_available_least': disk['available'] / units.Gi,
            'hypervisor_type': 'docker',
            'hypervisor_version': utils.convert_version_to_int('1.0'),
            'hypervisor_hostname': self._nodename,
            'cpu_info': '?',
            'supported_instances': jsonutils.dumps([
                ('i686', 'docker', 'lxc'),
                ('x86_64', 'docker', 'lxc')
            ])
        }
        return stats

    def _find_container_pid(self, container_id):
        n = 0
        while True:
            # NOTE(samalba): We wait for the process to be spawned inside the
            # container in order to get the the "container pid". This is
            # usually really fast. To avoid race conditions on a slow
            # machine, we allow 10 seconds as a hard limit.
            if n > 20:
                return
            info = self.docker.inspect_container(container_id)
            if info:
                pid = info['State']['Pid']
                # Pid is equal to zero if it isn't assigned yet
                if pid:
                    return pid
            time.sleep(0.5)
            n += 1

    def _get_memory_limit_bytes(self, instance):
        system_meta = utils.instance_sys_meta(instance)
        return int(system_meta.get('instance_type_memory_mb', 0)) * units.Mi

    def _get_image_name(self, context, instance, image):
        fmt = image['container_format']
        if fmt != 'docker':
            msg = _('Image container format not supported ({0})')
            raise exception.InstanceDeployFailure(msg.format(fmt),
                                                  instance_id=instance['name'])
        return image['name']

    def _pull_missing_image(self, context, image_meta, instance):
        msg = 'Image name "%s" does not exist, fetching it...'
        LOG.debug(msg, image_meta['name'])

        # TODO(imain): It would be nice to do this with file like object
        # passing but that seems a bit complex right now.
        snapshot_directory = CONF.docker.snapshots_directory
        fileutils.ensure_tree(snapshot_directory)
        with utils.tempdir(dir=snapshot_directory) as tmpdir:
            try:
                out_path = os.path.join(tmpdir, uuid.uuid4().hex)

                images.fetch(context, image_meta['id'], out_path,
                             instance['user_id'], instance['project_id'])
                self.docker.load_repository_file(
                    self._encode_utf8(image_meta['name']),
                    out_path
                )
            except Exception as e:
                LOG.warning(_('Cannot load repository file: %s'),
                            e, instance=instance, exc_info=True)
                msg = _('Cannot load repository file: {0}')
                raise exception.NovaException(msg.format(e),
                                              instance_id=image_meta['name'])

        return self.docker.inspect_image(self._encode_utf8(image_meta['name']))

    def _start_container(self, container_id, instance, network_info=None):
        self.docker.start(container_id)
        if not network_info:
            return
        try:
            self.plug_vifs(instance, network_info)
            self._attach_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot setup network: %s'),
                        e, instance=instance, exc_info=True)
            msg = _('Cannot setup network: {0}')
            self.docker.kill(container_id)
            self.docker.remove_container(container_id, force=True)
            raise exception.InstanceDeployFailure(msg.format(e),
                                                  instance_id=instance['name'])

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        image_name = self._get_image_name(context, instance, image_meta)
        args = {
            'hostname': instance['name'],
            'mem_limit': self._get_memory_limit_bytes(instance),
            'cpu_shares': self._get_cpu_shares(instance),
            'network_disabled': True,
        }

        image = self.docker.inspect_image(self._encode_utf8(image_name))
        if not image:
            image = self._pull_missing_image(context, image_meta, instance)
        if not (image and image['ContainerConfig']['Cmd']):
            args['Cmd'] = ['sh']
        # Glance command-line overrides any set in the Docker image
        if (image_meta and
                image_meta.get('properties', {}).get('os_command_line')):
            args['Cmd'] = image_meta['properties'].get('os_command_line')

        container_id = self._create_container(instance, image_name, args)
        if not container_id:
            raise exception.InstanceDeployFailure(
                _('Cannot create container'),
                instance_id=instance['name'])

        self._start_container(container_id, instance, network_info)

    def restore(self, instance):
        container_id = self._get_container_id(instance)
        if not container_id:
            return

        self._start_container(container_id, instance)

    def soft_delete(self, instance):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        try:
            self.docker.stop(container_id)
        except errors.APIError as e:
            if 'Unpause the container before stopping' not in e.explanation:
                LOG.warning(_('Cannot stop container: %s'),
                            e, instance=instance, exc_info=True)
                raise
            self.docker.unpause(container_id)
            self.docker.stop(container_id)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.soft_delete(instance)
        self.cleanup(context, instance, network_info,
                     block_device_info, destroy_disks)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        """Cleanup after instance being destroyed by Hypervisor."""
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self.docker.remove_container(container_id, force=True)
        network.teardown_network(container_id)
        self.unplug_vifs(instance, network_info)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self.docker.stop(container_id)
        try:
            network.teardown_network(container_id)
            if network_info:
                self.unplug_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot destroy the container network'
                          ' during reboot {0}').format(e),
                        exc_info=True)
            return

        self.docker.start(container_id)
        try:
            if network_info:
                self.plug_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot setup network on reboot: {0}'), e,
                        exc_info=True)
            return

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self.docker.start(container_id)
        if not network_info:
            return
        try:
            self.plug_vifs(instance, network_info)
            self._attach_vifs(instance, network_info)
        except Exception as e:
            LOG.debug(_('Cannot setup network: %s'),
                      e, instance=instance, exc_info=True)
            msg = _('Cannot setup network: {0}')
            self.docker.kill(container_id)
            self.docker.remove_container(container_id, force=True)
            raise exception.InstanceDeployFailure(msg.format(e),
                                                  instance_id=instance['name'])

    def power_off(self, instance, timeout=0, retry_interval=0):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self.docker.stop(container_id, timeout)

    def pause(self, instance):
        """Pause the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        try:
            cont_id = self._get_container_id(instance)
            if not self.docker.pause(cont_id):
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Error pause container: %s'),
                      e, instance=instance, exc_info=True)
            msg = _('Cannot pause container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance['name'])

    def unpause(self, instance):
        """Unpause paused VM instance.

        :param instance: nova.objects.instance.Instance
        """
        try:
            cont_id = self._get_container_id(instance)
            if not self.docker.unpause(cont_id):
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Error unpause container: %s'),
                      e, instance=instance, exc_info=True)
            msg = _('Cannot unpause container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance['name'])

    def get_console_output(self, context, instance):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        return self.docker.get_container_logs(container_id)

    def snapshot(self, context, instance, image_href, update_task_state):
        container_id = self._get_container_id(instance)
        if not container_id:
            raise exception.InstanceNotRunning(instance_id=instance['uuid'])

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
        (image_service, image_id) = glance.get_remote_image_service(
            context, image_href)
        image = image_service.show(context, image_id)
        if ':' not in image['name']:
            commit_name = self._encode_utf8(image['name'])
            tag = 'latest'
        else:
            parts = self._encode_utf8(image['name']).rsplit(':', 1)
            commit_name = parts[0]
            tag = parts[1]

        self.docker.commit(container_id, repository=commit_name, tag=tag)

        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)

        metadata = {
            'is_public': False,
            'status': 'active',
            'disk_format': 'raw',
            'container_format': 'docker',
            'name': image['name'],
            'properties': {
                'image_location': 'snapshot',
                'image_state': 'available',
                'status': 'available',
                'owner_id': instance['project_id'],
                'ramdisk_id': instance['ramdisk_id']
            }
        }
        if instance['os_type']:
            metadata['properties']['os_type'] = instance['os_type']

        try:
            raw = self.docker.get_image(commit_name)
            # Patch the seek/tell as urllib3 throws UnsupportedOperation
            raw.seek = lambda x=None, y=None: None
            raw.tell = lambda: None
            image_service.update(context, image_href, metadata, raw)
        except Exception as e:
            LOG.debug(_('Error saving image: %s'),
                      e, instance=instance, exc_info=True)
            msg = _('Error saving image: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance['name'])

    def _get_cpu_shares(self, instance):
        """Get allocated CPUs from configured flavor.

        Docker/lxc supports relative CPU allocation.

        cgroups specifies following:
         /sys/fs/cgroup/lxc/cpu.shares = 1024
         /sys/fs/cgroup/cpu.shares = 1024

        For that reason we use 1024 as multiplier.
        This multiplier allows to divide the CPU
        resources fair with containers started by
        the user (e.g. docker registry) which has
        the default CpuShares value of zero.
        """
        flavor = flavors.extract_flavor(instance)
        return int(flavor['vcpus']) * 1024

    def _create_container(self, instance, image_name, args):
        name = "nova-" + instance['uuid']
        args.update({'name': self._encode_utf8(name)})
        return self.docker.create_container(image_name, **args)

    def get_host_uptime(self, host):
        return hostutils.sys_uptime()
