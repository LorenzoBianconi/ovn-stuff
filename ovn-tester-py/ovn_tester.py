#!/usr/bin/env python

import os
import sys
import ovn_utils
import netaddr
import time
import yaml
import ovn_fake

sandboxes = [] # ovn sanbox list
farm_list = [ "127.0.0.1" ]

controller = {
    "name": "ovn-central",
    "ip": "127.0.0.1",
    "user": "root",
    "password": ""
}

def create_sandbox(sandbox_create_args = {}, iteration = 0):
    amount = sandbox_create_args.get("amount", 1)

    bcidr = sandbox_create_args.get("cidr", "1.0.0.0/8")
    base_cidr = netaddr.IPNetwork(bcidr)
    cidr = "{}/{}".format(str(base_cidr.ip + iteration * amount + 1),
                          base_cidr.prefixlen)
    start_cidr = netaddr.IPNetwork(cidr)
    sandbox_cidr = netaddr.IPNetwork(start_cidr)
    if not sandbox_cidr.ip + amount in sandbox_cidr:
        message = _("Network %s's size is not big enough for %d sandboxes.")
        raise exceptions.InvalidConfigException(
                message  % (start_cidr, amount))

    for i in range(amount):
        sandbox = {
                "farm": farm_list[ i % len(farm_list) ],
                "name" : "ovn-chassis-%s" % iteration
        }
        sandboxes.append(sandbox)

def run_test():
    # create sandox list
    n_sandboxes = 10
    for i in range(n_sandboxes):
        create_sandbox(iteration = i)

    print("***** creating following sanboxes *****")
    print(yaml.dump(sandboxes))

    # start ovn-northd on ovn central
    fake_multinode_args = {
        "node_net": "192.16.0.0",
        "node_net_len": "16",
        "node_ip": "192.16.0.1",
        "ovn_cluster_db": False,
        "central_ip": "192.16.0.1",
        "sb_proto": "ssl",
        "max_timeout_s": 10,
        "cluster_cmd_path": "/root/ovn-heater/runtime/ovn-fake-multinode"
    }
    ovn = ovn_fake.OvnFake(controller)
    ovn.add_central(fake_multinode_args)

    # creat swith-per-node topology
    lnetwork_create_args = {
        "start_ext_cidr": "3.0.0.0/16"
    }
    for i in range(n_sandboxes):
        ovn.add_chassis_node(sandboxes, fake_multinode_args, iteration = i)
        if lnetwork_create_args.get('gw_router_per_network', False):
            ovn.add_chassis_node_localnet(sandboxes, fake_multinode_args,
                                          iteration = i)
            ovn.add_chassis_external_host(sandboxes, lnetwork_create_args,
                                          iteration = i)

    for i in range(n_sandboxes):
        ovn.connect_chassis_node(sandboxes, fake_multinode_args, iteration = i)
        ovn.wait_chassis_node(sandboxes, fake_multinode_args, iteration = i)

    lswitch_create_args = {
        "start_cidr" : "16.0.0.0/16",
        "nlswitch": n_sandboxes,
    }
    lport_bind_args = {
        "internal" : True,
    }
    # create ovn topology
    ovn.create_routed_network(lswitch_create_args = lswitch_create_args,
                              lport_bind_args = lport_bind_args,
                              sandboxes = sandboxes)

if __name__ == '__main__':
    sys.exit(run_test())
