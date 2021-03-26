import paramiko
from io import StringIO

class SSH:
    def __init__(self, node = {}, container = None):
        ip = node.get("ip", "127.0.0.1")
        username = node.get("user", "root")
        password = node.get("password", "")
        port = node.get("port", 22)

        self.container = container

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(ip, username = username, password = password,
                         port = port)

    def run(self, cmd = "", stdout = None):
        if self.container:
            command = 'docker exec ' + self.container + ' ' + cmd
        else:
            command = cmd

        ssh_stdin, ssh_stdout, ssh_stderr = self.ssh.exec_command(command)
        exit_code = ssh_stdout.channel.recv_exit_status()

        if stdout:
            stdout.write(ssh_stdout.read().decode('ascii'))

class OvsVsctl:
    def __init__(self, node = {}, container = None):
        self.ssh = SSH(node = node, container = container)

    def run(self, cmd = "", prefix = "ovs-vsctl ", stdout = None):
        self.ssh.run(cmd = prefix + cmd, stdout = stdout)

    def add_port(self, name = "", brige = "", internal = True,
                 ifaceid = None):
        cmd = "add-port {} {}".format(brige, name)
        if internal:
            cmd = cmd + " -- set interface {} type=internal".format(name)
        if ifaceid:
            cmd = cmd + " -- set Interface {} external_ids:iface-id={}".format(
                    name, ifaceid)
            cmd = cmd + " -- set Interface {} external_ids:iface-status=active".format(name)
            cmd = cmd + " -- set Interface {} admin_state=up".format(name)
        self.run(cmd = cmd)

    def bind_vm_port(self, lport = None):
        self.run('ethtool -K {p} tx off &> /dev/null'.format(p=lport["name"]),
                 prefix = "")
        self.run('ip netns add {p}'.format(p=lport["name"]), prefix = "")
        self.run('ip link set {p} netns {p}'.format(p=lport["name"]),
                 prefix = "")
        self.run('ip netns exec {p} ip link set {p} address {m}'.format(
            p=lport["name"], m=lport["mac"]), prefix = "")
        self.run('ip netns exec {p} ip addr add {ip} dev {p}'.format(
            p=lport["name"], ip=lport["ip"]), prefix = "")
        self.run('ip netns exec {p} ip link set {p} up'.format(
            p=lport["name"]), prefix = "")

        self.run('ip netns exec {p} ip route add default via {gw}'.format(
            p=lport["name"], gw=lport["gw"]), prefix = "")

class OvnNbctl:
    def __init__(self, node = {}, container = None):
        self.ssh = SSH(node = node, container = container)

    def run(self, cmd = "", stdout = None):
        self.ssh.run(cmd = "ovn-nbctl " + cmd, stdout = stdout)

    def lr_add(self, name = ""):
        self.run(cmd = "lr-add {}".format(name))
        return { "name": name }

    def lr_port_add(self, router = "", name = "", mac = None, ip = None):
        self.run(cmd = "lrp-add {} {} {} {}".format(router, name, mac, ip))
        return { "name": name }

    def ls_add(self, name = ""):
        self.run(cmd = "ls-add {}".format(name))
        return { "name": name }

    def ls_port_add(self, lswitch = "", name = "", router_port = None,
                    mac = "", ip = "", gw = ""):
        self.run(cmd = "lsp-add {} {}".format(lswitch, name))
        if router_port:
            cmd = "lsp-set-type {} router".format(name)
            cmd = cmd + " -- lsp-set-addresses {} router".format(name)
            cmd = cmd + " -- lsp-set-options {} router-port={}".format(name, router_port)
            self.run(cmd = cmd)
        elif len(mac) or len(ip):
            cmd = "lsp-set-addresses {} \"{} {}\"".format(name, mac, ip)
            self.run(cmd = cmd)
        return { "name" : name, "mac" : mac, "ip" : ip, "gw" : gw }

class OvnSbctl:
    def __init__(self, node = {}, container = None):
        self.ssh = SSH(node = node, container = container)

    def run(self, cmd = "", stdout = None):
        self.ssh.run(cmd = "ovn-sbctl --no-leader-only " + cmd, stdout = stdout)

    def chassis_bound(self, chassis = ""):
        cmd = "--bare --columns _uuid find chassis name={}".format(chassis)
        stdout = StringIO()
        self.run(cmd = cmd, stdout = stdout)
        return len(stdout.getvalue().splitlines()) == 1
