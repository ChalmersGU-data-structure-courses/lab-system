#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Client for RPCC servers.

To create a client proxy, instantiate the RPCCProxy class.

   rpcc = RPCC("https://some.where/", api=1, attrdicts=True)

Functions on the server appear as methods on the proxy object. 

  print(rpcc.server_list_functions())

Documentation is printed by calling a doc method on the function 
attribute:

  rpcc.server_list_functions.doc()

A list of functions is printed by calling that method on the proxy 
object:

  rpcc.doc()

The proxy object handles sessions automagically. When a function is called
that expects a session argument, and where no such argument is given,
proxy.session_start() is called, and the result kept.

A convenience method rpcc.login([<username>[, <password>]]) calls
session_start() and then session_auth_login(). Username and password are
filled in using getpass.

The proxy uses JSON when communicating with the server.

If the Python kerberos module is installed, the client will perform
a GSSAPI authentication to the server by implicitly adding the 'token'
argument to the session_auth_kerberos call.

If the expand_data option is given as True when instantiating the proxy,
the proxy will insert and expand attributes not returned by the server
on _dig calls such that non-returned simple values will be returned the value None,
and non-returned lists will be returned as empty lists.

If the rwattrdicts option is set to True, results are returned as writable
Attrdicts. which in some cases makes the application code easier to read.

If the trace_json option is given as True, the proxy will print the generated JSON
sent to the server and the resulting answer from the server.
This might be an aid for developers working against the server
who cannot use rpcc_client in the final product.
Note that the JSON data might expose sensitive information such as passwords and session tokens.

If the leave_session_at_exit is set to True, the session with the RPC server will stopped
whenever the program exits in a controlled manner.

If the await_revision_locks option is given as True, all _dig and _fetch calls will first check
if the server has an active revision lock. In that case, the call will be delayed in periods of
10 seconds until the revision lock is gone or optionally if the revision lock has changed.
If a single revision lock causes a delay of more than 5 minutes, the call will fail and the application
exit with a failure message.
This option is only necessary for applications that rely on that its own changes need to be visible
to itself in order to work correctly. Typically for integrations that run repeatedly.

The configure_revision_check function may be used to configure the details of this functionality


person_dig({"cid": {"name": "viktor"}}, {"nid": True, "assignments": {"nid": True, "role": {"public_sv": True,
"public_en": True}, "time_active": True}})


person_dig({"cid.name": "viktor"}, "nid,assignments(nid, role(public_sv, public_en), time_active)")

