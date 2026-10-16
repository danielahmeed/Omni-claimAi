#!/usr/bin/env python3
"""Start OmniClaim AI.

    python server.py            then open http://localhost:8080

Configuration comes from environment variables or a .env file; see
.env.example and docs/CONFIGURATION.md.
"""

import logging
import os
import signal
import sys
import threading

from omniclaim import __version__
from omniclaim.app import create_server, create_service
from omniclaim.config import ON_CLOUD_RUN, PORT


def main() -> None:
    # Never crash on characters the console cannot print (Windows code pages).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    host = os.environ.get("HOST") or ("0.0.0.0" if ON_CLOUD_RUN else "127.0.0.1")
    service = create_service()
    service.initialize()
    server = create_server(service, host, PORT)

    ai = service.gemini.status()
    if ai["configured"]:
        where = f"Vertex AI, project {ai['project']}, location {ai['location']}" if ai["backend"] == "vertex" else "Gemini API key"
        ai_line = f"Gemini: {ai['model']} via {where}"
    else:
        ai_line = "Gemini: not configured, running in demo mode (" + (ai["hint"] or "see docs/CONFIGURATION.md") + ")"
    if ON_CLOUD_RUN:
        print(f"OmniClaim AI {__version__} listening on port {PORT} (Cloud Run service {os.environ.get('K_SERVICE')})")
    else:
        print(f"OmniClaim AI {__version__} running at http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{PORT}")
    print(ai_line)
    print(f"Settings editable in the UI: {'yes' if service.settings.writable else 'no (environment variables)'}")
    sys.stdout.flush()

    if ai["configured"] and os.environ.get("GEMINI_STARTUP_CHECK", "true").lower() != "false":
        def startup_check():
            result = service.gemini.test_connection()
            if result["ok"]:
                logging.getLogger("omniclaim").info("Gemini check OK: %s answered in %s ms", result["model"], result["latencyMs"])
            else:
                logging.getLogger("omniclaim").warning("Gemini check FAILED: %s", result["message"])
        threading.Thread(target=startup_check, daemon=True).start()

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    main()
