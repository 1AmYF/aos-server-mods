"""
Survive is a gamemode where players have to fight off waves of zombie bots.

The code is based on basicbot.py by hompy, was developed by Beige (Laon) into this
gamemode, then revised and extended by IAmYourFriend https://twitter.com/1AmYF

Setup:

    Using a bot script with Pyspades/Pysnip requires adding the "local" attribute:
      https://pastebin.com/raw/5qc1eCDf

    Set game_mode in your server config to "survive". Set friendly_fire to "on_grief"
    to allow teamkilling of griefers.
    It is recommended to use maps that are open, mostly flat and not too high, to
    prevent zombies getting "lost" and spending most of their time digging themselves
    out of buildings or mountains somewhere. It also encourages players to build their
    own defenses against the zombies.
    By default, the bases are randomly placed throughout the maps. They can be placed
    at fixed locations using map txt metadata. It is also possible to change the name
    of the bots individually for maps. Example:

        extensions = {
            'bot_name' : 'Santa',
            'base_locations' : [(128, 255, 50), (255, 255, 39), (384, 255, 50)]
        }

    When you add daycycle.py to your script list, zombies will become stronger at night
    (stronger at destructing blocks).

Commands:

    /addbot <amount> <team>
        Manually add bots.
    /toggleai
        Toggle the activity of the bots.
    /war
        Enable an alternative spawn setup where humans and zombies spawn from opposite
        corners of the map.
"""

from pyspades.server import input_data, weapon_input, set_tool, block_action, Territory
from pyspades.common import Vertex3
from pyspades.collision import vector_collision, collision_3d
from pyspades.constants import *
from commands import admin, add, get_team
from enet import Address
from math import cos, sin, floor, isnan
import random

BOT_DEFAULT_NAME = "Zombie"
BOT_RESPAWN_TIME = 11
BOT_HP = 100
BOT_ATTACK_DAMAGE = 20
BOT_HIT_GRENADE = 0.18
BOT_HIT_RIFLE = 0.32
BOT_HIT_SMG = 0.17
BOT_HIT_SHOTGUN = 0.23
BOT_HIT_SPADE = 0.16
BOT_BLOCK_BREAK_CHANCE = 80
BOT_BLOCK_BREAK_CHANCE_STRONG = 20
BOTS_MIN = 5
BOTS_MAX = 16
BOTS_PER_PLAYER = 1
HUMAN_SPAWN_RANGE = 128


@admin
def addbot(connection, amount=None, team=None):
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


@admin
def toggleai(connection):
    protocol = connection.protocol
    protocol.ai_enabled = not protocol.ai_enabled
    if not protocol.ai_enabled:
        for bot in protocol.bots:
            bot.flush_input()
    state = "enabled" if protocol.ai_enabled else "disabled"
    protocol.send_chat("AI %s!" % state)
    protocol.irc_say("* %s %s AI" % (connection.name, state))


@admin
def war(connection):
    protocol = connection.protocol
    for bot in protocol.bots:
        bot.kill()
    protocol.war = not protocol.war
    state = "enabled" if protocol.war else "disabled"
    protocol.send_chat("War %s!" % state)


add(addbot)
add(toggleai)
add(war)


def destroy_block(protocol, x, y, z):
    if protocol.map.get_solid(x, y, z) is None:
        return False
    block_action.value = DESTROY_BLOCK
    block_action.player_id = 32
    block_action.x = x
    block_action.y = y
    block_action.z = z
    protocol.send_contained(block_action, save=True)
    protocol.update_entities()
    return True


def is_invalid_coord(x, y, z):
    return x < 0 or y < 0 or z < 0 or x > 511 or y > 511 or z > 62


class LocalPeer:
    address = Address("localhost", 0)
    roundTripTime = 0.0

    def send(self, *arg, **kw):
        pass

    def reset(self):
        pass


