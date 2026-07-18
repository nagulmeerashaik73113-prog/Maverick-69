"""
Tiny Flask server so uptime monitors (UptimeRobot, Railway healthchecks, etc.)
have something to ping. Not strictly required on Railway (which keeps a
worker/service alive on its own), but harmless to include and useful if you
ever move this to a host like Replit that sleeps idle web-less processes.
"""

import logging
from threading import Thread
from flask import Flask

app = Flask(__name__)
log = logging.getLogger("bot.keep_alive")

# Quiet down Flask's default request logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)


@app.route("/")
def home():
    return "✅ Bot is alive and running."


def run():
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    log.info("Keep-alive web server started on port 8080.")
