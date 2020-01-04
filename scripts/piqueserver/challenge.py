"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

See how many kills you can get in 5 minutes. With highscores. Originally
written for the target practice server with bots, based on an idea by F176.
If a map timelimit is set, it will be extended for the challenge duration.

Options
^^^^^^^

.. code-block:: python

    [challenge]
    # Set the duration of a challenge.
    challenge_duration = "5min"

    # Save highscores into a csv file. The top scores will be listed with
    # the /highscore command. The csv file will be written into the map
    # folder as mapname_challenge.csv (if global_highscores is false, otherwise
    # they will be written as challenge_scores.csv in the main server folder).
    save_highscores = true

    # Show highscores individually for each map, or make global highscores
    # over all maps.
    global_highscores = false

    # How many of the top scores to show when using the /highscore command.
    show_scores = 10

Commands
^^^^^^^^

* ``/challenge`` Start the timer (use command again to abort)
* ``/highscore`` Show the top scores (if enabled)
"""

from pyspades.constants import *
from piqueserver.commands import command
from piqueserver.config import config, cast_duration
from twisted.internet import reactor
from twisted.internet.task import LoopingCall
import time
import operator
import os.path

CHALLENGE_CONFIG = config.section("challenge")
DURATION = CHALLENGE_CONFIG.option("challenge_duration", default="5min", cast=cast_duration)
SAVE_HIGHSCORES = CHALLENGE_CONFIG.option("save_highscores", default=True, cast=bool)
GLOBAL_HIGHSCORES = CHALLENGE_CONFIG.option("global_highscores", default=False, cast=bool)
SHOW_SCORES = CHALLENGE_CONFIG.option("show_scores", default=10, cast=int)

CSV_SEP = ";"


def get_highscore_filename(mapname):
    if GLOBAL_HIGHSCORES.get():
        return os.path.join(config.config_dir, "challenge_scores.csv")
    else:
        return os.path.join(config.config_dir, "maps", mapname + "_challenge.csv")


def save_highscores(playername, kills, mapname, playerip):
    formatnow = time.strftime("%d.%m.%Y %H:%M:%S")
    playernamesecure = ""
    if playername is not None and len(playername) > 0:
        playernamesecure = playername.replace(CSV_SEP, ",")
    f = open(get_highscore_filename(mapname), "a")
    f.write(playernamesecure + CSV_SEP + str(kills) + CSV_SEP + mapname +
            CSV_SEP + str(int(DURATION.get() / 60)) + CSV_SEP + formatnow +
            CSV_SEP + str(playerip) + "\n")
    f.close()


@command()
def highscore(connection):
    """
    Show the top scores
    /highscore
    """
    if not SAVE_HIGHSCORES.get():
        return "Highscores are disabled"
    mapname = connection.protocol.map_info.rot_info.name
    if not os.path.exists(get_highscore_filename(mapname)):
        return "No highscores yet"
    scores = list()
    file = open(get_highscore_filename(mapname), "r")
    for line in file:
        if line is not None and len(line.strip()) > 0:
            scores.append(line.strip().split(CSV_SEP))
    if len(scores) > 0:
        sortedscores = sorted(scores, key=lambda x: int(x[1]), reverse=True)
        displayscores = list()
        i = 1
        for playervalues in sortedscores:
            duplicate = False
            for addedplayer in displayscores:
                if playervalues[0] == addedplayer[0]:
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
            scoreline = place + displayvalues[0] + "  (" + displayvalues[1] + " kills"
            if GLOBAL_HIGHSCORES.get():
                scoreline += " on map " + displayvalues[2] + ")"
            else:
                scoreline += ")"
            strscores.append(scoreline)
            i += 1
        connection.send_lines(strscores)


@command()
def challenge(connection):
    """
    Start the timer (use command again to abort)
    /challenge
    """
    if connection.challenge_loop is None:
        return
    connection.challenge_kills = 0
    if connection.challenge_loop.running:
        connection.challenge_loop.stop()
        return "Challenge cancelled"
    else:
        dur_mins = int(DURATION.get() / 60)
        connection.challenge_remaining = dur_mins
        connection.challenge_loop.start(60, now=False)
        if connection.protocol.default_time_limit and connection.protocol.advance_call is not None:
            remaining = (connection.protocol.advance_call.getTime() - reactor.seconds()) / 60
            if remaining < dur_mins:
                connection.protocol.set_time_limit(dur_mins + 1)
        msg = "%s started the %s minutes challenge! To join type /challenge"

        connection.protocol.send_chat(msg % (connection.name, dur_mins), irc=True)
        return "Get as many kills as possible during the next %s minutes!" % dur_mins


def apply_script(protocol, connection, config):
    class ChallengeConnection(connection):
        challenge_loop = None
        challenge_kills = 0
        challenge_remaining = 0

        def challenge_check(self):
            if self.challenge_remaining <= 1:
                self.challenge_loop.stop()
                self.protocol.send_chat("%s completed the challenge: %s kills in %s minutes"
                                        % (self.name, self.challenge_kills, int(DURATION.get() / 60)),
                                        irc=True)
                if SAVE_HIGHSCORES.get() and self.challenge_kills > 0:
                    save_highscores(self.name, self.challenge_kills,
                                    self.protocol.map_info.rot_info.name,
                                    self.address[0])
            else:
                self.challenge_remaining -= 1
                self.send_chat("%s minutes of challenge left" % self.challenge_remaining)

        def on_team_join(self, team):
            if self.challenge_loop is None:
                self.challenge_loop = LoopingCall(self.challenge_check)
            elif self.challenge_loop.running:
                self.challenge_loop.stop()
            return connection.on_team_join(self, team)

        def on_kill(self, killer, type, grenade):
            if killer is not None and self is not killer:
                killer.challenge_kills += 1
            return connection.on_kill(self, killer, type, grenade)

        def on_disconnect(self):
            if self.challenge_loop is not None and self.challenge_loop.running:
                self.challenge_loop.stop()
            return connection.on_disconnect(self)

    return protocol, ChallengeConnection