def apply_script(protocol, connection, config):
    class SurviveProtocol(protocol):
        game_mode = TC_MODE
        bots = None
        ai_enabled = True
        placeof = 3
        war = False
        strong = False
        bot_name = None

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

        def on_map_change(self, map):
            if self.max_players == 32:
                self.max_players = 32 - BOTS_MAX
            self.green_team.locked = True
            self.balanced_teams = 0
            self.respawn_waves = False
            self.bots = []
            self.bot_name = self.map_info.extensions.get("bot_name", BOT_DEFAULT_NAME)
            protocol.on_map_change(self, map)

        def on_map_leave(self):
            for bot in self.bots[:]:
                bot.disconnect()
            self.bots = None
            protocol.on_map_leave(self)

        def reset_game(self, player=None, territory=None):
            return

        def get_cp_entities(self):
            cps = self.map_info.extensions.get("base_locations", [])
            entities = []
            i = 0
            if len(cps) > 0:
                for poscp in cps:
                    z = 0
                    if len(poscp) == 2:
                        z = self.map.get_z(poscp[0], poscp[1])
                    else:
                        z = poscp[2]
                    if poscp is not None and not is_invalid_coord(poscp[0], poscp[1], z):
                        entities.append(Territory(i, self, *(poscp[0], poscp[1], z)))
                        i += 1
            else:
                entities = protocol.get_cp_entities(self)
            if len(entities) > 0:
                for ent in entities:
                    ent.team = self.blue_team
                    self.blue_team.spawn_cp = ent
            return entities

        def update_day_color(self):
            if not self.strong and (self.current_time >= 22.50 or self.current_time <= 4.10):
                self.send_chat("The night begins. Zombies are getting stronger!")
                self.strong = True
            elif self.strong and self.current_time < 22.50 and self.current_time > 4.10:
                self.strong = False
            protocol.update_day_color(self)

    class SurviveConnection(connection):
        aim = None
        last_aim = None
        aim_at = None
        input = None
        ticks_stumped = 0
        ticks_stumped2 = 0
        ticks_stumped3 = 0
        last_pos = None
        distance_to_aim = None
        jump_count = 0
        spade_count = 0
        sec = 15
        sec2 = 15
        discar = 0
        knock = 4

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

        def join_game(self, team):
            self.name = self.protocol.bot_name + str(self.player_id)
            self.team = team
            self.set_weapon(RIFLE_WEAPON, True)
            self.protocol.players[(self.name, self.player_id)] = self
            self.on_login(self.name)
            self.spawn()

        def on_login(self, name):
            # prevent players from picking reserved bot name
            if (not self.local and len(name) > len(self.protocol.bot_name) and
                    len(name) < (len(self.protocol.bot_name) + 3) and
                    name.startswith(self.protocol.bot_name)):
                reportmsg = ("Disconnected human player %s, invalid name." % (name))
                print reportmsg
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

        def update(self):
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position

            if self.world_object.dead:
                return

            for i in self.team.other.get_players():
                if (i.world_object) and (not i.world_object.dead) and (not i.god):
                    some = Vertex3()
                    some.set_vector(i.world_object.position)
                    some -= pos
                    distance_to_new_aim = some.normalize()
                    if distance_to_new_aim < self.distance_to_aim:
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
                                    self.input.add("primary_fire")
                                    self.dig(0)
                            elif (pos.z < aim_at_pos.z and
                                  abs(floor(aim_at_pos.x) - floor(pos.x) <= 1) and
                                  abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1):
                                self.ticks_stumped3 += 1
                                if self.ticks_stumped3 >= self.sec2:
                                    self.input.add("primary_fire")
                                    self.sec2 += 15
                                    self.dig(2)
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
                        if (self.ticks_stumped >= self.sec):
                            self.input.add("primary_fire")
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
                            self.input.add("primary_fire")
                            self.dig(i)
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
            if self.tool == WEAPON_TOOL:
                self.on_shoot_set(self.world_object.fire)
                self.weapon_object.set_shoot(self.world_object.fire)
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
                        hit_amount = BOT_ATTACK_DAMAGE
                        type = MELEE_KILL
                        self.on_hit(hit_amount, player, type, None)
                        player.hit(hit_amount, self, type)
                        # knockback
                        if not player.local:
                            player.input = set()
                            player.input.add("jump")
                            player.flush_input()

        def dig(self, i):
            if not self.protocol.strong:
                bindo = BOT_BLOCK_BREAK_CHANCE
            else:
                bindo = BOT_BLOCK_BREAK_CHANCE_STRONG
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position
            map = self.protocol.map

            if self.world_object.dead:
                return
            ix = int(floor(pos.x))
            iy = int(floor(pos.y))
            iz = int(floor(pos.z))
            for x in xrange(ix - 1, ix + 2):
                for y in xrange(iy - 1, iy + 2):
                    for z in xrange(iz - 1 + i, iz + 2 + i):
                        rough = random.randint(0, bindo)
                        if rough == 0:
                            if z > 61 or not destroy_block(self.protocol, x, y, z):
                                return
                            if map.get_solid(x, y, z):
                                map.destroy_point(x, y, z)
                                map.check_node(x, y, z, True)
                            self.on_block_removed(x, y, z)
                        else:
                            continue

        def on_spawn(self, pos):
            if self.local:
                self.respawn_time = BOT_RESPAWN_TIME
                self.set_hp(BOT_HP)
            max_bots = BOTS_MAX
            min_bots = BOTS_MIN
            blue_players = self.protocol.blue_team.count()
            plus_bots = BOTS_PER_PLAYER
            if blue_players <= 7 and BOTS_PER_PLAYER == 1 and BOTS_MAX == 16:
                plus_bots = BOTS_PER_PLAYER + 1
            bot_amount = blue_players + plus_bots
            if bot_amount > max_bots:
                bot_amount = max_bots
            elif bot_amount < min_bots:
                bot_amount = min_bots
            missing_bots = bot_amount - len(self.protocol.bots)
            if not self.local and missing_bots > 0:
                    addbot(self, missing_bots, "green")
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
            return connection.on_spawn(self, pos)

        def on_spawn_location(self, pos):
            x = -1
            y = -1
            if self.protocol.war:
                if self.team == self.protocol.blue_team:
                    x = random.randint(0, 16)
                    y = random.randint(0, 16)
                elif self.team == self.protocol.green_team:
                    x = random.randint(495, 511)
                    y = random.randint(495, 511)
            else:
                if self.team == self.protocol.blue_team:
                    x = random.randint(256 - HUMAN_SPAWN_RANGE, 256 + HUMAN_SPAWN_RANGE)
                    y = random.randint(256 - HUMAN_SPAWN_RANGE, 256 + HUMAN_SPAWN_RANGE)
                elif self.team == self.protocol.green_team:
                    if self.protocol.placeof == 0:
                        x = random.randint(0, 16)
                        y = random.randint(0, 16)
                    elif self.protocol.placeof == 1:
                        x = random.randint(0, 16)
                        y = random.randint(495, 511)
                    elif self.protocol.placeof == 2:
                        x = random.randint(495, 511)
                        y = random.randint(0, 16)
                    elif self.protocol.placeof == 3:
                        x = random.randint(495, 511)
                        y = random.randint(495, 511)
            if x >= 0 and y >= 0:
                z = self.protocol.map.get_z(x, y) - 3
                return x, y, z
            return connection.on_spawn_location(self, pos)

        def on_disconnect(self):
            if self.team == self.protocol.blue_team:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_disconnect(self)

        def on_team_changed(self, old_team):
            if old_team == self.protocol.blue_team:
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_team_changed(self, old_team)

        def on_kill(self, killer, type, grenade):
            pos = self.world_object.position
            if not self.local and type == MELEE_KILL:
                if killer.local:
                    for bot in self.protocol.bots:
                        if ((bot.world_object) and (not bot.world_object.dead) and
                                (not bot == killer)):
                            bot.set_hp(50)
                            bot.set_location((pos.x, pos.y, pos.z))
                            break
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_kill(self, killer, type, grenade)

        def on_hit(self, hit_amount, hit_player, type, grenade):
            if not self.local and not hit_player.local and grenade:
                return False

            if hit_player.local:
                if grenade:
                    return hit_amount * BOT_HIT_GRENADE
                elif self.tool == WEAPON_TOOL:
                    if self.weapon == RIFLE_WEAPON:
                        return hit_amount * BOT_HIT_RIFLE
                    elif self.weapon == SMG_WEAPON:
                        return hit_amount * BOT_HIT_SMG
                    elif self.weapon == SHOTGUN_WEAPON:
                        return hit_amount * BOT_HIT_SHOTGUN
                else:
                    return hit_amount * BOT_HIT_SPADE
            connection.on_hit(self, hit_amount, hit_player, type, grenade)

        def on_fall(self, damage):
            if self.local:
                return False
            connection.on_fall(self, damage)

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

    return SurviveProtocol, SurviveConnection
