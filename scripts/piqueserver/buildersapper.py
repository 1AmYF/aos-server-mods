"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

**buildersapper.py** enables two class modes for players to choose from:
    - Builder: refills after placing the last block, heal teammates with
      spade, grenades build a structure.
    - Sapper: ammo refills, reduced body damage, deadly grenades.

On first join a random mode is assigned. Modes can be switched with commands.
Use server settings to change how many refills a player can have.
Originally written to use with build-focused gamemodes like Babel or Push.

Options
^^^^^^^

.. code-block:: python

    [buildersapper]
    # Maximum amount of refills the builder mode can have.
    block_refills = 1

    # Maximum amount of ammo refills the sapper mode can have.
    ammo_refills = 1

Commands
^^^^^^^^

* ``/builder``
    Choose the builder mode.

* ``/sapper``
    Choose the sapper mode.

* ``/mode``
    Show information about the modes.
"""

from pyspades.constants import *
from pyspades.common import make_color
from pyspades import contained as loaders
from piqueserver.commands import command
from piqueserver.config import config
from random import choice

BUILDER_HEAL_RATE = 5
SAPPER_HIT_AMOUNT = 0.6

BUILDER, SAPPER = range(2)
MODE_CONFIG = config.section("buildersapper")


@command()
def builder(connection):
    """
    Choose the builder mode
    /builder
    """
    if connection.class_mode == BUILDER:
        return "You are already a builder."
    connection.class_mode = BUILDER
    connection.kill()


@command()
def sapper(connection):
    """
    Choose the sapper mode
    /sapper
    """
    if connection.class_mode == SAPPER:
        return "You are already a sapper."
    connection.class_mode = SAPPER
    connection.kill()


@command()
def mode(connection):
    """
    Show information about the modes
    /mode
    """
    msg = []
    msg.append("You are a %s. Choose a mode by typing:" %
               ("sapper" if connection.class_mode == SAPPER else "builder"))
    msg.append("/builder for %s refill(s) after last block, heal teammates with spade, "
               "build grenade." % connection.block_refills_max)
    msg.append("/sapper for %s ammo refill(s), less body damage, deadly grenade." %
               connection.ammo_refills_max)
    connection.send_lines(msg)


def is_invalid_coord(x, y, z):
    return x < 0 or y < 0 or z < 0 or x > 511 or y > 511 or z > 61


def build_block(connection, x, y, z, color):
    if is_invalid_coord(x, y, z):
        return
    set_color = loaders.SetColor()
    set_color.value = make_color(*color)
    set_color.player_id = 32
    connection.protocol.broadcast_contained(set_color)
    block_action = loaders.BlockAction()
    block_action.player_id = 32
    block_action.x = x
    block_action.y = y
    block_action.z = z
    block_action.value = BUILD_BLOCK
    connection.protocol.map.set_point(x, y, z, color)
    connection.protocol.broadcast_contained(block_action, save=True)


def build_grenade_structure(connection, position):
    x = int(position.x)
    y = int(position.y)
    z = int(position.z)
    structure = [(x, y, z), (x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z),
                 (x, y, z - 1), (x + 1, y, z - 1), (x - 1, y, z - 1), (x, y + 1, z - 1),
                 (x, y - 1, z - 1), (x, y, z - 2), (x + 1, y, z - 2), (x - 1, y, z - 2),
                 (x, y + 1, z - 2), (x, y - 1, z - 2), (x, y, z - 3), (x + 1, y, z - 3),
                 (x - 1, y, z - 3), (x, y + 1, z - 3), (x, y - 1, z - 3)]
    for pos in structure:
        if connection.on_block_build_attempt(pos[0], pos[1], pos[2]) is not False:
            build_block(connection, pos[0], pos[1], pos[2], connection.color)


def apply_script(protocol, connection, config):
    class BuilderSapperConnection(connection):
        class_mode = None
        block_refills_max = MODE_CONFIG.option("block_refills", 1).get()
        block_refills = 0
        ammo_refills_max = MODE_CONFIG.option("ammo_refills", 1).get()
        ammo_refills = 0

        def on_spawn(self, pos):
            if self.class_mode is None:
                self.class_mode = choice([SAPPER, BUILDER])
            self.block_refills = self.block_refills_max
            self.ammo_refills = self.ammo_refills_max
            self.send_chat("You are a %s. For more info type /mode" %
                           ("sapper" if self.class_mode == SAPPER else "builder"))
            return connection.on_spawn(self, pos)

        def on_shoot_set(self, fire):
            if fire and self.class_mode == SAPPER:
                self.check_for_ammo_refill()
            return connection.on_shoot_set(self, fire)

        def check_for_ammo_refill(self):
            if self.ammo_refills > 0 and self.weapon_object.current_stock == 0:
                self.weapon_object.current_stock = self.weapon_object.stock
                weapon_reload = loaders.WeaponReload()
                weapon_reload.player_id = self.player_id
                weapon_reload.clip_ammo = self.weapon_object.ammo
                weapon_reload.reserve_ammo = self.weapon_object.stock
                self.send_contained(weapon_reload)
                self.ammo_refills -= 1
                self.send_chat("Your ammo has been refilled! (refills left: %d)" %
                               self.ammo_refills)

        def on_line_build(self, points):
            if self.class_mode == BUILDER:
                self.check_for_block_refill()
            return connection.on_line_build(self, points)

        def on_block_build(self, x, y, z):
            if self.class_mode == BUILDER:
                self.check_for_block_refill()
            return connection.on_block_build(self, x, y, z)

        def check_for_block_refill(self):
            if self.blocks < 1 and self.block_refills > 0:
                self.refill()
                self.block_refills -= 1
                self.send_chat("You have been refilled! (refills left: %d)" %
                               self.block_refills)

        def on_refill(self):
            self.block_refills = self.block_refills_max
            self.ammo_refills = self.ammo_refills_max
            return connection.on_refill(self)

        def on_hit(self, hit_amount, hit_player, type, grenade):
            if (self.class_mode == BUILDER and self.tool == SPADE_TOOL and
                    self.team == hit_player.team):
                if hit_player.hp >= 100:
                    self.send_chat(hit_player.name + " is at full health.")
                elif hit_player.hp > 0:
                    hit_player.set_hp(hit_player.hp + BUILDER_HEAL_RATE)
            elif (hit_player.class_mode == SAPPER and hit_amount <= 100 and
                    type != HEADSHOT_KILL):
                hit_amount *= SAPPER_HIT_AMOUNT
                if hit_player != self:
                    hit_player.hit(hit_amount, self)
                else:
                    hit_player.hit(hit_amount, None)
                return False
            return connection.on_hit(self, hit_amount, hit_player, type, grenade)

        def grenade_exploded(self, grenade):
            if self.class_mode == BUILDER:
                build_grenade_structure(self, grenade.position)
                return False
            return connection.grenade_exploded(self, grenade)

    return protocol, BuilderSapperConnection
