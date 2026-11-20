"HTTP and WebSocket fixture for direct upstream tests"

import base64
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Service(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        "Serve identifiable HTTP responses and a WebSocket greeting"

        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept = base64.b64encode(hashlib.sha1(key.encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            message = b"upstream websocket reached"
            self.wfile.write(bytes([0x81, len(message)]) + message)
            self.wfile.flush()
            self.close_connection = True
            return

        body = json.dumps(
            {"upstream": os.environ.get("FIXTURE_NAME", "ipv6"), "host": self.headers["Host"]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Service).serve_forever()
