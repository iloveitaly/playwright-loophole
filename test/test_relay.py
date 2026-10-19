import http.client
import os
import socket
import ssl

import pytest


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_raw_tcp_preserves_host_and_tls_sni(address, scheme, expected_text):
    port = int(os.environ["LOOPHOLE_HTTPS_PORT" if scheme == "https" else "LOOPHOLE_HTTP_PORT"])
    hostname = "service.loophole.test"
    with socket.create_connection((address, port), timeout=10) as raw:
        stream = raw
        if scheme == "https":
            context = ssl.create_default_context(cafile=os.environ["LOOPHOLE_CA_CERT"])
            # Connect to loopback, but verify the upstream certificate by its hostname.
            stream = context.wrap_socket(raw, server_hostname=hostname)
        try:
            stream.sendall(
                f"GET / HTTP/1.1\r\nHost: {hostname}:{port}\r\nConnection: close\r\n\r\n".encode()
            )
            response = http.client.HTTPResponse(stream)
            response.begin()
            assert response.status == 200
            assert expected_text in response.read().decode()
        finally:
            if stream is not raw:
                stream.close()
