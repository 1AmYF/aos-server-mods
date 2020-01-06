"""
build.py by IAmYourFriend https://twitter.com/1AmYF

build.py is a gamemode for building. By default, only players with a login
are able to build, unless a public build region is defined on the map where
anyone can build instantly. Temporary build permissions can be given using
the commands.

Killing and fall damage is disabled, green team is locked and god mode is
assigned automatically. To limit griefing, grenades are disabled (you only see
and hear your own grenade explosions) and block destruction with weapons is
only possible for players with a login.

Setup:

    Set game_mode in your server config to "build". To define a public build
    area, add the coordinates (x and y) of the upper left and the bottom right
    corner to the map txt metadata.
    Example (of making the entire left half of the map public):

        extensions = {
            'public_build_area' : (0, 0, 255, 512)
        }

    Recommended scripts to use along with this mode:
        - autosave (automatic backups of the map)
        - griefwatch (reports when a player removes a lot of blocks)
        - multibuild (ingame mapping tool)

Commands:

    Note: All actions done with these commands are not persistent, only last
    as long as the server runs and will be lost on a server restart.

    /protect <area>
        Protect an area inside the public build region. If no argument is given,
        all protected areas will be listed. Example: /protect B2

    /build <#id> <area>
        Give temporary build permission to a player for a protected area. Lasts
        until the player disconnects or the command is repeated to revert the
        permission. Example: /build #3 B2

    /buildpw <password> <area>
        Quick way of giving a player a password for a protected area, so he
        can continue building there when he joins again later. Repeat the command
        to remove the password. If no area is given, all areas for that password
        will be listed. Example: /buildpw secret B2

    /allow <password>
        Using the password given with the /buildpw command to get permission
        for areas. Example: /allow secret

    /lockdown
        Freeze the map, nobody is able to build or login anymore, except the
        admin role. Repeat the command to revert it. Example: /lockdown
"""

from commands import add, admin, get_player
from pyspades.constants import *
from pyspades.server import *
from pyspades.common import coordinates, to_coordinates


CANT_BUILD_MSG = "You need permission to build in this area."
LOCKDOWN_MSG = "The map is currently protected."
BUILD_ROLES = ("admin", "moderator", "guard", "trusted", "builder")
HIDE_COORD = (0, 0, 63)


@admin
def protect(connection, area=None):
    if area is None:
        areas_str = ""
        for protected_coord in connection.protocol.protected_areas:
            areas_str += to_coordinates(protected_coord[0], protected_coord[1]) + " "
        if areas_str == "":
            areas_str = "none"
        return "Protected areas: " + areas_str
    else:
        area_coord = coordinates(area)
        connection.protocol.protected_areas.symmetric_difference_update([area_coord])
        message = ("The area at %s is now %s" % (area.upper(), "protected" if area_coord in
                   connection.protocol.protected_areas else "unprotected"))
        connection.protocol.send_chat(message)


@admin
def build(connection, player, area=None):
    if player is None:
        raise ValueError()
    player = get_player(connection.protocol, player)
    if area is None:
        if len(player.allowed_areas) < 1:
            raise ValueError()
        else:
            player.allowed_areas.clear()
            connection.protocol.send_chat(player.name +
                                          " can no longer build at protected areas")
    else:
        area_coord = coordinates(area)
        player.allowed_areas.symmetric_difference_update([area_coord])
        message = ("%s can %s build at %s" % (player.name, "temporary"
                   if area_coord in player.allowed_areas else "no longer", area.upper()))
        connection.protocol.send_chat(message)


@admin
def buildpw(connection, password=None, area=None):
    if password is None and area is None:
        pws_str = ""
        for pw in connection.protocol.password_areas:
            pws_str += pw + " "
        if pws_str == "":
            pws_str = "none"
        return "Passwords: " + pws_str
    elif area is None:
        areas_str = ""
        for pw_coord in connection.protocol.password_areas.get(password):
            areas_str += to_coordinates(pw_coord[0], pw_coord[1]) + " "
        if areas_str == "":
            areas_str = "none"
        return "Areas for " + password + ": " + areas_str
    else:
        if connection.protocol.password_areas.get(password) is None:
            connection.protocol.password_areas[password] = set()
        areas = connection.protocol.password_areas[password]
        area_coord = coordinates(area)
        areas.symmetric_difference_update([area_coord])
        message = ("%s now %s with %s" % (area.upper(),
                   "allowed" if area_coord in areas else "disallowed", password))
        if len(areas) < 1:
            connection.protocol.password_areas.pop(password, None)
        return message


