"""
multibuild.py by IAmYourFriend

How to use:

Step 1: Type /mbreg and start "registering" your starting blocks.
Place single blocks everywhere where you want your building to
appear.

Step 2: Type /mb to start multibuilding. Important: Start building
exactly at the last starting block you placed during step 1.

During the use of /mbreg, your orientation (= in which direction
you look) will matter for the multibuild, as the building will be
mirrored accordingly. Type /mbdir to disable this.

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
def mbdir(connection):
    connection.ignore_direction = not connection.ignore_direction
    if connection.ignore_direction:
        return "Ignoring direction now."
    else:
        return "No longer ignoring direction."


add(mbreg)
add(mb)
add(mbdir)


def is_invalid_coord(x, y, z):
    return x < 0 or y < 0 or z < 0 or x > 511 or y > 511 or z > 62


def build_block(connection, x, y, z, color):
    if is_invalid_coord(x, y, z):
        return
    set_color = SetColor()
    set_color.value = make_color(*color)
    set_color.player_id = connection.player_id
    connection.protocol.send_contained(set_color)
    block_action.player_id = connection.player_id
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
    if not self.ignore_direction and not lastregblock[3] == regblock[3]:
        if abs(lastregblock[3] - regblock[3]) == 2:
            x = x * -1
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
    return (x, y, z)


def apply_script(protocol, connection, config):
    class MultibuildConnection(connection):
        is_registering = False
        is_multibuilding = False
        ignore_direction = False
        # x, y, z, direction (3 = north, 0 = east, 1 = south, 2 = west)
        startingblocks = []

        def on_block_build_attempt(self, x, y, z):
            if self.is_registering:
                self.startingblocks.append((x, y, z, get_direction(self)))
            elif self.is_multibuilding:
                for regblock in self.startingblocks:
                    block_diff = get_multiblock_diff(self, regblock, (x, y, z))
                    build_block(self,
                                regblock[0] + block_diff[0],
                                regblock[1] + block_diff[1],
                                regblock[2] + block_diff[2], self.color)
                if self.god:
                    self.refill()
                return False
            return connection.on_block_build_attempt(self, x, y, z)

        def on_line_build_attempt(self, points):
            if self.is_multibuilding:
                for point in points:
                    for regblock in self.startingblocks:
                        block_diff = get_multiblock_diff(self, regblock, point)
                        build_block(self,
                                    regblock[0] + block_diff[0],
                                    regblock[1] + block_diff[1],
                                    regblock[2] + block_diff[2], self.color)
                if self.god:
                    self.refill()
                return False
            return connection.on_line_build_attempt(self, points)

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
                            for regblock in self.startingblocks:
                                block_diff = get_multiblock_diff(self, regblock, block)
                                destroy_block(self,
                                              regblock[0] + block_diff[0],
                                              regblock[1] + block_diff[1],
                                              regblock[2] + block_diff[2])
                        return False
            return connection.on_block_destroy(self, x, y, z, value)

    return protocol, MultibuildConnection
