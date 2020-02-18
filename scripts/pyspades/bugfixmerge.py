"""
Collection of the most critical bugfixes for Pyspades/Pysnip
from various authors.
"""

from pyspades.constants import *
from pyspades.server import intel_drop
import re


def is_printable_ascii(string):
    pattern = re.compile("[\x20-\x7E]")
    return pattern.match(string)


def is_invalid_name(name):
    return (name is None or
            len(name) > 15 or
            len(name.strip()) == 0 or
            "#" in name or
            not is_printable_ascii(name))


def apply_script(protocol, connection, config):
    class BugFixMergeConnection(connection):

        def on_login(self, name):
            if is_invalid_name(name):
                self.kick(silent=True)
            return connection.on_login(self, name)

        def on_line_build_attempt(self, points):
            if self.blocks + 5 < len(points):
                return False
            value = connection.on_line_build_attempt(self, points)
            if value is False:
                return value
            for point in points:
                x, y, z = point
                if x < 0 or x > 511 or y < 0 or y > 511 or z < 0 or z > 61:
                    return False
            return value

        def drop_flag(self):
            protocol = self.protocol
            game_mode = protocol.game_mode
            if game_mode == CTF_MODE:
                for flag in (protocol.blue_team.flag,
                             protocol.green_team.flag):
                    player = flag.player
                    if player is not self:
                        continue
                    position = self.world_object.position
                    x = int(position.x)
                    y = int(position.y)
                    z = max(0, int(position.z))
                    if x < 0 or x > 511 or y < 0 or y > 511 or z < 0 or z > 63:
                        x, y, z = 255, 255, 61
                    z = self.protocol.map.get_z(x, y, z)
                    flag.set(x, y, z)
                    flag.player = None
                    intel_drop.player_id = self.player_id
                    intel_drop.x = flag.x
                    intel_drop.y = flag.y
                    intel_drop.z = flag.z
                    self.protocol.send_contained(intel_drop, save=True)
                    self.on_flag_drop()
                    break
            elif game_mode == TC_MODE:
                for entity in protocol.entities:
                    if self in entity.players:
                        entity.remove_player(self)

    return protocol, BugFixMergeConnection
