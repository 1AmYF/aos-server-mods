"""
autosave.py by IAmYourFriend https://twitter.com/1AmYF

Automatically creates backups of the current map in a given
interval and also removes older saves. Saving will be skipped
if nobody was on the server during the interval.

Commands:

    Command /autosave toggles the feature.
    Command /save will save the map manually.
    Command /recentsaves shows the last 5 saves.
"""

import os
import fnmatch
from time import time, strftime, localtime
from twisted.internet.task import LoopingCall
from twisted.internet.reactor import callLater
from commands import add, admin

# Interval to save the map
SAVE_INTERVAL_MINS = 60  # minutes

# Save all maps into a folder named mapname_BAK
SAVE_TO_FOLDER = True

# Suffix for the name of the map folder
MAP_FOLDER_SUFFIX = "_BAK"

# Remove old backups, set to False to disable this
DELETE_AFTER_DAYS = 30  # days

# Date format for the map filename
DATE_FORMAT = "%Y%m%d-%H%M"


@admin
def save(connection):
    connection.protocol.write_map_file()
    return "Map saved."


@admin
def autosave(connection):
    if not connection.protocol.autosave:
        connection.protocol.autosave = True
        return "Autosave enabled."
    else:
        connection.protocol.autosave = False
        return "Autosave disabled."


@admin
def recentsaves(connection):
    responsestr = ""
    filelist = connection.protocol.get_maps_list()
    if filelist is None or len(filelist) < 1:
        return "No saves yet."
    else:
        filelist.sort()
        for f in filelist[len(filelist) - 5:]:
            if SAVE_TO_FOLDER:
                responsestr += (connection.protocol.map_info.rot_info.name +
                                MAP_FOLDER_SUFFIX + "/")
            responsestr += f + " "
    return responsestr


add(save)
add(autosave)
add(recentsaves)


def apply_script(protocol, connection, config):
    class AutoMapSaveProtocol(protocol):
        autosave = True
        activity = False

        def __init__(self, *arg, **kwargs):
            protocol.__init__(self, *arg, **kwargs)
            self.save_loop = LoopingCall(self.autosave_map)
            self.save_loop.start(SAVE_INTERVAL_MINS * 60.0, now=False)

        def autosave_map(self):
            if self.autosave:
                if self.activity:
                    self.write_map_file()
                self.activity = len(self.players) > 0

        def get_map_path(self):
            joined = os.path.join(os.getcwd(), "maps")
            if SAVE_TO_FOLDER:
                newdir = self.map_info.rot_info.name + MAP_FOLDER_SUFFIX
                joined = os.path.join(joined, newdir)
                if not os.path.isdir(joined):
                    os.mkdir(joined)
            return joined

        def write_map_file(self):
            newfile = "{0}.{1}.vxl".format(self.map_info.rot_info.name,
                                           strftime(DATE_FORMAT, localtime()))
            open(os.path.join(self.get_map_path(), newfile), "wb").write(self.map.generate())
            if DELETE_AFTER_DAYS:
                self.delete_old_maps()

        def get_maps_list(self):
            return fnmatch.filter(os.listdir(self.get_map_path()),
                                  self.map_info.rot_info.name + ".*.vxl")

        def delete_old_maps(self):
            for f in self.get_maps_list():
                pf = os.path.join(self.get_map_path(), f)
                if os.path.isfile(pf) and os.stat(pf).st_mtime < time() - (DELETE_AFTER_DAYS * 86400):
                    os.remove(pf)

    class AutoMapSaveConnection(connection):
        def on_team_join(self, team):
            self.protocol.activity = True
            return connection.on_team_join(self, team)

    return AutoMapSaveProtocol, AutoMapSaveConnection
