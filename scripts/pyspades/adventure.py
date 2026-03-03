"""
adventure.py by IAmYourFriend https://github.com/1AmYF

adventure.py is a mini-gamemode for single player with 2 different endings
made in January 2019. Parts of the code are derived from the survive
gamemode and the hookshot script.

Setup:

    Using a bot script with Pyspades/Pysnip requires adding the "local" attribute:
      https://pastebin.com/raw/5qc1eCDf

    Set game_mode in your server config to "adventure" (in the serverlist, the name
    of the gamemode will be shown as "adv") and add the map "The Journey"
    (thejourney.vxl) which is required for this mode to work.

Commands:

    /setlevel <level>
        Manually set your level to jump to later parts of the story.
"""

from pyspades.server import input_data, weapon_input, set_tool, chat_message, kill_action
from pyspades.contained import ChatMessage, KillAction
from pyspades.common import Vertex3
from pyspades.collision import vector_collision
from pyspades.constants import *
from commands import admin, add, get_team
from enet import Address
from math import cos, sin, floor, isnan
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
import random
import time
import textwrap

PUBLIC_MODE_NAME = "adv"
TEAM_BLUE_COLOR = (160, 125, 80)
TEAM_GREEN_COLOR = (150, 0, 0)
TEAM_NAME = "Team"
AMOUNT_OF_DEMONS = 2
BOT_RESPAWN_TIME = 5
BOT_HP = 10
HIDE_COORD = (0, 0, 63)
DEFAULT_FOG = (128, 232, 255)
DARKNESS_COORD = (25, 290, 59)
FLIGHT_COORD = (510, 29, 40)
STUCK_MSG_INTERVAL = 50
SAVE_STATS = False
CSV_SEPARATOR = ";"


@admin
def setlevel(connection, level):
    connection.adv_level = int(level)
    return "Level set to %s" % connection.adv_level


add(setlevel)


def get_human_player(protocol):
    for i in protocol.players.values():
        if not i.local:
            return i
    return None


def is_in_region(connection, x1, y1, x2, y2):
    if connection.world_object is not None:
        pos = connection.world_object.position
        return pos.x >= x1 and pos.y >= y1 and pos.x <= x2 and pos.y <= y2
    else:
        return False


def mirror_input_from_player(bot, player):
    if player.world_object.up:
        bot.input.add("up")
    if player.world_object.down:
        bot.input.add("down")
    if player.world_object.left:
        bot.input.add("right")
    if player.world_object.right:
        bot.input.add("left")
    if player.world_object.jump:
        bot.input.add("jump")
    if player.world_object.crouch:
        bot.input.add("crouch")
    if player.world_object.sneak:
        bot.input.add("sneak")
    if player.world_object.sprint:
        bot.input.add("sprint")
    if bot.tool != player.tool:
        bot.set_tool(player.tool)


def get_now_in_secs():
    return int(time.time())


def is_bot_hit_time(bot):
    if bot.hit_time <= 0:
        return False
    elif (get_now_in_secs() - bot.hit_time) > 10:
        return True
    else:
        return False


def init_adv_roles(connection):
    demon_counter = 0
    for i in connection.protocol.players.values():
        if i.local:
            if i.bot_type == 1:
                connection.role_guide = i
                i.set_location((146, 380, 5))
            elif i.bot_type == 2:
                connection.role_you = i
                i.set_location((383, 110, 30))
            elif i.bot_type == 3:
                i.respawn_time = BOT_RESPAWN_TIME
                connection.role_demons.append(i)
                decider = len(connection.role_demons) % 2
                y_vary = (demon_counter / 2) % 2
                if decider:
                    i.demon_spawn = (241, 150, 15)
                else:
                    i.demon_spawn = (241, 161, 15)
                    demon_counter += 2
                i.set_location(i.demon_spawn)
            elif i.bot_type == 4:
                connection.role_boss = i
                i.set_location((330, 188, 45))


def set_loc(connection, start, goal, posi, ori, counter):
    if connection.disable_flight or counter > 490:
        return False
    if posi[0] < 5:
        posi = start
    reactor.callLater(0.01 * counter, connection.set_location, (posi[0], posi[1], posi[2] - 1))
    return set_loc(connection, start, goal,
                   (posi[0] + ori[0], posi[1] + ori[1], posi[2] + ori[2]), ori, counter + 1)


