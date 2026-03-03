"""
botstc.py by IAmYourFriend https://github.com/1AmYF

botstc.py is a territorial control and co-op gamemode against bots. A maximum
of 6 players have to capture all bases on the map and fight off the bots.
Originally created for the *Sauerkraut server named "Shoot 'Em Up" in October
2016. Trailer for this mode: https://youtu.be/HLb30O3W3S8

Players spawn on a green floor and only will be attacked by bots once they step
out of it. Difficulty (bot amount and their respawn time) can be voted on with
commands.

Parts of the code are derived from the survive gamemode.

Setup:

    Set game_mode in your server config to "botstc" (in the serverlist, the name
    of the gamemode will be shown as "bots") and add maps that were made for this
    mode to the rotation.

    To create a new map for this mode, map txt metadata is required. Example:

        extensions = {
            'blue_spawn' : (95, 415),
            'spawn_center' : (255, 255),
            'bots_spawn_range' : 165,
            'base_locations' : [(90, 89), (424, 89), (424, 424), (295, 390),
                                (195, 356), (404, 195), (200, 183), (359, 331)]
        }

Commands:

    /addbot <amount> <team>
        Manually add bots.
    /toggleai
        Toggle the activity of the bots.
    /difficulty <index>
        Force a new difficulty (using the index number of the difficulties list).
    /easy
        Vote for easy difficulty (if voting is enabled).
    /normal
        Vote for normal difficulty (if voting is enabled).
    /hard
        Vote for hard difficulty (if voting is enabled).
"""

from pyspades.contained import InputData, SetTool, WeaponInput, BlockAction
from pyspades.server import Territory
from pyspades.common import Vertex3
from pyspades.collision import vector_collision
from pyspades.constants import *
from piqueserver.commands import command, get_team
from piqueserver.config import config
from enet import Address
from twisted.internet.task import LoopingCall
from math import cos, sin, floor, isnan
from collections import Counter
import os.path
import random
import time

BOT_NAME = "Bot"
BOT_ATTACK_DAMAGE = 50
BLUE_SPAWN_RADIUS = 5
PUBLIC_MODE_NAME = "bots"
BOTS_MAX = 26
SKIP_COMPLETION_MSG_AFTER_HOURS = 3
ACTIVITY_DELAY_SECS = 1
VOTE_DIFFICULTY = True
VOTE_DELAY_SECS = 60
SPAWN_ZONE_COLOR = (0, 255, 0)
SAVE_MAP_STATS = False

# (description, initial bots amount, add bots per player, bot respawn time, bot hp)
BOTS_DIFFICULTIES = [
    ("Supereasy", 6, 1, 18, 10),
    ("Easy", 7, 2.5, 14, 40),
    ("Normal", 8, 3, 12, 100),
    ("Hard", 10, 4, 6, 100),
    ("Extreme", 14, 6, 2, 100),
    ("Suicide", 32, 8, 1, 100)
]


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


@command(admin_only=True)
def difficulty(connection, value=None):
    """
    Force a new difficulty
    /difficulty <index>
    """
    if value is not None:
        if not connection.admin:
            return S_NO_RIGHTS
        value = int(value)
        protocol = connection.protocol
        if value < 0 or value > len(BOTS_DIFFICULTIES) - 1:
            raise ValueError()
        protocol.bots_difficulty = BOTS_DIFFICULTIES[value]
        change_msg = "Difficulty changed to: %s" % protocol.bots_difficulty[0]
        protocol.broadcast_chat(change_msg)
        protocol.irc_say(change_msg)


def allow_vote(connection):
    by_personal_vote = True
    by_success_vote = True
    if connection.last_vote_time_secs is not None:
        by_personal_vote = (connection.last_vote_time_secs +
                            VOTE_DELAY_SECS) < get_now_in_secs()
    if connection.protocol.last_vote_success_secs is not None:
        by_success_vote = (connection.protocol.last_vote_success_secs +
                           VOTE_DELAY_SECS) < get_now_in_secs()
    return by_personal_vote and by_success_vote


