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

import errno


from oslo_concurrency import processutils
from oslo_log import log as logging

from nova.i18n import _
from nova.i18n import _LW
from nova import utils
from nova.virt import volumeutils

LOG = logging.getLogger(__name__)


def execute(*args, **kwargs):
    return utils.execute(*args, **kwargs)


def get_iscsi_initiator():
    return volumeutils.get_iscsi_initiator()


def get_fc_hbas():
    """Get the Fibre Channel HBA information."""
    out = None
    try:
        out, err = execute('systool', '-c', 'fc_host', '-v',
                           run_as_root=True)
    except processutils.ProcessExecutionError as exc:
        # This handles the case where rootwrap is used
        # and systool is not installed
        # 96 = nova.cmd.rootwrap.RC_NOEXECFOUND:
        if exc.exit_code == 96:
            LOG.warn(_LW("systool is not installed"))
        return []
    except OSError as exc:
        # This handles the case where rootwrap is NOT used
        # and systool is not installed
        if exc.errno == errno.ENOENT:
            LOG.warn(_LW("systool is not installed"))
        return []

    if out is None:
        raise RuntimeError(_("Cannot find any Fibre Channel HBAs"))

    lines = out.split('\n')
    # ignore the first 2 lines
    lines = lines[2:]
    hbas = []
    hba = {}
    lastline = None
    for line in lines:
        line = line.strip()
        # 2 newlines denotes a new hba port
        if line == '' and lastline == '':
            if len(hba) > 0:
                hbas.append(hba)
                hba = {}
        else:
            val = line.split('=')
            if len(val) == 2:
                key = val[0].strip().replace(" ", "")
                value = val[1].strip()
                hba[key] = value.replace('"', '')
        lastline = line

    return hbas


def get_fc_wwpns():
    """Get Fibre Channel WWPNs from the system, if any."""
    # Note modern linux kernels contain the FC HBA's in /sys
    # and are obtainable via the systool app
    hbas = get_fc_hbas()

    wwpns = []
    if hbas:
        for hba in hbas:
            if hba['port_state'] == 'Online':
                wwpn = hba['port_name'].replace('0x', '')
                wwpns.append(wwpn)

    return wwpns


def get_fc_wwnns():
    """Get Fibre Channel WWNNs from the system, if any."""
    # Note modern linux kernels contain the FC HBA's in /sys
    # and are obtainable via the systool app
    hbas = get_fc_hbas()

    wwnns = []
    if hbas:
        for hba in hbas:
            if hba['port_state'] == 'Online':
                wwnn = hba['node_name'].replace('0x', '')
                wwnns.append(wwnn)

    return wwnns
