###############################################################################
#
# Copyright 2012 Stendec <me@stendec.me>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################
"""
This is the core of NakedSun where, among other things, the event loop is
entered when the MUD starts. The core is also responsible for setting up the
basic servers.
"""

###############################################################################
# Imports
###############################################################################

import os
import argparse
import signal
import sys

import pants

import nakedsun
import nakedsun.logger as log

try:
    import pwd
    import grp
except ImportError:
    pwd = None
    grp = None

do_uid = hasattr(os, "getuid")

###############################################################################
# The Signal Handler
###############################################################################

def signal_HUP(signum, frame):
    """
    If we catch a SIGHUP, the MUD should perform a copyover.
    """
    raise nakedsun.mudsys.SystemCopyover

###############################################################################
# Helper Functions
###############################################################################

def assume_uid(uid, gid, umask):
    """
    Assume the given UID, GID, and UMASK.
    """

    # First, make sure we have values.
    if uid is None:
        uid = nakedsun.settings.get("uid")
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        pass

    if gid is None:
        gid = nakedsun.settings.get("gid")
    try:
        gid = int(gid)
    except (TypeError, ValueError):
        pass

    if umask is None:
        umask = nakedsun.settings.get("umask")
    try:
        umask = int(umask)
    except (TypeError, ValueError):
        if umask:
            log.warning("Invalid value for umask %r." % umask)
        umask = None

    # Do the UID first.
    if not uid is None:
        # Try assuming the new UID.
        try:
            # Make sure we're working with an integer.
            if isinstance(uid, basestring):
                try:
                    uid = pwd.getpwnam(uid).pw_uid
                except KeyError:
                    log.critical("No such user %r." % uid)
                    log.shutdown()
                    sys.exit(1)

            if os.getuid() != uid:
                # Now set it.
                os.setuid(uid)

                # Show a message.
                try:
                    log.info("Assuming the UID %d (%s)." % (uid,
                                                    pwd.getpwuid(uid).pw_name))
                except (KeyError, AttributeError):
                    log.info("Assuming the UID %d." % uid)
        except OSError:
            try:
                log.critical("Unable to assume the UID %d (%s)." % (uid,
                                                    pwd.getpwuid(uid).pw_name))
            except (KeyError, AttributeError):
                log.critical("Unable to assume the UID %d." % uid)
            log.shutdown()
            sys.exit(1)

    # Anti-Root Protection
    if os.getuid() == 0:
        if uid == 0:
            log.warning("The server is running as root. This is "
                        "not recommended.")
        else:
            log.critical("Please do not run the server as root.")
            log.critical("Set a UID via the --uid command-line argument, or "
                         "in the MUD configuration file. If the server must "
                         "run as root, provide a UID of 0.")
            log.shutdown()
            sys.exit(1)

    # Now do the GID.
    if not gid is None:
        # Try assuming the new GID.
        try:
            # Make sure we're working with an integer.
            if isinstance(gid, basestring):
                try:
                    gid = grp.getgrnam(gid).gr_gid
                except KeyError:
                    log.critical("No such group %r." % gid)
                    log.shutdown()
                    sys.exit(1)

            if os.getgid() != gid:
                # Now set it.
                os.setgid(gid)

                # Log a message.
                try:
                    log.info("Assuming the GID %d (%s)." % (gid,
                                                    grp.getgrgid(gid).gr_name))
                except (KeyError, AttributeError):
                    log.info("Assuming the GID %d." % gid)
        except OSError:
            try:
                log.critical("Unable to assume the GID %d (%s)." % (gid,
                                                    grp.getgrgid(gid).gr_name))
            except (KeyError, AttributeError):
                log.critical("Unable to assume the GID %d." % gid)
            log.shutdown()
            sys.exit(1)

    # Lastly, the umask.
    if not umask is None:
        old = os.umask(umask)
        log.info("Assuming the umask %04o (old was %04o)." % (umask, old))

def inject(name, module):
    """
    Inject a module into sys.modules with the given name.
    """
    log.debug("Injecting %r into sys.modules as %r." % (module.__name__, name))
    sys.modules[name] = module

###############################################################################
# The Main Function
###############################################################################

