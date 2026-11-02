from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.controller.handler import DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import ether_types

import time


class ExamController(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    LINK_CAPACITY = 10000000
    THRESHOLD = 75

    def __init__(self, *args, **kwargs):

        super(ExamController, self).__init__(*args, **kwargs)

        self.datapaths = {}

        self.previous_bytes = None
        self.previous_time = None

        self.backup_active = False
        self.path_installed = False

        self.monitor_thread = hub.spawn(self.monitor)

    # Register switches

    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER
    )
    def switch_features_handler(self, ev):

        datapath = ev.msg.datapath

        self.datapaths[datapath.id] = datapath

        self.logger.info(
            "Switch S%d connected",
            datapath.id
        )

        if len(self.datapaths) == 3 and not self.path_installed:

            self.logger.info("All switches connected")

            self.install_path(False)

    # Handle switch disconnection

    @set_ev_cls(
        ofp_event.EventOFPStateChange,
        [MAIN_DISPATCHER, DEAD_DISPATCHER]
    )
    def state_change_handler(self, ev):

        datapath = ev.datapath

        if ev.state == DEAD_DISPATCHER:

            self.datapaths.pop(datapath.id, None)

            self.logger.warning(
                "Switch S%d disconnected",
                datapath.id
            )

    # Add flow rules

    def add_flow(self, datapath, priority, match, actions):

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        flow = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            cookie=0xA11CE
        )

        datapath.send_msg(flow)

    # Delete only our previous flow rules

    def delete_old_flows(self, datapath):

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        flow = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE,
            cookie=0xA11CE,
            cookie_mask=0xffffffffffffffff,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=parser.OFPMatch()
        )

        datapath.send_msg(flow)

    # Install primary or backup route

    def install_path(self, backup):

        if len(self.datapaths) != 3:
            return

        for datapath in self.datapaths.values():

            self.delete_old_flows(datapath)

        hub.sleep(0.5)

        if backup:

            self.logger.warning(
                "BACKUP PATH ACTIVATED: S1-S3-S2"
            )

            forward = {
                1: (1, 3),
                3: (2, 3),
                2: (3, 1)
            }

            reverse = {
                2: (1, 3),
                3: (3, 2),
                1: (2, 1)
            }

        else:

            self.logger.info(
                "PRIMARY PATH ACTIVATED: S1-S2"
            )

            forward = {
                1: (1, 2),
                2: (2, 1)
            }

            reverse = {
                2: (1, 2),
                1: (2, 1)
            }

        self.install_direction(
            forward,
            "10.0.0.1",
            "10.0.0.2"
        )

        self.install_direction(
            reverse,
            "10.0.0.2",
            "10.0.0.1"
        )

        self.backup_active = backup
        self.path_installed = True

    # Install IPv4 and ARP rules

    def install_direction(self, routes, source, destination):

        for switch_id, ports in routes.items():

            datapath = self.datapaths.get(switch_id)

            if datapath is None:
                continue

            in_port, out_port = ports

            parser = datapath.ofproto_parser

            actions = [
                parser.OFPActionOutput(out_port)
            ]

            # IPv4 forwarding

            ip_match = parser.OFPMatch(
                in_port=in_port,
                eth_type=ether_types.ETH_TYPE_IP,
                ipv4_src=source,
                ipv4_dst=destination
            )

            self.add_flow(
                datapath,
                300,
                ip_match,
                actions
            )

            # ARP forwarding

            arp_match = parser.OFPMatch(
                in_port=in_port,
                eth_type=ether_types.ETH_TYPE_ARP,
                arp_spa=source,
                arp_tpa=destination
            )

            self.add_flow(
                datapath,
                300,
                arp_match,
                actions
            )

    # Monitor S1-S2 link

    def monitor(self):

        while True:

            hub.sleep(2)

            datapath = self.datapaths.get(1)

            if datapath is None:
                continue

            parser = datapath.ofproto_parser

            request = parser.OFPPortStatsRequest(
                datapath,
                0,
                2
            )

            datapath.send_msg(request)

    # Receive port statistics

    @set_ev_cls(
        ofp_event.EventOFPPortStatsReply,
        MAIN_DISPATCHER
    )
    def port_stats_reply_handler(self, ev):

        datapath = ev.msg.datapath

        if datapath.id != 1:
            return

        now = time.time()

        for stat in ev.msg.body:

            if stat.port_no != 2:
                continue

            current_bytes = stat.tx_bytes

            if self.previous_bytes is None:

                self.previous_bytes = current_bytes
                self.previous_time = now

                return

            elapsed = now - self.previous_time

            if elapsed <= 0:
                return

            difference = max(
                0,
                current_bytes - self.previous_bytes
            )

            bandwidth = (difference * 8) / elapsed

            utilization = (
                bandwidth / self.LINK_CAPACITY
            ) * 100

            self.logger.info(
                "S1-S2 Utilization: %.2f%%",
                utilization
            )

            # Congestion detection

            if (
                utilization > self.THRESHOLD
                and not self.backup_active
            ):

                self.logger.warning(
                    "CONGESTION DETECTED!"
                )

                self.install_path(True)

            # Return to primary path

            elif (
                utilization < 50
                and self.backup_active
            ):

                self.logger.info(
                    "Returning to primary path"
                )

                self.install_path(False)

            self.previous_bytes = current_bytes
            self.previous_time = now
