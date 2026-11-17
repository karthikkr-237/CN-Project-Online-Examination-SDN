from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel

ACCESS = dict(bw=100, delay='1ms', loss=0, max_queue_size=1000)
PRIMARY = dict(bw=10, delay='5ms', loss=0, max_queue_size=50)
ALTERNATE = dict(bw=10, delay='5ms', loss=0, max_queue_size=100)

EXPECTED = {
    ('s1', 'h1', 1), ('s1', 'h2', 2), ('s1', 'h3', 3), ('s1', 'h_bad', 4),
    ('s1', 's2', 5), ('s1', 's3', 6),
    ('s2', 's_server', 1), ('s2', 's1', 2), ('s2', 's3', 3),
    ('s3', 's1', 1), ('s3', 's2', 2),
}


class ExamTopo(Topo):

    def build(self):
        h1 = self.addHost('h1', ip='10.0.0.1/8', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/8', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/8', mac='00:00:00:00:00:03')
        s_server = self.addHost('s_server', ip='10.0.0.4/8', mac='00:00:00:00:00:04')
        h_bad = self.addHost('h_bad', ip='10.0.0.5/8', mac='00:00:00:00:00:05')

        s1 = self.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', dpid='0000000000000002', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', dpid='0000000000000003', protocols='OpenFlow13')

        self.addLink(h1, s1, **ACCESS)
        self.addLink(h2, s1, **ACCESS)
        self.addLink(h3, s1, **ACCESS)
        self.addLink(h_bad, s1, **ACCESS)
        self.addLink(s_server, s2, **ACCESS)

        self.addLink(s1, s2, **PRIMARY)
        self.addLink(s1, s3, **ALTERNATE)
        self.addLink(s3, s2, **ALTERNATE)


topos = {'examtopo': ExamTopo}


def check_ports(net):
    actual = set()
    for link in net.links:
        n1, n2 = link.intf1.node, link.intf2.node
        actual.add((n1.name, n2.name, n1.ports[link.intf1]))
        actual.add((n2.name, n1.name, n2.ports[link.intf2]))

    print('\n=== Switch port map (switch -> neighbour : port) ===')

    for sw, nb, p in sorted(x for x in actual if x[0] in ('s1', 's2', 's3')):
        print('  %s -> %-9s : port %d' % (sw, nb, p))

    missing = EXPECTED - actual

    for sw, nb, p in sorted(missing):
        print('  MISMATCH: expected %s port %d -> %s' % (sw, p, nb))

    print('Port map matches the specification.\n' if not missing else
          'WARNING: port map differs! Fix the controller mapping first.\n')


def run():
    setLogLevel('info')
    net = Mininet(topo=ExamTopo(), switch=OVSSwitch, link=TCLink,
                  controller=None, autoSetMacs=False, waitConnected=False)

    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
    net.start()
    check_ports(net)

    print('Wait ~3 s for the controller to install flows, then try: pingall')

    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
