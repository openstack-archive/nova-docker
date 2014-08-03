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

import time
import uuid

from nova.openstack.common import timeutils
import novadocker.virt.docker.client as docker_client


class MockClient(object):
    def __init__(self, endpoint=None):
        self._containers = {}
        self.name = None

        # Fake repository
        self._repository = {'image_with_cmd':
                            {'ContainerConfig':
                             {'Cmd': 'echo Test'}},
                            'image_without_cmd':
                            {'ContainerConfig':
                             {'Cmd': None}}}
        self._images = {}
        self._image_data = {}

    def _fake_id(self):
        return uuid.uuid4().hex + uuid.uuid4().hex

    def _image_name(self, image_name):
        """Split full image name to host and image name."""
        if '/' in image_name:
            host, image_name = image_name.split('/', 1)
        return image_name

    def _is_image_exists(self, image_name):
        """Check whether Images is listed in self._repository."""
        image_name = self._image_name(image_name)
        if image_name in self._repository:
            return image_name in self._images
        return True

    def _is_daemon_running(self):
        return True

    @docker_client.filter_data
    def list_containers(self, _all=True):
        containers = []
        for container_id in self._containers.iterkeys():
            containers.append({
                'Status': 'Exit 0',
                'Created': int(time.time()),
                'Image': 'ubuntu:12.04',
                'Ports': '',
                'Command': 'bash ',
                'Id': container_id
            })
        return containers

    def create_container(self, args, name):
        self.name = name
        data = {
            'Hostname': '',
            'User': '',
            'Memory': 0,
            'MemorySwap': 0,
            'AttachStdin': False,
            'AttachStdout': False,
            'AttachStderr': False,
            'PortSpecs': None,
            'Tty': True,
            'OpenStdin': True,
            'StdinOnce': False,
            'Env': None,
            'Cmd': [],
            'Dns': None,
            'Image': None,
            'Volumes': {},
            'VolumesFrom': ''
        }
        data.update(args)
        if not self._is_image_exists(args['Image']):
            return None
        container_id = self._fake_id()
        self._containers[container_id] = {
            'id': container_id,
            'running': False,
            'config': data
        }
        return container_id

    def start_container(self, container_id):
        if container_id not in self._containers:
            return False
        self._containers[container_id]['running'] = True
        return True

    @docker_client.filter_data
    def inspect_image(self, image_name):
        if not self._is_image_exists(image_name):
            return None

        image_name = self._image_name(image_name)
        if image_name in self._images:
            return self._images[image_name]
        return {'ContainerConfig': {'Cmd': None}}

    @docker_client.filter_data
    def inspect_container(self, container_id):
        if container_id not in self._containers:
            return
        container = self._containers[container_id]
        info = {
            'Args': [],
            'Config': container['config'],
            'Created': str(timeutils.utcnow()),
            'ID': container_id,
            'Image': self._fake_id(),
            'NetworkSettings': {
                'Bridge': '',
                'Gateway': '',
                'IPAddress': '',
                'IPPrefixLen': 0,
                'PortMapping': None
            },
            'Path': 'bash',
            'ResolvConfPath': '/etc/resolv.conf',
            'State': {
                'ExitCode': 0,
                'Ghost': False,
                'Pid': 0,
                'Running': container['running'],
                'StartedAt': str(timeutils.utcnow())
            },
            'SysInitPath': '/tmp/docker',
            'Volumes': {},
        }
        return info

    def stop_container(self, container_id, timeout=None):
        if container_id not in self._containers:
            return False
        self._containers[container_id]['running'] = False
        return True

    def kill_container(self, container_id):
        if container_id not in self._containers:
            return False
        self._containers[container_id]['running'] = False
        return True

    def destroy_container(self, container_id):
        if container_id not in self._containers:
            return False

        # Docker doesn't allow to destroy a running container.
        if self._containers[container_id]['running']:
            return False

        del self._containers[container_id]
        return True

    def unpause_container(self, container_id):
        if container_id not in self._containers:
            return False

        self._containers[container_id]['paused'] = False
        return True

    def pause_container(self, container_id):
        if container_id not in self._containers:
            return False

        self._containers[container_id]['paused'] = True
        return True

    def pull_repository(self, name):
        image_name = self._image_name(name)
        if image_name in self._repository:
            self._images[image_name] = self._repository[image_name]
        return True

    def push_repository(self, name, headers=None):
        return True

    def commit_container(self, container_id, name):
        if container_id not in self._containers:
            return False
        return True

    def get_container_logs(self, container_id):
        if container_id not in self._containers:
            return False
        return '\n'.join([
            'Lorem ipsum dolor sit amet, consectetur adipiscing elit. ',
            'Vivamus ornare mi sit amet orci feugiat, nec luctus magna ',
            'vehicula. Quisque diam nisl, dictum vitae pretium id, ',
            'consequat eget sapien. Ut vehicula tortor non ipsum ',
            'consectetur, at tincidunt elit posuere. In ut ligula leo. ',
            'Donec eleifend accumsan mi, in accumsan metus. Nullam nec ',
            'nulla eu risus vehicula porttitor. Sed purus ligula, ',
            'placerat nec metus a, imperdiet viverra turpis. Praesent ',
            'dapibus ornare massa. Nam ut hendrerit nunc. Interdum et ',
            'malesuada fames ac ante ipsum primis in faucibus. ',
            'Fusce nec pellentesque nisl.'])

    def get_image(self, name):
        if (name not in self._images or
           name not in self._image_data):
            raise Exception
        return self._image_data[name]

    def get_image_resp(self, name):
        return open('/dev/null', 'rb')

    def save_repository_file(self, name, path):
        with open(path, 'w+'):
            pass

    def load_repository(self, name, data):
        self._image_data[name] = data

    def load_repository_file(self, name, path):
        pass

    def ping(self):
        return True
