#!/bin/bash

WORKSPACE=/tmp/ovn-test/
LOCALNET_IP=192.168.123.254
EXT_DEV=ens8

dec2hex() {
	printf "%02x" $1
}

exec_remote_cmd() {
	local remote=$1
	local cmd=$2
	shift 2
	ssh $USER_ID@$remote "$cmd $@"
}

get_list_depth() {
	set -- $1
	echo $#
}

set_default_evn() {
	mkdir -p $WORKSPACE
	# disable selinux
	setenforce 0
	# disable firewalld
	systemctl stop firewalld.service
	# tidy-up bridge conf
	ovs-vsctl del-br br-int
}

check_default() {
	[ -z "$LOGICAL_PORT" ] && LOGICAL_PORT=30
	[ -z "$LOGICAL_SWITCH" ] && LOGICAL_SWITCH=1
	[ -z "$CENTRAL_IP" ] && CENTRAL_IP=192.168.0.1
	[ -z "$CONTROLLER_IP_LIST" ] && CONTROLLER_IP_LIST=192.168.0.2
	[ -z "$RUN_TEST" ] && RUN_TEST=1
	[ -z "$USER_ID" ] && USER_ID=root
	[ -z "$DIR" ] && DIR=$HOME
	[ -z "$DELAY" ] && DELAY=1
	[ -z "$N" ] && N=10
	[ -z "$M" ] && M=0
	[ -z "$ACL" ] && ACL=0
	[ -z "$EXT" ] && EXT=""
}

check_operation() {
	# $1: operation
	# $2: port to check
	# $3: remove device (optional)
	case $1 in
		ADD)
			ovn-nbctl get Logical_Switch_Port "$2" up >/dev/null 2>&1
			echo $?
			;;
		REMOVE)
			exec_remote_cmd $3 ovs-vsctl "find Interface name=$2" | grep $2
			echo $?
			;;
		*) echo -1 ;;
	esac
}

usage() {
echo -e "
Usage: $0 [-APSIDNMiude] <setup|run_test|create_fake_vm|remove_fake_vm|configure_ovn_ctrl|dump|help>
		-A: enable/disable default ACL configuration
		-P: # of OVN logical port/switch\t(default 30)
		-S: # of OVN logical switch\t\t(default 1)
		-I: northd/southd dbs ip address\t(default 192.168.0.1)
		-i: ovn-controller ip address list\t(default 192.168.0.2)
		-u: device username\t\t\t(default root)
		-d: script folder\t\t\t(default $HOME)
		-N: random bound\t\t\t(default 10)
		-M: # of test round\t\t\t(default 0 - no test)
		-D: test rate [sec]\t\t\t(defaulr 1s)
		-e: enable/disable localnet connection\t(default none)
		    - GR: use Gateway Router
		    - GP: use Gateway Router Port

		- run_test: run add/remove port test for M times
		- setup: create a OVN overlay network (switch=L2 or router=L3)
		- configure_ovn_ctrl: configute ovn-ctrl daemon
		- create_fake_vm: create a 'fake' vm using namespaces
		- remove_fake_vm: remove a 'fake' vm
		- dump: dump northd/southd configuration
	"
}

dump() {
	echo "********* ovn-nbctl show *********"
	ovn-nbctl show
	echo "********* ovn-sbctl show *********"
	ovn-sbctl show
}

create_fake_vm() {
	# $1: ovn logical switch id
	# $2: ovn logical switch port id

	local MAC=00:$(dec2hex $(($1/254))):$(dec2hex $(($1%254))):00:$(dec2hex $(($2/254))):$(dec2hex $(($2%254)))
	local IP=$((1+$1/254)).$(($1%254)).$(($2/254)).$(($2%254))

	ip netns add sw$1pod$2
	ovs-vsctl add-port br-int sw$1pod$2 \
		-- set interface sw$1pod$2 type=internal \
		-- set Interface sw$1pod$2 external_ids:iface-id=sw$1-port$2
	ip link set sw$1pod$2 netns sw$1pod$2
	ip -n sw$1pod$2 link set sw$1pod$2 address $MAC
	ip -n sw$1pod$2 addr add "$IP/16" dev sw$1pod$2
	ip -n sw$1pod$2 link set sw$1pod$2 up
	ip -n sw$1pod$2 route add default via $((1+$1/254)).$(($1%254)).254.254

	ip -n sw$1pod$2 addr add "2001:db8:$1::$(($2+10))/64" dev sw$1pod$2
	ip -n sw$1pod$2 route add default via 2001:db8:$1::1
}

