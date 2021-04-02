import ovn_utils
import time
import netaddr
import random
import string
from randmac import RandMac

class OvnWorkload:
    def __init__(self, controller = None):
        self.controller = controller

    def add_central(self, fake_multinode_args = {}):
        print("***** creating central node *****")
    
        node_net = fake_multinode_args.get("node_net")
        node_net_len = fake_multinode_args.get("node_net_len")
        node_ip = fake_multinode_args.get("node_ip")
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
        
        if fake_multinode_args.get("ovn_monitor_all"):
            monitor_cmd = "OVN_MONITOR_ALL=yes"
        else:
            monitor_cmd = "OVN_MONITOR_ALL=no"
    
        if fake_multinode_args.get("ovn_cluster_db"):
            cluster_db_cmd = "OVN_DB_CLUSTER=yes"
        else:
            cluster_db_cmd = "OVN_DB_CLUSTER=no"
    
        cmd = "cd {} && CHASSIS_COUNT=0 GW_COUNT=0 IP_HOST={} IP_CIDR={} IP_START={} {} {} CREATE_FAKE_VMS=no ./ovn_cluster.sh start".format(
                ovn_fake_path, node_net, node_net_len, node_ip, monitor_cmd, cluster_db_cmd
            )
        client = ovn_utils.SSH(self.controller)
        client.run(cmd = cmd)
    
        time.sleep(5)

    def add_chassis_node_localnet(self, sandboxes = [], fake_multinode_args = {},
                                  iteration = 0):
        sandbox = sandboxes[iteration % len(sandboxes)]
    
        print("***** creating localnet on %s controller *****" % sandbox["name"])
    
        cmd = "ovs-vsctl -- set open_vswitch . external-ids:ovn-bridge-mappings={}:br-ex".format(
            fake_multinode_args.get("physnet", "providernet")
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node, container = sandbox["name"])
        client.run(cmd = cmd)
    
    def add_chassis_external_host(self, sandboxes = [], lnetwork_create_args = {},
                                  iteration = 0):
        sandbox = sandboxes[iteration % len(sandboxes)]
        cidr = netaddr.IPNetwork(lnetwork_create_args.get('start_ext_cidr'))
        ext_cidr = cidr.next(iteration)
    
        gw_ip = netaddr.IPAddress(ext_cidr.last - 1)
        host_ip = netaddr.IPAddress(ext_cidr.last - 2)
    
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node, container = sandbox["name"])
        client.run(cmd = "ip link add veth0 type veth peer name veth1")
        client.run(cmd = "ip link add veth0 type veth peer name veth1")
        client.run(cmd = "ip netns add ext-ns")
        client.run(cmd = "ip link set netns ext-ns dev veth0")
        client.run(cmd = "ip netns exec ext-ns ip link set dev veth0 up")
        client.run(cmd = "ip netns exec ext-ns ip addr add {}/{} dev veth0".format(
                   host_ip, ext_cidr.prefixlen))
        client.run(cmd = "ip netns exec ext-ns ip route add default via {}".format(
                   gw_ip))
        client.run(cmd = "ip link set dev veth1 up")
        client.run(cmd = "ovs-vsctl add-port br-ex veth1")
    
    def add_chassis_node(self, sandboxes = [], fake_multinode_args = {},
                         iteration = 0):
        node_net = fake_multinode_args.get("node_net")
        node_net_len = fake_multinode_args.get("node_net_len")
        node_cidr = netaddr.IPNetwork("{}/{}".format(node_net, node_net_len))
        node_ip = str(node_cidr.ip + iteration + 1)
    
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
    
        sandbox = sandboxes[iteration % len(sandboxes)]
    
        print("***** adding %s controller *****" % sandbox["name"])
    
        if fake_multinode_args.get("ovn_monitor_all"):
            monitor_cmd = "OVN_MONITOR_ALL=yes"
        else:
            monitor_cmd = "OVN_MONITOR_ALL=no"
    
        if fake_multinode_args.get("ovn_cluster_db"):
            cluster_db_cmd = "OVN_DB_CLUSTER=yes"
        else:
            cluster_db_cmd = "OVN_DB_CLUSTER=no"
    
        cmd = "cd {} && IP_HOST={} IP_CIDR={} IP_START={} {} {} ./ovn_cluster.sh add-chassis {} {}".format(
            ovn_fake_path, node_net, node_net_len, node_ip, monitor_cmd, cluster_db_cmd,
            sandbox["name"], "tcp:0.0.0.1:6642"
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node)
        client.run(cmd)

    def connect_chassis_node(self, sandboxes = [], fake_multinode_args = {},
                             iteration = 0):
        sandbox = sandboxes[iteration % len(sandboxes)]
        node_prefix = fake_multinode_args.get("node_prefix", "")
    
        print("***** connecting %s controller *****" % sandbox["name"])
    
        central_ip = fake_multinode_args.get("central_ip")
        sb_proto = fake_multinode_args.get("sb_proto", "ssl")
        ovn_fake_path = fake_multinode_args.get("cluster_cmd_path")
    
        central_ips = [ip.strip() for ip in central_ip.split('-')]
        remote = ",".join(["{}:{}:6642".format(sb_proto, r) for r in central_ips])
    
        cmd = "cd {} && ./ovn_cluster.sh set-chassis-ovn-remote {} {}".format(
            ovn_fake_path, sandbox["name"], remote
        )
        node = {
            "ip": sandbox["farm"],
        }
        client = ovn_utils.SSH(node)
        client.run(cmd = cmd)

    def wait_chassis_node(self, sandboxes = [], fake_multinode_args = {},
                          iteration = 0, controller = {}):
        sandbox = sandboxes[iteration % len(sandboxes)]
        max_timeout_s = fake_multinode_args.get("max_timeout_s")
        for i in range(0, max_timeout_s * 10):
            sbctl = ovn_utils.OvnSbctl(self.controller,
                                       container = self.controller["name"])
            if sbctl.chassis_bound(chassis = sandbox["name"]):
                break
            time.sleep(0.1)

    def bind_and_wait_port(self, lport = None, lport_bind_args = {},
                           sandboxes = [], iteration = 0):
        sandbox = sandboxes[iteration % len(sandboxes)]
        node = {
            "ip": sandbox["farm"],
        }
        internal = lport_bind_args.get("internal", False)
        internal_vm = lport_bind_args.get("internal_vm", True)
        vsctl = ovn_utils.OvsVsctl(node = node, container = sandbox["name"])
        # add ovs port
        vsctl.add_port(lport["name"], "br-int", internal = internal,
                       ifaceid = lport["name"])
        if internal and internal_vm:
            vsctl.bind_vm_port(lport)


    def create_lswitch_port(self, nbctl = None, lswitch = None,
                            lport_create_args = {}, iteration = 0):
        cidr = lswitch.get("cidr", None)
        if cidr:
            ip = str(next(netaddr.iter_iprange(cidr.ip + iteration + 1,
                                               cidr.last)))
            ip_mask = '{}/{}'.format(ip, cidr.prefixlen)
            gw = str(netaddr.IPAddress(cidr.last - 1))
            name = "lp_{}".format(ip)
        else:
            name = "lp_".join(random.choice(string.ascii_letters) for i in range(10))
            ip_mask = ""
            ip = ""
            gw = ""
        lswitch_port = nbctl.ls_port_add(lswitch["name"], name,
                                         mac = str(RandMac()),
                                         ip = ip, gw = gw)
        return lswitch_port

    def create_lswitch(self, nbctl = None, lswitch_create_args = {},
                       iteration = 0):
        start_cidr = lswitch_create_args.get("start_cidr", "")
        if start_cidr:
            start_cidr = netaddr.IPNetwork(start_cidr)
            cidr = start_cidr.next(iteration)
            name = "lswitch_%s" % cidr
        else:
            name = 'lswitch_'.join(random.choice(string.ascii_letters) for i in range(10))

        print("***** creating lswitch {} *****".format(name))
        lswitch = nbctl.ls_add(name)
        if start_cidr:
            lswitch["cidr"] = cidr

        return lswitch

    def connect_lswitch_to_router(self, nbctl = None, lrouter = None,
                                  lswitch = None):
        gw = netaddr.IPAddress(lswitch["cidr"].last - 1)
        lrouter_port_ip = '{}/{}'.format(gw, lswitch["cidr"].prefixlen)
        mac = RandMac()
        lrouter_port = nbctl.lr_port_add(lrouter["name"], lswitch["name"],
                                         mac, lrouter_port_ip)
        lswitch_port = nbctl.ls_port_add(lswitch["name"],
                                         "rp-" + lswitch["name"],
                                         lrouter["name"])

    def create_routed_network(self, lswitch_create_args = {},
                              lport_bind_args = {}, sandboxes = None):
        # create logical router
        nbctl = ovn_utils.OvnNbctl(self.controller,
                                   container = self.controller["name"])
        name = ''.join(random.choice(string.ascii_letters) for i in range(10))
        router = nbctl.lr_add("lrouter_" + name)

        # create logical switches
        lswitches = []
        lports = []
        for i in range(lswitch_create_args.get("nlswitch", 10)):
            lswitch = self.create_lswitch(nbctl, lswitch_create_args, i)
            lswitches.append(lswitch)
            self.connect_lswitch_to_router(nbctl, router, lswitch)
            lport = self.create_lswitch_port(nbctl, lswitch, iteration = i)
            lports.append(lport)
            self.bind_and_wait_port(lport, lport_bind_args = lport_bind_args,
                                    sandboxes = sandboxes, iteration = i)
