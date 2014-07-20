#!/usr/bin/python

from subprocess import call
import os
import sys
import time

from jinja2 import Environment, PackageLoader
import etcd


env = Environment(loader=PackageLoader('haproxy', 'templates'))
POLL_TIMEOUT = 5


def get_etcd_addr():
    """
    Determine the host and port that etcd should be available on using the
    `ETCD_HOST` environment variable..

    :returns:
        A 2-tuple with the hostname/IP and the numeric TCP port at which etcd
        can be reached.

    """

    etcd_host = os.environ.get("ETCD_HOST", None)
    if not etcd_host:
        print("ETCD_HOST not set")
        sys.exit(1)

    host, port = etcd_host, 4001
    if ":" in host:
        host, port = host.split(":")

    return host, int(port)


def get_services():
    """
    Find all services which have been published to etcd and have exposed a
    port.

    :returns:
        A dictionary of dictionaries keyed on service name. The inner
        dictionary includes the TCP port that the service uses, along with a
        list of IP:port values that refer to containers which have exposed the
        service port (thereby acting as backend services).

    """

    host, port = get_etcd_addr()
    client = etcd.Client(host=host, port=int(port))
    backends = client.read('/backends', recursive=True)
    services = {}

    for i in backends.children:
        if i.key[1:].count("/") != 2:
            continue

        ignore, service, container = i.key[1:].split("/")
        endpoints = services.setdefault(service, dict(port="", backends=[]))
        if container == "port":
            endpoints["port"] = i.value
            continue

        endpoints["backends"].append(dict(name=container, addr=i.value))

    return services


def generate_config(services):
    """
    Generate a configuration file for haproxy and save it to disk.

    It is expected that the results of :py:func:`get_services` will be passed
    to this function.

    :param dict services:
        A dictionary of dictionaries, keyed on service name.

    """

    template = env.get_template('haproxy.cfg.tmpl')
    with open("/etc/haproxy.cfg", "w") as f:
        f.write(template.render(services=services))


if __name__ == "__main__":
    current_services = {}
    while True:
        try:
            services = get_services()

            if not services or services == current_services:
                time.sleep(POLL_TIMEOUT)
                continue

            print("config changed. reload haproxy")
            generate_config(services)
            ret = call(["./reload-haproxy.sh"])
            if ret != 0:
                print("reloading haproxy returned: ", ret)
                time.sleep(POLL_TIMEOUT)
                continue
            current_services = services
        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_TIMEOUT)
