"""
push.py last modified 2019-03-06
Contributors: danhezee, StackOverflow, izzy, Danke, noway421, IAmYourFriend

The concept:
    Each team spawns at a set location with the enemy intel. They must "push"
    the intel towards their control point, which is also at a set location.
    The only way to arrive there is by building bridges over the deadly water.
    Further introduction to the game mode: https://youtu.be/DdisPY6vDD0

How to setup new maps:
    Spawn and CP locations must be configured via extensions in the map's
    map_name.txt metadata. Example:

extensions = {
    'push': True,
    'push_spawn_range' : 5,
    'push_blue_spawn' : (91, 276, 59),
    'push_blue_cp' : (91, 276, 59),
    'push_green_spawn' : (78, 86, 59),
    'push_green_cp' : (78, 86, 59),
    'water_damage' : 100
}

Additional (but optional) extensions, to mark each teams build area and prevent
the enemy from building there (and thereby helping the enemy). The build area
is defined by x and y of upper left corner, followed by x and y of bottom right
corner on the map. Example:

    'push_blue_build_area' : (64, 100, 243, 500),
    'push_green_build_area' : (268, 100, 447, 500),
"""

from pyspades.constants import *
from pyspades.common import make_color
from pyspades.server import set_color
from commands import add, admin, alias, get_team
from twisted.internet.task import LoopingCall
from random import randint
import colorsys
import time

# Disallow removal of map blocks. This allows a larger variety of maps that
# rely on more fragile structures. It also prevents griefing (like removing
# the map blocks before and after your teams bridge). Using server setting
# 'user_blocks_only' instead doesn't work reliable.
PROTECT_MAP_BLOCKS = True

# Allow the usage of /r to quickly respawn. As players can't refill blocks at
# their base, they would have to suicide otherwise. This is illogical, messes
# up their kill-death ratio and gives them an undeserved punishing respawn time.
ALLOW_RESPAWN_COMMAND = True

# How long to wait to allow the command /r again
RESPAWN_CMD_DELAY = 15  # seconds

# A player has to wait this amount after he spawned before he can pick
# the intel up. This is to reduce the instant/careless intel pickups.
INTEL_PICKUP_DELAY = 3  # seconds

# How long can you remove your own last blocks
BLOCK_REMOVAL_DELAY = 15  # seconds

# Reset intel after it was dropped somewhere
RESET_INTEL_AFTER_DROP = 3  # minutes

# No building near cp within this range (can be overwritten using
# map extension parameter "push_cp_protect_range")
DEFAULT_CP_PROTECT_RANGE = 8  # blocks

# Disable grenade damage within enemy spawn.
DISABLE_GRENADES_AT_SPAWN = False

CANT_DESTROY = "You can't destroy your team's blocks!"
NO_BLOCKS = "Out of blocks! Refill at base or type /r"
BUILDING_AT_CP = "You can't build near your base!"
BUILDING_AT_ENEMY_AREA = "Don't build for your enemy!"


def get_now_in_secs():
    return int(time.time())


def byte_rgb_to_hls(rgb):
    hls = colorsys.rgb_to_hls(*tuple(c / 255.0 for c in rgb))
    return tuple(int(round(c * 255)) for c in hls)


def byte_hls_to_rgb(hls):
    rgb = colorsys.hls_to_rgb(*tuple(c / 255.0 for c in hls))
    return tuple(int(round(c * 255)) for c in rgb)


def compare_hs(block_hls, team_hls):
    # if hue and saturation match
    return block_hls[0] == team_hls[0] and block_hls[2] == team_hls[2]


def byte_middle_range(byte):
    half = 50 / 2.0  # half of (byte/5.1)
    min = byte - half
    max = byte + half
    if min < 0:
        min = 0
        max = half
    elif max > 255:
        min = 255 - half
        max = 255
    return int(round(min)), int(round(max))


def create_area(x, y, range):
    return (x - range, y - range, x + range, y + range)


def is_in_area(x, y, top_x, top_y, bottom_x, bottom_y):
    return x >= top_x and y >= top_y and x < bottom_x and y < bottom_y


def has_flag(connection):
    flag = connection.team.other.flag
    if flag.player is not None:
        if flag.player is connection:
            return True
    return False


def reset_intel_position(protocol, team):
    # Flag should always spawn on z-top to prevent griefers burying it under blocks
    pos = (team.other.spawn[0],
           team.other.spawn[1],
           protocol.map.get_z(team.other.spawn[0], team.other.spawn[1], 1))
    team.flag.set(*pos)  # If spawn not set, it would throw error.
    team.flag.update()
    protocol.send_chat("The %s intel has been reset." % team.name)


@admin
def resetintel(connection, value):
    team = get_team(connection, value)
    reset_intel_position(connection.protocol, team)


