===============================
nova-docker
===============================

Docker driver for OpenStack Nova.

Free software: Apache license

----------------------------
Installation & Configuration
----------------------------

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
1. Clone the nova-docker repo.
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Clone the Repo::

  $ git clone https://github.com/stackforge/nova-docker.git
  $ cd nova-docker

For Icehouse Release::

  $ git checkout 9045ca4

For Juno Release::

  $ git checkout 2f23a09




^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2. Install the python modules.
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For example::

  $ python setup.py install

Note: There are better and cleaner ways of managing Python modules, such as using distribution packages or 'pip'. The setup.py file and Debian's stdeb, for instance, may be used to create Debian/Ubuntu packages.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
3. Enable the driver in Nova's configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In nova.conf::

  compute_driver=novadocker.virt.docker.DockerDriver

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
4. Optionally tune site-specific settings.
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In nova.conf::

  [docker]
  # Commented out. Uncomment these if you'd like to customize:
  ## vif_driver=novadocker.virt.docker.vifs.DockerGenericVIFDriver
  ## snapshots_directory=/var/tmp/my-snapshot-tempdir

--------------------------
Uploading Images to Glance
--------------------------

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
1. Enable the driver in Glance's configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In glance-api.conf::

  container_formats=ami,ari,aki,bare,ovf,ova,docker

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2. Save docker images to Glance
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Images may now be saved directly to Glance::

  $ docker pull busybox
  $ docker save busybox | glance image-create --is-public=True --container-format=docker --disk-format=raw --name busybox

**Note:** At present, only administrators should be allowed to manage images.  With devstack you can make yourself administrator by sourcing openrc as::

  source openrc admin

Once done you can go back to a user::

  source openrc demo

The name of the image in Glance should be explicitly set to the same name as the image as it is known to Docker. In the example above, an image has been tagged in Docker as 'busybox'. Matching this is the '--name busybox' argument to *glance image-create*. If these names do not align, the image will not be bootable.

^^^^^^^^^^^^^^^^^^^^^
3. Generate a keypair
^^^^^^^^^^^^^^^^^^^^^

You can optionally create a keypair to use in your docker images::

  nova keypair-add mykey > mykey.pem

^^^^^^^^^^^^^^^^^^^^^
4. Start a container
^^^^^^^^^^^^^^^^^^^^^

Start a new container.  This uses the key created above::

  nova boot --flavor m1.small --image cirros --key-name mykey test1

^^^^^^^^^^^^^^^^^^^^^
5. ssh into container
^^^^^^^^^^^^^^^^^^^^^

You can check the IP address of the container by using::

  nova list

And then ssh into it::

  ssh -i ../devstack/mykey.pem cirros@<IP ADDRESS>

-----
Notes
-----

* Earlier releases of this driver required the deployment of a private docker registry. This is no longer required. Images are now saved and loaded from Glance.
* Images loaded from Glance may do bad things. Only allow administrators to add images. Users may create snapshots of their containers, generating images in Glance -- these images are managed and thus safe.

----------
Contact Us
----------
Join us in #nova-docker on Freenode IRC

--------
Features
--------

* TODO
