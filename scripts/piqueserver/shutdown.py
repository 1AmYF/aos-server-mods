"""
shutdown.py by IAmYourFriend https://github.com/1AmYF

Shut the server down with a command, or automatically after a minimum
uptime and when the last player has left. The minimum uptime can be set
by adding "minimum_uptime" (value in minutes) to the server config.

Commands:

    /shutdown
        Force shutdown of the server.
"""

from piqueserver.commands import command
from pyspades.constants import *
from twisted.internet.task import LoopingCall
from twisted.internet.reactor import callLater
import time
import os
import sys


CHECK_AFTER_DISCONNECT = 20  # seconds


@command(admin_only=True)
def shutdown(connection):
    """
    Force shutdown of the server
    /shutdown
    """
    do_shutdown(connection.protocol, "Shutdown command received.")


def get_now_in_secs():
    return int(time.time())


def has_players(protocol):
    if len(protocol.connections) < 1:
        return False
    else:
        for p in protocol.connections.values():
            if not p.local:
                return True
    return False


def check_for_shutdown(protocol):
    if protocol.shutdown_when_no_players and not has_players(protocol):
        do_shutdown(protocol, "Server is shutting down.")


def do_shutdown(protocol, message):
    sys.stdout.write(message + "\n")
    os._exit(0)


def apply_script(protocol, connection, config):

    class ShutdownConnection(connection):

        def on_disconnect(self):
            if not has_players(self.protocol):
                callLater(CHECK_AFTER_DISCONNECT, check_for_shutdown, self.protocol)
            connection.on_disconnect(self)

    class ShutdownProtocol(protocol):
        shutdown_when_no_players = False
        shutdown_check_loop = None
        minimum_uptime_mins = config.get("minimum_uptime", 0)
        startup_time_secs = 0

        def __init__(self, *arg, **kw):
            protocol.__init__(self, *arg, **kw)
            self.startup_time_secs = get_now_in_secs()
            if self.minimum_uptime_mins > 0:
                self.shutdown_check_loop = LoopingCall(self.wait_until_shutdown_check)
                self.shutdown_check_loop.start(60)

        def wait_until_shutdown_check(self):
            if get_now_in_secs() >= (self.startup_time_secs +
                                     (self.minimum_uptime_mins * 60)):
                self.shutdown_check_loop.stop
                self.shutdown_when_no_players = True
                check_for_shutdown(self)
            else:
                self.shutdown_when_no_players = False

    return ShutdownProtocol, ShutdownConnection