remove_fake_vm() {
	# $1: ovn logical switch id
	# $2: ovn logical switch port id

	ip netns del sw$1pod$2
	ovs-vsctl del-port br-int sw$1pod$2
}

create_ovn_ls_port() {
	# $1: switch id
	# $2: port id
	# $3: mac address
	# $4: ip address

	ovn-nbctl lsp-add sw$1 sw$1-port$2 \
		  -- lsp-set-addresses sw$1-port$2 "$3 $4"
	[ $ACL -ne 0 ] && ovn-nbctl acl-add sw$1 to-lport 1002 \
	          "outport == \"sw$1-port$2\" && ip4 && ip4.src == 0.0.0.0/0 && icmp4" allow-related \
		  -- acl-add sw$1 to-lport 1002 "outport == \"sw$1-port$2\" && ip4 && ip4.src == 0.0.0.0/0 && tcp && tcp.dst == 22" allow-related \
		  -- acl-add sw$1 to-lport 1001 "outport == \"sw$1-port$2\" && ip" drop \
		  -- acl-add sw$1 from-lport 1002 "inport == \"sw$1-port$2\" && ip4 && ip4.dst == {255.255.255.255, 10.1.0.0/16} && udp && udp.src == 68 && udp.dst == 67" allow \
		  -- acl-add sw$1 from-lport 1002 "inport == \"sw$1-port$2\" && ip" allow-related \
		  -- acl-add sw$1 from-lport 1001 "inport == \"sw$1-port$2\"" drop
}

remove_ovn_ls_port() {
	# $1: switch id
	# $2: port id

	ovn-nbctl lsp-del sw$1-port$2
	[ $ACL -ne 0 ] && ovn-nbctl acl-del sw$1 to-lport 1002 \
		  "outport == \"sw$1-port$2\" && ip4 && ip4.src == 0.0.0.0/0 && icmp4" \
		  -- acl-del sw$1 to-lport 1002 "outport == \"sw$1-port$2\" && ip4 && ip4.src == 0.0.0.0/0 && tcp && tcp.dst == 22" \
		  -- acl-del sw$1 to-lport 1001 "outport == \"sw$1-port$2\" && ip" \
		  -- acl-del sw$1 from-lport 1002 "inport == \"sw$1-port$2\" && ip4 && ip4.dst == {255.255.255.255, 10.1.0.0/16} && udp && udp.src == 68 && udp.dst == 67" \
		  -- acl-del sw$1 from-lport 1002 "inport == \"sw$1-port$2\" && ip" \
		  -- acl-del sw$1 from-lport 1001 "inport == \"sw$1-port$2\""
}

configure_ovn_ctrl() {
	# $1: controller id
	# $2: # of port/controller
	# $3: local 'public' ip address
	# $4: northd/southd 'public' ip address
	# $5: # of logical switches
	# $6: # of port switch

	set_default_evn

	echo ctrl-$1 > /etc/openvswitch/system-id.conf

	# clear all configured namespaces
	ip -all netns delete

	# clean ovn-controller configuration
	systemctl restart ovn-controller
	
	ovs-vsctl set open_vswitch . system-type=ctrl-$1 \
		  -- set open_vswitch . external-ids:system-id=ctrl-$1 \
		  -- set open_vswitch . external-ids:hostname=ctrl-$1 \
		  -- set open_vswitch . external-ids:ovn-bridge="br-int" \
		  -- set open_vswitch . external-ids:ovn-encap-ip=$3 \
		  -- set open_vswitch . external-ids:ovn-encap-type="geneve" \
		  -- set open . external-ids:ovn-remote=tcp:$4:6642

	# wait for the bridge to come up
	until [ -d /sys/class/net/br-int ]; do
		sleep 1
	done
	
	# crate fake vms
	for i in $(seq 1 $5); do
		for j in $(seq $((($1-1)*$2+1+(i-1)*$6)) \
			       $((($1*$2)+(i-1)*$6))); do
			create_fake_vm $i $j
		done
	done
}

