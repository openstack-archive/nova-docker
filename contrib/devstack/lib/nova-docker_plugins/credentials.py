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

import os
import variables


def get_keystone_creds():
    d = {}
    env = os.environ.get('OS_USERNAME')
    if env is None:
        d['username'] = variables.username
        d['password'] = variables.password
        d['auth_url'] = variables.auth_url
        d['tenant_name'] = variables.tenant_name
    else:
        d['username'] = os.environ['OS_USERNAME']
        d['password'] = os.environ['OS_PASSWORD']
        d['auth_url'] = os.environ['OS_AUTH_URL']
        d['tenant_name'] = os.environ['OS_TENANT_NAME']
    return d


def get_nova_creds():
    d = {}
    env = os.environ.get('OS_USERNAME')
    if env is None:
        d['username'] = variables.username
        d['api_key'] = variables.password
        d['auth_url'] = variables.auth_url
        d['project_id'] = variables.tenant_name
    else:
        d['username'] = os.environ['OS_USERNAME']
        d['api_key'] = os.environ['OS_PASSWORD']
        d['auth_url'] = os.environ['OS_AUTH_URL']
        d['project_id'] = os.environ['OS_TENANT_NAME']
    return d


def get_glance_creds():
    env = os.environ.get('GLANCE_ENDPOINT')
    if env is None:
        d = variables.glance_endpoint
    else:
        d = os.environ['GLANCE_ENDPOINT']
    return d


def get_master_creds():
    d = {}
    d['username'] = variables.master_user
    if variables.master_pass is None:
        d['key_filename'] = variables.master_key
    else:
        d['password'] = variables.master_pass
    return d


def get_master_ip():
    return master_ip


def get_env_vars():
    d = {}
    d['floating_ip_pool'] = variables.floating_ip_pool
    return d
