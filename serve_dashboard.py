#!/usr/bin/env python3
"""
Health Dashboard HTTP Server — Static File Server
Serves health_dashboard.html and last_report.json.
"""
import http.server
import json
import os
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18900
DIR = Path(__file__).parent.resolve()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path

        # Health check endpoint
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            report = DIR / "last_report.json"
            if report.exists():
                data = json.loads(report.read_text())
                status = 200 if data.get("overall") == "green" else 503
                self.wfile.write(json.dumps({"status": data["overall"], "code": status}).encode())
            else:
                self.wfile.write(json.dumps({"status": "no-report", "code": 503}).encode())
            return

        # API endpoint
        if path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            report = DIR / "last_report.json"
            if report.exists():
                self.wfile.write(report.read_bytes())
            else:
                self.wfile.write(json.dumps({"status": "no-report"}).encode())
            return

        # JSON report (for dashboard fetch)
        if path == "/last_report.json":
            report = DIR / "last_report.json"
            if report.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(report.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"not found"}')
            return

        # Serve the dashboard HTML for any root-like path
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = (DIR / "health_dashboard.html").read_bytes()
        self.wfile.write(html)

    def log_message(self, fmt, *args):
        if args and args[0] in ("200",):
            return  # quiet for 200s
        print(f"[{os.path.basename(__file__)}] {fmt % args}")

    # Suppress automatic directory listing (return 404 for unknown paths)
    def do_HEAD(self):
        self.do_GET()


if __name__ == "__main__":
    print(f"\033[36m📊 Clowie Health Dashboard\033[0m")
    print(f"   URL:     http://localhost:{PORT}")
    print(f"   API:     http://localhost:{PORT}/api/health")
    print(f"   Serving: {DIR}")
    print(f"")

    httpd = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")