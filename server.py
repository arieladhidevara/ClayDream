from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import os
import urllib.parse

ROOT = Path(__file__).resolve().parent
CAPTURES_DIR = ROOT / "captures"
PORT = 8000

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class ClayDreamHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/images":
            self.send_images_json()
            return

        return super().do_GET()

    def send_images_json(self):
        CAPTURES_DIR.mkdir(exist_ok=True)

        images = [
            path.name
            for path in CAPTURES_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]

        # Newest first.
        images.sort(
            key=lambda name: (CAPTURES_DIR / name).stat().st_mtime,
            reverse=True
        )

        body = json.dumps(images).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.chdir(ROOT)
    CAPTURES_DIR.mkdir(exist_ok=True)

    mimetypes.add_type("image/webp", ".webp")

    server = ThreadingHTTPServer(("localhost", PORT), ClayDreamHandler)
    print(f"ClayDream gallery running at http://localhost:{PORT}")
    print(f"Watching folder: {CAPTURES_DIR}")
    server.serve_forever()