def get_formatted_duration(completedseconds):
    completedformatmin = str(int(floor(completedseconds / 60)))
    if len(completedformatmin) == 1:
        completedformatmin = "0" + completedformatmin
    completedformatsec = str(int(completedseconds % 60))
    if len(completedformatsec) == 1:
        completedformatsec = "0" + completedformatsec
    return completedformatmin + ":" + completedformatsec


def save_stats(connection):
    playername = connection.name
    formatnow = time.strftime("%d.%m.%Y %H:%M:%S")
    playernamesecure = ""
    if playername is not None and len(playername) > 0:
        playernamesecure = playername.replace(CSV_SEPARATOR, ",")
    duration = get_formatted_duration(get_now_in_secs() - connection.adv_started)
    f = open("adventure_stats.csv", "a")
    f.write(playernamesecure + CSV_SEPARATOR + str(connection.adv_level) + CSV_SEPARATOR +
            str(connection.kills) + CSV_SEPARATOR + str(duration) + CSV_SEPARATOR +
            formatnow + CSV_SEPARATOR + str(connection.address[0]) + "\n")
    f.close()


def add_bot(connection, amount=None, team=None):
    protocol = connection.protocol
    if team:
        bot_team = get_team(connection, team)
    blue, green = protocol.blue_team, protocol.green_team
    amount = int(amount or 1)
    for i in xrange(amount):
        if not team:
            bot_team = blue if blue.count() < green.count() else green
        bot = protocol.add_bot(bot_team)
        if not bot:
            return "Added %s bot(s)" % i
    return "Added %s bot(s)" % amount


class LocalPeer:
    address = Address("localhost", 0)
    roundTripTime = 0.0

    def send(self, *arg, **kw):
        pass

    def reset(self):
        pass