configure_ovn_ctrl_list() {
	# configure remote ovn-controller
	local ctrl_idx=1
	for dev in $CONTROLLER_IP_LIST; do
		exec_remote_cmd $dev $DIR/ovn-test-scale.sh configure_ovn_ctrl \
				$ctrl_idx $NUM_POD_CTRL $dev $CENTRAL_IP \
				$LOGICAL_SWITCH $LOGICAL_PORT

		# take note of where the ports are located
		rm -f $WORKSPACE/$dev
		for i in $(seq 1 $LOGICAL_SWITCH); do
			for j in $(seq $(((ctrl_idx-1)*NUM_POD_CTRL+1+(i-1)*LOGICAL_PORT)) \
				       $(((ctrl_idx*NUM_POD_CTRL)+(i-1)*LOGICAL_PORT))); do
				echo "sw${i}pod$j" >> $WORKSPACE/$dev
			done
		done
		ctrl_idx=$((ctrl_idx+1))
	done
}

create_ovn_ls() {
	# $1: ovn logical switch id

	ovn-nbctl ls-add sw$1
	for port in $(seq $((($1-1)*LOGICAL_PORT + 1)) $(($1*LOGICAL_PORT))); do
		local MAC=00:$(dec2hex $(($1/254))):$(dec2hex $(($1%254))):00:$(dec2hex $((port/254))):$(dec2hex $((port%254)))
		local IP=$((1+$1/254)).$(($1%254)).$((port/254)).$((port%254))

		create_ovn_ls_port $1 $port "$MAC $IP 2001:db8:$1::$((port+10))"
	done
}

create_ovn_ls_ext() {
	# $1: localnet port mac address
	# $2: router port name

	ovn-nbctl ls-add sw-ext
	ovn-nbctl lsp-add sw-ext ext-lr0 -- \
		  lsp-set-type ext-lr0 router -- \
		  lsp-set-addresses ext-lr0 $1 -- \
		  lsp-set-options ext-lr0 router-port=$2 -- \
		  lsp-add sw-ext ext-localnet -- \
		  lsp-set-addresses ext-localnet unknown -- \
		  lsp-set-type ext-localnet localnet -- \
		  lsp-set-options ext-localnet network_name=extNet
}

create_ovn_lr() {
	# $1: localnet port mac address
	# $2: localnet port ip address

	if [ "$EXT" = GR ]; then
		ovn-nbctl create Logical_Router name=lr0 options:chassis=ctrl-1
		ovn-nbctl lrp-add lr0 lr0-ext $1 $2
	else
		ovn-nbctl lr-add lr0
		if [ "$EXT" = GP ]; then
			ovn-nbctl lrp-add lr0 lr0-ext $1 $2
			ovn-nbctl lrp-set-gateway-chassis lr0-ext ctrl-1 20
		fi
	fi
	for dev in $(seq 1 $LOGICAL_SWITCH); do
		local MAC=00:$(dec2hex $((dev/254))):$(dec2hex $((dev%254))):ff:$(dec2hex $((dev/254))):$(dec2hex $((dev%254)))

		if [ "$EXT" = GR -o "$EXT" = GP ]; then
			# Enable SNAT
			ovn-nbctl lr-nat-add lr0 snat $LOCALNET_IP $((1+$dev/254)).$(($dev%254)).0.0/24
		fi
		create_ovn_ls $dev
		#ovn-nbctl lrp-add lr0 lrp$dev $MAC $((1+$dev/254)).$(($dev%254)).254.254/16 -- \
		ovn-nbctl lrp-add lr0 lrp$dev $MAC $((1+$dev/254)).$(($dev%254)).254.254/16 2001:db8:$dev::1/64 -- \
			  lsp-add sw$dev sw$dev-portr0 -- \
			  lsp-set-type sw$dev-portr0 router -- \
			  lsp-set-addresses sw$dev-portr0 $MAC -- \
			  lsp-set-options sw$dev-portr0 router-port=lrp$dev
	done
}

