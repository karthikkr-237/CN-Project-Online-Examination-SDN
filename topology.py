from mininet.topo import Topo


class ExamTopo(Topo):

    def build(self):

        # Create hosts
        h1 = self.addHost('h1', ip='10.0.0.1/8')
        h2 = self.addHost('h2', ip='10.0.0.2/8')
        h3 = self.addHost('h3', ip='10.0.0.3/8')

        # Create switches
        s1 = self.addSwitch('s1', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', protocols='OpenFlow13')

        # Connect hosts
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)

        # Connect switches in triangular topology
        self.addLink(s1, s2)
        self.addLink(s1, s3)
        self.addLink(s3, s2)


topos = {
    'examtopo': ExamTopo
}
