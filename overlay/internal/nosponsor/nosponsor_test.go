package nosponsor

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"
)

func TestBlocked(t *testing.T) {
	for host, want := range map[string]bool{
		"sanaei.dev":                true,
		"sponsors.sanaei.dev":       true,
		"ADS.Sanaei.Dev.":           true,
		"a.b.sanaei.dev":            true,
		"notsanaei.dev":             false,
		"sanaei.dev.evil.com":       false,
		"github.com":                false,
		"raw.githubusercontent.com": false,
	} {
		if got := Blocked(host); got != want {
			t.Errorf("Blocked(%q) = %v, want %v", host, got, want)
		}
	}
}

// The real resolver path: blocked names must fail as "not found", others must resolve.
func TestResolver(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	for _, host := range []string{"sponsors.sanaei.dev", "sanaei.dev", "anything.new.sanaei.dev"} {
		addrs, err := net.DefaultResolver.LookupHost(ctx, host)
		var dnsErr *net.DNSError
		if err == nil || !errors.As(err, &dnsErr) || !dnsErr.IsNotFound {
			t.Errorf("LookupHost(%q) = %v, %v; want not-found error", host, addrs, err)
		}
	}

	// Blocked names must also fail through a plain HTTP-style dial.
	if _, err := (&net.Dialer{}).DialContext(ctx, "tcp", "sponsors.sanaei.dev:443"); err == nil {
		t.Error("dial to sponsors.sanaei.dev succeeded")
	}

	if addrs, err := net.DefaultResolver.LookupHost(ctx, "github.com"); err != nil || len(addrs) == 0 {
		t.Errorf("LookupHost(github.com) = %v, %v; want addresses", addrs, err)
	}
}