add_remove_port() {
	#1: decide if we want to add or remove a port
	local var=$((TOTAL_LOGICAL_PORT + (RANDOM%(2*N)-N) - $((LOGICAL_PORT*LOGICAL_SWITCH))))
	local port

	if [ $var -lt 0 ]; then
		# add a port
		TOTAL_LOGICAL_PORT=$((TOTAL_LOGICAL_PORT+1))
	else
		# remove a port
		TOTAL_LOGICAL_PORT=$((TOTAL_LOGICAL_PORT-1))
	fi

	#empty the pool
	for i in $(seq 1 $LOGICAL_SWITCH); do
		pool[$i]=0
	done

	#2: decide where to add/remove the port
	local total=1
	for i in $(seq 1 $LOGICAL_SWITCH); do
		local port_cnt=$(fgrep -r sw$i $WORKSPACE  | wc -l)
		local num=0
		if [ $var -lt 0 ]; then
			num=$((LOGICAL_PORT - port_cnt + N))
		elif [ $port_cnt -gt 0 ]; then
			num=$((port_cnt - LOGICAL_PORT + N))
		fi

		if [ $num -gt 0 ]; then
			pool[$i]=$num
			total=$((total+num))
		fi
	done

	local rnd=$((RANDOM%total))
	local count=0

	# i is the index of selected logical switch
	for i in $(seq 1 $LOGICAL_SWITCH); do
		count=$((count+${pool[$i]}))
		[ $rnd -lt $count ] && break
	done

	port=$(fgrep -r sw${i}pod $WORKSPACE/ | cut -d 'd' -f 2 | sort -rn | head -n 1)

	if [ $var -lt 0 ]; then
		local limit=$((RANDOM%(NUM_CTRL+1)))
		local idx=1

		# choose a random controller
		for dev in $CONTROLLER_IP_LIST; do
			[ $idx -eq $limit ] && break
			idx=$((idx+1))
		done
		port=$((port+1))
	else
		for dev in $CONTROLLER_IP_LIST; do
			egrep -qr ^sw${i}pod$port$ $WORKSPACE/$dev
			[ $? -eq 0 ] && break
		done
	fi

	if [ $var -lt 0 ]; then
		local MAC=00:$(dec2hex $((i/254))):$(dec2hex $((i%254))):00:$(dec2hex $((port/254))):$(dec2hex $((port%254)))
		local IP=$((1+i/254)).$((i%254)).$((port/254)).$((port%254))

		echo -ne "Adding port $port on controller $dev ns\t\t\t[sw${i}pod$port].."
		create_ovn_ls_port $i $port $MAC $IP
		exec_remote_cmd $dev $DIR/ovn-test-scale.sh create_fake_vm $i $port
		[ $(check_operation ADD sw$i-port$port) -eq 0 ] && echo "ok" || echo "failed"
		echo sw${i}pod$port >> $WORKSPACE/$dev
	else
		echo -ne "Removing port $port on controller $dev ns\t\t[sw${i}pod$port].."
		remove_ovn_ls_port $i $port
		exec_remote_cmd $dev $DIR/ovn-test-scale.sh remove_fake_vm $i $port
		[ $(check_operation REMOVE sw$i-port$port $dev) -eq 1 ] && echo "ok" || echo "failed"
		sed "/sw${i}pod$port/d" -i $WORKSPACE/$dev
	fi
}

run_test() {
	echo -e " ********* $0: starting tests ********* "
	for i in $(seq 1 $M); do
		echo -en "Attempt $i:\t"
		add_remove_port
		sleep $DELAY
	done
}

