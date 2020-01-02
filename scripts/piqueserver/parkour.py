"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

**parkour.py** is a parkour gamemode with highscores. Players spawn on the same
team at the same location and have to make it to their base to complete the
parkour. Example: https://youtu.be/CIvmWNBpfi8

Setup
^^^^^

Set game_mode in your server config to "parkour" and add parkour maps to the
rotation.

To create a new parkour map, map txt metadata is required. Example:

>>> extensions = {
...     'water_damage' : 100,
...     'parkour_start' : (127, 256, 50),
...     'parkour_end' : (382, 256, 50),
...     'parkour_checkpoints' : ((187, 256, 50), (240, 256, 39), (289, 256, 50))
... }

'parkour_start' marks the coordinate for spawn, 'parkour_end' for the base
location. If a player dies during the parkour, he will spawn to the closest
checkpoint coordinate behind him (the parkour direction needs to be from
left to right on the map view).

Options
^^^^^^^

.. code-block:: python

    [parkour]
    # Every parkour completion will be saved into a csv file and the top scores will
    # be listed with the /highscore command (the csv file will be written into the
    # map folder as mapname_scores.csv).
    save_highscores = true

    # How many of the top scores to show when using the /highscore command.
    show_scores = 10

Commands
^^^^^^^^

* ``/highscore``
    List the top highscores (if enabled).
* ``/reset``
    Reset your time/score and retry the parkour from start.
