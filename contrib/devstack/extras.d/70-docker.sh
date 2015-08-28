# docker.sh - Devstack extras script to install Docker

if [[ $VIRT_DRIVER == "docker" ]]; then

  if [[ $1 == "source" ]]; then

    # Keep track of the current directory
    SCRIPT_DIR=$(cd $(dirname "$0") && pwd)
    TOP_DIR=$SCRIPT_DIR

    echo $SCRIPT_DIR $TOP_DIR

    # Import common functions
    source $TOP_DIR/functions

    # Load local configuration
    source $TOP_DIR/stackrc

    FILES=$TOP_DIR/files

    # Get our defaults
    source $TOP_DIR/lib/nova_plugins/hypervisor-docker

  elif [[ $2 == "install" ]] ; then

    # Install docker package and images
    # * downloads a base busybox image and a glance registry image if necessary
    # * install the images in Docker's image cache


    SERVICE_TIMEOUT=${SERVICE_TIMEOUT:-60}


    # Install Docker Service
    # ======================

    if is_fedora; then
      install_package docker-io socat dnsmasq
    else
      # Stop the auto-repo updates and do it when required here
      NO_UPDATE_REPOS=True

      # Set up home repo
      curl -sSL https://get.docker.com/gpg | sudo apt-key add -
      install_package python-software-properties && \
          sudo sh -c "echo deb $DOCKER_APT_REPO ubuntu-trusty main > /etc/apt/sources.list.d/docker.list"
      apt_get update
      install_package --force-yes docker-engine socat
    fi

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
fi


