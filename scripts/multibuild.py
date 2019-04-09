"""
multibuild.py by IAmYourFriend

How to use:

Step 1: Type /mbreg and start "registering" your starting blocks.
Place single blocks everywhere where you want your building to
appear.

Step 2: Type /mb to start multibuilding. Important: Start building
exactly at the last starting block you placed during step 1.

During the use of /mbreg, your orientation (= in which direction
you look) is stored in case you want to mirror your multibuild
accordingly. You can enable 2 types of mirrors:
/mbmirror 1 (normal, reversing mirror)
/mbmirror 2 (non-reversing mirror)

You can toggle /mbreg or /mb all the time if you want to pause the
feature and build normal again.

Short video showcasing the feature:
https://twitter.com/1AmYF/status/1078610014867202048
"""

from pyspades.constants import *
from pyspades.contained import BlockAction, SetColor
from pyspades.server import block_action
from pyspades.common import make_color
from commands import add, admin, alias
from math import atan2, pi
from twisted.internet.reactor import callLater


BUILD_DELAY = 0.04


@admin
def mbreg(connection):
    connection.is_multibuilding = False
    connection.is_registering = not connection.is_registering
    if connection.is_registering:
        connection.startingblocks = []
        return "Place your starting blocks now."
    else:
        return "No longer placing starting blocks."


@admin
def mb(connection):
    if len(connection.startingblocks) < 1:
        return "You haven't placed any starting blocks yet. Use /mbreg"
    connection.is_registering = False
    connection.is_multibuilding = not connection.is_multibuilding
    if connection.is_multibuilding:
        return "Start multibuilding at your last placed block!"
    else:
        return "No longer multibuilding."


@admin
def mbmirror(connection, mirror=0):
    mirror = int(mirror)
    if mirror < 0 or mirror > 2:
        raise ValueError()
    connection.mirror = mirror
    if mirror == 0:
        return "Mirror disabled. Type /mbmirror 1 or /mbmirror 2 to enable."
    else:
        return ("Mirror type set to: %s (%s)" % (str(mirror),
                "reversing" if mirror == 1 else "non-reversing"))


add(mbreg)
add(mb)
add(mbmirror)


def is_invalid_coord(x, y, z):
    return x < 0 or y < 0 or z < 0 or x > 511 or y > 511 or z > 62


def build_block(connection, x, y, z, color):
    if is_invalid_coord(x, y, z):
        return
    set_color = SetColor()
    set_color.value = make_color(*color)
    set_color.player_id = 32
    connection.protocol.send_contained(set_color)
    block_action.player_id = 32
    block_action.x = x
    block_action.y = y
    block_action.z = z
    block_action.value = BUILD_BLOCK
    connection.protocol.map.set_point(x, y, z, color)
    connection.protocol.send_contained(block_action, save=True)


def destroy_block(connection, x, y, z):
    if is_invalid_coord(x, y, z):
        return
    if connection.protocol.map.get_solid(x, y, z):
        block_action.player_id = connection.player_id
        block_action.x = x
        block_action.y = y
        block_action.z = z
        block_action.value = DESTROY_BLOCK
        connection.protocol.map.destroy_point(x, y, z)
        connection.protocol.send_contained(block_action, save=True)


def get_direction(self):
    return int(round(atan2(self.world_object.orientation.y,
                           self.world_object.orientation.x) / pi * 2) % 4)


def get_multiblock_diff(self, regblock, xyz_new):
    lastregblock = self.startingblocks[len(self.startingblocks) - 1]
    x = xyz_new[0] - lastregblock[0]
    y = xyz_new[1] - lastregblock[1]
    z = xyz_new[2] - lastregblock[2]
    if self.mirror > 0 and not lastregblock[3] == regblock[3]:
        if abs(lastregblock[3] - regblock[3]) == 2:
            if self.mirror == 2 or not lastregblock[3] % 2:
                x = x * -1
            if self.mirror == 2 or lastregblock[3] % 2:
                y = y * -1
        else:
            tmp_x = x
            x = y
            y = tmp_x
            if regblock[3] == 1 or regblock[3] == 2:
                x = x * -1
            else:
                y = y * -1
            if lastregblock[3] > 1:
                x = x * -1
                y = y * -1
            if self.mirror == 1 and (lastregblock[3] == regblock[3] + 1 or
                                     lastregblock[3] - regblock[3] == -3):
                if regblock[3] % 2:
                    x = x * -1
                else:
                    y = y * -1
    return (x, y, z)


def rollout_multiblocks(self, coord, destroy=False):
    delay = 0
    first = True
    for regblock in reversed(self.startingblocks):
        if first:
            first = False
            continue
        block_diff = get_multiblock_diff(self, regblock, coord)
        mb_x = regblock[0] + block_diff[0]
        mb_y = regblock[1] + block_diff[1]
        mb_z = regblock[2] + block_diff[2]
        if destroy:
            callLater(delay, destroy_block, self, mb_x, mb_y, mb_z)
        else:
            callLater(delay, build_block, self, mb_x, mb_y, mb_z, self.color)
        delay += BUILD_DELAY


def apply_script(protocol, connection, config):
    class MultibuildConnection(connection):
        is_registering = False
        is_multibuilding = False
        mirror = 0
        # x, y, z, direction (0 = east, 1 = south, 2 = west, 3 = north)
        startingblocks = []

        def on_block_build(self, x, y, z):
            if self.is_registering:
                self.startingblocks.append((x, y, z, get_direction(self)))
            elif self.is_multibuilding:
                rollout_multiblocks(self, (x, y, z))
                if self.god:
                    self.refill()
            return connection.on_block_build(self, x, y, z)

        def on_line_build(self, points):
            if self.is_registering:
                for point in points:
                    self.startingblocks.append((point[0], point[1], point[2],
                                               get_direction(self)))
            elif self.is_multibuilding:
                delay = 0
                for point in points:
                    callLater(delay, rollout_multiblocks, self, point)
                    delay += BUILD_DELAY
                if self.god:
                    self.refill()
            return connection.on_line_build(self, points)

        def on_block_destroy(self, x, y, z, value):
            if self.is_registering or self.is_multibuilding:
                blocks = None
                if value == DESTROY_BLOCK:
                    blocks = ((x, y, z),)
                elif value == SPADE_DESTROY:
                    blocks = ((x, y, z), (x, y, z + 1), (x, y, z - 1))
                if blocks is not None:
                    if self.is_registering:
                        for block in blocks:
                            newstartingblocks = []
                            for sblock in self.startingblocks:
                                if not (block[0] == sblock[0] and
                                        block[1] == sblock[1] and
                                        block[2] == sblock[2]):
                                    newstartingblocks.append(sblock)
                            self.startingblocks = newstartingblocks
                    elif self.is_multibuilding:
                        for block in blocks:
                            rollout_multiblocks(self, block, destroy=True)
            return connection.on_block_destroy(self, x, y, z, value)

    return protocol, MultibuildConnection
