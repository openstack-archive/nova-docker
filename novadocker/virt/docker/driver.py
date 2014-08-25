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

"""
A Docker Hypervisor which allows running Linux Containers instead of VMs.
"""

import os
import socket
import time
import uuid

from oslo.config import cfg

from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova import exception
from nova.image import glance
from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log
from nova.openstack.common import units
from nova import utils
from nova.virt import driver
from nova.virt import images
from novadocker.virt.docker import client as docker_client
from novadocker.virt.docker import hostinfo
from novadocker.virt.docker import network
from novadocker.virt import hostutils

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('instances_path', 'nova.compute.manager')

docker_opts = [
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

    @property
    def docker(self):
        if self._docker is None:
            self._docker = docker_client.DockerHTTPClient()
        return self._docker

    def init_host(self, host):
        if self._is_daemon_running() is False:
            raise exception.NovaException(
                _('Docker daemon is not running or is not reachable'
                  ' (check the rights on /var/run/docker.sock)'))

    def _is_daemon_running(self):
        try:
            return self.docker.ping()
        except socket.error:
            return False

    def list_instances(self, inspect=False):
        res = []
        for container in self.docker.list_containers():
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

    def _attach_vifs(self, instance, network_info):
        """Plug VIFs into container."""
        if not network_info:
            return
        container_id = self._find_container_by_name(instance['name']).get('id')
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

    def _find_container_by_name(self, name):
        for info in self.list_instances(inspect=True):
            if info['Config'].get('Hostname') == name:
                return info
        return {}

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

    def get_available_resource(self, nodename):
        if not hasattr(self, '_nodename'):
            self._nodename = nodename
        if nodename != self._nodename:
            LOG.error(_('Hostname has changed from %(old)s to %(new)s. '
                        'A restart is required to take effect.'
                        ) % {'old': self._nodename,
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
        LOG.debug(msg % image_meta['name'])

        # TODO(imain): It would be nice to do this with file like object
        # passing but that seems a bit complex right now.
        snapshot_directory = CONF.docker.snapshots_directory
        fileutils.ensure_tree(snapshot_directory)
        with utils.tempdir(dir=snapshot_directory) as tmpdir:
            try:
                out_path = os.path.join(tmpdir, uuid.uuid4().hex)

                images.fetch(context, image_meta['id'], out_path,
                             instance['user_id'], instance['project_id'])
                self.docker.load_repository_file(image_meta['name'], out_path)
            except Exception as e:
                msg = _('Cannot load repository file: {0}')
                raise exception.NovaException(msg.format(e),
                                              instance_id=image_meta['name'])

        return self.docker.inspect_image(image_meta['name'])

    def _start_container(self, instance, network_info=None):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return

        self.docker.start_container(container_id)
        try:
            self.plug_vifs(instance, network_info)
            self._attach_vifs(instance, network_info)
        except Exception as e:
            msg = _('Cannot setup network: {0}')
            self.docker.kill_container(container_id)
            self.docker.destroy_container(container_id)
            raise exception.InstanceDeployFailure(msg.format(e),
                                                  instance_id=instance['name'])

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        image_name = self._get_image_name(context, instance, image_meta)
        args = {
            'Hostname': instance['name'],
            'Image': image_name,
            'Memory': self._get_memory_limit_bytes(instance),
            'CpuShares': self._get_cpu_shares(instance),
            'NetworkDisabled': True,
        }

        image = self.docker.inspect_image(image_name)
        if not image:
            image = self._pull_missing_image(context, image_meta, instance)
        if not (image and image['ContainerConfig']['Cmd']):
            args['Cmd'] = ['sh']
        # Glance command-line overrides any set in the Docker image
        if (image_meta and
                image_meta.get('properties', {}).get('os_command_line')):
            args['Cmd'] = image_meta['properties'].get('os_command_line')

        container_id = self._create_container(instance, args)
        if not container_id:
            raise exception.InstanceDeployFailure(
                _('Cannot create container'),
                instance_id=instance['name'])

        self._start_container(instance, network_info)

    def restore(self, instance):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return

        self._start_container(instance)

    def soft_delete(self, instance):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return
        self.docker.stop_container(container_id)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        self.soft_delete(instance)
        self.cleanup(context, instance, network_info,
                     block_device_info, destroy_disks)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Cleanup after instance being destroyed by Hypervisor."""
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return
        self.docker.destroy_container(container_id)
        network.teardown_network(container_id)
        self.unplug_vifs(instance, network_info)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return
        if not self.docker.stop_container(container_id):
            LOG.warning(_('Cannot stop the container, '
                          'please check docker logs'))
            return
        try:
            network.teardown_network(container_id)
            self.unplug_vifs(instance, network_info)
        except Exception:
            LOG.debug('Cannot destroy the container network during reboot')
            return

        if not self.docker.start_container(container_id):
            LOG.warning(_('Cannot restart the container, '
                          'please check docker logs'))
            return
        try:
            self.plug_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot setup network on reboot: {0}').format(e))
            return

    def power_on(self, context, instance, network_info, block_device_info):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return
        self.docker.start_container(container_id)
        try:
            self.plug_vifs(instance, network_info)
            self._attach_vifs(instance, network_info)
        except Exception as e:
            msg = _('Cannot setup network: {0}')
            self.docker.kill_container(container_id)
            self.docker.destroy_container(container_id)
            raise exception.InstanceDeployFailure(msg.format(e),
                                                  instance_id=instance['name'])

    def power_off(self, instance, timeout=0, retry_interval=0):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            return
        self.docker.stop_container(container_id, timeout)

    def pause(self, instance):
        """Pause the specified instance.

        :param instance: nova.objects.instance.Instance
        """
        try:
            cont_id = self._find_container_by_name(instance['name']).get('id')
            if not self.docker.pause_container(cont_id):
                raise exception.NovaException
        except Exception as e:
            msg = _('Cannot pause container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance['name'])

    def unpause(self, instance):
        """Unpause paused VM instance.

        :param instance: nova.objects.instance.Instance
        """
        try:
            cont_id = self._find_container_by_name(instance['name']).get('id')
            if not self.docker.unpause_container(cont_id):
                raise exception.NovaException
        except Exception as e:
            msg = _('Cannot unpause container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance['name'])

    def get_console_output(self, context, instance):
        container_id = self._find_container_by_name(instance.name).get('id')
        if not container_id:
            return
        return self.docker.get_container_logs(container_id)

    def snapshot(self, context, instance, image_href, update_task_state):
        container_id = self._find_container_by_name(instance['name']).get('id')
        if not container_id:
            raise exception.InstanceNotRunning(instance_id=instance['uuid'])

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
        (image_service, image_id) = glance.get_remote_image_service(
            context, image_href)
        image = image_service.show(context, image_id)
        name = image['name']
        default_tag = (':' not in name)
        commit_name = name if not default_tag else name + ':latest'

        self.docker.commit_container(container_id, commit_name)

        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)

        metadata = {
            'is_public': False,
            'status': 'active',
            'disk_format': 'raw',
            'container_format': 'docker',
            'name': name,
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
            fh = self.docker.get_image_resp(commit_name)
            image_service.update(context, image_href, metadata, fh)
        except Exception as e:
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

    def _create_container(self, instance, args):
        name = "nova-" + instance['uuid']
        return self.docker.create_container(args, name)

    def get_host_uptime(self, host):
        return hostutils.sys_uptime()