def vote_difficulty(connection, difficulty):
    diff_desc = BOTS_DIFFICULTIES[difficulty][0].lower()
    if BOTS_DIFFICULTIES[difficulty][0] == connection.protocol.bots_difficulty[0]:
        connection.send_chat("Difficulty is already %s." % diff_desc)
    elif not allow_vote(connection):
        connection.send_chat("Please wait %s seconds before voting again." %
                             (connection.last_vote_time_secs +
                              VOTE_DELAY_SECS - get_now_in_secs()))
    else:
        connection.voted_difficulty = difficulty
        connection.last_vote_time_secs = get_now_in_secs()
        vote_successful = check_for_difficulty_change(connection.protocol)
        connection.protocol.irc_say("%s voted for %s difficulty"
                                    % (connection.name, diff_desc))
        if not vote_successful:
            connection.protocol.broadcast_chat("%s voted for %s difficulty, if you agree type /%s"
                                               % (connection.name, diff_desc, diff_desc))


@command()
def easy(connection):
    """
    Vote for easy difficulty
    /easy
    """
    if VOTE_DIFFICULTY:
        vote_difficulty(connection, 1)


@command()
def normal(connection):
    """
    Vote for normal difficulty
    /normal
    """
    if VOTE_DIFFICULTY:
        vote_difficulty(connection, 2)


@command()
def hard(connection):
    """
    Vote for hard difficulty
    /hard
    """
    if VOTE_DIFFICULTY:
        vote_difficulty(connection, 3)


def get_now_in_secs():
    return int(time.time())


def get_formatted_completion_time(completedseconds, compact=False):
    m, s = divmod(completedseconds, 60)
    h, m = divmod(m, 60)
    if compact:
        return "%d:%02d:%02d" % (h, m, s)
    elif (h == 0):
        return "%02d:%02d mins" % (m, s)
    else:
        return "%d:%02d:%02d hours" % (h, m, s)


def save_map_stats(mapname, completedseconds):
    formatnow = time.strftime("%d.%m.%Y %H:%M:%S")
    separator = ";"
    f = open(os.path.join(config.config_dir, "botstc_stats.csv"), "a")
    f.write(formatnow + separator + mapname + separator +
            get_formatted_completion_time(completedseconds, True) + "\n")
    f.close()


def get_top_capture_player(capturingplayers):
    if len(capturingplayers) > 0:
        sortedplayers = Counter(capturingplayers)
        for value, count in sortedplayers.most_common():
            return "%s (%s checkpoints)" % (value, count)
    else:
        return None


def check_for_difficulty_change(protocol, ignore_player_id=None):
    if protocol.players is not None and len(protocol.players) > 0:
        new_difficulty = None
        for p in protocol.players.values():
            ignore_player = False
            if p.local or (ignore_player_id is not None and (p.player_id == ignore_player_id)):
                ignore_player = True
            if not ignore_player:
                if (p.voted_difficulty is not None and
                        (new_difficulty is None or new_difficulty == p.voted_difficulty)):
                    new_difficulty = p.voted_difficulty
                else:
                    return False
        if new_difficulty is not None:
            new_difficulty_data = BOTS_DIFFICULTIES[new_difficulty]
            if new_difficulty_data[0] != protocol.bots_difficulty[0]:
                protocol.last_vote_success_secs = get_now_in_secs()
                protocol.bots_difficulty = new_difficulty_data
                vote_success_msg = ("Vote successful. Difficulty changed to: %s"
                                    % protocol.bots_difficulty[0].lower())
                protocol.irc_say(vote_success_msg)
                protocol.broadcast_chat(vote_success_msg)
                return True
    return False


class LocalPeer:
    address = Address(str.encode("localhost"), 0)
    roundTripTime = 0.0

    def send(self, *arg, **kw):
        pass

    def reset(self):
        pass


