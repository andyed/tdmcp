"""Timeline transport — first-class endpoint that survives TDMCP_BRIDGE_ALLOW_EXEC=0.

Pure functions; reach TD globals via ``import td`` INSIDE each function so the
module imports cleanly off-TD (mirrors ``mcp/services/api_service.py``). Raise
``ValueError`` on bad input; the router turns it into the standard 400
``{ok:false,error:{message}}`` envelope.

Verbs (exhaustive, matches the Node-side tool schema):
  - ``play``  -> ``op('/').time.play = True``
  - ``pause`` -> ``op('/').time.play = False``
  - ``seek``  -> ``op('/').time.frame = clamp(frame, [start, end])``
  - ``cue``   -> rejected with a message directing callers to manage_cue
  - ``rate``  -> ``op('/').time.rate = float(rate)`` (frames per second)

Returns the §3.x timeline-state dict the Node tool already emits — same shape as
the legacy exec path, so the rewired tool can collapse both branches into one
result handler.
"""


def _root_time(td):
    """Return the project's authoritative root ``timeCOMP``."""
    root = td.op("/")
    if root is None or getattr(root, "time", None) is None:
        raise RuntimeError("TouchDesigner root timeline is unavailable")
    return root.time


def _state(td):
    """Snapshot the live timeline state in the documented shape."""
    timeline = _root_time(td)
    return {
        "play": bool(timeline.play),
        "frame": int(timeline.frame),
        "rate": float(timeline.rate),
        "startFrame": int(timeline.start),
        "endFrame": int(timeline.end),
        "fps": float(timeline.rate),
    }


def _play(td, _frame, _rate, _cue_name):
    _root_time(td).play = True


def _pause(td, _frame, _rate, _cue_name):
    _root_time(td).play = False


def _seek(td, frame, _rate, _cue_name):
    if frame is None:
        raise ValueError("seek requires `frame`.")
    timeline = _root_time(td)
    target = max(int(timeline.start), min(int(frame), int(timeline.end)))
    timeline.frame = target


def _cue(td, _frame, _rate, cue_name):
    if not cue_name:
        raise ValueError("cue requires `cueName`.")
    raise ValueError(
        "TouchDesigner's root timeline has no named-cue API; "
        "use the manage_cue tool to recall %r." % cue_name
    )


def _rate(td, _frame, rate, _cue_name):
    if rate is None:
        raise ValueError("rate requires `rate`.")
    _root_time(td).rate = float(rate)


_ACTIONS = {
    "play": _play,
    "pause": _pause,
    "seek": _seek,
    "cue": _cue,
    "rate": _rate,
}


def control(action, frame=None, rate=None, cue_name=None):
    """Drive the project timeline. Returns ``{action, ...state}``.

    Raises ``ValueError`` on missing/invalid args or an unknown cue, mirroring
    the exec script's cross-field validation. The router maps that to HTTP 400.
    """
    import td

    handler = _ACTIONS.get(action)
    if handler is None:
        raise ValueError("Unsupported transport action: %r" % action)
    handler(td, frame, rate, cue_name)

    state = _state(td)
    state["action"] = action
    return state
