"""
Author: Nick Christensen AKA a_girl
Distant Drag Build Client Bug Patch for (0.75) and possibly (0.76)
This server side script prevents exploitation of a mostly unknown client bug
regarding drag building. Exploiters of this bug are able to drag build from
any remote point to which they have a clear line of sight to their current
location (as long as they don't crash their client by going too far out).
Obviously this ability has some heavy implications in situations involving
bridging or towering. I strongly recommended that this script be implemented
in any building oriented game mode such as babel or push. Just add it to your
script list in your config file and it will do the rest. To avoid the
proliferation of the knowledge of this bug, I will not go into details on how
to perform it.

Modified by IAmYourFriend:
The previous version of this script assumes where the linebuild started by
checking the player orientation. This produces false positives (e.g. fbpatch
grabs the coordinate next to the one that the client uses, especially during
movement. See https://youtu.be/bUbCkEJSkPc for a demonstration).
Removed the orientation check and replaced it with a check on the distance
between the players location when he started to linebuild and the first
coordinate delivered in points in function on_line_build_attempt. This
version can still produce false positives when player position on server
and client differs, but it is now less likely to happen than before.
"""

from pyspades.world import *


# Calculate the distance.
def distance(a, b):
    x1, y1, z1 = a
    x2, y2, z2 = b
    x = x2 - x1
    y = y2 - y1
    z = z2 - z1
    sum = (x ** 2) + (y ** 2) + (z ** 2)
    return math.sqrt(sum)


def apply_script(protocol, connection, config):
    class fbpatch2Connection(connection):

        line_build_pos = None

        def on_secondary_fire_set(self, secondary):
            # If right mouse button has been clicked to initiate drag building;
            # distinguishes from the right click release that marks the end point.
            if secondary == True:
                # 1 refers to block tool; if the tool in hand is a block
                if self.tool == 1:
                    # Grab player current position at drag build start
                    self.line_build_pos = (self.world_object.position.x,
                                           self.world_object.position.y,
                                           self.world_object.position.z)
            return connection.on_secondary_fire_set(self, secondary)

        def on_line_build_attempt(self, points):
            # Check the distance of line start (taken from points) and player position
            # when he started the line build. Allow build if distance is reasonable.
            if (self.line_build_pos is None or
                    distance(self.line_build_pos, points[0]) < 6):
                return connection.on_line_build_attempt(self, points)
            else:
                # Deny build
                return False

    return protocol, fbpatch2Connection
