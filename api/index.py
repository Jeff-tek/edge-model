"""Minimal Vercel Python entrypoint - satisfies Vercel's Python detection.

The actual site is the static dashboard/ (see vercel.json outputDirectory).
This handler just prevents 'No python entrypoint found' on Vercel builds.
"""

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"edge-model api ok")
        return