"""

import atexit
import datetime
import getpass
import json
import logging
import os
import socket
import sys
import time
import typing
import requests

from typing import *

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_sentinel = object()


class ExtendedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()[:19]
        elif isinstance(o, datetime.date):
            return o.isoformat()
        elif isinstance(o, ClientCreate) and hasattr(o, "result") and hasattr(o.result, "nid"):
            return {"nid": o.result.nid}
        else:
            super().default(o)


def parse_object(o):
    if "__dt" in o:
        return datetime.datetime.strptime(o["__dt"], "%Y-%m-%dT%H:%M:%S")
    elif "__d" in o:
        return datetime.datetime.strptime(o["__d"], "%Y-%m-%d").date()
    else:
        return AttrDict(o)


class AttrDict(dict):
    """A dictionary where keys can also be accessed as attributes."""

    _sentinel = object()

    def __init__(self, rawdict=None):
        super().__init__()
        if not rawdict:
            return

        for (key, value) in list(rawdict.items()):
            self[key] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        raise ValueError("Cannot set attributes on AttrDict:s")


# NOTE! This class is intentionally NOT USED. It is only a way of type hinting the dicts returned inside the
# RPCCError class.
class RPCCErrorData(AttrDict):
    name = None  # type: str
    namelist = None  # type: typing.List[str]
    value = None  # type: typing.Any
    desc = None  # type: str
    id = None  # type: str
    traceback = None  # type: typing.List[str]

    def __init__(self):
        raise NotImplementedError("This class is only used to give type hints to the RPCCError class!")


class RPCCError(Exception):
    def __init__(self, error_list):
        self.error_list = error_list  # type: typing.List[RPCCErrorData]

    def has_error_named(self, exname: str = None, partial: str = None) -> bool:
        if partial:
            return any([(partial in e) for e in self.all_error_names()])
        else:
            return any([(exname == e) for e in self.all_error_names()])

    def all_error_names(self):
        return [e["name"] for e in self.error_list]

    def all_errors_named(self, exname: str = None, partial: str = None) -> typing.Set[str]:
        if partial:
            return {partial in e["name"] for e in self.error_list}
        else:
            return {exname == e["name"] for e in self.error_list}

    def __str__(self):
        slist = []
        for err in self.error_list:
            s = "{name=" + err.name
            if err.value is not None:
                s += ' value="%s"' % (err.value,)
            if err.traceback:
                s += " traceback=%s" % (err.traceback,)
            s += ' desc="%s"}' % (err.desc,)
            slist.append(s)
        return "[" + ",\n".join(slist) + "]"


class AssertRPCCError:
    def __init__(self, error_substring: str):
        self.error = error_substring

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        assert exc_type is not None, "expected an error but none was raised"
        assert exc_type == RPCCError, "expected an RPCCError but got %s" % (exc_val,)
        assert len(exc_val.args[0]) == 1, "expected a single RPCCError but got multiple"
        assert self.error in exc_val.args[0][0].name, "expected error like '%s' but got %s" % (
            self.error,
            exc_val.args[0][0].name,
        )
        return True


ClientDolistType = typing.TypeVar("ClientDolistType", bound="ClientDolist")


class RPCC(object):
    class FunctionProxy(object):
        def __init__(self, proxy, funname):
            self.proxy = proxy
            self.funname = funname

        def doc(self):
            print(self.proxy.server_documentation(self.funname))

        def __call__(self, *args, **kwargs):
            return self.proxy._call(self.funname, args, kwargs)

    def __init__(
        self,
        url,
        api_version: int = 0,
        server=None,
        debug: Optional[bool] = None,
        default_create_fetch={"nid": True},
        session_id=None,
        logger=None,
        options: dict = None,
    ):
        self._fundefs = {}
        self._debug = debug
        self._session_id = session_id
        self._envelope = {}
        self._default_create_fetch = default_create_fetch
        self._pending_dolist: "Optional[ClientDolist]" = None
        self._options = options or {}
        self._options.update({"complex_dates": True})
        self._time = None
        self._auth = None
        self._api = api_version
        self._logger = logger
        self._next_session_renew = None
        if url:
            self._url = url + ("/" if url[-1] != "/" else "") + "json?v%s" % (api_version,)
            self._server = None
        else:
            self._url = None
            self._server = server

        if session_id:
            self._session_id = session_id
            try:
                x = self.session_info()
            except RPCCError as e:
                if any([x.name == "LookupError::NoSuchSession" for x in e.error_list]):
                    self._session_id = None

        if self._session_id is None:
            self.session_start()

    def __getattr__(self, name):
        if name[0] != "_":
            return self.FunctionProxy(self, name)

    def _call(self, fun, args, kwargs=None):
        if self._next_session_renew and time.time() > self._next_session_renew and self._session_id:
            self._next_session_renew = None
            self._call("session_renew", [])

        calldict = {"function": fun, "params": list(args), "session": self._session_id}
        if kwargs:
            calldict["named_params"] = kwargs
        if self._options:
            calldict["options"] = self._options

        call = ExtendedJSONEncoder().encode(calldict)
        start_time = time.time()

        if self._logger:
            self._logger.debug(f"CALL {fun}")
        if self._url:
            response = requests.post(self._url, data=call, verify=False, headers={"Content-Type": "application/json"})
            retstr = response.text
        elif self._server:
            import rpcc

            req = rpcc.http.HTTPRequest(self._server, "internal")
            req.full_path = "/json"
            req.query_string = "?v0"
            req.remote_address = self._default_remote_address
            req.remote_port = "internal"
            req.method = "POST"
            req.content_type = "application/json"
            req.content_charset = "utf-8"
            req.data = call
            (req.protocol, _, _) = self._server.find_protocol_handler("POST", "json")
            resp = req.protocol.request(req)
            retstr = resp.data
        else:
            raise RuntimeError()

        self._time = time.time() - start_time
        if self._logger:
            self._logger.debug(f"RETURN {len(retstr)} characters in {self._time:.1f} seconds")
        ret = json.loads(retstr, object_hook=parse_object)
        self._envelope = AttrDict({k: v for (k, v) in ret.items() if k not in {"return", "errors"}})
        self._meta = ret.get("meta", {})
        self._session_id = self._envelope.get("session", None)
        self._auth = self._envelope.get("authuser", None)

        if fun == "session_start" or fun == "session_renew":
            self._next_session_renew = time.time() + 3600

        if "errors" not in ret:
            return ret["result"]

        err = RPCCError(ret["errors"])
        if err.has_error_named("RuntimeError::SessionRequired"):
            self._call("session_start", [])
            return self._call(fun, args, kwargs)

        raise err

    def get_last_stable_coordinate(self):
        return self._meta.last_stable_coordinate

    def login(self, user=None, password=None):
        if user is None:
            user = getpass.getuser()
        if password is None:
            password = getpass.getpass("Password for %s@%s: " % (user, self._url))
        return self.session_auth_login(user, password)

    def get_dolist(self, debug=False, trace_json=None) -> ClientDolistType:
        if self._pending_dolist is not None and self._pending_dolist.has_any_actions():
            raise RuntimeError("You have already created a do list, but have not yet called .run() on it.")
        dolist = ClientDolist(self, debug=self._debug_do or debug, trace_json=trace_json)
        self._pending_dolist = dolist
        return dolist

    def get_created_coordinate(self) -> dict:
        return {
            "revision": self._envelope.meta["created_revision"],
            "timestamp": self._envelope.meta["created_start_time"],
        }


class RPCCObjectReference:
    def rpcc_dolist_lookup(self):
        raise NotImplementedError()


class DolistAction:
    def output(self):
        raise NotImplementedError()


class _Changeable(DolistAction):
    def __init__(self):
        self.changes = []
        self.fetch = None

    def set_fetch(self, fetch=None, **kwargs):
        if (fetch and kwargs) or (not fetch and not kwargs):
            raise ValueError("Fetch or kwargs please")
        self.fetch = fetch or kwargs
        return self

    def set(self, attr: str = None, _value=None, **multiple) -> "_Changeable":
        if attr:
            if _value is not None:
                return self.add_change(attr, "set", _value)
            else:
                return self.add_change(attr, "clear", True)
        for (k, v) in multiple.items():
            if v is not None:
                self.add_change(k, "set", v)
            else:
                self.add_change(k, "clear", True)
        return self

    def clear(self, *attrs: str):
        for attr in attrs:
            self.add_change(attr, "clear", True)
        return self

    def add(self, attr: str, value) -> "_Changeable":
        return self.add_change(attr, "add", value)

    def remove(self, attr: str = None, _value=None, **multiple) -> "_Changeable":
        return self.del_(attr, _value, **multiple)

    def del_(self, attr: str = None, _value=None, **multiple) -> "_Changeable":
        if attr:
            return self.add_change(attr, "del", _value)
        for (k, v) in multiple.items():
            self.add_change(k, "del", v)

    def add_change(self, attr: str, op: typing.Union[str, dict], value: typing.Any = None) -> "_Changeable":
        if hasattr(value, "rpcc_dolist_lookup"):
            value = value.rpcc_dolist_lookup()
        elif isinstance(value, list) or isinstance(value, set) or isinstance(value, tuple):
            value = [(v.rpcc_dolist_lookup() if hasattr(v, "rpcc_dolist_lookup") else v) for v in value]
        if isinstance(op, dict):
            self.changes.append({attr: op})
        else:
            self.changes.append({attr: {op: value}})
        return self

    def add_changes(self, *changes: typing.Union[typing.Tuple[str, str, typing.Any], typing.Tuple[str, dict]]):
        for ch in changes:
            self.add_change(*ch)

    def has_any_changes(self):
        return len(self.changes) > 0

    def stop_now(self):
        """Set default active attribute to stop now = .add_change('time_active', 'stop_now', True)"""
        self.add_change("time_active", "stop_now", True)

    def prettyprint_changes(self):
        for c in self.changes:
            print("    ", "".join([(x if ord(x) >= 32 else "¿") for x in str(c)]))

    def changes_log_string(self):
        ch = []
        for c in self.changes:
            ((attr, change),) = c.items()
            ((op, value),) = change.items()
            if op == "set":
                ch.append(f"{attr}={value}")
            elif op == "add":
                ch.append(f"{attr}+={value}")
            elif op == "clear":
                ch.append(f"!{attr}")
            elif op == "del":
                ch.append(f"{attr}-={value}")
            else:
                ch.append("".join([(x if ord(x) >= 32 else "¿") for x in str(c)]))
        return " // ".join(ch)


class ClientUpdate(_Changeable):
    def __init__(self, dolist: "ClientDolist", typ: str, lookup: typing.Dict[str, typing.Any]):
        super().__init__()
        self.dolist = dolist
        self.typ = typ
        self.lookup = lookup
        self.result = None

    def output(self):
        if len(self.changes) == 0:
            return None
        upd = {self.typ: self.lookup, "changes": self.changes}
        if self.fetch:
            upd["fetch"] = self.fetch
        o = {"update": upd}

        return o

    def set_result(self, res):
        self.result = res[self.typ]

    def run(self, *args, **kwargs):
        self.dolist.run(*args, **kwargs)

    def log_string(self):
        return f"update {self.typ} {self.lookup}: {self.changes_log_string()}"

    def prettyprint(self):
        if len(self.changes) == 0:
            return

        print("  Update '%s' %s" % (self.typ, self.lookup))
        self.prettyprint_changes()
        if self.fetch:
            print("    Fetch: %s" % (self.fetch,))


class ClientCreate(_Changeable, RPCCObjectReference):
    def __init__(self, dolist: "ClientDolist", typ: str, reference: str, **setops):
        super().__init__()
        self.dolist = dolist
        self.typ = typ
        self.reference = reference
        self.changes = []
        self.fetch = self.dolist.client._default_create_fetch
        self.result = None
        self.set(**setops)

    def rpcc_dolist_lookup(self):
        if self.result is not None:
            if "nid" in self.result:
                return {"nid": self.result.nid}
            else:
                raise ValueError(
                    "In order to use a create object as a value in another dolist than it was created, "
                    "you must ensure that it has .set_fetch(nid=True) (or that the RPCC instance has a"
                    "default_create_fetch={'nid': True}"
                )
        return {"reference": self.reference}

    def set_result(self, res):
        self.result = res[self.typ]

    def output(self):
        o = {self.typ: self.reference}
        if self.changes:
            o["changes"] = self.changes
        if self.fetch:
            o["fetch"] = self.fetch
        return {"create": o}

    def run(self, *args, **kwargs):
        self.dolist.run(*args, **kwargs)

    def log_string(self):
        return f"create {self.typ}: {self.changes_log_string()}"

    def prettyprint(self):
        print("  Create '%s'" % (self.typ,))
        self.prettyprint_changes()
        if self.fetch:
            print("    Fetch: %s" % (self.fetch,))


class ClientApply(DolistAction):
    def __init__(self, dolist: "ClientDolist"):
        self.dolist = dolist

    def output(self):
        return {"apply": True}

    def run(self, *args, **kwargs):
        self.dolist.run(*args, **kwargs)

    def prettyprint(self):
        print("  Apply.")


class ClientFetch(DolistAction):
    def __init__(self, dolist: "ClientDolist", model: str, lookup: dict = None, template: dict = None):
        self.dolist = dolist
        self.model = model
        self.lookup = lookup
        self.template = template
        self.result = None

    def lookup(self, **kwargs) -> "ClientFetch":
        self.lookup = kwargs.copy()
        return self

    def template(self, **kwargs) -> "ClientFetch":
        self.template = kwargs.copy()
        return self

    def output(self):
        return {"fetch": {self.model: self.lookup, "template": self.template}}

    def run(self, *args, **kwargs):
        self.dolist.run(*args, **kwargs)

    def prettyprint(self):
        print("  Fetch '%s': " % (self.model,))
        print("    Lookup: %s" % (self.lookup,))
        print("    Template: %s" % (self.template,))


class ClientRedact(DolistAction):
    def __init__(self, dolist: "ClientDolist", model: str, lookup: dict = None):
        self.dolist = dolist
        self.model = model
        self.lookup = lookup

    def output(self):
        return {"redact": {self.model: self.lookup}}

    def log_string(self):
        return f"redact {self.model} {self.lookup}"

    def prettyprint(self):
        print("  Redact '%s': " % (self.model,))
        print("    Lookup: %s" % (self.lookup,))


class ClientDolist:
    """A ClientDolist instance is a client-side representation of a list of intended changes which will be performed
    atomically on the server. A ClientDolist is packed into a single RPC:do() call to the server. Either all changes
    succeed or none do.

    Actions to perform when the dolist is run (i.e. when the do() call is made to the server) are added using
    .add_create(), .add_update(), .add_redact() and .add_apply(). Any number of callbacks can also be added
    using .add_run_callback() - all will be called in order when the dolist is run.
    """

    def __init__(self, client: RPCC = None, debug=False, trace_json=False):
        self.client = client
        self.actions: List[DolistAction] = []
        self.refid = 0
        self.lastref = None
        self.has_run = False
        self.debug = debug
        self.trace_json = trace_json
        self.total_actions = 0
        self.run_return = []
        self.run_callbacks: List[Tuple[Callable, Tuple, Dict]] = []

    def __enter__(self) -> "ClientDolist":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            if self.has_any_actions() and not self.has_run:
                self.run()
        else:
            self.client._pending_dolist = None

    def add_run_callback(self, clbl: Callable, /, *args, **kwargs):
        self.run_callbacks.append((clbl, args, kwargs))

    def action_count(self):
        return len(self.actions)

    def has_any_actions(self):
        return len(self.actions) > 0

    def add_update(
        self,
        typ: typing.Union[str, RPCCObjectReference],
        obj: typing.Union[typing.Dict, RPCCObjectReference] = None,
        **lookup,
    ) -> ClientUpdate:
        """Add an update for an instance of model <typ>, identified either by <obj> or by a lookup. Returns an object
        which represents the update, on which you call methods to add specific operations.

        Example:
            x_up = dolist.update(x, {"nid": 1234512345})
            x_up.set("foo", "bar")
            x_up.add("email", "additional@email.com")
        """
        if isinstance(typ, ClientCreate):
            obj = typ
            typ = typ.typ
        if not isinstance(typ, str):
            raise ValueError(f"Expected a model name as first argument - got {typ}")
        if len(lookup) > 1:
            raise ValueError("The lookup argument to .add_update() may only be one item long.")

        if hasattr(obj, "result") and hasattr(obj.result, "nid"):
            lookup = {"nid": obj.result.nid}
        elif hasattr(obj, "rpcc_dolist_lookup"):
            if len(lookup) > 0:
                ((key, value),) = lookup.items()
                raise ValueError("Did you mean .add_update(%s, %s).set('%s', %s)?" % (typ, obj, key, value))
            lookup = obj.rpcc_dolist_lookup()
        elif isinstance(obj, dict):
            if len(lookup) > 0:
                ((key, value),) = lookup.items()
                raise ValueError("Did you mean .add_update(%s, %s).set('%s', %s)?" % (typ, obj, key, value))
            lookup = obj
        elif obj is not None:
            raise ValueError("What is obj? Baby don't hurt me, don't hurt me, no more...")
        upd = ClientUpdate(self, typ, lookup)
        self._add(upd)
        # self.what.append(upd)
        return upd

    def add_create(self, typ: str, reference: str = None, **setops) -> ClientCreate:
        """Add a creation of an instance of model <typ>, optionally identified by <reference>, optionally with
        initial values for one or many attributes.

        Returns an object with methods for adding specific changes to the newly created instance (.add, .set and so on).
        Any extra arguments to this method are added as .set():
            dolist.add_create("x", foo="bar", bar=7)
        is identical to
            x = dolist.add_create("x")
            x.set("foo", "bar")
            x.set("bar", 7)
        """
        if reference is None:
            reference = "__client_ref__%d__" % (self.refid,)
            self.lastref = reference
            self.refid += 1
        cr = ClientCreate(self, typ, reference, **setops)
        self._add(cr)
        return cr

    def add_apply(self):
        self._add(ClientApply(self))

    def add_redact(self, typ: str, obj: typing.Union[typing.Dict, RPCCObjectReference] = None, **lookup):
        """Add a redact for an instance of model <typ>, identified either by <obj> or by a lookup."""
        if len(lookup) > 1:
            raise ValueError("The lookup argument to .add_update may only be one item long.")

        if hasattr(obj, "result") and hasattr(obj.result, "nid"):
            lookup = {"nid": obj.result.nid}
        elif hasattr(obj, "rpcc_dolist_lookup"):
            if len(lookup) > 0:
                ((key, value),) = lookup.items()
                raise ValueError("Did you mean .add_update(%s, %s).set('%s', %s)?" % (typ, obj, key, value))
            lookup = obj.rpcc_dolist_lookup()
        elif isinstance(obj, dict):
            if len(lookup) > 0:
                ((key, value),) = lookup.items()
                raise ValueError("Did you mean .add_update(%s, %s).set('%s', %s)?" % (typ, obj, key, value))
            lookup = obj
        elif obj is not None:
            raise ValueError("What is obj? Baby don't hurt me, don't hurt me, no more...")

        # self.what.append(ClientRedact(self, typ, lookup))
        self._add(ClientRedact(self, typ, lookup))

    def _add(self, action: DolistAction):
        # if self.partition_size and len(self.what) >= self.partition_size:
        #     # if self.section_level == 0:
        #     self.run(if_more_than=1)
        self.actions.append(action)

    def run(self, client: RPCC = None, min_dolist_size: int = None):
        """Make this ClientDolist into a do() call and execute it, either via a client given to the
        constructor or via a client given in this call.

        If if_more_than is not given, this call represents a final use of the ClientDolist - all actions
        will be sent to the server and no actions may be added to this ClientDolist afterwards.

        If if_more_than is given, and less than if_more_than actions have been added to the ClientDolist,
        nothing will be done. If at least if_more_than actions have been added, the list will be run, and
        then reset.

        If if_more_than is not given, it is an error to add more actions after a call to .run().
        """
        if self.client is None:
            if client is None:
                raise ValueError("An RPCC client needs to be specified either at initialize or at call time")
            cli = client
        else:
            cli = self.client
            self.client._pending_dolist = None

        if self.client is not None and self.has_run:
            # Catch the common error when a dolist is run, then added to, then run again, when what was intended
            # was to add to a new dolist. Only meaningful on bound dolists - unbound can intentionally be run
            # for multiple clients.
            raise RuntimeError("This dolist has already run")

        if min_dolist_size is not None and len(self.actions) < min_dolist_size:
            return None

        do_call_items = []
        for w in self.actions:
            output = w.output()
            if output:
                do_call_items.append(output)

        if self.trace_json and do_call_items:
            print("JSON:")
            print(json.dumps(do_call_items, sort_keys=True, indent=2))

        if self.debug and do_call_items:
            self.prettyprint()

        self.total_actions += len(do_call_items)

        # Make the call (if anything is to be done).
        if do_call_items:
            ret = cli.do(do_call_items)
        else:
            ret = []

        # Map requested response data from the call agains the actions which requested it.
        retidx = 0
        for w in self.actions:
            if isinstance(w, ClientUpdate) or isinstance(w, ClientCreate):
                if w.fetch is not None and ret:
                    w.set_result(ret[retidx])
                    retidx += 1
            if isinstance(w, ClientFetch) and ret:
                w.result = ret[retidx]
                retidx += 1

        for (clbl, args, kwargs) in self.run_callbacks:
            clbl(*args, **kwargs)

        if min_dolist_size is not None:
            # If the user gave a conditional, they expect to continue using this list.
            self.actions = []
            self.run_callbacks = []
        else:
            # If the user didn't give a conditional
            self.has_run = True

        self.run_return.extend(ret)
        # self.section_level = 0
        return ret

    def reset(self):
        self.has_run = False
        self.actions = []
        self.run_callbacks = []

    def log_strings(self) -> Iterable[str]:
        if len(self.actions) == 0 or len(getattr(self.actions[0], "changes", [])) == 0:
            return []
        return ["dolist"] + ["  " + w.log_string() for w in self.actions]

    def prettyprint(self):
        print("Dolist of %d items" % (len(self.actions),))
        for w in self.actions:
            w.prettyprint()

    def total_action_count(self):
        return self.total_actions


def tmpl(*keys):
    """Helper to make a more readable template argument to dig functions.

    tmpl("a.b", "b", "c.d.e", "c.d.f") will expand to
        {"a": {"b": True}, "b": True, "c": {"d": {"e": True, "f": True}}}

    """
    out = {}
    for key in keys:
        path = key.split(".")
        build = out
        for component in path[:-1]:
            build = build.setdefault(component, dict())
        build[path[-1]] = True
    return out


def out(dct, pfx=""):
    """Helper to pretty-print dig results."""
    for k in sorted(dct.keys()):
        if isinstance(dct[k], list):
            for (i, v) in enumerate(dct[k]):
                out(v, "%s.%s[%d]" % (pfx, k, i))
        elif isinstance(dct[k], dict):
            out(dct[k], pfx + "." + k)
        else:
            print("%s.%s: %s" % (pfx, k, str(dct[k])))


def srch(dic):
    """Helper to make a more readable search argument to dig functions.

    srch({"a.b": 12, "b": 13, "c.d.e": "foo", "c.d.f": "bar"}) will expand to
        {"a": {"b": 12}, "b": 13, "c": {"d": {"e": "foo", "f": "bar"}}}
    """
    out = {}
    for key, value in dic.items():
        path = key.split(".")
        add_at = out
        for component in path[:-1]:
            add_at = add_at.setdefault(component, dict())
        add_at[path[-1]] = value
    return out
