"""
wordfilter.py by IAmYourFriend https://twitter.com/1AmYF

Handles swear words in chat, pm, playernames and votekick reasons and
also adds a cooldown to pms.
"""

import time
import re

# Words that will trigger a kick
KICK_WORDS = ["kfcni"]

# Words that will be replaced by filter
FILTER_WORDS = ["nigger", "nigg", "chink", "gook", "kike", "fuck", "bitch", "faggot", "tranny"]

# Additional words to disallow in usernames (KICK_WORDS and FILTER_WORDS are already included)
KICK_NAMES = ["admin"]

# Additional words to disallow in votekicks (KICK_WORDS and FILTER_WORDS are already included)
REJECT_VOTEKICK = ["gay", "jew"]

# What to replace filtered words with
FILTER_REPLACE = "***"

# Player has to wait this time to send a pm again (set to 0 to disable this)
PM_COOLDOWN = 6  # seconds


def get_now_in_secs():
    return int(time.time())


def has_filtered_word(message):
    for w in KICK_WORDS:
        if w in message.lower():
            return True
    for w in FILTER_WORDS:
        if w in message.lower():
            return True
    return False


def apply_filter(connection, message):
    if message is not None and len(message) > 0:
        if any(word in message.lower() for word in KICK_WORDS):
            report = "%s #%s kicked for language: %s" % (connection.name, connection.player_id, message)
            print report
            connection.protocol.irc_say(report)
            connection.kick(silent=True)
            return None
        elif any(word in message.lower() for word in FILTER_WORDS):
            for w in FILTER_WORDS:
                pattern = re.compile(w, re.IGNORECASE)
                message = pattern.sub(FILTER_REPLACE, message)
    return message


def apply_script(protocol, connection, config):

    class WordfilterConnection(connection):
        last_pm_sent = 0

        def on_login(self, name):
            if name is not None:
                has_kick_name = False
                for w in KICK_NAMES:
                    if w in name.lower():
                        has_kick_name = True
                        break
                if has_kick_name or has_filtered_word(name):
                    self.kick(silent=True)
            return connection.on_login(self, name)

        def on_chat(self, value, is_global):
            value = apply_filter(self, value)
            if self.disconnected:
                return False
            return connection.on_chat(self, value, is_global)

        def on_command(self, command, parameters):
            if command is not None and len(parameters) > 0:
                if command.lower() == "pm":
                    # Check if attribute is present in case a pm is sent from IRC
                    if PM_COOLDOWN > 0 and hasattr(self, "last_pm_sent"):
                        if get_now_in_secs() < self.last_pm_sent + PM_COOLDOWN:
                            self.send_chat("Please wait %s seconds before sending another pm" %
                                           (self.last_pm_sent + PM_COOLDOWN - get_now_in_secs()))
                            return False
                        self.last_pm_sent = get_now_in_secs()
                    for i, val in enumerate(parameters):
                        if i > 0:
                            parameters[i] = apply_filter(self, val)
                            if self.disconnected:
                                return False
                if command.lower() == "votekick":
                    for w in parameters[1:]:
                        if has_filtered_word(w) or w.lower() in REJECT_VOTEKICK:
                            self.send_chat("Invalid votekick reason")
                            return False
            return connection.on_command(self, command, parameters)

    return protocol, WordfilterConnection
