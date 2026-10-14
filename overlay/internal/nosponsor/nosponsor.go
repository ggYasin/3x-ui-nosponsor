// Package nosponsor stops the panel process from resolving sponsor/ad domains.
//
// It is added to the 3x-ui source by remove-sponsors.py and imported for its
// side effect. Every DNS lookup made through Go's resolver (which every HTTP
// client in the panel uses, whatever transport it builds) is checked: a
// blocked domain or any of its subdomains gets NXDOMAIN without the query
// ever leaving the process. Xray runs as a separate process and is unaffected.
package nosponsor

import (
	"context"
	"encoding/binary"
	"net"
	"strings"
	"sync"
)

// BlockedDomains lists domains that, with all their subdomains, never resolve.
var BlockedDomains = []string{
	"sanaei.dev",
}

func init() {
	net.DefaultResolver.PreferGo = true
	net.DefaultResolver.Dial = dial
}

// Blocked reports whether host is a blocked domain or a subdomain of one.
func Blocked(host string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	for _, d := range BlockedDomains {
		if host == d || strings.HasSuffix(host, "."+d) {
			return true
		}
	}
	return false
}

func dial(ctx context.Context, network, address string) (net.Conn, error) {
	var d net.Dialer
	c, err := d.DialContext(ctx, network, address)
	if err != nil {
		return nil, err
	}
	// Go's resolver picks packet or stream framing by checking for net.PacketConn,
	// so the UDP wrapper must keep implementing it.
	if uc, ok := c.(*net.UDPConn); ok {
		return &udpConn{UDPConn: uc}, nil
	}
	return &streamConn{Conn: c}, nil
}

// answered holds canned NXDOMAIN replies waiting to be read.
type answered struct {
	mu      sync.Mutex
	pending []byte
}

func (a *answered) push(b []byte) {
	a.mu.Lock()
	a.pending = append(a.pending, b...)
	a.mu.Unlock()
}

// pop copies pending bytes into b. Datagram reads consume the whole reply.
func (a *answered) pop(b []byte, datagram bool) (int, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if len(a.pending) == 0 {
		return 0, false
	}
	n := copy(b, a.pending)
	if datagram {
		a.pending = nil
	} else {
		a.pending = a.pending[n:]
	}
	return n, true
}

type udpConn struct {
	*net.UDPConn
	a answered
}

func (c *udpConn) Write(b []byte) (int, error) {
	if reply := blockedReply(b); reply != nil {
		c.a.push(reply)
		return len(b), nil
	}
	return c.UDPConn.Write(b)
}

func (c *udpConn) Read(b []byte) (int, error) {
	if n, ok := c.a.pop(b, true); ok {
		return n, nil
	}
	return c.UDPConn.Read(b)
}

type streamConn struct {
	net.Conn
	a answered
}

// Write expects Go's framing: the 2-byte length and the message in one write.
func (c *streamConn) Write(b []byte) (int, error) {
	if len(b) > 2 {
		if reply := blockedReply(b[2:]); reply != nil {
			c.a.push(binary.BigEndian.AppendUint16(nil, uint16(len(reply))))
			c.a.push(reply)
			return len(b), nil
		}
	}
	return c.Conn.Write(b)
}

func (c *streamConn) Read(b []byte) (int, error) {
	if n, ok := c.a.pop(b, false); ok {
		return n, nil
	}
	return c.Conn.Read(b)
}

// blockedReply returns an NXDOMAIN reply if query asks for a blocked name, else nil.
func blockedReply(query []byte) []byte {
	name, end, ok := question(query)
	if !ok || !Blocked(name) {
		return nil
	}
	r := make([]byte, end)
	copy(r, query[:end])
	r[2] = 0x80 | query[2]&0x79           // QR=1, keep opcode and RD
	r[3] = 0x80 | 3                       // RA=1, RCODE=NXDOMAIN
	binary.BigEndian.PutUint16(r[4:6], 1) // one question, no other records
	clear(r[6:12])
	return r
}

// question parses the first question of a DNS message. end is the offset just
// past its QTYPE and QCLASS.
func question(m []byte) (name string, end int, ok bool) {
	if len(m) < 12 || binary.BigEndian.Uint16(m[4:6]) == 0 {
		return "", 0, false
	}
	var labels []string
	for i := 12; i < len(m); {
		l := int(m[i])
		if l == 0 {
			end = i + 1 + 4
			if end > len(m) {
				return "", 0, false
			}
			return strings.Join(labels, "."), end, true
		}
		if l&0xC0 != 0 || i+1+l > len(m) {
			return "", 0, false
		}
		labels = append(labels, string(m[i+1:i+1+l]))
		i += 1 + l
	}
	return "", 0, false
}