"""

import time
import operator
from pyspades.constants import *
from piqueserver.commands import command
from piqueserver.config import config
from math import floor
import os.path

PARKOUR_CONFIG = config.section("parkour")
SAVE_HIGHSCORES = PARKOUR_CONFIG.option("save_highscores", default=True, cast=bool)
SHOW_SCORES = PARKOUR_CONFIG.option("show_scores", default=10, cast=int)

CSV_SEP = ";"
HIDE_COORD = (0, 0, 63)


def get_highscore_filename(connection):
    return (os.path.join(config.config_dir, "maps",
            connection.protocol.map_info.rot_info.name + "_scores.csv"))


@command()
def highscore(connection):
    """
    List the top highscores
    /highscore
    """
    if not SAVE_HIGHSCORES.get():
        return "Highscores are disabled"
    if not os.path.exists(get_highscore_filename(connection)):
        return "No highscores yet"
    scores = list()
    file = open(get_highscore_filename(connection), "r")
    for line in file:
        if line is not None and len(line.strip()) > 0:
            scores.append(line.strip().split(CSV_SEP))

    if len(scores) > 0:
        sortedscores = sorted(scores, key=operator.itemgetter(1))
        displayscores = list()
        i = 1
        for playervalues in sortedscores:
            duplicate = False
            for addedplayer in displayscores:
                if compare_str_ignore_case(playervalues[0], addedplayer[0]):
                    duplicate = True
                    break
            if not duplicate:
                displayscores.append(playervalues)
                i += 1
                if i > SHOW_SCORES.get():
                    break

        i = 1
        strscores = []
        for displayvalues in displayscores:
            place = str(i) + ". "
            if i < 10:
                place += " "
            strscores.append(place + displayvalues[0] + "  (" + displayvalues[1] +
                             " mins, deaths: " + displayvalues[2] + ")")
            i += 1
        connection.send_lines(strscores)


def compare_str_ignore_case(str1, str2):
    if str1 is not None and len(str1) > 0 and str2 is not None and len(str2) > 0:
        return str1.lower().strip() == str2.lower().strip()
    else:
        return str1 == str2


@command()
def reset(connection):
    """
    Reset your time/score and retry the parkour from start
    /reset
    """
    if connection.team is connection.protocol.blue_team:
        connection.isresetting = True
        connection.kill()


def save_highscore(connection, playername, parkourtime, deaths, playerip):
    formatnow = time.strftime("%d.%m.%Y %H:%M:%S")
    playernamesecure = ""
    if playername is not None and len(playername) > 0:
        playernamesecure = playername.replace(CSV_SEP, ",")
    f = open(get_highscore_filename(connection), "a")
    f.write("\n" + playernamesecure + CSV_SEP + str(parkourtime) + CSV_SEP +
            str(deaths) + CSV_SEP + formatnow + CSV_SEP + str(playerip))
    f.close()


def get_now_in_secs():
    return int(time.time())


def get_formatted_parkour_time(completedseconds):
    completedformatmin = str(int(floor(completedseconds / 60)))
    if len(completedformatmin) == 1:
        completedformatmin = "0" + completedformatmin
    completedformatsec = str(int(completedseconds % 60))
    if len(completedformatsec) == 1:
        completedformatsec = "0" + completedformatsec
    return completedformatmin + ":" + completedformatsec


def reset_player_stats(self):
    self.joinedtimestamp = get_now_in_secs()
    self.completedparkour = False
    self.reachedcheckpoint = 0
    self.deathcount = 0


def apply_script(protocol, connection, config):
    class ParkourConnection(connection):
        joinedtimestamp = None
        completedparkour = False
        reachedcheckpoint = 0
        deathcount = 0
        isresetting = False

        def on_team_join(self, team):
            if team is self.protocol.blue_team:
                reset_player_stats(self)
            return connection.on_team_join(self, team)

        def on_flag_take(self):
            return False

        def on_spawn_location(self, pos):
            if self.team is self.protocol.blue_team:
                if self.isresetting:
                    reset_player_stats(self)
                self.isresetting = False
                ext = self.protocol.map_info.extensions
                if self.reachedcheckpoint > 0:
                    return ext["parkour_checkpoints"][self.reachedcheckpoint - 1]
                else:
                    return ext["parkour_start"]
            return connection.on_spawn_location(self, pos)

        def on_kill(self, killer, type, grenade):
            if self.team is self.protocol.blue_team and not self.isresetting:
                self.deathcount += 1
                checkpoints = self.protocol.map_info.extensions["parkour_checkpoints"]
                i = len(checkpoints)
                self.reachedcheckpoint = 0
                for cp in reversed(checkpoints):
                    if self.world_object.position.x >= cp[0]:
                        self.reachedcheckpoint = i
                        break
                    i -= 1
            return connection.on_kill(self, killer, type, grenade)

        def on_refill(self):
            if self.team is self.protocol.blue_team and not self.completedparkour:
                self.completedparkour = True
                if self.joinedtimestamp is not None:
                    displaytime = get_formatted_parkour_time(get_now_in_secs() -
                                                             self.joinedtimestamp)
                    msg = "Congratulations, %s completed the parkour! Stats: %s mins, %s deaths"
                    completedmessage = msg % (self.name, displaytime, self.deathcount)
                    self.protocol.send_chat(completedmessage)
                    self.protocol.irc_say(completedmessage)
                    if SAVE_HIGHSCORES.get():
                        save_highscore(self, self.name, displaytime,
                                       self.deathcount, self.address[0])
            return connection.on_refill(self)

        def on_connect(self):
            self.protocol.green_team.locked = True
            self.protocol.balanced_teams = 0
            self.protocol.building = False
            self.protocol.fall_damage = False
            return connection.on_connect(self)

        def on_disconnect(self):
            if self.team is self.protocol.blue_team and not self.completedparkour:
                if self.joinedtimestamp is not None:
                    displaytime = get_formatted_parkour_time(get_now_in_secs() -
                                                             self.joinedtimestamp)
                    msg = "%s ragequit after %s mins, %s deaths"
                    failmessage = msg % (self.name, displaytime, self.deathcount)
                    self.protocol.send_chat(failmessage)
                    self.protocol.irc_say(failmessage)
            connection.on_disconnect(self)

    class ParkourProtocol(protocol):
        game_mode = CTF_MODE

        def on_base_spawn(self, x, y, z, base, entity_id):
            if entity_id == BLUE_BASE:
                return self.map_info.extensions["parkour_end"]
            return HIDE_COORD

        def on_flag_spawn(self, x, y, z, flag, entity_id):
            return HIDE_COORD

    return ParkourProtocol, ParkourConnection