def apply_script(protocol, connection, config):
    class BotsTcProtocol(protocol):
        game_mode = TC_MODE
        bots = None
        ai_enabled = True
        placeof = 3

        bots_difficulty = BOTS_DIFFICULTIES[int(config.get("bots_difficulty", 2))]
        blue_spawn = None
        spawn_center = None
        bots_spawn = None
        bots_spawn_range = 0
        gameisfinished = False
        maploadtimestamp = None
        capturingplayers = []
        last_vote_success_secs = None

        def add_bot(self, team):
            if len(self.connections) + len(self.bots) >= 32:
                return None
            bot = self.connection_class(self, None)
            bot.join_game(team)
            self.bots.append(bot)
            return bot

        def on_world_update(self):
            if self.loop_count % 7200 == 0:
                if self.placeof == 3:
                    self.placeof = 0
                else:
                    self.placeof += 1
            if self.bots and self.ai_enabled:
                for bot in self.bots:
                    bot.update()
            protocol.on_world_update(self)

        def mark_spawn_ground(self):
            x_offset = self.blue_spawn[0] - BLUE_SPAWN_RADIUS
            y_offset = self.blue_spawn[1] - BLUE_SPAWN_RADIUS
            for x in range(x_offset, x_offset + (BLUE_SPAWN_RADIUS * 2)):
                for y in range(y_offset, y_offset + (BLUE_SPAWN_RADIUS * 2)):
                    z = self.map.get_z(x, y)
                    self.map.set_point(x, y, z, SPAWN_ZONE_COLOR)
                    block_action = BlockAction()
                    block_action.x = x
                    block_action.y = y
                    block_action.z = z
                    block_action.player_id = 32
                    block_action.value = DESTROY_BLOCK
                    self.broadcast_contained(block_action, save=True)
                    block_action.value = BUILD_BLOCK
                    self.broadcast_contained(block_action, save=True)

        def reset_game(self, player=None, territory=None):
            self.gameisfinished = True
            if self.maploadtimestamp is not None:
                completedseconds = get_now_in_secs() - self.maploadtimestamp
                if completedseconds < SKIP_COMPLETION_MSG_AFTER_HOURS * 60 * 60:
                    completionmessage = ("Level completed after %s" %
                                         get_formatted_completion_time(completedseconds))
                    self.broadcast_chat(completionmessage)
                    self.irc_say(completionmessage)
                topplayer = get_top_capture_player(self.capturingplayers)
                if topplayer is not None:
                    topmessage = "Most captures done by %s" % topplayer
                    self.broadcast_chat(topmessage)
                    self.irc_say(topmessage)
                if SAVE_MAP_STATS:
                    save_map_stats(self.map_info.rot_info.name, completedseconds)
            return protocol.reset_game(self, player=None, territory=None)

        def on_map_change(self, map):
            self.game_mode_name = PUBLIC_MODE_NAME
            if self.max_players == 32:
                self.max_players = 32 - BOTS_MAX
            self.green_team.locked = True
            self.balanced_teams = 0
            self.respawn_waves = False
            self.building = False
            self.gameisfinished = False
            self.blue_spawn = self.map_info.extensions.get("blue_spawn", (128, 384))
            self.spawn_center = self.map_info.extensions.get("spawn_center", (255, 255))
            self.bots_spawn = self.map_info.extensions.get("bots_spawn", None)
            self.bots_spawn_range = self.map_info.extensions.get("bots_spawn_range", 150)
            self.bots = []
            self.mark_spawn_ground()
            self.maploadtimestamp = get_now_in_secs()
            self.capturingplayers = []
            protocol.on_map_change(self, map)

        def on_map_leave(self):
            for bot in self.bots[:]:
                bot.disconnect()
            self.bots = None
            protocol.on_map_leave(self)

        def on_cp_capture(self, cp):
            if cp is not None and cp.players is not None:
                for p in cp.players:
                    self.capturingplayers.append(p.name)
            return protocol.on_cp_capture(self, cp)

        def get_cp_entities(self):
            cps = self.map_info.extensions.get("base_locations", [])
            entities = []
            i = 0
            if len(cps) > 0:
                for poscp in cps:
                    if poscp is not None:
                        entities.append(Territory(i, self, poscp[0], poscp[1],
                                                  self.map.get_z(poscp[0], poscp[1])))
                        i += 1
            else:
                entities = protocol.get_cp_entities(self)
                for ent in entities:
                    ent.team = None
                    self.blue_team.spawn_cp = ent
            return entities

    class BotsTcConnection(connection):
        aim = None
        last_aim = None
        aim_at = None
        input = None
        grenade_call = None
        ticks_stumped = 0
        ticks_stumped2 = 0
        ticks_stumped3 = 0
        last_pos = None
        distance_to_aim = None
        jump_count = 0
        spade_count = 0
        sec = 15
        sec2 = 15
        nature = None
        discar = 0
        knock = 4

        spawn_time = 0
        voted_difficulty = None
        last_vote_time_secs = None

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
            self.last_pos = Vertex3()
            self.turn_speed = 0.15  # rads per tick
            self.input = set()

        def on_connect(self):
            if not self.local and len(self.protocol.connections) <= 1:
                self.protocol.last_vote_success_secs = None
                self.protocol.bots_difficulty = BOTS_DIFFICULTIES[2]
            connection.on_connect(self)

        def join_game(self, team):
            self.name = BOT_NAME + str(self.player_id)
            self.team = team
            self.set_weapon(RIFLE_WEAPON, True)
            self.protocol.players[(self.player_id)] = self
            self.on_login(self.name)
            self.spawn()

        def on_login(self, name):
            # prevent players from picking reserved bot name
            if (not self.local and len(name) > len(BOT_NAME) and
                    len(name) < (len(BOT_NAME) + 3) and name.startswith(BOT_NAME)):
                reportmsg = ("Disconnected human player %s, invalid name." % (name))
                self.protocol.irc_say(reportmsg)
                self.disconnect()
            return connection.on_login(self, name)

        def disconnect(self, data=0):
            if not self.local:
                return connection.disconnect(self)
            if self.disconnected:
                return
            self.protocol.bots.remove(self)
            self.disconnected = True
            self.on_disconnect()

        def is_at_spawn(self, player):
            if player is not None and player.team == player.protocol.blue_team:
                sx = player.protocol.blue_spawn[0]
                sy = player.protocol.blue_spawn[1]
                px, py, pz = player.world_object.position.get()
                if (px < sx + BLUE_SPAWN_RADIUS and px > sx - BLUE_SPAWN_RADIUS and
                        py < sy + BLUE_SPAWN_RADIUS and py > sy - BLUE_SPAWN_RADIUS):
                    return True
            return False

        def relocate_stuck_bot(self, bot):
            me_x = bot.world_object.position.x - 0.5
            me_y = bot.world_object.position.y - 0.5
            bot.set_location_safe((me_x, me_y, self.protocol.map.get_z(me_x, me_y) - 10))

        def update(self):
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position

            if (self.world_object.dead or
                    self.spawn_time + ACTIVITY_DELAY_SECS >= get_now_in_secs()):
                return

            for i in self.team.other.get_players():
                if ((i.world_object) and (not i.world_object.dead) and
                        (not i.god) and (not self.is_at_spawn(i))):
                    some = Vertex3()
                    some.set_vector(i.world_object.position)
                    some -= pos
                    distance_to_new_aim = some.normalize()
                    if (self.distance_to_aim is not None and
                            distance_to_new_aim < self.distance_to_aim):
                        self.aim_at = i
                        self.last_aim = None

            if self.aim_at and self.aim_at.world_object:
                real_aim_at_pos = self.aim_at.world_object.position
                if obj.can_see(self.aim_at.world_object.position.x,
                               self.aim_at.world_object.position.y,
                               self.aim_at.world_object.position.z):
                    aim_at_pos = self.aim_at.world_object.position
                    self.last_aim = Vertex3()
                    self.last_aim.set_vector(aim_at_pos)
                else:
                    if self.last_aim is None:
                        aim_at_pos = self.aim_at.world_object.position
                    else:
                        aim_at_pos = self.last_aim
                self.aim.set_vector(aim_at_pos)
                self.aim -= pos
                self.distance_to_aim = self.aim.normalize()
                self.input.add("up")
                self.input.add("sprint")
                self.last_pos -= pos
                moved = Vertex3()
                moved.set_vector(self.last_pos)
                distance_moved = self.last_pos.length_sqr()
                self.last_pos.set_vector(pos)

                if self.distance_to_aim <= 2.0:
                    self.target_orientation.set_vector(self.aim)
                    self.input.discard("sprint")
                    self.input.add("primary_fire")
                    self.left_spade()
                else:
                    some = Vertex3()
                    some.x, some.y, some.z = self.aim.x, self.aim.y, 0
                    self.target_orientation.set_vector(some)

                if ((self.world_object.velocity.z != 0 and
                        abs(floor(aim_at_pos.x) - floor(pos.x)) <= 10 and
                        abs(floor(aim_at_pos.y) - floor(pos.y)) <= 10) or
                        (abs(floor(aim_at_pos.x) - floor(pos.x)) <= 1 and
                         abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1)):
                    try:
                        if aim_at_pos == self.aim_at.world_object.position:
                            if pos.z > aim_at_pos.z:
                                self.input.add("jump")
                                self.ticks_stumped3 += 1
                                self.sec = 15
                                self.ticks_stumped = 0
                                self.ticks_stumped2 = 0
                                if self.ticks_stumped3 >= self.sec2:
                                    self.sec2 += 15
                                    self.relocate_stuck_bot(self)
                            elif (pos.z < aim_at_pos.z and
                                  abs(floor(aim_at_pos.x) - floor(pos.x) <= 1) and
                                  abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1):
                                self.ticks_stumped3 += 1
                                if self.ticks_stumped3 >= self.sec2:
                                    self.sec2 += 15
                        else:
                            self.last_aim = None
                    except AttributeError:
                        self.last_aim = None
                else:
                    self.sec2 = 15
                    self.ticks_stumped3 = 0
                    if (moved.x == 0) or (moved.y == 0):
                        self.input.discard("sprint")
                        self.ticks_stumped += 1
                        self.input.add("jump")
                        # prevent them from getting stuck in blocks:
                        if self.ticks_stumped > 600:
                            self.relocate_stuck_bot(self)
                        if (self.ticks_stumped >= self.sec):
                            if self.sec % 30 == 0:
                                i = 1
                            else:
                                if floor(aim_at_pos.z) < floor(pos.z):  # up
                                    i = 0
                                elif floor(aim_at_pos.z) > floor(pos.z):  # down
                                    i = 2
                                elif floor(aim_at_pos.z) == floor(pos.z):
                                    i = 1
                            self.sec += 15
                            self.relocate_stuck_bot(self)
                    else:
                        self.sec = 15
                        self.ticks_stumped = 0
                        self.ticks_stumped2 = 0
            else:
                self.last_aim = None
                self.distance_to_aim = float("inf")

            # orientate towards target
            diff = ori - self.target_orientation
            diff.z = 0.0
            diff = diff.length_sqr()
            if diff > 0.001:
                p_dot = ori.perp_dot(self.target_orientation)
                if p_dot > 0.0:
                    ori.rotate(self._turn_vector)
                else:
                    ori.unrotate(self._turn_vector)
                new_p_dot = ori.perp_dot(self.target_orientation)
                if new_p_dot * p_dot < 0.0:
                    ori.set_vector(self.target_orientation)
            else:
                ori.set_vector(self.target_orientation)

            obj.set_orientation(*ori.get())
            self.flush_input()

        def flush_input(self):
            input = self.input
            world_object = self.world_object
            pos = world_object.position
            if not self.world_object.dead:
                if self.local:
                    for i in self.team.get_players():
                        if (i.world_object) and (not i.world_object.dead) and (not i == self):
                            pos2 = i.world_object.position
                            if floor(pos2.x) == floor(pos.x) and floor(pos2.y) == floor(pos.y):
                                if self.protocol.loop_count % 30 == 0:
                                    self.discar = random.randint(-3, 10)
                                elif self.discar == 3 or self.discar == 4 or self.discar == 5:
                                    input.add("left")
                                elif self.discar == 6 or self.discar == 7 or self.discar == 8:
                                    input.add("right")
                                elif self.discar == 9:
                                    input.add("right")
                                    input.discard("up")
                                elif self.discar == 10:
                                    input.add("left")
                                    input.discard("up")
                                break
                    if self.protocol.loop_count - self.jump_count < 30:
                        input.discard("jump")
                    else:
                        self.jump_count = self.protocol.loop_count

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
                        if ("sprint" in input) and ("jump" not in input):
                            m_x = self.aim.x + pos.x
                            m_y = self.aim.y + pos.y
                            m_z = pos.z
                            if not isnan(m_x) and not isnan(m_y) and not isnan(m_z):
                                if not self.protocol.map.get_solid(m_x, m_y, m_z):
                                    self.set_location((m_x, m_y, m_z))

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
                shoot_changed = not (primary == world_object.primary_fire and
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
                self.on_shoot_set(self.world_object.fire)
                self.weapon_object.set_shoot(self.world_object.fire)
            self.on_tool_changed(self.tool)
            if self.filter_visibility_data:
                return
            set_tool = SetTool()
            set_tool.player_id = self.player_id
            set_tool.value = self.tool
            self.protocol.broadcast_contained(set_tool)

        def left_spade(self):
            obj = self.world_object
            pos = obj.position
            ori = obj.orientation
            if self.world_object.dead:
                return
            if self.protocol.loop_count - self.spade_count < 24:
                return
            else:
                self.spade_count = self.protocol.loop_count
            for player in self.team.other.get_players():
                if (player.world_object) and (not player.world_object.dead):
                    if ((vector_collision(pos, player.world_object.position, 3)) and
                            (obj.validate_hit(player.world_object, MELEE, 5, 5))):
                        hit_amount = BOT_ATTACK_DAMAGE
                        type = MELEE_KILL
                        self.on_hit(hit_amount, player, type, None)
                        player.hit(hit_amount, self, type)
                        # knockback
                        if not player.local:
                            player.input = set()
                            player.input.add("jump")
                            player.flush_input()

        def on_spawn(self, pos):
            if self.local:
                self.spawn_time = get_now_in_secs()
                self.respawn_time = self.protocol.bots_difficulty[3]
                if self.protocol.bots_difficulty[4] != 100:
                    self.set_hp(self.protocol.bots_difficulty[4])
            elif not self.protocol.gameisfinished:
                self.send_chat("Capture all checkpoints! Current difficulty: %s."
                               % self.protocol.bots_difficulty[0].lower())

            # add bots depending on amount of human players
            if not self.protocol.gameisfinished:
                min_bots = self.protocol.bots_difficulty[1]
                add_bots_per_player = self.protocol.bots_difficulty[2]
                bot_amount = int(min_bots + (self.protocol.blue_team.count() *
                                 add_bots_per_player) - add_bots_per_player)
                if bot_amount > BOTS_MAX:
                    bot_amount = BOTS_MAX
                elif bot_amount < min_bots:
                    bot_amount = min_bots
                missing_bots = bot_amount - len(self.protocol.bots)
                if not self.local and missing_bots > 0:
                        addbot(self, missing_bots, self.protocol.green_team.name)
                if self.local and missing_bots < 0:
                        self.disconnect()
                        return

            if not self.local:
                return connection.on_spawn(self, pos)
            self.world_object.set_orientation(1.0, 0.0, 0.0)
            self.set_tool(SPADE_TOOL)
            self.aim_at = None
            self.spade_count = 0
            self.jump_count = 0
            self.sec = 15
            self.sec2 = 15
            self.ticks_stumped = 0
            self.ticks_stumped2 = 0
            self.ticks_stumped3 = 0
            self.last_pos.set(*pos)
            connection.on_spawn(self, pos)

        def on_spawn_location(self, pos):
            if self.team is self.protocol.blue_team:
                x = self.protocol.blue_spawn[0]
                y = self.protocol.blue_spawn[1]
                return x, y, self.protocol.map.get_z(x, y) - 3
            elif self.team is self.protocol.green_team:
                x = self.protocol.spawn_center[0]
                y = self.protocol.spawn_center[1]
                z = -1
                if self.protocol.bots_spawn is not None:
                    spot = random.choice(self.protocol.bots_spawn)
                    if len(spot) == 2:
                        x, y = spot
                    else:
                        x, y, z = spot
                x += random.randint(-self.protocol.bots_spawn_range,
                                    self.protocol.bots_spawn_range)
                y += random.randint(-self.protocol.bots_spawn_range,
                                    self.protocol.bots_spawn_range)
                if z < 0:
                    z = self.protocol.map.get_z(x, y) - 3
                return x, y, z
            return connection.on_spawn_location(self, pos)

        def on_disconnect(self):
            if self.team == self.protocol.blue_team:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            if not self.local:
                check_for_difficulty_change(self.protocol, self.player_id)
            connection.on_disconnect(self)

        def on_team_changed(self, old_team):
            if old_team == self.protocol.blue_team:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_team_changed(self, old_team)

        def on_kill(self, killer, type, grenade):
            if not self.local and type == MELEE_KILL:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_kill(self, killer, type, grenade)

        def on_fall(self, damage):
            if self.local:
                return False
            connection.on_fall(self, damage)

        def on_flag_take(self):
            if not self.team == self.protocol.blue_team:
                return False
            return connection.on_flag_take(self)

        def on_block_destroy(self, x, y, z, mode):
            if self.tool != SPADE_TOOL or mode == GRENADE_DESTROY:
                return False
            return connection.on_block_destroy(self, x, y, z, mode)

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

        def send_loader(self, loader, acyk=False, byte=0):
            if self.local:
                return
            return connection.send_loader(self, loader, ack, byte)

    return BotsTcProtocol, BotsTcConnection
