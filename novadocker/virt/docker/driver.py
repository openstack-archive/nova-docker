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
import shutil
import socket
import time
import uuid

from docker import errors
from docker import utils as docker_utils
import eventlet
from oslo_config import cfg
from oslo_log import log
from oslo_utils import fileutils
from oslo_utils import importutils
from oslo_utils import units
from oslo_utils import versionutils

from nova.compute import arch
from nova.compute import flavors
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova import exception
from nova.image import glance
from nova import objects
from nova import utils
from nova import utils as nova_utils
from nova.virt import driver
from nova.virt import firewall
from nova.virt import hardware
from nova.virt import images
from novadocker.i18n import _, _LI, _LE, _LW
from novadocker.virt.docker import client as docker_client
from novadocker.virt.docker import hostinfo
from novadocker.virt.docker import network
from novadocker.virt import hostutils

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.conf.netconf')
CONF.import_opt('instances_path', 'nova.compute.manager')

docker_opts = [
    cfg.StrOpt('root_directory',
               default='/var/lib/docker',
               help='Path to use as the root of the Docker runtime.'),
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
                    'snapshots.'),
    cfg.BoolOpt('inject_key',
                default=False,
                help='Inject the ssh public key at boot time'),
    cfg.StrOpt('shared_directory',
               default=None,
               help='Shared directory where glance images located. If '
                    'specified, docker will try to load the image from '
                    'the shared directory by image ID.'),
    cfg.BoolOpt('privileged',
                default=False,
                help='Set true can own all root privileges in a container.'),
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
        # NOTE(zhangguoqing): For passing the nova unit tests
        self.active_migrations = {}

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

    def attach_interface(self, instance, image_meta, vif):
        """Attach an interface to the container."""
        self.vif_driver.plug(instance, vif)
        container_id = self._find_container_by_uuid(instance['uuid']).get('id')
        self.vif_driver.attach(instance, vif, container_id)

    def detach_interface(self, instance, vif):
        """Detach an interface from the container."""
        self.vif_driver.unplug(instance, vif)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for vif in network_info:
            self.vif_driver.plug(instance, vif)
        self._start_firewall(instance, network_info)

    def _attach_vifs(self, instance, network_info):
        """Plug VIFs into container."""
        if not network_info:
            return

        if os.name == 'nt':
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
        utils.execute('ip', 'netns', 'exec', container_id, 'ip', 'link',
                      'set', 'lo', 'up', run_as_root=True)

        for vif in network_info:
            self.vif_driver.attach(instance, vif, container_id)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)
        self._stop_firewall(instance, network_info)

    def _encode_utf8(self, value):
        return unicode(value).encode('utf-8')

    def _find_container_by_uuid(self, uuid):
        try:
            name = "nova-" + uuid
            containers = self.docker.containers(all=True,
                                                filters={'name': name})
            if containers:
                # NOTE(dims): We expect only one item in the containers list
                return self.docker.inspect_container(containers[0]['id'])
        except errors.APIError as e:
            if e.response.status_code != 404:
                raise
        return {}

    def _get_container_id(self, instance):
        return self._find_container_by_uuid(instance['uuid']).get('id')

    def get_info(self, instance):
        container = self._find_container_by_uuid(instance['uuid'])
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
        info = hardware.InstanceInfo(
            max_mem_kb=mem,
            mem_kb=mem,
            num_cpu=num_cpu,
            cpu_time_ns=0,
            state=(power_state.RUNNING if running
                   else power_state.SHUTDOWN)
        )
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
            'vcpus': hostinfo.get_total_vcpus(),
            'vcpus_used': hostinfo.get_vcpus_used(self.list_instances(True)),
            'memory_mb': memory['total'] / units.Mi,
            'memory_mb_used': memory['used'] / units.Mi,
            'local_gb': disk['total'] / units.Gi,
            'local_gb_used': disk['used'] / units.Gi,
            'disk_available_least': disk['available'] / units.Gi,
            'hypervisor_type': 'docker',
            'hypervisor_version': versionutils.convert_version_to_int('1.0'),
            'hypervisor_hostname': self._nodename,
            'cpu_info': '?',
            'numa_topology': None,
            'supported_instances': [
                (arch.I686, hv_type.DOCKER, vm_mode.EXE),
                (arch.X86_64, hv_type.DOCKER, vm_mode.EXE)
            ]
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
        if isinstance(instance, objects.Instance):
            return instance.get_flavor().memory_mb * units.Mi
        else:
            system_meta = utils.instance_sys_meta(instance)
            return int(system_meta.get(
                'instance_type_memory_mb', 0)) * units.Mi

    def _get_image_name(self, context, instance, image):
        fmt = image.container_format
        if fmt != 'docker':
            msg = _('Image container format not supported ({0})')
            raise exception.InstanceDeployFailure(msg.format(fmt),
                                                  instance_id=instance['name'])
        return image.name

    def _pull_missing_image(self, context, image_meta, instance):
        msg = 'Image name "%s" does not exist, fetching it...'
        LOG.debug(msg, image_meta.name)

        shared_directory = CONF.docker.shared_directory
        if (shared_directory and
                os.path.exists(os.path.join(shared_directory,
                                            image_meta.id))):
            LOG.debug('Found %s in shared_directory', image_meta.id)
            try:
                LOG.debug('Loading repository file into docker %s',
                          self._encode_utf8(image_meta.name))
                self.docker.load_repository_file(
                    self._encode_utf8(image_meta.name),
                    os.path.join(shared_directory, image_meta.id))
                return self.docker.inspect_image(
                    self._encode_utf8(image_meta.name))
            except Exception as e:
                # If failed to load image from shared_directory, continue
                # to download the image from glance then load.
                LOG.warning(_('Cannot load repository file from shared '
                              'directory: %s'),
                            e, instance=instance, exc_info=True)

        # TODO(imain): It would be nice to do this with file like object
        # passing but that seems a bit complex right now.
        snapshot_directory = CONF.docker.snapshots_directory
        fileutils.ensure_tree(snapshot_directory)
        with utils.tempdir(dir=snapshot_directory) as tmpdir:
            try:
                out_path = os.path.join(tmpdir, uuid.uuid4().hex)

                LOG.debug('Fetching image with id %s from glance',
                          image_meta.id)
                images.fetch(context, image_meta.id, out_path,
                             instance['user_id'], instance['project_id'])
                LOG.debug('Loading repository file into docker %s',
                          self._encode_utf8(image_meta.name))
                self.docker.load_repository_file(
                    self._encode_utf8(image_meta.name),
                    out_path
                )
                return self.docker.inspect_image(
                    self._encode_utf8(image_meta.name))
            except Exception as e:
                LOG.warning(_('Cannot load repository file: %s'),
                            e, instance=instance, exc_info=True)
                msg = _('Cannot load repository file: {0}')
                raise exception.NovaException(msg.format(e),
                                              instance_id=image_meta.name)

    def _extract_dns_entries(self, network_info):
        dns = []
        if network_info:
            for net in network_info:
                subnets = net['network'].get('subnets', [])
                for subnet in subnets:
                    dns_entries = subnet.get('dns', [])
                    for dns_entry in dns_entries:
                        if 'address' in dns_entry:
                            dns.append(dns_entry['address'])
        return dns if dns else None

    def _get_key_binds(self, container_id, instance):
        binds = None
        # Handles the key injection.
        if CONF.docker.inject_key and instance.get('key_data'):
            key = str(instance['key_data'])
            mount_origin = self._inject_key(container_id, key)
            binds = {mount_origin: {'bind': '/root/.ssh', 'ro': True}}
        return binds

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid},
                  instance=instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _get_neutron_events(self, network_info):
        # NOTE(danms): We need to collect any VIFs that are currently
        # down that we expect a down->up event for. Anything that is
        # already up will not undergo that transition, and for
        # anything that might be stale (cache-wise) assume it's
        # already up so we don't block on it.
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _start_container(self, container_id, instance, network_info=None):
        binds = self._get_key_binds(container_id, instance)
        dns = self._extract_dns_entries(network_info)
        self.docker.start(container_id, binds=binds, dns=dns,
                          privileged=CONF.docker.privileged)

        if not network_info:
            return
        timeout = CONF.vif_plugging_timeout
        if (utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = []

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self.plug_vifs(instance, network_info)
                self._attach_vifs(instance, network_info)
        except eventlet.timeout.Timeout:
            LOG.warn(_LW('Timeout waiting for vif plugging callback for '
                         'instance %(uuid)s'), {'uuid': instance['name']})
            if CONF.vif_plugging_is_fatal:
                self.docker.kill(container_id)
                self.docker.remove_container(container_id, force=True)
                raise exception.InstanceDeployFailure(
                    'Timeout waiting for vif plugging',
                    instance_id=instance['name'])
        except (Exception) as e:
            LOG.warning(_('Cannot setup network: %s'),
                        e, instance=instance, exc_info=True)
            msg = _('Cannot setup network: {0}')
            self.docker.kill(container_id)
            self.docker.remove_container(container_id, force=True)
            raise exception.InstanceDeployFailure(msg.format(e),
                                                  instance_id=instance['name'])

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              flavor=None):
        image_name = self._get_image_name(context, instance, image_meta)
        args = {
            'hostname': instance['name'],
            'mem_limit': self._get_memory_limit_bytes(instance),
            'cpu_shares': self._get_cpu_shares(instance),
            'network_disabled': True,
        }

        try:
            image = self.docker.inspect_image(self._encode_utf8(image_name))
        except errors.APIError:
            image = None

        if not image:
            image = self._pull_missing_image(context, image_meta, instance)
        # Glance command-line overrides any set in the Docker image
        if (image_meta is not None and
                image_meta.properties.get("os_command_line") is not None):
            args['command'] = image_meta.properties.get("os_command_line")

        if 'metadata' in instance:
            args['environment'] = nova_utils.instance_meta(instance)

        container_id = self._create_container(instance, image_name, args)
        if not container_id:
            raise exception.InstanceDeployFailure(
                _('Cannot create container'),
                instance_id=instance['name'])

        self._start_container(container_id, instance, network_info)

    def _inject_key(self, id, key):
        if isinstance(id, dict):
            id = id.get('id')
        sshdir = os.path.join(CONF.instances_path, id, '.ssh')
        key_data = ''.join([
            '\n',
            '# The following ssh key was injected by Nova',
            '\n',
            key.strip(),
            '\n',
        ])
        fileutils.ensure_tree(sshdir)
        keys_file = os.path.join(sshdir, 'authorized_keys')
        with open(keys_file, 'a') as f:
            f.write(key_data)
        os.chmod(sshdir, 0o700)
        os.chmod(keys_file, 0o600)
        return sshdir

    def _cleanup_key(self, instance, id):
        if isinstance(id, dict):
            id = id.get('id')
        dir = os.path.join(CONF.instances_path, id)
        if os.path.exists(dir):
            LOG.info(_LI('Deleting instance files %s'), dir,
                     instance=instance)
            try:
                shutil.rmtree(dir)
            except OSError as e:
                LOG.error(_LE('Failed to cleanup directory %(target)s: '
                              '%(e)s'), {'target': dir, 'e': e},
                          instance=instance)

    def restore(self, instance):
        container_id = self._get_container_id(instance)
        if not container_id:
            return

        self._start_container(container_id, instance)

    def _stop(self, container_id, instance, timeout=5):
        try:
            self.docker.stop(container_id, max(timeout, 5))
        except errors.APIError as e:
            if 'Unpause the container before stopping' not in e.explanation:
                LOG.warning(_('Cannot stop container: %s'),
                            e, instance=instance, exc_info=True)
                raise
            self.docker.unpause(container_id)
            self.docker.stop(container_id, timeout)

    def soft_delete(self, instance):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self._stop(container_id, instance)

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
            self.unplug_vifs(instance, network_info)
            return
        self.docker.remove_container(container_id, force=True)
        network.teardown_network(container_id)
        self.unplug_vifs(instance, network_info)
        if CONF.docker.inject_key:
            self._cleanup_key(instance, container_id)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        self._stop(container_id, instance)
        try:
            network.teardown_network(container_id)
            if network_info:
                self.unplug_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot destroy the container network'
                          ' during reboot {0}').format(e),
                        exc_info=True)
            return

        binds = self._get_key_binds(container_id, instance)
        dns = self._extract_dns_entries(network_info)
        self.docker.start(container_id, binds=binds, dns=dns)
        try:
            if network_info:
                self.plug_vifs(instance, network_info)
                self._attach_vifs(instance, network_info)
        except Exception as e:
            LOG.warning(_('Cannot setup network on reboot: {0}'), e,
                        exc_info=True)
            return

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        container_id = self._get_container_id(instance)
        if not container_id:
            return
        binds = self._get_key_binds(container_id, instance)
        dns = self._extract_dns_entries(network_info)
        self.docker.start(container_id, binds=binds, dns=dns)
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
        self._stop(container_id, instance, timeout)

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
            return ''
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
        if isinstance(instance, objects.Instance):
            flavor = instance.get_flavor()
        else:
            flavor = flavors.extract_flavor(instance)
        return int(flavor['vcpus']) * 1024

    def _create_container(self, instance, image_name, args):
        name = "nova-" + instance['uuid']
        hostname = args.pop('hostname', None)
        cpu_shares = args.pop('cpu_shares', None)
        network_disabled = args.pop('network_disabled', False)
        environment = args.pop('environment', None)
        command = args.pop('command', None)
        host_config = docker_utils.create_host_config(**args)
        return self.docker.create_container(image_name,
                                            name=self._encode_utf8(name),
                                            hostname=hostname,
                                            cpu_shares=cpu_shares,
                                            network_disabled=network_disabled,
                                            environment=environment,
                                            command=command,
                                            host_config=host_config)

    def get_host_uptime(self):
        return hostutils.sys_uptime()
