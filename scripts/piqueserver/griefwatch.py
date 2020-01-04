"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

**griefwatch.py** reports warnings on suspected grief activity. The warning
will be sent to IRC, written into the log file and also sent ingame to players
with a staff role. Two commands allow tracking of block activity.

The warnings depend on the gamemode:
    - CTF or any other normal gamemode: reports removal of team blocks
    - Build: reports removal of both team and map blocks
    - Push: reports block spam at spawn, pillar spam (= blocking path),
      breaking blocks while on enemy side (= maybe teleport/other glitch)

Block removal warnings are triggered when removing lots of blocks in a short
time. Note that a warning alone is no proof that the player was really
griefing.

Setup
^^^^^

It is important to put this script **BEFORE** blockinfo in the config script
list. It will not work otherwise.

Commands
^^^^^^^^

* ``/inspect``
    Show coordinates of a block, it's color values and who placed it.

* ``/blocklog``
    Every block removal will be logged into a file (intended only for
    temporary use). Find it as block_removal.log in the log folder.
    Columns in the log file:
    name, id, team, tool, weapon, position, blockposition, distance, ip, time
"""

from pyspades.constants import *
from piqueserver.commands import command
from piqueserver.config import config
from pyspades.collision import distance_3d_vector
from pyspades.common import prettify_timespan, to_coordinates
from twisted.logger import Logger
from twisted.internet.reactor import seconds
import os.path

DEFAULTMODE, BUILD, PUSH = range(3)

BLOCK_REMOVAL_MAX = 20
BLOCK_REMOVAL_MINS = 2
BLOCK_TEAM_REMOVAL_MAX = 20
BLOCK_TEAM_REMOVAL_MINS = 2
SPAWN_BLOCKS_MAX = 200
PILLAR_HEIGHT_MAX = 4
PILLARS_MAX = 10

log = Logger()


@command(admin_only=True)
def inspect(connection):
    """
    Show coordinates of a block, it's color values and who placed it
    /inspect
    """
    if not connection.block_inspect:
        connection.block_inspect = True
        return "Hit a block to inspect it."
    else:
        connection.block_inspect = False
        return "No longer inspecting blocks."


@command(admin_only=True)
def blocklog(connection):
    """
    Every block removal will be logged into a file
    /blocklog
    """
    if not connection.protocol.block_log:
        connection.protocol.block_log = True
        return "Block removal logging enabled."
    else:
        connection.protocol.block_log = False
        return "Block removal logging disabled."


def log_block_removal(self, x, y, z):
    f = open(os.path.join(config.config_dir, "logs", "block_removal.log"), "a")
    self.blockposition.x = x
    self.blockposition.y = y
    self.blockposition.z = z
    distance = int(distance_3d_vector(self.world_object.position, self.blockposition))
    sep = ";"
    info = (self.name + sep + str(self.player_id) + sep + str(self.team.id) + sep +
            str(self.tool) + sep + str(self.weapon) + sep +
            str((int(self.world_object.position.x),
                 int(self.world_object.position.y),
                 int(self.world_object.position.z))) +
            sep + str((x, y, z)) + sep + str(distance) + sep +
            self.address[0] + sep + str(seconds()))
    f.write(info + "\n")
    f.close()


def is_in_area(x, y, top_x, top_y, bottom_x, bottom_y):
    return top_x <= x < bottom_x and top_y <= y < bottom_y


def send_warning(protocol, message):
    log.info(message)
    for player in protocol.players.values():
        if player.admin or player.user_types.moderator or player.user_types.guard:
            player.send_chat(message)
    irc_relay = protocol.irc_relay
    if irc_relay:
        if irc_relay.factory.bot and irc_relay.factory.bot.colors:
            message = "\x0304" + message + "\x0f"
        irc_relay.send(message)


def apply_script(protocol, connection, config):
    class GriefWatchConnection(connection):
        class blockposition():
            x = 0
            y = 0
            z = 0
        block_inspect = False
        spawn_blocks = 0
        pillar_blocks = 0
        pillar_count = 0
        pillar_counted = False
        pillar_last_xy = None
        located_on_enemy_side = False
        last_block_time = 0

        def check_for_block_removal(self, x, y, z, team_blocks_only=False):
            if self.blocks_removed is not None:
                time = seconds() - (BLOCK_TEAM_REMOVAL_MINS if team_blocks_only
                                    else BLOCK_REMOVAL_MINS) * 60.0
                block_time = 0
                amount = 0
                for b in reversed(self.blocks_removed):
                    if (team_blocks_only and b[1] is not None and b[1][0] != self.name and
                        b[1][1] == self.team.id) or (not team_blocks_only and
                                                     (b[1] is None or b[1][0] != self.name)):
                        if block_time == 0:
                            block_time = b[0]
                        if b[0] < time:
                            break
                        amount += 1
                if (amount > 1 and block_time > self.last_block_time + 30 and
                        not amount % (BLOCK_TEAM_REMOVAL_MAX if team_blocks_only
                                      else BLOCK_REMOVAL_MAX)):
                    send_warning(self.protocol, "Warning: %s #%s removed %s%s blocks (%s)"
                                 % (self.name, self.player_id, amount,
                                    " team" if team_blocks_only else "",
                                    to_coordinates(x, y)))
                    self.last_block_time = block_time

        def check_for_spawn_block_spam(self, x, y):
            range = 10  # spawn_range
            area = self.team.spawn
            if is_in_area(x, y, area[0] - range, area[1] - range,
                          area[0] + range, area[1] + range):
                self.spawn_blocks += 1
            if self.spawn_blocks >= SPAWN_BLOCKS_MAX:
                send_warning(self.protocol, "Warning: Potential block spam at spawn by %s #%s"
                             % (self.name, self.player_id))
                self.spawn_blocks = 0

        def check_for_pillar_block_spam(self, x, y):
            if self.pillar_last_xy is not None:
                if self.pillar_last_xy[0] == x and self.pillar_last_xy[1] == y:
                    if not self.pillar_counted:
                        self.pillar_blocks += 1
                else:
                    self.pillar_blocks = 0
                    self.pillar_counted = False
                if self.pillar_blocks >= PILLAR_HEIGHT_MAX - 1:
                    self.pillar_count += 1
                    self.pillar_counted = True
                    self.pillar_blocks = 0
                if self.pillar_count >= PILLARS_MAX:
                    send_warning(self.protocol, "Warning: Potential pillar spam by %s #%s"
                                 % (self.name, self.player_id))
                    self.pillar_count = 0
            self.pillar_last_xy = (x, y)

        def check_for_located_on_enemy_side(self):
            area = self.team.other.build_area
            if (area is not None and self.world_object is not None and
                    is_in_area(self.world_object.position.x,
                               self.world_object.position.y,
                               *area)):
                if not self.located_on_enemy_side:
                    x, y, z = self.get_location()
                    send_warning(self.protocol, "Warning: %s #%s is on enemy side (%s)"
                                 % (self.name, self.player_id, to_coordinates(x, y)))
                self.located_on_enemy_side = True

        def on_spawn(self, pos):
            self.located_on_enemy_side = False
            return connection.on_spawn(self, pos)

        def on_block_build(self, x, y, z):
            if self.protocol.current_mode == PUSH:
                self.check_for_spawn_block_spam(x, y)
                self.check_for_pillar_block_spam(x, y)
            return connection.on_block_build(self, x, y, z)

        def on_line_build(self, points):
            if self.protocol.current_mode == PUSH:
                for point in points:
                    self.check_for_spawn_block_spam(point[0], point[1])
            return connection.on_line_build(self, points)

        def on_block_destroy(self, x, y, z, mode):
            if self.block_inspect:
                message = ("Position " + str((x, y, z)) + ", Color " +
                           str(self.protocol.map.get_color(x, y, z)))
                info = None
                if self.protocol.block_info is not None:
                    if (x, y, z) in self.protocol.block_info:
                        info = self.protocol.block_info[(x, y, z)]
                    else:
                        info = None
                if info is not None:
                    message += ", placed by %s (%s)" % (info[0], "Green" if info[1] else "Blue")
                else:
                    message += ", map block"
                self.send_chat(message)
                return False
            return connection.on_block_destroy(self, x, y, z, mode)

        def on_block_removed(self, x, y, z):
            if self.protocol.current_mode == PUSH and not self.located_on_enemy_side:
                self.check_for_located_on_enemy_side()
            elif self.protocol.current_mode == BUILD:
                self.check_for_block_removal(x, y, z)
            elif self.protocol.current_mode == DEFAULTMODE:
                self.check_for_block_removal(x, y, z, team_blocks_only=True)
            if self.protocol.block_log:
                log_block_removal(self, x, y, z)
            connection.on_block_removed(self, x, y, z)

    class GriefWatchProtocol(protocol):
        current_mode = DEFAULTMODE
        block_log = False

        def on_map_change(self, map):
            if self.game_mode_name.lower() == "build":
                self.current_mode = BUILD
            elif self.game_mode_name.lower() == "push":
                self.current_mode = PUSH
            return protocol.on_map_change(self, map)

    return GriefWatchProtocol, GriefWatchConnection