def main():
    """
    Initialize everything and launch NakedSun. This method is in charge of
    parsing command line arguments, locating the MUD library, loading all the
    available modules, loading the world, etc.
    """

    ## Argument Parsing

    parser = argparse.ArgumentParser(
                prog="python -m nakedsun",
                description=nakedsun.__doc__,
                version="NakedSun %s" % nakedsun.version
                )

    # Basic Options

    parser.add_argument("--path", dest="lib", default="lib", metavar="PATH",
                        help="Load the MUD library from PATH.")
    parser.add_argument("--copyover", help=argparse.SUPPRESS)

    # Network Options
    group = parser.add_argument_group(
                u"Network Options",
                u"These options allow you to override the default listening "
                u"addresses for the server."
                )

    group.add_argument("-b", "--bind", dest="addr", default=None,
                    help=u"Bind the telnet server to the given ADDRESS:PORT.")
    group.add_argument("--http", dest="http_addr", default=None,
                    help=u"Bind the HTTP server to the given ADDRESS:PORT.")

    # Logging Options

    group = parser.add_argument_group(u"Logging Options")

    group.add_argument("-l", "--log", default="../log", metavar="PATH",
        help=u"Store log files at PATH, relative to the MUD library.")
    group.add_argument("--level", default="INFO",
        help=u"Only log messages of LEVEL or higher. (Default: INFO)")
    group.add_argument("--no-color", default=True, action="store_false",
        dest="color", help=u"Disable console output colorization.")

    # UID/GID Manipulation

    if do_uid:
        group = parser.add_argument_group(
            u"User/Group ID Manipulation",
            u"These options, if used, will be acted upon *immediately* before "
            u"entering the main event loop. This is slightly unsafe, since "
            u"any code in the MUD library will be executed before the new "
            u"user and/or group identity is assumed. However, this is "
            u"necessary to ensure the server is able to bind low ports on UNIX"
            u" systems as root. The provided values may be either names "
            u"or numbers. These values may also be set in the MUD's "
            u"configuration file.")

        group.add_argument("-u", "--uid", help=u"Run as the specified user.")
        group.add_argument("-g", "--gid",
            help=u"Run as the specified group.")
        group.add_argument("--umask", help=u"Use the provided umask.")
        group.add_argument("--early", default=False, action="store_true",
            help=u"Assume the new identity early, before executing any code "
                 u"from the MUD library.")

    # Finally, parse the arguments.
    args = parser.parse_args()

    ## Logging

    log.initialize(args.color, args.level, os.path.join(args.lib, args.log))
    log.naked(u"NakedSun v%s by Stendec <me@stendec.me>" % nakedsun.version)

    ## Enter the MUD Library

    path = os.path.realpath(args.lib)
    if not os.path.exists(path) or not (
            os.path.exists(os.path.join(path, 'muddata')) or
            os.path.exists(os.path.join(path, 'config'))):
        log.error(u"Cannot find the MUD library at: %s" % path)
        log.shutdown()
        sys.exit(1)

    if path != os.getcwd():
        log.info(u"Changing working directory to: %s" % path)
        os.chdir(path)

    ## Load Configuration

    log.info(u"Loading MUD configuration from file.")
    nakedsun.settings.initialize()

    ## Networking Initialization

    log.info(u"Initializing the network.")

    from . import network
    network.initialize(args.addr, args.http_addr)

    ## Early UID/GID Manipulation

    if do_uid and args.early:
        assume_uid(args.uid, args.gid, args.umask)

    ## NakedMud Compatibility

    if nakedsun.settings.get("nakedmud_compatible"):
        log.info("Loading NakedMud Compatibility Layer.")
        from . import nmcompat

    # Inject a series of modules into sys.modules for NakedMud compatibility.
    log.info(u"Injecting global modules for NakedMud compatibility.")
    for module in ("account", "auxiliary", "bitvectors", "char", "event",
                   "hooks", "mudsock", "mud", "mudsys", "obj", "room",
                   "storage"):
        inject(module, getattr(nakedsun, module))

    ## MUD Library Initialization

    log.info(u"Loading the MUD library.")

    # If it doesn't exist, die.
    if not os.path.exists("pymodules"):
        log.error(u"Cannot find pymodules in the MUD library.")
        log.shutdown()
        sys.exit(1)

    # Either load pymodules as a module or load its contents.
    if os.path.exists(os.path.join("pymodules", "__init__.py")):
        log.debug("Importing module: pymodules")
        import pymodules

    else:
        log.debug("pymodules is not a package. Entering directory.")
        path = os.path.abspath("pymodules")
        sys.path.insert(0, path)

        # Scan through.
        for fn in sorted(os.listdir("pymodules")):
            full = os.path.join(path, fn)

            # Skip hidden entries, non-.py files, and folders that aren't
            # python packages.
            if fn.startswith(".") or (os.path.isfile(full) and not
                    fn.endswith(".py")) or (os.path.isdir(full) and not
                    os.path.exists(os.path.join(full, "__init__.py"))):
                continue

            # If it's a file, trim off the end.
            if fn.endswith(".py"):
                fn = fn[:-3]

            # Log a message, and then load the module.
            log.debug("Importing module: %s" % fn)

            try:
                nakedsun.mudsys.pymodules[fn] = __import__(fn)
            except Exception:
                log.exception("An error occurred when attempting to import "
                              "Python module: %s (%s)" % (fn, full))
                log.shutdown()
                sys.exit(1)

    ## Copyover Recovery

    log.todo("Copyover Recovery.")

    ## Register Signals

    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_HUP)

    ## Late UID/GID Manipulation

    if do_uid and not args.early:
        assume_uid(args.uid, args.gid, args.umask)

    ## The Event Loop

    log.info(u"Entering the game loop.")
    log.line()

    begin_copyover = False

    try:
        pants.engine.start()
    except nakedsun.mudsys.SystemCopyover:
        begin_copyover = True
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print ''

    log.line()

    if begin_copyover:
        log.todo("Copyover.")

    ## Cleanup

    nakedsun.hooks.run("shutdown")

    log.info(u"Exiting normally.")
    log.shutdown()
    sys.exit(0)
