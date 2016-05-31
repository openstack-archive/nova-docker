#!/usr/bin/env python

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from keystoneclient.v2_0 import client as keystoneClient
from keystoneclient import session as keystoneSession
from glanceclient import Client as glanceClient
from novaclient import client as novaClient
import credentials
import paramiko


class KeystoneManager(object):
    def __init__(self, **kwargs):
        """Get an endpoint and auth token from Keystone.
        :param username: name of user param password: user's password
        :param tenant_id: unique identifier of tenant
        :param tenant_name: name of tenant
        :param auth_url: endpoint to authenticate against
        :param token: token to use instead of username/password
        """
        kc_args = {}

        if kwargs.get('endpoint'):
            kc_args['endpoint'] = kwargs.get('auth_url')
        else:
            kc_args['auth_url'] = kwargs.get('auth_url')

        if kwargs.get('tenant_id'):
            kc_args['tenant_id'] = kwargs.get('tenant_id')
        else:
            kc_args['tenant_name'] = kwargs.get('tenant_name')

        if kwargs.get('token'):
            kc_args['token'] = kwargs.get('token')
        else:
            kc_args['username'] = kwargs.get('username')
            kc_args['password'] = kwargs.get('password')

        print (kc_args)

        self.ksclient = keystoneClient.Client(**kc_args)
        self.session = keystoneSession.Session(auth=self.ksclient)
        self.token = self.ksclient.auth_token
        self.tenant_id = self.ksclient.project_id
        self.tenant_name = self.ksclient.tenant_name
        self.username = self.ksclient.username
        self.password = self.ksclient.password
        self.project_id = self.ksclient.project_id
        self.auth_url = self.ksclient.auth_url

    def get_session(self):
        if self.session is None:
            self.session = keystoneSession.Session(auth=self.ksclient)
        return self.session

    def get_endpoint(self):
        if self.auth_url is None:
            self.auth_url = self.ksclient.auth_url
        return self.auth_url

    def get_token(self):
        if self.token is None:
            self.token = self.ksclient.auth_token
        return self.token

    def get_tenant_id(self):
        if self.tenant_id is None:
            self.tenant_id = self.ksclient.project_id
        return self.tenant_id

    def get_tenant_name(self):
        if self.tenant_name is None:
            self.tenant_name = self.ksclient.tenant_name
        return self.tenant_name

    def get_username(self):
        if self.username is None:
            self.username = self.ksclient.username
        return self.username

    def get_password(self):
        if self.password is None:
            self.password = self.ksclient.password
        return self.password

    def get_project_id(self):
        if self.project_id is None:
            self.project_id = self.ksclient.project_id
        return self.project_id


class NovaManager(object):
    def __init__(self, **kwargs):
        self.nova = novaClient.Client("2", **kwargs)
        self.docker_hypervisors = []

    def get_flavors(self):
        print (self.nova.flavors.list())
        return self.nova.flavors.list()

    def get_hypervisors_number(self):
        x = self.nova.hypervisors.list()
        print ("Number of hypervisors :", len(x))
        return len(x)

    def get_hypervisor_ip(self,id):
        return getattr(self.nova.hypervisors.get(id), "host_ip")

    def get_hypervisor_type(self,id):
        return getattr(self.nova.hypervisors.get(id), "hypervisor_type")

    def get_docker_hypervisors_ip(self):
        for x in range(1, novaManager.get_hypervisors_number()):
            if novaManager.get_hypervisor_type(x) == 'docker':
                self.docker_hypervisors.\
                    append(novaManager.get_hypervisor_ip(x))
        return self.docker_hypervisors

    def create_floating_ip(self):
        unused_floating_ips = 0
        y = None
        floating_ips_list = self.nova.floating_ips.list()
        for i in floating_ips_list:
            x = getattr(i, "fixed_ip")
            if x is None:
                unused_floating_ips += 1
        if unused_floating_ips == 0:
            y = self.nova.floating_ips.\
                create(credentials.get_env_vars()['floating_ip_pool'])
            print (y)
        return y


class GlanceManager(object):
    def __init__(self, **kwargs):
        kc_args = {}

        if kwargs.get('endpoint'):
            kc_args['endpoint'] = kwargs.get('endpoint')

        if kwargs.get('token'):
            kc_args['token'] = kwargs.get('token')

        print kc_args

        self.glclient = glanceClient('1', **kc_args)
        self.dockerimages = []

    def get_docker_images(self):
        imagelist = self.glclient.images.list()
        for i in imagelist:
            x = getattr(i, "container_format")
            if x == 'docker':
                imagename = getattr(i, "name")
                self.dockerimages.append(imagename)
        return self.dockerimages


class OpenStackManager(object):
    def __init__(self, **kwargs):
        print None

    def pull_docker_images(self):
        # Prefetch all docker images from Glance on all docker compute nodes.
        if credentials.get_keystone_creds()['username'] == 'admin':
            dockerIPs = novaManager.get_docker_hypervisors_ip()
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            print (credentials.get_master_creds())
            ssh.connect(credentials.get_master_ip(), **credentials.get_master_creds())
            for i in dockerIPs:
                print ('Docker hypervisor IP address:', i)
                for j in dockerimages:
                    ssh_stdin, ssh_stdout, ssh_stderr = \
                        ssh.exec_command("ssh %s 'docker pull %s'" % (i, j))
                    print (ssh_stdout.readlines())
            ssh.close()
        return None


if __name__ == '__main__':
    # Connect to Keystone
    kwargs = {}
    kwargs = credentials.get_keystone_creds()
    keystoneManager = KeystoneManager(**kwargs)

    # Get the list of the docker images names
    kwargs = {}
    kwargs['token'] = keystoneManager.get_token()
    kwargs['endpoint'] = credentials.get_glance_creds()
    glanceManager = GlanceManager(**kwargs)
    dockerimages = glanceManager.get_docker_images()

    # Connect to Nova
    kwargs = credentials.get_nova_creds()
    novaManager = NovaManager(**kwargs)

    openStackManager = OpenStackManager()

    # Prefetch all docker images from Glance on all docker compute nodes.
    openStackManager.pull_docker_images()