@alias('r')
def respawn(connection):
    if connection.world_object is not None and not connection.world_object.dead:
        if (connection.last_spawn_time is None or connection.last_spawn_time +
                RESPAWN_CMD_DELAY <= get_now_in_secs()):
            if has_flag(connection):
                connection.drop_flag()
            connection.spawn()
        else:
            connection.send_chat(
                "Please wait %s seconds before using this command again."
                % (connection.last_spawn_time + RESPAWN_CMD_DELAY - get_now_in_secs()))


add(resetintel)
if ALLOW_RESPAWN_COMMAND:
    add(respawn)


def get_entity_location(connection, entity_id):
    if entity_id == BLUE_BASE:
        return connection.protocol.blue_team.cp
    elif entity_id == GREEN_BASE:
        return connection.protocol.green_team.cp

    elif entity_id == BLUE_FLAG:
        return (connection.protocol.green_team.spawn[0],
                connection.protocol.green_team.spawn[1],
                1)
    elif entity_id == GREEN_FLAG:
        return (connection.protocol.blue_team.spawn[0],
                connection.protocol.blue_team.spawn[1],
                1)


def get_spawn_location(connection):
    # distance from spawn center to randomly spawn in
    spawn_range = connection.protocol.spawn_range
    xb = connection.team.spawn[0]
    yb = connection.team.spawn[1]
    xb += randint(-spawn_range, spawn_range)
    yb += randint(-spawn_range, spawn_range)
    return (xb, yb, connection.protocol.map.get_z(xb, yb))


