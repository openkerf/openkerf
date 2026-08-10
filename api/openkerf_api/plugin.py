"""
MeerK40t plugin entry point for the OpenKerf API.

Discovered automatically through the `meerk40t.extension` setuptools
entry-point group (see meerk40t/external_plugins.py), so this package changes
nothing in the MeerK40t repository itself.
"""

_server = None


def plugin(kernel, lifecycle=None):
    global _server

    if lifecycle == "register":
        _ = kernel.translation

        @kernel.console_option(
            "port", "p", type=int, default=8080, help=_("port to listen on")
        )
        @kernel.console_option(
            "bind",
            "b",
            type=str,
            default="127.0.0.1",
            help=_("address to bind to (0.0.0.0 exposes the API to the LAN)"),
        )
        @kernel.console_option(
            "frontend",
            "f",
            type=str,
            default=None,
            help=_("directory with the built frontend to serve at /"),
        )
        @kernel.console_option(
            "token",
            "t",
            type=str,
            default=None,
            help=_("token for write actions (generated when omitted)"),
        )
        @kernel.console_option(
            "quit",
            "q",
            type=bool,
            action="store_true",
            help=_("shut the running OpenKerf API down"),
        )
        @kernel.console_command(
            "openkerf", help=_("starts the OpenKerf read-only API (default port 8080)")
        )
        def openkerf_api(
            command,
            channel,
            _,
            port=8080,
            bind="127.0.0.1",
            frontend=None,
            token=None,
            quit=False,
            **kwargs,
        ):
            global _server

            if quit:
                if _server is None:
                    channel(_("OpenKerf API is not running."))
                    return
                _server.stop()
                _server = None
                channel(_("OpenKerf API stopped."))
                return

            if _server is not None and _server.is_running():
                channel(_("OpenKerf API already running."))
                return

            try:
                from .server import ApiServer
            except ImportError as e:
                channel(_("OpenKerf API needs fastapi and uvicorn: {error}").format(error=e))
                return

            server = ApiServer(
                kernel, port=port, bind=bind, frontend=frontend, token=token
            )
            try:
                server.start()
            except OSError as e:
                channel(_("Could not start on port {port}: {error}").format(port=port, error=e))
                return
            _server = server
            channel(
                _("OpenKerf API on http://{bind}:{port}/").format(bind=bind, port=port)
            )
            if server.local_only:
                channel(_("Write actions are open (localhost only)."))
            else:
                # The machine is now controllable from the network. Say so, and
                # say what the token is — it is the only thing standing in front.
                channel(
                    _("Reachable from the network. Token for write actions: {token}").format(
                        token=server.token
                    )
                )

    elif lifecycle == "shutdown":
        if _server is not None:
            _server.stop()
            _server = None
