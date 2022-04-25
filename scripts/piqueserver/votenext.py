"""
votenext.py by IAmYourFriend https://twitter.com/1AmYF

votenext.py is a simple way for players to vote for loading the next map in
the rotation by only typing /next. Unlike votekick or votemap, the votes will be
remembered and the progress will be checked again everytime someone types /next
or disconnects from the server.

Config Options:

    [votenext]
    # Percentage of votes necessary for the next map to load
    vote_percentage = 80

    # How long players have to wait to be able to vote on a newly loaded map
    min_map_uptime = "1min"
"""

import time
from pyspades.constants import *
from piqueserver.commands import command
from piqueserver.config import config, cast_duration

VOTENEXT_CONFIG = config.section("votenext")
VOTE_PERCENTAGE = VOTENEXT_CONFIG.option("vote_percentage", default=80, cast=int)
MIN_MAP_UPTIME = VOTENEXT_CONFIG.option("min_map_uptime", default="1min", cast=cast_duration)


@command()
def next(connection):
    if not connection.voted_next:
        if not allow_votes(connection.protocol):
            msg = "Please wait %s seconds before requesting the next map."
            connection.send_chat(msg % (connection.protocol.mapstarttime +
                                        MIN_MAP_UPTIME.get() - get_now_in_secs()))
        else:
            connection.voted_next = True
            check_for_map_change(connection.protocol)
            connection.protocol.irc_say("%s voted for next map" % connection.name)
            if not connection.protocol.vote_next_successful:
                msg = "%s voted to load the next map, if you agree type /next"
                connection.protocol.broadcast_chat(msg % connection.name)
    else:
        connection.send_chat("You have voted already.")


def allow_votes(protocol):
    if protocol.mapstarttime is not None and not protocol.vote_next_successful:
        return (protocol.mapstarttime + MIN_MAP_UPTIME.get()) < get_now_in_secs()
    else:
        return False


def get_now_in_secs():
    return int(time.time())


def reset_player_votes(protocol):
    protocol.vote_next_successful = False
    if protocol.players is not None and len(protocol.players) > 0:
        for p in protocol.players.values():
            p.voted_next = False


def is_bot(connection):
    try:
        return connection.local
    except AttributeError:
        return False


def check_for_map_change(protocol, ignore_player_id=None):
    if protocol.players is not None and len(protocol.players) > 0 and allow_votes(protocol):
        valid_voters = 0
        valid_votes = 0
        for p in protocol.players.values():
            ignore_player = False
            if is_bot(p) or (ignore_player_id is not None and (p.player_id == ignore_player_id)):
                ignore_player = True
            if not ignore_player:
                valid_voters += 1
                if p.voted_next:
                    valid_votes += 1
        if valid_voters > 0 and valid_votes >= VOTE_PERCENTAGE.get() * valid_voters / float(100):
            protocol.vote_next_successful = True
            protocol.advance_rotation("Vote successful.")


def apply_script(protocol, connection, config):
    class VoteNextProtocol(protocol):
        mapstarttime = None
        vote_next_successful = False

        def on_map_change(self, map):
            reset_player_votes(self)
            self.mapstarttime = get_now_in_secs()
            protocol.on_map_change(self, map)

    class VoteNextConnection(connection):
        voted_next = False

        def on_disconnect(self):
            if not is_bot(self):
                check_for_map_change(self.protocol, self.player_id)
            connection.on_disconnect(self)

    return VoteNextProtocol, VoteNextConnection