setup() {
	# $1: selected configuration (switch/router)

	NUM_CTRL=$(get_list_depth "$CONTROLLER_IP_LIST")
	# sanity checks
	# - in L2 we have just one logical switch
	# - LOGICAL_PORT has to be multiple of NUM_CTRL
	[ "$1" != router -a $LOGICAL_SWITCH -gt 1 ] && LOGICAL_SWITCH=1
	LOGICAL_PORT=$(((LOGICAL_PORT/NUM_CTRL)*NUM_CTRL))
	[ $LOGICAL_PORT -lt $NUM_CTRL ] && LOGICAL_PORT=$NUM_CTRL

	TOTAL_LOGICAL_PORT=$((LOGICAL_PORT*LOGICAL_SWITCH))
	NUM_POD_CTRL=$((LOGICAL_PORT/NUM_CTRL))

	echo -e "
********* $0: current configuration *********
- configuration\t\t\t= OVN logical $1
- # of ovn logical switch\t= $LOGICAL_SWITCH
- # of pods/switch\t\t= $LOGICAL_PORT
- ovn-northd/southd ip addr\t= $CENTRAL_IP
- ovn-controller ip list\t= $CONTROLLER_IP_LIST
- random bound\t\t\t= $N
- # of rounds\t\t\t= $M
"

	{
		# configure a new environment
		set_default_evn
		# clear ovn configuration
		for r in $(ovn-nbctl lr-list | awk '{print $1}'); do
			ovn-nbctl lr-del $r
		done
		for dev in $(ovn-nbctl ls-list | awk '{print $1}'); do
			ovn-nbctl ls-del $dev
		done
		if [ "$EXT" != GR -a "$EXT" != GP ]; then
			ovn-nbctl ls-del sw-ext
			ovs-vsctl remove open . external_ids ovn-bridge-mappings
			ovs-vsctl del-br br-ext
		fi

		systemctl restart ovn-northd

		ovn-sbctl set-connection ptcp:6642
		ovn-nbctl set-connection ptcp:6641

		echo ovn-central > /etc/openvswitch/system-id.conf
		if [ "$1" = router ]; then
			# XXX define mac/ip if used for localnet
			create_ovn_lr 02:0a:7f:00:01:29 "$LOCALNET_IP/24 2001:db8:f0f0::1/64"
		else
			create_ovn_ls 1
		fi

		# configure remote ovn-controller list
		configure_ovn_ctrl_list

		# configure dataNet
		if [ "$EXT" = GR -o "$EXT" = GP ]; then
			create_ovn_ls_ext 02:0a:7f:00:01:29 lr0-ext
			ovs-vsctl add-br br-ext
			ovs-vsctl set Open_vSwitch . external-ids:ovn-bridge-mappings=extNet:br-ext
			# XXX define ethernet if used for localnet
			ovs-vsctl add-port br-ext $EXT_DEV
		fi
	} >/dev/null 2>&1

	# run the test
	[ $M -gt 0 ] && run_test
}

while true; do
	case $1 in
		-P)
			LOGICAL_PORT=$2
			shift 2 ;;
		-S)
			LOGICAL_SWITCH=$2
			shift 2 ;;
		-I)
			CENTRAL_IP=$2
			shift 2 ;;
		-d)
			DIR=$2
			shift 2 ;;
		-D)
			DELAY=$2
			shift 2 ;;
		-i)
			CONTROLLER_IP_LIST=$2
			shift 2 ;;
		-u)
			USER_ID=$2
			shift 2 ;;
		-N)
			N=$2
			shift 2 ;;
		-M)
			M=$2
			shift 2 ;;
		-A)
			ACL=$2
			shift 2 ;;
		-e)
			EXT=$2
			shift 2 ;;
		*)
			break ;;
	esac
done
check_default

case $1 in
	dump|create_fake_vm|remove_fake_vm|\
	configure_ovn_ctrl|setup|run_test) $@ ;;
	help|*) usage ;;
esac