def apply_script(protocol, connection, config):
    class AdventureProtocol(protocol):
        game_mode = CTF_MODE
        bots = None
        placeof = 3

        def __init__(self, *arg, **kw):
            protocol.__init__(self, *arg, **kw)
            self.add_adventure_bots()

        def add_bot(self, team, bot_type=0):
            if self.bots and len(self.connections) + len(self.bots) >= 32:
                return None
            bot = self.connection_class(self, None)
            bot.bot_type = bot_type
            bot.join_game(team)
            self.bots.append(bot)
            return bot

        def add_adventure_bots(self):
            self.add_bot(self.blue_team, 1)
            for x in range(0, AMOUNT_OF_DEMONS):
                self.add_bot(self.green_team, 3)
            self.add_bot(self.blue_team, 2)
            self.add_bot(self.green_team, 4)

        def on_world_update(self):
            if self.loop_count % 7200 == 0:
                if self.placeof == 3:
                    self.placeof = 0
                else:
                    self.placeof += 1
            if self.bots:
                for bot in self.bots:
                    bot.update()
            protocol.on_world_update(self)

        def on_map_change(self, map):
            self.game_mode_name = PUBLIC_MODE_NAME
            self.blue_team.color = TEAM_BLUE_COLOR
            self.blue_team.name = TEAM_NAME
            self.green_team.color = TEAM_GREEN_COLOR
            self.green_team.name = TEAM_NAME
            self.max_players = 1
            self.green_team.locked = True
            self.spectator_team.locked = True
            self.balanced_teams = 0
            self.respawn_waves = False
            self.fall_damage = False
            self.building = False
            self.bots = []
            protocol.on_map_change(self, map)

        def on_map_leave(self):
            for bot in self.bots[:]:
                bot.disconnect()
            self.bots = None
            protocol.on_map_leave(self)

        def on_base_spawn(self, x, y, z, base, entity_id):
            return HIDE_COORD

        def on_flag_spawn(self, x, y, z, flag, entity_id):
            return HIDE_COORD

    class AdventureConnection(connection):
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

        _turn_speed = None
        _turn_vector = None

        spawn_time = 0
        hit_time = 0

        bot_type = 0  # 1 = guide, 2 = mirror, 3 = demon, 4 = boss
        adv_level = 0
        adv_pause = 2
        adv_stuck = 0
        adv_started = None
        adv_loop = None
        role_guide = None
        role_you = None
        role_demons = []
        role_boss = None
        demon_spawn = None
        flight_trigger = 3
        flight_iterations = 0
        fog_iterations = 0
        boss_iterations = 0
        notice_iterations = 0
        disable_flight = False

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

        def join_game(self, team):
            use_weapon = RIFLE_WEAPON
            # Set bot name by bot_type
            if self.bot_type == 1:
                self.name = "The Guide"
                self.team = self.protocol.blue_team
            elif self.bot_type == 2:
                self.name = "You"
                self.team = self.protocol.blue_team
            elif self.bot_type == 3:
                self.name = "Demon" + str(self.player_id)
                self.team = self.protocol.green_team
            elif self.bot_type == 4:
                self.name = "Manager"
                self.team = self.protocol.green_team
            self.set_weapon(use_weapon, True)
            self.protocol.players[(self.name, self.player_id)] = self
            self.on_login(self.name)
            self.spawn()

        def disconnect(self, data=0):
            if not self.local:
                return connection.disconnect(self)
            if self.disconnected:
                return
            self.protocol.bots.remove(self)
            self.disconnected = True
            self.on_disconnect()

        def relocate_stuck_bot(self, bot):
            me_x = bot.world_object.position.x
            me_y = bot.world_object.position.y
            bot.set_location_safe((me_x, me_y, self.protocol.map.get_z(me_x, me_y) - 10))

        def update(self):
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position

            if self.world_object.dead:
                return
            for i in self.protocol.players.values():
                if ((not i.local) and (i.world_object) and
                        (not i.world_object.dead) and (not i.god)):
                    if self.bot_type == 2 and not is_in_region(i, 295, 66, 385, 154):
                        self.flush_input()
                        return
                    elif self.bot_type == 3 and not is_in_region(i, 19, 101, 249, 213):
                        self.flush_input()
                        return
                    elif self.bot_type == 4:
                        if is_in_region(i, 295, 159, 385, 247):
                            if self.hit_time == 0:
                                self.hit_time = get_now_in_secs() + 12
                                return
                        else:
                            self.flush_input()
                            return

                    some = Vertex3()
                    some.set_vector(i.world_object.position)
                    some -= pos
                    distance_to_new_aim = some.normalize()
                    if distance_to_new_aim < self.distance_to_aim:
                        self.aim_at = i
                        self.last_aim = None
                    break

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

                is_active_bot = self.bot_type == 3 or (self.bot_type == 4 and
                                                       is_bot_hit_time(self))

                if is_active_bot:
                    self.input.add("up")
                    if self.bot_type == 3:
                        self.input.add("sprint")
                elif self.bot_type == 2:
                    mirror_input_from_player(self, get_human_player(self.protocol))
                self.last_pos -= pos
                moved = Vertex3()
                moved.set_vector(self.last_pos)
                distance_moved = self.last_pos.length_sqr()
                self.last_pos.set_vector(pos)

                if is_active_bot and self.distance_to_aim <= 2.0:
                    self.target_orientation.set_vector(self.aim)
                    self.input.discard("sprint")
                    self.input.add("primary_fire")
                    self.left_spade()
                else:
                    some = Vertex3()
                    some.x, some.y, some.z = self.aim.x, self.aim.y, 0
                    self.target_orientation.set_vector(some)

                if is_active_bot:
                    if (self.world_object.velocity.z != 0 and
                            abs(floor(aim_at_pos.x) - floor(pos.x)) <= 10 and
                            abs(floor(aim_at_pos.y) - floor(pos.y)) <= 10) or (
                            abs(floor(aim_at_pos.x) - floor(pos.x)) <= 1 and
                            abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1):
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
                    if self.bot_type != 2 and self.protocol.loop_count - self.jump_count < 30:
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
                        input_data.player_id = self.player_id
                        input_data.up = world_object.up
                        input_data.down = world_object.down
                        input_data.left = world_object.left
                        input_data.right = world_object.right
                        input_data.jump = world_object.jump
                        input_data.crouch = world_object.crouch
                        input_data.sneak = world_object.sneak
                        input_data.sprint = world_object.sprint
                        self.protocol.send_contained(input_data)
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
                        weapon_input.player_id = self.player_id
                        weapon_input.primary = primary
                        weapon_input.secondary = secondary
                        self.protocol.send_contained(weapon_input)
                input.clear()

        def set_tool(self, tool):
            if self.on_tool_set_attempt(tool) is False:
                return
            self.tool = tool
            self.on_tool_changed(self.tool)
            if self.filter_visibility_data:
                return
            set_tool.player_id = self.player_id
            set_tool.value = self.tool
            self.protocol.send_contained(set_tool)

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
                            (obj.validate_hit(player.world_object, MELEE, 5))):
                        hit_amount = 50
                        type = MELEE_KILL
                        self.on_hit(hit_amount, player, type, None)
                        player.hit(hit_amount, self, type)
                        # knockback
                        if not player.local:
                            player.input = set()
                            player.input.add("jump")
                            player.flush_input()

        def on_spawn(self, pos):
            self.speedhack_detect = False

            if self.local:
                self.spawn_time = get_now_in_secs()
                if self.bot_type == 3:
                    self.set_hp(BOT_HP)
            if not self.local:
                return connection.on_spawn(self, pos)
            self.world_object.set_orientation(1.0, 0.0, 0.0)
            if self.bot_type == 1:
                self.set_tool(BLOCK_TOOL)
            else:
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

        def on_disconnect(self):
            if not self.local:
                for i in self.protocol.players.values():
                    if i.local:
                        i.aim_at = None

            if self.adv_loop is not None:
                self.adv_loop.stop()
            if self.world_object is not None and not self.local and self.adv_started is not None:
                self.protocol.set_fog_color(DEFAULT_FOG)
                if SAVE_STATS:
                    save_stats(self)
                duration = get_formatted_duration(get_now_in_secs() - self.adv_started)
                statmessage = ("%s reached level %s after %s mins and %s kills"
                               % (self.name, self.adv_level, duration, self.kills))
                self.protocol.irc_say(statmessage)
            connection.on_disconnect(self)

        def on_team_changed(self, old_team):
            if old_team == self.protocol.blue_team:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_team_changed(self, old_team)

        def on_team_join(self, team):
            if not self.local:
                if team is not None and not team.spectator:
                    self.respawn_time = 4
                    if self.adv_loop is None:
                        self.adv_started = get_now_in_secs()
                        self.adv_loop = LoopingCall(self.adv_activity)
                        self.adv_loop.start(1)

                if team.spectator and self.team is None:
                    self.send_chat("- No spectating -")
                    reactor.callLater(2, self.kick)
            return connection.on_team_join(self, team)

        def get_spawn_location(self):
            if self.local:
                if self.bot_type == 3 and self.demon_spawn is not None:
                    return self.demon_spawn[0], self.demon_spawn[1], self.demon_spawn[2]
                else:
                    return 1, 1, 1
            else:
                if self.adv_level >= 200:
                    self.protocol.set_fog_color((0, 0, 0))
                    return DARKNESS_COORD[0], DARKNESS_COORD[1], DARKNESS_COORD[2]
                else:
                    return 79, 383, 55
            return connection.get_spawn_location(self)

        def on_weapon_set(self, weapon):
            return False

        def on_animation_update(self, jump, crouch, sneak, sprint):
            if not self.local and jump:
                for i in self.protocol.players.values():
                    if i.local and i.bot_type == 2:
                        i.input.add("jump")
            return connection.on_animation_update(self, jump, crouch, sneak, sprint)

        def on_kill(self, killer, type, grenade):
            if not self.local and type == MELEE_KILL:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            if not killer.local and self.local and self.bot_type == 4:
                return False
            if not self.local:
                if type != MELEE_KILL:
                    return False
                else:
                    self.levelup(200)
                    self.adv_pause = 0
            connection.on_kill(self, killer, type, grenade)

        def on_hit(self, hit_amount, hit_player, type, grenade):
            if self.local and self.bot_type == 4 and not hit_player.local:
                self.hit_time = get_now_in_secs()
                hit_player.set_hp(100)
            elif not self.local and hit_player.local and hit_player.bot_type == 4:
                return False
            elif not self.local and not hit_player.local and grenade:
                return False
            return connection.on_hit(self, hit_amount, hit_player, type, grenade)

        def on_hack_attempt(self, reason):
            return False

        def on_flag_take(self):
                return False

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

        def msg(self, sender, message, echo=0):
            if self.world_object is None:
                return
            chat_message.chat_type = CHAT_ALL
            chat_message.player_id = sender.player_id
            prefix = ""
            lines = textwrap.wrap(message, MAX_CHAT_SIZE - len(prefix) - 1)
            for line in lines:
                chat_message.value = "%s%s" % (prefix, line)
                self.send_contained(chat_message)
            if echo > 1:
                reactor.callLater(echo, self.send_chat, "(Echo)  %s" % message)

        def kill_role_you(self):
            kill_action.kill_type = FALL_KILL
            kill_action.killer_id = self.player_id
            kill_action.player_id = self.role_you.player_id
            self.send_contained(kill_action)

        def is_above_height(self, z):
            pos = self.world_object.position
            return pos.z < z

        def levelup(self, level=-1):
            if level >= 0:
                self.adv_level = level
            else:
                self.adv_level += 1
            self.adv_stuck = -self.adv_pause

        def stuckup(self):
            self.adv_stuck += 1

        def say_stuck_msg(self, add=0):
            return (self.adv_stuck + add) > 0 and not (self.adv_stuck + add) % STUCK_MSG_INTERVAL

        def start_flight(self):
            if self.flight_trigger >= 3:
                self.flight_trigger = 0
                self.flight_iterations += 1
                self.nonstopflight(FLIGHT_COORD)
            else:
                self.flight_trigger += 1

        def stop_flight(self):
            self.disable_flight = True

        def nonstopflight(self, coord):
            if self.world_object is not None:
                self.disable_flight = False
                a, b, c = 510, coord[1], coord[2]
                d, e, f = self.world_object.position.get()
                set_loc(self, coord, (a, b, c), (d, e, f), (-1, 0, 0), 1)

        def adv_activity(self):
            if self.world_object is None:
                return
            if self.adv_pause > 0:
                self.adv_pause -= 1
                return
            if self.role_guide is None:
                init_adv_roles(self)

            # LEVELS
            if self.adv_level == 0:
                self.protocol.set_fog_color(DEFAULT_FOG)
                self.adv_pause = 1
                self.levelup()
            elif self.adv_level == 1:
                self.msg(self, "What a nice day for a mountain hike!")
                reactor.callLater(13, self.msg, self,
                                  "I wonder what the view is like from up there")
                self.adv_pause = 15
                self.levelup()
            elif self.adv_level == 2:
                if self.is_above_height(7) and is_in_region(self, 132, 369, 149, 385):
                    reactor.callLater(2, self.msg, self.role_guide,
                                      "Hello %s. I expected you" % self.name)
                    reactor.callLater(10, self.msg, self.role_guide, "Please, take a seat here")
                    self.adv_pause = 10
                    self.levelup()
                else:
                    self.stuckup()
                    if self.say_stuck_msg():
                        self.msg(self, "I should go up to the mountain now")
            elif self.adv_level == 3:
                if self.is_above_height(7) and is_in_region(self, 144, 371, 1489, 382):
                    reactor.callLater(4, self.msg, self.role_guide,
                                      "Are you comfortable? I need to show you something")
                    reactor.callLater(14, self.msg, self.role_guide, "But first, close your eyes")
                    self.adv_pause = 18
                    self.levelup()
                else:
                    self.stuckup()
                    if self.say_stuck_msg():
                        self.msg(self.role_guide, "Sit down on the chair please")
            elif self.adv_level == 4:
                self.set_location(DARKNESS_COORD)
                self.protocol.set_fog_color((0, 0, 0))
                reactor.callLater(5, self.msg, self.role_guide, "Good. Now take a deep breath...")
                reactor.callLater(15, self.msg, self.role_guide,
                                  "and imagine looking into a mirror")
                self.adv_pause = 20
                self.levelup()
            elif self.adv_level == 5:
                self.set_location((297, 110, 30))
                self.protocol.set_fog_color((200, 200, 200))
                self.adv_pause = 15
                self.levelup()
            elif self.adv_level == 6:
                you_x = self.role_you.world_object.position.x
                you_y = self.role_you.world_object.position.y
                if is_in_region(self, you_x - 3, you_y - 3, you_x + 3, you_y + 3):
                    self.adv_pause = 6
                    self.levelup()
                else:
                    self.stuckup()
                    if self.adv_stuck == 0 or self.say_stuck_msg():
                        self.msg(self.role_guide, "Get closer, look right into the eye")
            elif self.adv_level == 7:
                self.protocol.set_fog_color((255, 0, 0))
                self.role_you.respawn_time = 60
                self.kill_role_you()
                reactor.callLater(2, self.msg, self.role_guide, "Oh no... something is wrong")
                reactor.callLater(12, self.msg, self.role_guide, "You stared too deep")
                reactor.callLater(18, self.msg, self.role_guide, "You unleashed...")
                self.adv_pause = 22
                self.levelup()
            elif self.adv_level == 8:
                self.set_location((197, 156, 24))
                self.msg(self.role_guide, "your inner demons!")
                self.adv_pause = 12
                self.levelup()
            elif self.adv_level == 9:
                self.protocol.set_fog_color((255, 255, 255))
                self.msg(self.role_guide, "Run into the light!")
                self.adv_pause = 0
                self.levelup()
            elif self.adv_level == 10:
                if not self.is_above_height(29) and is_in_region(self, 0, 64, 55, 255):
                    self.adv_pause = 0
                    self.levelup(100)
                    self.protocol.set_fog_color((255, 255, 255))
                    self.fog_iterations = 0
                    self.set_location(FLIGHT_COORD)
                    self.start_flight()
                else:
                    self.stuckup()
                    if self.say_stuck_msg(10):
                        self.msg(self.role_guide, "Run into the light!")
            # Win
            elif self.adv_level == 100:
                self.protocol.set_fog_color((255, 255 - (self.fog_iterations * 6),
                                             255 - (self.fog_iterations * 2)))
                self.fog_iterations += 1
                self.start_flight()
                self.adv_pause = 0
                if self.flight_iterations >= 10:
                    self.role_guide.set_location((374, 383, 59))
                    self.adv_pause = 4
                    self.stop_flight()
                    self.levelup()
            elif self.adv_level == 101:
                self.protocol.set_fog_color(DEFAULT_FOG)
                self.set_location((384, 383, 59))
                reactor.callLater(3, self.msg, self.role_guide,
                                  "Congratulations %s. You left your demons behind"
                                  % self.name, 2)
                reactor.callLater(13, self.msg, self.role_guide,
                                  "You are now free to use your full potential. Good luck!", 2)
                reactor.callLater(30, self.send_chat,
                                  "You reached the good ending (1 of 2 endings)")
                self.adv_pause = 36
                self.levelup()
            elif self.adv_level == 102:
                self.send_chat("You can leave the server now")
                self.adv_pause = STUCK_MSG_INTERVAL
            # Lose
            elif self.adv_level == 200:
                reactor.callLater(7, self.msg, self.role_guide,
                                  "That went wrong. You were not supposed to die!")
                reactor.callLater(14, self.msg, self.role_guide,
                                  "You failed to escape your demons. This affects your life")
                reactor.callLater(23, self.msg, self.role_guide,
                                  "I will show you your future now")
                self.adv_pause = 29
                self.levelup()
            elif self.adv_level == 201:
                self.protocol.set_fog_color(DEFAULT_FOG)
                self.set_location((330, 214, 45))
                reactor.callLater(4, self.msg, self.role_guide,
                                  "The demons prevent you from using your potential")
                reactor.callLater(13, self.msg, self.role_guide,
                                  "You will spend the rest of your life in a dead-end job!")
                reactor.callLater(22, self.send_chat,
                                  "You reached the bad ending (1 of 2 endings)")
                self.adv_pause = 23
                self.levelup()
            elif self.adv_level == 202:
                if self.notice_iterations >= STUCK_MSG_INTERVAL:
                    self.notice_iterations = 0
                if self.notice_iterations == 18:
                    self.send_chat("You can leave the server now")
                if self.boss_iterations >= 60:
                    self.boss_iterations = 0
                if self.boss_iterations == 15 or self.boss_iterations == 45:
                    self.msg(self.role_boss, "Are you daydreaming? Get back to work!")
                elif self.boss_iterations == 0 or self.boss_iterations == 30:
                    self.msg(self.role_boss,
                             "%s! What do you think you're doing? Get back to work!" % self.name)
                self.boss_iterations += 1
                self.notice_iterations += 1
                self.adv_pause = 0

    return AdventureProtocol, AdventureConnection
