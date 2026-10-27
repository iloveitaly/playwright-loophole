import http.client
import os
import socket
import ssl
from pathlib import Path

import pytest

HOSTNAME = "service.loophole.test"
TIMEOUT_SECONDS = 10
EXPECTED_STATUS = 200


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_raw_tcp_preserves_host_and_tls_sni(address, scheme, expected_text):
    port = int(os.environ["LOOPHOLE_HTTPS_PORT" if scheme == "https" else "LOOPHOLE_HTTP_PORT"])

    with socket.create_connection((address, port), timeout=TIMEOUT_SECONDS) as raw:
        stream = raw
        if scheme == "https":
            ca_cert_path = Path(os.environ["LOOPHOLE_CA_CERT"])
            context = ssl.create_default_context(cafile=ca_cert_path)
            # connect to loopback, but verify the upstream certificate by its hostname
            stream = context.wrap_socket(raw, server_hostname=HOSTNAME)

        try:
            stream.sendall(
                f"GET / HTTP/1.1\r\nHost: {HOSTNAME}:{port}\r\nConnection: close\r\n\r\n".encode()
            )
            response = http.client.HTTPResponse(stream)
            response.begin()
            response_body = response.read().decode()

            assert response.status == EXPECTED_STATUS
            assert expected_text in response_body
        finally:
            if stream is not raw:
                stream.close()
