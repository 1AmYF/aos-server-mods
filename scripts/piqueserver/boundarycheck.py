# Bans a player that moves out of map boundaries (using noclip cheat).

from twisted.internet import reactor
from twisted.logger import Logger

BAN_LENGTH = 60  # minutes

log = Logger()


def apply_script(protocol, connection, config):
    class BoundaryCheckConnection(connection):
        def on_position_update(self):
            if (not self.local and self.world_object is not None and
                    self.world_object.position is not None):
                x = int(self.world_object.position.x)
                y = int(self.world_object.position.y)
                z = int(self.world_object.position.z)
                if x < 0 or x > 511 or y < 0 or y > 511 or z > 62:
                    self.spawn()
                    report_msg = ("Warning: %s #%s out of map boundaries (%s %s %s)" %
                                  (self.name, self.player_id, str(x), str(y), str(z)))
                    log.info(report_msg)
                    # self.protocol.irc_say(report_msg)
                    reactor.callLater(0.2, self.ban, "Hack Detected - Noclip", BAN_LENGTH)
            return connection.on_position_update(self)

    return protocol, BoundaryCheckConnection
