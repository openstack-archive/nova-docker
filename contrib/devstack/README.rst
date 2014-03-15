The contrib/devstack/ directory contains the files necessary to integrate Docker Nova driver with devstack.

To install::

    $ git clone ...  /opt/stack/novadocker
    $ cd /opt/stack/novadocker
    $ DEVSTACK_DIR=.../path/to/devstack
    $ cp contrib/devstack/lib/nova_plugins/hypervisor-docker ${DEVSTACK_DIR}/lib/nova_plugins/
    $ cp contrib/devstack/extras.d/70-docker.sh ${DEVSTACK_DIR}/extras.d/

To configure devstack to run docker nova driver::

    $ cd ${DEVSTACK_DIR}
    $ echo "VIRT_DRIVER=docker" >> ${DEVSTACK_DIR}/localrc
    $ echo "DOCKER_REGISTRY_IMAGE=samalba/docker-registry" >> ${DEVSTACK_DIR}/localrc
    # this is needed to work around stackrc trying to download wrong images.
    $ patch -p0 < /opt/stack/nova-docker/stackrc.diff

Run devstack as normal::

    $ ./stack.sh