def allow(connection, password):
    areas = connection.protocol.password_areas.get(password)
    if areas is None or len(areas) < 1:
        return "Invalid key"
    else:
        connection.allowed_areas.update(areas)
        areas_str = ""
        for a in areas:
            areas_str += to_coordinates(a[0], a[1]) + " "
        connection.protocol.irc_say("%s got permission for %s" %
                                    (connection.name, areas_str))
        return "Permission allowed for " + areas_str


@admin
def lockdown(connection):
    if not connection.protocol.lockdown:
        connection.protocol.lockdown = True
        return "Lockdown enabled."
    else:
        connection.protocol.lockdown = False
        return "Lockdown disabled."


add(protect)
add(build)
add(buildpw)
add(allow)
add(lockdown)


def is_in_area(area_coord, x, y):
    sx, sy = area_coord
    return x >= sx and y >= sy and x < sx + 64 and y < sy + 64


def is_in_public_area(connection, x, y):
    for area_coord in connection.protocol.protected_areas:
        if is_in_area(area_coord, x, y):
            return False
    public_area = connection.protocol.public_build_area
    return (public_area is not None and public_area[0] <= x < public_area[2] and
            public_area[1] <= y < public_area[3])


def has_protected_area(connection, x, y):
    for area_coord in connection.allowed_areas:
        if is_in_area(area_coord, x, y):
            return True
    return False


def has_role(connection):
    return any(t in connection.user_types for t in BUILD_ROLES)


def can_build(connection, x, y):
    return (not connection.protocol.lockdown and
            (is_in_public_area(connection, x, y) or
             has_role(connection) or
             has_protected_area(connection, x, y)))


def apply_script(protocol, connection, config):
    class BuildModeConnection(connection):
        allowed_areas = None

        def on_flag_take(self):
            return False

        def on_grenade(self, time_left):
            if self.god:
                self.refill()
            return False

        def on_shoot_set(self, fire):
            if self.tool == WEAPON_TOOL and fire and self.weapon_object.current_stock <= 1:
                self.refill()
            connection.on_shoot_set(self, fire)

        def on_connect(self):
            self.allowed_areas = set()
            self.protocol.green_team.locked = True
            self.protocol.balanced_teams = 0
            self.protocol.fall_damage = False
            self.killing = False
            self.god = True
            return connection.on_connect(self)

        def on_user_login(self, user_type, verbose=True):
            if user_type in BUILD_ROLES:
                if self.protocol.lockdown and user_type != "admin":
                    self.send_chat(LOCKDOWN_MSG)
                    return False
                self.building = True
            return connection.on_user_login(self, user_type, verbose)

        def on_line_build_attempt(self, points):
            if self.protocol.lockdown:
                return False
            if not has_role(self):
                for point in points:
                    if not can_build(self, point[0], point[1]):
                        return False
            return connection.on_line_build_attempt(self, points)

        def on_block_build_attempt(self, x, y, z):
            if not can_build(self, x, y):
                self.send_chat(LOCKDOWN_MSG if self.protocol.lockdown
                               else CANT_BUILD_MSG)
                return False
            return connection.on_block_build_attempt(self, x, y, z)

        def on_block_destroy(self, x, y, z, value):
            if not can_build(self, x, y):
                return False
            if self.tool == WEAPON_TOOL and not has_role(self):
                return False
            return connection.on_block_destroy(self, x, y, z, value)

    class BuildModeProtocol(protocol):
        game_mode = CTF_MODE
        protected_areas = set()
        password_areas = {}
        public_build_area = None
        lockdown = False

        def on_base_spawn(self, x, y, z, base, entity_id):
            return HIDE_COORD

        def on_flag_spawn(self, x, y, z, flag, entity_id):
            return HIDE_COORD

        def on_map_change(self, map):
            self.public_build_area = self.map_info.extensions.get("public_build_area")
            return protocol.on_map_change(self, map)

    return BuildModeProtocol, BuildModeConnection
