# Copyright (c) 2013 dotCloud, Inc.
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

from docker import client


class DockerHTTPClient(client.Client):
    def __init__(self):
        super(DockerHTTPClient, self).__init__(
            base_url='unix://var/run/docker.sock',
            version='1.7',
            timeout=10
        )

    def pause_container(self, container_id):
        url = self._url("/containers/{0}/pause".format(container_id))
        res = self._post(url)
        return (res.status_code == 204)

    def unpause_container(self, container_id):
        url = self._url("/containers/{0}/unpause".format(container_id))
        res = self._post(url)
        return (res.status_code == 204)

    def load_repository_file(self, name, path):
        with open(path) as fh:
            self.load_image(fh)

    def get_container_logs(self, container_id):
        params = {
            'logs': 1,
            'stdout': 1,
            'stderr': 1,
            'stream': 0
        }
        return self.attach_socket(container_id, params)