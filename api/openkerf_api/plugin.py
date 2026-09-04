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

        # Without a rasteriser `op raster` throws its own children away while planning and
        # every raster operation comes out of the machine blank. The wxPython GUI registers
        # one; headless there is nothing. We fill that gap, and only that gap: if the wx
        # rasteriser is already there, it wins.
        from .rasterizer import register as register_rasterizer

        register_rasterizer(kernel)

        # Bridges have to survive a save and an open, and without these two lines they do
        # not. `core/svg_io.py:897` only `literal_eval`s an `mk*` attribute that is in this
        # registry; MeerK40t registers both of them in `main.py:258` — its own entry point,
        # which our stack never runs. Measured without them: the export writes
        # `mktablength="5160.23622047244"`, the reload hands it back as the *string*, and
        # `final_geometry()` then dies on `ufunc 'greater' did not contain a loop with
        # signature matching types (Float64DType, StrDType)` — so opening a saved project
        # with bridges in it broke the cut plan. With them the reload gives the float back
        # and the estimate matches the 19.3 s from before the save.
        for index, attribute in enumerate(("mktablength", "mktabpositions")):
            kernel.register(f"registered_mk_svg_parameters/tabs{index}", attribute)

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
            "library",
            "l",
            type=str,
            help=_("path to the library database (its own folder for testing)"),
        )
        @kernel.console_option(
            "operations",
            "o",
            type=str,
            help=_("path to the layer list (its own folder for testing)"),
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
            library=None,
            operations=None,
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
                kernel,
                port=port,
                bind=bind,
                frontend=frontend,
                token=token,
                # A database of its own is what a test needs: otherwise trial materials and
                # sheets run through the user's library.
                library_path=library,
                # And a layer list of its own, for the same reason and with a hole of its
                # own: the list is keyed to the kernel name, so every instance on this
                # computer shares one file with the app the user works in. A script that
                # makes layers — the handbook's pictures do — reads and writes that file
                # without saying so.
                operations_path=operations,
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
                # The machine is now controllable from the network. Only print the
                # token itself when the engine generated it — a token the caller
                # already knows (the `-t` option, as in a Docker deployment) has no
                # business ending up in a log a caller does not otherwise control.
                if token is None:
                    channel(
                        _(
                            "Reachable from the network. Token for write actions: {token}"
                        ).format(token=server.token)
                    )
                else:
                    channel(
                        _(
                            "Reachable from the network. Write actions need the token given with -t."
                        )
                    )

    elif lifecycle == "shutdown":
        if _server is not None:
            _server.stop()
            _server = None
