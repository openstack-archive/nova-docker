#!/bin/bash
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

# Save trace setting
XTRACE=$(set +o | grep xtrace)
set -o xtrace

DOCKER_UNIX_SOCKET=/var/run/docker.sock

# main loop
if [[ "$1" == "stack" && "$2" == "install" ]]; then
    echo_summary "Running stack install"
elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
    echo_summary "Running stack post-config"
    wget http://get.docker.com -O install_docker.sh
    sudo chmod 777 install_docker.sh
    sudo bash -x install_docker.sh
    sudo rm install_docker.sh

    if is_fedora; then
      install_package socat dnsmasq
     fi

    # CentOS/RedHat distros don't start the services just after the package
    # is installed if it is not explicitily set. So the script fails on
    # them in this killall because there is nothing to kill.
    sudo killall docker || true

    # Enable debug level logging
    if [ -f "/etc/default/docker" ]; then
        sudo cat /etc/default/docker
        sudo sed -i 's/^.*DOCKER_OPTS=.*$/DOCKER_OPTS=\"--debug --storage-opt dm.override_udev_sync_check=true\"/' /etc/default/docker
        sudo cat /etc/default/docker
    fi
    if [ -f "/etc/sysconfig/docker" ]; then
        sudo cat /etc/sysconfig/docker
        sudo sed -i 's/^.*OPTIONS=.*$/OPTIONS=--debug --selinux-enabled/' /etc/sysconfig/docker
        sudo cat /etc/sysconfig/docker
    fi
    if [ -f "/usr/lib/systemd/system/docker.service" ]; then
        sudo cat /usr/lib/systemd/system/docker.service
        sudo sed -i 's/docker daemon/docker daemon --debug/' /usr/lib/systemd/system/docker.service
        sudo cat /usr/lib/systemd/system/docker.service
        sudo systemctl daemon-reload
    fi

    # Start the daemon - restart just in case the package ever auto-starts...
    restart_service docker

    echo "Waiting for docker daemon to start..."
    DOCKER_GROUP=$(groups | cut -d' ' -f1)
    CONFIGURE_CMD="while ! /bin/echo -e 'GET /version HTTP/1.0\n\n' | socat - unix-connect:$DOCKER_UNIX_SOCKET 2>/dev/null | grep -q '200 OK'; do
      # Set the right group on docker unix socket before retrying
      sudo chgrp $DOCKER_GROUP $DOCKER_UNIX_SOCKET
      sudo chmod g+rw $DOCKER_UNIX_SOCKET
      sleep 1
    done"
    if ! timeout $SERVICE_TIMEOUT sh -c "$CONFIGURE_CMD"; then
      die $LINENO "docker did not start"
    fi
fi
if [[ "$1" == "unstack" ]]; then
    echo_summary "Running unstack"
    stop_service docker
fi

# Restore xtrace
$XTRACE