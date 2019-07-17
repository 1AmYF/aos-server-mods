# Prevents bullets from destroying blocks beyond fog range.
# Recommended to use especially in gamemodes like Push or Babel.

from pyspades.constants import WEAPON_TOOL
from pyspades.collision import distance_3d_vector

MAX_BLOCK_SHOOT_DISTANCE = 139  # blocks


def apply_script(protocol, connection, config):
    class FogBlockConnection(connection):
        class blockposition():
            x = 0
            y = 0
            z = 0

        def on_block_destroy(self, x, y, z, value):
            if self.tool is WEAPON_TOOL:
                self.blockposition.x = x
                self.blockposition.y = y
                self.blockposition.z = z
                distance = int(distance_3d_vector(self.world_object.position,
                                                  self.blockposition))
                if distance >= MAX_BLOCK_SHOOT_DISTANCE:
                    return False
            return connection.on_block_destroy(self, x, y, z, value)
    return protocol, FogBlockConnection