def apply_script(protocol, connection, config):
    class PushConnection(connection):
        last_spawn_time = None
        # list entry format: ((x, y, z), timestamp when block was placed)
        last_blocks = None

        def is_in_invalid_area(self, x, y, check_area, error_message):
            if is_in_area(x, y, check_area[0], check_area[1],
                          check_area[2], check_area[3]):
                self.send_chat(error_message)
                return True
            else:
                return False

        def invalid_build_position(self, x, y, z):
            # prevent teams from building near their cp
            if self.is_in_invalid_area(x, y, create_area(self.team.cp[0], self.team.cp[1],
                                       self.protocol.cp_protect_range), BUILDING_AT_CP):
                return True
            # prevent teams from building in enemy build area
            if self.team.build_area is not None and self.is_in_invalid_area(
                        x, y, self.team.other.build_area, BUILDING_AT_ENEMY_AREA):
                return True
            return False

        def random_color(self):
            (h, l, s) = self.team.hls
            l = randint(self.team.light_range[0], self.team.light_range[1])
            color = byte_hls_to_rgb((h, l, s))

            self.color = color
            set_color.player_id = self.player_id
            set_color.value = make_color(*color)
            self.send_contained(set_color)
            self.protocol.send_contained(set_color, save=True)

        def on_line_build_attempt(self, points):
            can_build = connection.on_line_build_attempt(self, points)
            if can_build is False:
                return False

            if ALLOW_RESPAWN_COMMAND and self.blocks == len(points):
                self.send_chat(NO_BLOCKS)

            for point in points:
                if self.invalid_build_position(*point):
                    return False

            if self.last_blocks is None:
                self.last_blocks = []
            if BLOCK_REMOVAL_DELAY > 0:
                for point in points:
                    x, y, z = point[0], point[1], point[2]
                    if not self.protocol.map.get_solid(x, y, z):
                        self.last_blocks.append(((x, y, z), get_now_in_secs()))

            self.random_color()
            return can_build

        def on_block_build_attempt(self, x, y, z):
            can_build = connection.on_block_build_attempt(self, x, y, z)
            if can_build is False:
                return False

            if ALLOW_RESPAWN_COMMAND and self.blocks == 0:
                self.send_chat(NO_BLOCKS)

            if self.invalid_build_position(x, y, z):
                return False

            if self.last_blocks is None:
                self.last_blocks = []
            if BLOCK_REMOVAL_DELAY > 0:
                self.last_blocks.append(((x, y, z), get_now_in_secs()))

            self.random_color()
            return can_build

        def on_block_destroy(self, x, y, z, value):
            is_trusted = (self.admin or self.god or self.user_types.moderator or
                          self.user_types.guard or self.user_types.trusted)
            if value == DESTROY_BLOCK:
                blocks = ((x, y, z),)
            elif value == SPADE_DESTROY:
                blocks = ((x, y, z), (x, y, z + 1), (x, y, z - 1))
            elif value == GRENADE_DESTROY:
                blocks = []
                for nade_x in xrange(x - 1, x + 2):
                    for nade_y in xrange(y - 1, y + 2):
                        for nade_z in xrange(z - 1, z + 2):
                            blocks.append((nade_x, nade_y, nade_z))

            for block in blocks:
                is_last_block_removal = False
                if self.last_blocks is not None and not is_trusted:
                    for last in self.last_blocks:
                        if block == last[0]:
                            if last[1] + BLOCK_REMOVAL_DELAY < get_now_in_secs():
                                self.last_blocks.remove(last)
                                return False
                            self.last_blocks.remove(last)
                            is_last_block_removal = True
                            break
                if is_last_block_removal:
                    continue

                block_info = self.protocol.map.get_point(*block)
                if block_info[0] is True:
                    block_hls = byte_rgb_to_hls(block_info[1])
                    is_blue_block = compare_hs(block_hls, self.protocol.blue_team.hls)
                    is_green_block = compare_hs(block_hls, self.protocol.green_team.hls)
                    is_team_block = ((self.team is self.protocol.blue_team and is_blue_block) or
                                     (self.team is self.protocol.green_team and is_green_block))
                    if is_team_block and not is_trusted:
                        self.send_chat(CANT_DESTROY)
                        return False
                    if PROTECT_MAP_BLOCKS and not is_blue_block and not is_green_block:
                        return False
            return connection.on_block_destroy(self, x, y, z, value)

        def on_flag_take(self):
            if self.last_spawn_time + INTEL_PICKUP_DELAY > get_now_in_secs():
                return False
            return connection.on_flag_take(self)

        def on_spawn(self, pos):
            self.last_spawn_time = get_now_in_secs()
            self.last_blocks = None
            return connection.on_spawn(self, pos)

        def grenade_exploded(self, grenade):
            if DISABLE_GRENADES_AT_SPAWN:
                if not (self is None or self.name is None or
                        self.team is None or self.team.other is None):
                    grenade_x = int(grenade.position.x)
                    grenade_y = int(grenade.position.y)
                    spawn_x = self.team.other.spawn[0]
                    spawn_y = self.team.other.spawn[1]
                    spawn_range = self.protocol.spawn_range + 8
                    if is_in_area(grenade_x, grenade_y,
                                  spawn_x - spawn_range, spawn_y - spawn_range,
                                  spawn_x + spawn_range, spawn_y + spawn_range):
                        return False
            return connection.grenade_exploded(self, grenade)

    class PushProtocol(protocol):
        game_mode = CTF_MODE
        spawn_range = 0
        cp_protect_range = 0
        check_loop = None
        reset_intel_blue_timer = 0
        reset_intel_green_timer = 0

        def __init__(self, *arg, **kw):
            protocol.__init__(self, *arg, **kw)
            self.blue_team.hls = byte_rgb_to_hls(self.blue_team.color)
            self.blue_team.light_range = byte_middle_range(
                self.blue_team.hls[1])

            self.green_team.hls = byte_rgb_to_hls(self.green_team.color)
            self.green_team.light_range = byte_middle_range(
                self.green_team.hls[1])

        def check_intel_location(self, team, timer_val):
            if team.flag is not None:
                if team.flag.get()[2] >= 63:
                    reset_intel_position(self, team)
                    return 0
                elif team.flag.player is None:
                    timer_val += 1
                    if timer_val >= RESET_INTEL_AFTER_DROP * (60 / self.check_loop.interval):
                        reset_intel_position(self, team)
                        return 0
                    return timer_val
                else:
                    return 0
            return timer_val

        def check_intel_locations(self):
            self.reset_intel_blue_timer = self.check_intel_location(
                                              self.blue_team, self.reset_intel_blue_timer)
            self.reset_intel_green_timer = self.check_intel_location(
                                              self.green_team, self.reset_intel_green_timer)

        def on_map_change(self, map):
            extensions = self.map_info.extensions
            for must_have in ('push_blue_spawn', 'push_green_spawn',
                              'push_blue_cp', 'push_green_cp'):
                if must_have not in extensions:
                    raise Exception("Missing push map metadata: %s" % must_have)

            extensions['water_damage'] = 100
            # distance from spawn center to randomly spawn in
            self.spawn_range = extensions.get('push_spawn_range', 5)
            # distance from cp where building is not allowed
            self.cp_protect_range = extensions.get('push_cp_protect_range',
                                                   DEFAULT_CP_PROTECT_RANGE)

            self.blue_team.spawn = extensions.get('push_blue_spawn')
            self.blue_team.cp = extensions.get('push_blue_cp')
            self.blue_team.build_area = extensions.get('push_blue_build_area')

            self.green_team.spawn = extensions.get('push_green_spawn')
            self.green_team.cp = extensions.get('push_green_cp')
            self.green_team.build_area = extensions.get('push_green_build_area')

            self.map_info.get_entity_location = get_entity_location
            self.map_info.get_spawn_location = get_spawn_location

            if self.check_loop is not None:
                self.check_loop.stop()
            self.reset_intel_blue_timer = 0
            self.reset_intel_green_timer = 0
            self.check_loop = LoopingCall(self.check_intel_locations)
            self.check_loop.start(3, now=False)

            return protocol.on_map_change(self, map)

    return PushProtocol, PushConnection
