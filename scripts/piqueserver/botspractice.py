"""
botspractice.py by IAmYourFriend https://twitter.com/1AmYF

botspractice.py is a gamemode for target practice with bots. The bots will walk
around randomly in a fixed area surrounded by bases where players can refill
ammo. The bot creation code is derived from basicbot.py by hompy.

Setup:

    Set game_mode in your server config to "botspractice" (in the serverlist, the
    name of the gamemode will be shown as "bots").
    The bot spawn area and size can be defined individually for maps using map
    txt metadata. Example:

        extensions = {
            'spawn_center' : (128, 320),
            'bots_spawn_range' : 60
        }

Commands:

    /addbot <amount> <team>
        Manually add bots.
    /toggleai
        Toggle the activity of the bots.
"""

from math import cos, sin
from enet import Address
from pyspades.contained import InputData, SetTool, WeaponInput
from pyspades.server import Territory
from pyspades.common import Vertex3
from pyspades.collision import vector_collision
from pyspades.constants import *
from piqueserver.commands import command, get_team
from random import uniform, randint, choice

BOT_NAME = "Target"
BOT_AMOUNT = 16
BOT_RESPAWN_TIME = 3
BOT_HP = 100
BOT_SPAWN_RANGE_DEFAULT = 40
PUBLIC_MODE_NAME = "bots"

ORIENTATIONS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]


@command(admin_only=True)
def addbot(connection, amount=None, team=None):
    """
    Manually add bots
    /addbot <amount> <team>
    """
    protocol = connection.protocol
    if team:
        bot_team = get_team(connection, team)
    blue, green = protocol.blue_team, protocol.green_team
    amount = int(amount or 1)
    for i in range(amount):
        if not team:
            bot_team = blue if blue.count() < green.count() else green
        bot = protocol.add_bot(bot_team)
        if not bot:
            return "Added %s bot(s)" % i
    return "Added %s bot(s)" % amount


@command(admin_only=True)
def toggleai(connection):
    """
    Toggle the activity of the bots
    /toggleai
    """
    protocol = connection.protocol
    protocol.ai_enabled = not protocol.ai_enabled
    if not protocol.ai_enabled:
        for bot in protocol.bots:
            bot.flush_input()
    state = "enabled" if protocol.ai_enabled else "disabled"
    protocol.broadcast_chat("AI %s!" % state)
    protocol.irc_say("* %s %s AI" % (connection.name, state))


class LocalPeer:
    address = Address(str.encode("localhost"), 0)
    roundTripTime = 0.0

    def send(self, *arg, **kw):
        pass

    def reset(self):
        pass


