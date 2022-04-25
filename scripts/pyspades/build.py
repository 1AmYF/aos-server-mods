"""
build.py by IAmYourFriend https://twitter.com/1AmYF

build.py is a simple gamemode for building. Killing is disabled and only
players with a login are able to build.
"""

from pyspades.constants import *

# Roles that receive build permission on login
BUILD_ROLES = ("admin", "moderator", "guard", "trusted", "builder")

HIDE_COORD = (0, 0, 63)


def apply_script(protocol, connection, config):
    class BuildModeConnection(connection):
        def on_flag_take(self):
            return False

        def on_grenade(self, time_left):
            if not self.building:
                return False
            return connection.on_grenade(self, time_left)

        def on_connect(self):
            self.building = False
            self.killing = False
            return connection.on_connect(self)

        def on_user_login(self, user_type, verbose=True):
            if user_type in BUILD_ROLES:
                self.god = True
                self.building = True
            return connection.on_user_login(self, user_type, verbose)

    class BuildModeProtocol(protocol):
        game_mode = CTF_MODE

        def on_base_spawn(self, x, y, z, base, entity_id):
            return HIDE_COORD

        def on_flag_spawn(self, x, y, z, flag, entity_id):
            return HIDE_COORD

        def on_map_change(self, map):
            self.green_team.locked = True
            self.balanced_teams = 0
            self.fall_damage = False
            return protocol.on_map_change(self, map)

    return BuildModeProtocol, BuildModeConnection
