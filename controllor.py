import os
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import ether_types, in_proto

SERVER_IP = '10.0.0.4'
EXAM_PORT = 5000
STUDENT_PORT_ON_S1 = {'10.0.0.1': 1, '10.0.0.2': 2, '10.0.0.3': 3}
BAD_IP, BAD_PORT_ON_S1 = '10.0.0.5', 4

S1_TO_S2, S1_TO_S3 = 5, 6
S2_TO_SERVER, S2_TO_S1, S2_TO_S3 = 1, 2, 3
S3_TO_S1, S3_TO_S2 = 1, 2

LINK_CAPACITY_MBPS = 5.0
POLL_INTERVAL = 2
CONGESTION_THRESHOLD = 75
RECOVERY_THRESHOLD = 50
MIN_DWELL = 6
MAX_SAMPLE_GAP = 10

COOKIE_BASE = 0xBA5E
COOKIE_EXAM = 0xA11CE
PRIO_BASE = 100
PRIO_EXAM = 300

PRIMARY, ALTERNATE = 'PRIMARY', 'ALTERNATE'
FULL_MASK = 0xffffffffffffffff


class ExamController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ExamController, self).__init__(*args, **kwargs)
        mode = os.environ.get('EXAM_MODE', 'dynamic').strip().lower()
        if mode not in ('static', 'dynamic'):
            self.logger.warning("Unknown EXAM_MODE '%s', using dynamic", mode)
            mode = 'dynamic'
        self.mode = mode
        self.datapaths = {}
        self.state = PRIMARY
        self.prev = None
        self.last_change = 0.0
        self.busy = False
        self.ready = False
        self.barriers = {}
        self.logger.info("=== Controller started in %s mode ===", self.mode.upper())
        self.logger.info("Port map: s1: h1=1 h2=2 h3=3 h_bad=4 s2=5 s3=6 | "
                         "s2: server=1 s1=2 s3=3 | s3: s1=1 s2=2")
        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info("Switch S%d connected (OpenFlow 1.3)", dp.id)
            if all(i in self.datapaths for i in (1, 2, 3)) and not self.busy:
                self.logger.info("All switches connected (DPIDs 1, 2, 3)")
                hub.spawn(self._initial_install)
        elif ev.state == DEAD_DISPATCHER:
            if self.datapaths.pop(dp.id, None) is not None:
                self.logger.warning("Switch S%d disconnected", dp.id)
            self.ready = False
            self.prev = None

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier_reply_handler(self, ev):
        key = (ev.msg.datapath.id, ev.msg.xid)
        event = self.barriers.pop(key, None)
        if event is not None:
            event.set()

    def _add_flow(self, dp, prio, match, out_port, cookie):
        parser, ofp = dp.ofproto_parser, dp.ofproto
        inst = [parser.OFPInstructionActions(
            ofp.OFPIT_APPLY_ACTIONS, [parser.OFPActionOutput(out_port)])]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, cookie=cookie, priority=prio,
                                      match=match, instructions=inst))

    def _delete_cookie(self, dp, cookie):
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, cookie=cookie, cookie_mask=FULL_MASK,
            table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
            match=parser.OFPMatch()))

    def _barrier(self, dps, timeout=3):
        events = []
        for dp in dps:
            req = dp.ofproto_parser.OFPBarrierRequest(dp)
            dp.set_xid(req)
            ev = hub.Event()
            self.barriers[(dp.id, req.xid)] = ev
            dp.send_msg(req)
            events.append((dp, req.xid, ev))
        for dp, xid, ev in events:
            if not ev.wait(timeout=timeout):
                self.barriers.pop((dp.id, xid), None)
                self.logger.warning("Barrier timeout on S%d", dp.id)

    def _exam_fwd_match(self, dp, student):
        return dp.ofproto_parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP, ip_proto=in_proto.IPPROTO_TCP,
            ipv4_src=student, ipv4_dst=SERVER_IP, tcp_dst=EXAM_PORT)

    def _exam_rev_match(self, dp, student):
        return dp.ofproto_parser.OFPMatch(
            eth_type=ether_types.ETH_TYPE_IP, ip_proto=in_proto.IPPROTO_TCP,
            ipv4_src=SERVER_IP, ipv4_dst=student, tcp_src=EXAM_PORT)

    def _install_base(self, dp):
        parser = dp.ofproto_parser
        if dp.id == 1:
            table = dict(STUDENT_PORT_ON_S1)
            table[BAD_IP] = BAD_PORT_ON_S1
            table[SERVER_IP] = S1_TO_S2
        elif dp.id == 2:
            table = {SERVER_IP: S2_TO_SERVER}
            for ip in list(STUDENT_PORT_ON_S1) + [BAD_IP]:
                table[ip] = S2_TO_S1
        else:
            return

        for ip, port in table.items():
            self._add_flow(dp, PRIO_BASE, parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_ARP, arp_tpa=ip), port, COOKIE_BASE)
            self._add_flow(dp, PRIO_BASE, parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=ip), port, COOKIE_BASE)

    def _install_exam_s1(self, dp, state):
        out_fwd = S1_TO_S2 if state == PRIMARY else S1_TO_S3
        for ip, sport in STUDENT_PORT_ON_S1.items():
            self._add_flow(dp, PRIO_EXAM, self._exam_fwd_match(dp, ip), out_fwd, COOKIE_EXAM)
            self._add_flow(dp, PRIO_EXAM, self._exam_rev_match(dp, ip), sport, COOKIE_EXAM)

    def _install_exam_s2(self, dp, state):
        out_rev = S2_TO_S1 if state == PRIMARY else S2_TO_S3
        for ip in STUDENT_PORT_ON_S1:
            self._add_flow(dp, PRIO_EXAM, self._exam_fwd_match(dp, ip), S2_TO_SERVER, COOKIE_EXAM)
            self._add_flow(dp, PRIO_EXAM, self._exam_rev_match(dp, ip), out_rev, COOKIE_EXAM)

    def _install_exam_s3(self, dp):
        for ip in STUDENT_PORT_ON_S1:
            self._add_flow(dp, PRIO_EXAM, self._exam_fwd_match(dp, ip), S3_TO_S2, COOKIE_EXAM)
            self._add_flow(dp, PRIO_EXAM, self._exam_rev_match(dp, ip), S3_TO_S1, COOKIE_EXAM)

    def _initial_install(self):
        self.busy = True
        try:
            dps = [self.datapaths[i] for i in (1, 2, 3)]
            for dp in dps:
                self._delete_cookie(dp, COOKIE_BASE)
                self._delete_cookie(dp, COOKIE_EXAM)
            self._barrier(dps)
            for dp in dps:
                self._install_base(dp)
            self.state = PRIMARY
            self._install_exam_s2(self.datapaths[2], PRIMARY)
            self._install_exam_s1(self.datapaths[1], PRIMARY)
            self._barrier(dps)
            self.prev = None
            self.last_change = time.monotonic()
            self.ready = True
            self.logger.info("Initial flows installed. Exam TCP path: PRIMARY (s1 -> s2)")
        except Exception as exc:
            self.logger.error("Initial install failed: %s", exc)
        finally:
            self.busy = False

    def _reroute(self, new_state):
        self.busy = True
        try:
            s1, s2, s3 = self.datapaths[1], self.datapaths[2], self.datapaths[3]
            if new_state == ALTERNATE:
                self.logger.info("[FLOWS] Installing alternate path s1 -> s3 -> s2")
                self._install_exam_s3(s3)
                self._barrier([s3])
                self._install_exam_s2(s2, ALTERNATE)
                self._barrier([s2])
                self._install_exam_s1(s1, ALTERNATE)
                self._barrier([s1])
            else:
                self.logger.info("[FLOWS] Returning exam TCP to s1 -> s2")
                self._install_exam_s1(s1, PRIMARY)
                self._install_exam_s2(s2, PRIMARY)
                self._barrier([s1, s2])
                hub.sleep(1)
                self._delete_cookie(s3, COOKIE_EXAM)
                self._barrier([s3])

            old = self.state
            self.state = new_state
            self.last_change = time.monotonic()
            self.logger.warning("[SDN] %s -> %s", old, new_state)
        except Exception as exc:
            self.logger.error("Reroute failed: %s", exc)
        finally:
            self.busy = False

    def _monitor(self):
        while True:
            hub.sleep(POLL_INTERVAL)
            dp = self.datapaths.get(1)
            if dp is None or not self.ready:
                continue
            dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, S1_TO_S2))

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        try:
            if ev.msg.datapath.id != 1:
                return
            now = time.monotonic()
            for stat in ev.msg.body:
                if stat.port_no != S1_TO_S2:
                    continue
                self._process_sample(stat.tx_bytes, now)
        except Exception as exc:
            self.logger.error("Malformed port stats reply ignored: %s", exc)

    def _process_sample(self, tx_bytes, now):
        if self.prev is None:
            self.prev = (tx_bytes, now)
            self.logger.info("[STATS] baseline stored (s1 port=%d)", S1_TO_S2)
            return

        old_bytes, old_time = self.prev
        dt = now - old_time
        self.prev = (tx_bytes, now)

        if tx_bytes < old_bytes or dt <= 0 or dt > MAX_SAMPLE_GAP:
            self.logger.warning("[STATS] invalid sample (reset/gap) - baseline refreshed")
            return

        rate = (tx_bytes - old_bytes) * 8 / (dt * 1000000.0)
        util = rate / LINK_CAPACITY_MBPS * 100

        self.logger.info("[STATS] s1 port=%d rate=%.2f Mbps utilisation=%.1f%% state=%s mode=%s",
                         S1_TO_S2, rate, util, self.state, self.mode)

        if self.mode == 'static' or self.busy or not self.ready:
            return

        if time.monotonic() - self.last_change < MIN_DWELL:
            return

        if self.state == PRIMARY and util > CONGESTION_THRESHOLD:
            self.logger.warning("[SDN] congestion threshold crossed (%.1f%% > %d%%)",
                                util, CONGESTION_THRESHOLD)
            self.busy = True
            hub.spawn(self._reroute, ALTERNATE)

        elif self.state == ALTERNATE and util < RECOVERY_THRESHOLD:
            self.logger.warning("[SDN] recovery threshold crossed (%.1f%% < %d%%)",
                                util, RECOVERY_THRESHOLD)
            self.busy = True
            hub.spawn(self._reroute, PRIMARY)
