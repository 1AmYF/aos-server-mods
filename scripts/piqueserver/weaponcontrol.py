"""
About
^^^^^

.. codeauthor:: IAmYourFriend https://twitter.com/1AmYF

**weaponcontrol.py** allows to disable weapons (Spade, Rifle, SMG,
Shotgun and/or Grenades). They can be disabled globally or individually
for maps (map will overrule server setting).

Setup
^^^^^

For global settings, add this to your server config:

.. code-block:: python

    [weapons]
    spade = true
    rifle = true
    smg = true
    shotgun = true
    grenades = true


Set those that you want to disable to false.
For individual map settings, add them to the map txt metadata:

>>> extensions = {
...     'weapons' : {
...         'spade' : True,
...         'rifle' : True,
...         'smg' : True,
...         'shotgun' : True,
...         'grenades' : True
...     }
... }

A disabled weapon can not be selected on join or by weapon change (on
join, the player will automatically receive an available weapon instead).
"""

from pyspades.constants import *
from pyspades import contained as loaders


DISABLED_GRENADE = "Grenades are disabled."
DISABLED_SPADE = "Spade damage is disabled."
DISABLED_WEAPON = "Your selected weapon is disabled."


def is_weapon_allowed(allowed_weapons, weapon):
    if allowed_weapons is None:
        return True
    return ((weapon == RIFLE_WEAPON and allowed_weapons["rifle"]) or
            (weapon == SMG_WEAPON and allowed_weapons["smg"]) or
            (weapon == SHOTGUN_WEAPON and allowed_weapons["shotgun"]))


def is_any_weapon_allowed(allowed_weapons):
    return (is_weapon_allowed(allowed_weapons, RIFLE_WEAPON) or
            is_weapon_allowed(allowed_weapons, SMG_WEAPON) or
            is_weapon_allowed(allowed_weapons, SHOTGUN_WEAPON))


def clear_ammo(connection):
    weapon_reload = loaders.WeaponReload()
    weapon_reload.player_id = connection.player_id
    weapon_reload.clip_ammo = 0
    weapon_reload.reserve_ammo = 0
    connection.weapon_object.clip_ammo = 0
    connection.weapon_object.reserve_ammo = 0
    connection.send_contained(weapon_reload)


def apply_script(protocol, connection, config):
    class WeaponControlConnection(connection):
        def on_spawn(self, pos):
            if not is_any_weapon_allowed(self.protocol.allowed_weapons):
                clear_ammo(self)
            return connection.on_spawn(self, pos)

        def on_weapon_set(self, weapon):
            if not is_weapon_allowed(self.protocol.allowed_weapons, weapon):
                self.send_chat(DISABLED_WEAPON)
                return False
            return connection.on_weapon_set(self, weapon)

        def set_weapon(self, weapon, local=False, no_kill=False, *args, **kwargs):
            if (is_any_weapon_allowed(self.protocol.allowed_weapons) and
                    not is_weapon_allowed(self.protocol.allowed_weapons, weapon)):
                if is_weapon_allowed(self.protocol.allowed_weapons, RIFLE_WEAPON):
                    weapon = RIFLE_WEAPON
                elif is_weapon_allowed(self.protocol.allowed_weapons, SMG_WEAPON):
                    weapon = SMG_WEAPON
                elif is_weapon_allowed(self.protocol.allowed_weapons, SHOTGUN_WEAPON):
                    weapon = SHOTGUN_WEAPON
                self.send_chat(DISABLED_WEAPON)
            return connection.set_weapon(self, weapon, local, no_kill, *args, **kwargs)

        def on_shoot_set(self, fire):
            if (self.tool == WEAPON_TOOL and
                    not is_any_weapon_allowed(self.protocol.allowed_weapons)):
                    clear_ammo(self)
            return connection.on_shoot_set(self, fire)

        def on_hit(self, hit_amount, hit_player, type, grenade):
            if (self.tool == SPADE_TOOL and
                    self.protocol.allowed_weapons is not None and
                    not self.protocol.allowed_weapons["spade"]):
                self.send_chat(DISABLED_SPADE)
                return False
            return connection.on_hit(self, hit_amount, hit_player, type, grenade)

        def on_grenade(self, time_left):
            if (self.protocol.allowed_weapons is not None and
                    not self.protocol.allowed_weapons["grenades"]):
                self.send_chat(DISABLED_GRENADE)
                return False
            return connection.on_grenade(self, time_left)

    class WeaponControlProtocol(protocol):
        allowed_weapons = None

        def on_map_change(self, map):
            self.allowed_weapons = self.map_info.extensions.get("weapons", None)
            if self.allowed_weapons is None:
                self.allowed_weapons = config.get("weapons", None)
            return protocol.on_map_change(self, map)

    return WeaponControlProtocol, WeaponControlConnection
