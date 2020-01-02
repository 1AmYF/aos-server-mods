"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

**autosave.py** is intended for build servers. Automatically creates
backups of the current map in a given interval and also removes older
saves. Saving will be skipped if nobody was on the server during the
interval.

Options
^^^^^^^

.. code-block:: python

    [autosave]
    # Interval to save the map.
    save_interval = "60min"

    # Save all maps into a folder named mapname_BAK.
    save_to_folder = true

    # Suffix for the name of the map folder.
    map_folder_suffix = "_BAK"

    # Remove old backups, set to zero days to disable this.
    delete_after = "30days"

    # Date format for the map filename.
    date_format = "%Y%m%d-%H%M"

Commands
^^^^^^^^

* ``/autosave`` Toogle the feature
* ``/save`` Manually save the map
* ``/recentsaves`` Show the last 5 saves
"""

import os
import fnmatch
from time import time, strftime, localtime
from twisted.internet.task import LoopingCall
from twisted.internet.reactor import callLater
from piqueserver.commands import command
from piqueserver.config import config, cast_duration

AUTOSAVE_CONFIG = config.section("autosave")
SAVE_INTERVAL = AUTOSAVE_CONFIG.option("save_interval", default="60min", cast=cast_duration)
SAVE_TO_FOLDER = AUTOSAVE_CONFIG.option("save_to_folder", default=True, cast=bool)
MAP_FOLDER_SUFFIX = AUTOSAVE_CONFIG.option("map_folder_suffix", default="_BAK")
DELETE_AFTER = AUTOSAVE_CONFIG.option("delete_after", default="30days", cast=cast_duration)
DATE_FORMAT = AUTOSAVE_CONFIG.option("date_format", default="%Y%m%d-%H%M")


@command(admin_only=True)
def autosave(connection):
    """
    Toogle the feature
    /autosave
    """
    if not connection.protocol.autosave:
        connection.protocol.autosave = True
        return "Autosave enabled."
    else:
        connection.protocol.autosave = False
        return "Autosave disabled."


@command(admin_only=True)
def save(connection):
    """
    Manually save the map
    /save
    """
    connection.protocol.write_map_file()
    return "Map saved."


def get_map_dir():
    return os.path.join(config.config_dir, "maps")


@command(admin_only=True)
def recentsaves(connection):
    """
    Show the last 5 saves
    /recentsaves
    """
    responsestr = ""
    filelist = connection.protocol.get_maps_list()
    if filelist is None or len(filelist) < 1:
        return "No saves yet."
    else:
        filelist.sort()
        for f in filelist[len(filelist) - 5:]:
            if SAVE_TO_FOLDER.get():
                responsestr += (connection.protocol.map_info.rot_info.name +
                                MAP_FOLDER_SUFFIX.get() + "/")
            responsestr += f + " "
    return responsestr


def apply_script(protocol, connection, config):
    class AutoMapSaveProtocol(protocol):
        autosave = True
        activity = False

        def __init__(self, *arg, **kwargs):
            protocol.__init__(self, *arg, **kwargs)
            self.save_loop = LoopingCall(self.autosave_map)
            self.save_loop.start(SAVE_INTERVAL.get(), now=False)

        def autosave_map(self):
            if self.autosave:
                if self.activity:
                    self.write_map_file()
                self.activity = len(self.players) > 0

        def get_map_path(self):
            joined = get_map_dir()
            if SAVE_TO_FOLDER.get():
                newdir = self.map_info.rot_info.name + MAP_FOLDER_SUFFIX.get()
                joined = os.path.join(joined, newdir)
                if not os.path.isdir(joined):
                    os.mkdir(joined)
            return joined

        def write_map_file(self):
            newfile = "{0}.{1}.vxl".format(self.map_info.rot_info.name,
                                           strftime(DATE_FORMAT.get(), localtime()))
            open(os.path.join(self.get_map_path(), newfile), "wb").write(self.map.generate())
            if DELETE_AFTER.get() > 0:
                self.delete_old_maps()

        def get_maps_list(self):
            return fnmatch.filter(os.listdir(self.get_map_path()),
                                  self.map_info.rot_info.name + ".*.vxl")

        def delete_old_maps(self):
            for f in self.get_maps_list():
                pf = os.path.join(self.get_map_path(), f)
                if os.path.isfile(pf) and os.stat(pf).st_mtime < time() - (DELETE_AFTER.get()):
                    os.remove(pf)

    class AutoMapSaveConnection(connection):
        def on_team_join(self, team):
            self.protocol.activity = True
            return connection.on_team_join(self, team)

    return AutoMapSaveProtocol, AutoMapSaveConnection