def apply_script(protocol, connection, config):
    class PracticeProtocol(protocol):
        game_mode = TC_MODE
        bots = None
        ai_enabled = True

        has_humans = False
        orientation_chooser = 0
        spawn_center = None
        bots_spawn_range = 0
        fixed_area = [0, 0, 0, 0]

        def add_bot(self, team):
            if len(self.connections) + len(self.bots) >= 32:
                return None
            bot = self.connection_class(self, None)
            bot.join_game(team)
            self.bots.append(bot)
            return bot

        def on_world_update(self):
            if self.bots and self.ai_enabled:
                for bot in self.bots:
                    bot.update()
            protocol.on_world_update(self)

        def on_map_change(self, map):
            self.game_mode_name = PUBLIC_MODE_NAME
            if self.max_players == 32:
                self.max_players = 32 - BOT_AMOUNT
            self.green_team.locked = True
            self.balanced_teams = 0
            self.respawn_waves = False
            self.bots = []
            self.spawn_center = self.map_info.extensions.get("spawn_center", (255, 255))
            self.bots_spawn_range = self.map_info.extensions.get("bots_spawn_range",
                                                                 BOT_SPAWN_RANGE_DEFAULT)
            self.fixed_area[0] = self.spawn_center[0] - self.bots_spawn_range
            self.fixed_area[1] = self.spawn_center[1] - self.bots_spawn_range
            self.fixed_area[2] = self.spawn_center[0] + self.bots_spawn_range
            self.fixed_area[3] = self.spawn_center[1] + self.bots_spawn_range
            protocol.on_map_change(self, map)

        def on_map_leave(self):
            for bot in self.bots[:]:
                bot.disconnect()
            self.bots = None
            protocol.on_map_leave(self)

        def get_cp_entities(self):
            distance = self.bots_spawn_range + 20
            cps = []
            cps.append((self.spawn_center[0], self.spawn_center[1]))
            cps.append((self.spawn_center[0] - distance, self.spawn_center[1]))
            cps.append((self.spawn_center[0], self.spawn_center[1] - distance))
            cps.append((self.spawn_center[0], self.spawn_center[1] + distance))
            cps.append((self.spawn_center[0] + distance, self.spawn_center[1]))
            entities = []
            i = 0
            if len(cps) > 0:
                for poscp in cps:
                    if poscp is not None:
                        entities.append(Territory(i, self, *(poscp[0], poscp[1],
                                        self.map.get_z(poscp[0], poscp[1]))))
                        i += 1
            else:
                entities = protocol.get_cp_entities(self)
            if len(entities) > 0:
                for ent in entities:
                    ent.team = self.blue_team
                    self.blue_team.spawn_cp = ent
            return entities

        def reset_game(self, player=None, territory=None):
            return

    class PracticeConnection(connection):
        aim = None
        aim_at = None
        input = None
        acquire_targets = True
        activity_counter = 0
        max_count = 100
        stuck_counter = 0
        prev_position_x = 0
        prev_position_y = 0

        _turn_speed = None
        _turn_vector = None

        def _get_turn_speed(self):
            return self._turn_speed

        def _set_turn_speed(self, value):
            self._turn_speed = value
            self._turn_vector = Vertex3(cos(value), sin(value), 0.0)

        turn_speed = property(_get_turn_speed, _set_turn_speed)

        def __init__(self, protocol, peer):
            if peer is not None:
                return connection.__init__(self, protocol, peer)
            self.local = True
            self.rapid_hack_detect = False
            self.speedhack_detect = False
            connection.__init__(self, protocol, LocalPeer())
            self.on_connect()
            self._send_connection_data()
            self.send_map()

            self.aim = Vertex3()
            self.target_orientation = Vertex3()
            self.turn_speed = 0.15  # rads per tick
            self.input = set()

        def join_game(self, team):
            self.name = BOT_NAME + str(self.player_id)
            self.team = team
            self.set_weapon(randint(0, 2), True)
            self.protocol.players[(self.player_id)] = self
            self.on_login(self.name)
            self.spawn()

        def on_spawn_location(self, pos):
            if self.team is self.protocol.blue_team:
                x = self.protocol.spawn_center[0] - self.protocol.bots_spawn_range - 30
                y = self.protocol.spawn_center[1]
                return x, y, self.protocol.map.get_z(x, y) - 3
            elif self.team is self.protocol.green_team:
                x = self.protocol.spawn_center[0]
                y = self.protocol.spawn_center[1]
                x += randint(-self.protocol.bots_spawn_range,
                             self.protocol.bots_spawn_range)
                y += randint(-self.protocol.bots_spawn_range,
                             self.protocol.bots_spawn_range)
                return x, y, self.protocol.map.get_z(x, y) - 3
            return connection.on_spawn_location(self, pos)

        def on_fall(self, damage):
            if self.local:
                return False
            connection.on_fall(self, damage)

        def disconnect(self, data=0):
            if not self.local:
                return connection.disconnect(self)
            if self.disconnected:
                return
            self.protocol.bots.remove(self)
            self.disconnected = True
            self.on_disconnect()

        def update(self):
            obj = self.world_object
            pos = obj.position
            ori = obj.orientation

            if (self.protocol.has_humans):
                turned = False
                self.activity_counter += 1
                if self.activity_counter == 5:
                    if (int(obj.position.x) == int(self.prev_position_x) and
                            int(obj.position.y) == int(self.prev_position_y)):
                        self.stuck_counter += 1
                    else:
                        self.stuck_counter = 0
                if self.stuck_counter == 4:
                    self.input.add("jump")
                elif self.stuck_counter == 8:
                    obj.set_orientation(ori.x * -1, ori.y * -1, 0)
                    self.input.add("up")
                    self.input.discard("crouch")
                    turned = True
                    self.stuck_counter += 1
                elif self.stuck_counter == 30:
                    self.spawn()
                if (self.activity_counter > self.max_count):
                    self.activity_counter = 0
                else:
                    return
                if not turned:
                    randact = choice(["up", "up", "up", "up", "crouch", None])
                    self.input.add(randact)
                    if (randint(0, 6) == 3):
                        self.input.add("jump")

                if (not turned and obj.position.x < self.protocol.fixed_area[0] and
                        ori.x != 1 or obj.position.y < self.protocol.fixed_area[1] and
                        ori.y != 1 or obj.position.x > self.protocol.fixed_area[2] and
                        ori.x != -1 or obj.position.y > self.protocol.fixed_area[3] and
                        ori.y != -1):
                    obj.set_orientation(ori.x * -1, ori.y * -1, 0)
                    self.input.add("up")
                    self.input.discard("crouch")
                self.prev_position_x = obj.position.x
                self.prev_position_y = obj.position.y

            self.flush_input()

        def flush_input(self):
            input = self.input
            world_object = self.world_object
            z_vel = world_object.velocity.z
            if "jump" in input and not (z_vel >= 0.0 and z_vel < 0.017):
                input.discard("jump")
            input_changed = not (
                ("up" in input) == world_object.up and
                ("down" in input) == world_object.down and
                ("left" in input) == world_object.left and
                ("right" in input) == world_object.right and
                ("jump" in input) == world_object.jump and
                ("crouch" in input) == world_object.crouch and
                ("sneak" in input) == world_object.sneak and
                ("sprint" in input) == world_object.sprint)
            if input_changed:
                if not self.freeze_animation:
                    world_object.set_walk("up" in input, "down" in input,
                                          "left" in input, "right" in input)
                    world_object.set_animation("jump" in input, "crouch" in input,
                                               "sneak" in input, "sprint" in input)
                if (not self.filter_visibility_data and
                        not self.filter_animation_data):
                    input_data = InputData()
                    input_data.player_id = self.player_id
                    input_data.up = world_object.up
                    input_data.down = world_object.down
                    input_data.left = world_object.left
                    input_data.right = world_object.right
                    input_data.jump = world_object.jump
                    input_data.crouch = world_object.crouch
                    input_data.sneak = world_object.sneak
                    input_data.sprint = world_object.sprint
                    self.protocol.broadcast_contained(input_data)
            primary = "primary_fire" in input
            secondary = "secondary_fire" in input
            shoot_changed = not (
                primary == world_object.primary_fire and
                secondary == world_object.secondary_fire)
            if shoot_changed:
                if primary != world_object.primary_fire:
                    if self.tool == WEAPON_TOOL:
                        self.weapon_object.set_shoot(primary)
                    if self.tool == WEAPON_TOOL or self.tool == SPADE_TOOL:
                        self.on_shoot_set(primary)
                world_object.primary_fire = primary
                world_object.secondary_fire = secondary
                if not self.filter_visibility_data:
                    weapon_input = WeaponInput()
                    weapon_input.player_id = self.player_id
                    weapon_input.primary = primary
                    weapon_input.secondary = secondary
                    self.protocol.broadcast_contained(weapon_input)
            input.clear()

        def set_tool(self, tool):
            if self.on_tool_set_attempt(tool) is False:
                return
            self.tool = tool
            if self.tool == WEAPON_TOOL:
                self.on_shoot_set(self.world_object.primary_fire)
                self.weapon_object.set_shoot(self.world_object.primary_fire)
            self.on_tool_changed(self.tool)
            if self.filter_visibility_data:
                return
            set_tool = SetTool()
            set_tool.player_id = self.player_id
            set_tool.value = self.tool
            self.protocol.broadcast_contained(set_tool)

        def on_team_join(self, team):
            if not self.local:
                self.protocol.has_humans = True
            return connection.on_team_join(self, team)

        def on_spawn(self, pos):
            if not self.local:
                missing_bots = BOT_AMOUNT - len(self.protocol.bots)
                if missing_bots > 0:
                    addbot(self, missing_bots, "green")
            if not self.local:
                return connection.on_spawn(self, pos)
            if self.protocol.orientation_chooser >= len(ORIENTATIONS):
                self.protocol.orientation_chooser = 0
            setori = ORIENTATIONS[self.protocol.orientation_chooser]
            self.protocol.orientation_chooser += 1
            self.world_object.set_orientation(setori[0], setori[1], setori[2])
            self.set_tool(choice([0, 1, 2, 2, 2, 2, 3]))
            self.aim_at = None
            self.acquire_targets = True
            self.respawn_time = BOT_RESPAWN_TIME
            self.set_hp(BOT_HP)
            self.stuck_counter = 0
            self.max_count += (self.player_id * 2)
            connection.on_spawn(self, pos)

        def on_disconnect(self):
            if len(self.protocol.players) - len(self.protocol.bots) - 1 <= 0:
                self.protocol.has_humans = False
            connection.on_disconnect(self)

        def _send_connection_data(self):
            if self.local:
                if self.player_id is None:
                    self.player_id = self.protocol.player_ids.pop()
                return
            connection._send_connection_data(self)

        def send_map(self, data=None):
            if self.local:
                self.on_join()
                return
            connection.send_map(self, data)

        def timer_received(self, value):
            if self.local:
                return
            connection.timer_received(self, value)

        def send_loader(self, loader, ack=False, byte=0):
            if self.local:
                return
            return connection.send_loader(self, loader, ack, byte)

    return PracticeProtocol, PracticeConnection
