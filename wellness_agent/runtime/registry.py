"""Engine Registry and dependency injection (RFC-002 Ch2).

The Engine Registry is the single source of truth for engine creation and
lifecycle management (RFC-002:574-582):

- every engine SHALL be registered exactly once; duplicate registration
  SHALL throw (RFC-002:658-677)
- the runtime SHALL obtain every engine through the registry (RFC-002:580)
- engines SHALL be singletons within a registry; request-specific state
  SHALL never live in engines (RFC-002:716-733)
- every interface SHALL support mock implementations for deterministic
  unit testing (RFC-002:864-881)
- the registry SHALL expose diagnostics: registered engines, version,
  health, initialization time, dependency graph (RFC-002:922-933)
- a failing engine SHALL prevent startup (RFC-002:936-947)

This registry is per-user scoped: each user's engines (memory, learning,
etc.) are stateful per user, so construction happens lazily on first use
through factories that resolve dependencies from the registry itself.
"""

import threading
from contextlib import contextmanager
from typing import Callable, Dict, Iterable, Tuple

from ..utils.storage import now_iso


class RegistrationError(ValueError):
    """Raised for duplicate or invalid registrations."""


class UnknownEngineError(KeyError):
    """Raised when an engine id was never registered."""


class CircularDependencyError(RegistrationError):
    """Raised when engine construction would recurse forever."""


class EngineRegistry:
    """Dependency injection container holding one instance per engine id.

    Engines are registered as factories (RFC-002:876: construction belongs
    to the container), built lazily on first `get`, and returned as
    singletons afterwards. Factories receive the registry itself, so they
    resolve dependencies through `registry.get(...)` — no engine ever
    instantiates another engine directly (RFC-002:1760-1770).
    """

    def __init__(self, user_id="default", version="1.0.0", environment="development"):
        self.user_id = user_id
        self.version = version
        self.environment = environment
        self._factories: Dict[str, Callable] = {}
        self._deps: Dict[str, Tuple[str, ...]] = {}
        self._instances: Dict[str, object] = {}
        self._init_times: Dict[str, str] = {}
        self._building = set()
        self._lock = threading.RLock()

    # ─── registration ────────────────────────────────────────────

    def register(self, engine_id, factory: Callable[["EngineRegistry"], object],
                 deps: Iterable[str] = ()) -> None:
        """Register an engine factory exactly once (RFC-002:658-677).

        Raises RegistrationError on duplicate registration or non-callable
        factories. `deps` documents the dependency edges for diagnostics.
        """
        if not isinstance(engine_id, str) or not engine_id:
            raise RegistrationError("engine id must be a non-empty string")
        if engine_id in self._factories:
            raise RegistrationError("duplicate registration: %s" % engine_id)
        if not callable(factory):
            raise RegistrationError("factory for '%s' is not callable" % engine_id)
        self._factories[engine_id] = factory
        self._deps[engine_id] = tuple(deps)

    def register_instance(self, engine_id, instance) -> None:
        """Register an already-built instance (eager singleton)."""
        self.register(engine_id, lambda registry: instance)
        self._instances[engine_id] = instance
        self._init_times[engine_id] = now_iso()

    # ─── resolution ──────────────────────────────────────────────

    def get(self, engine_id):
        """Resolve an engine by id; builds it lazily on first use.

        Raises UnknownEngineError for unregistered ids and
        RegistrationError when a declared dependency is missing.
        """
        if engine_id not in self._factories:
            raise UnknownEngineError("unknown engine: %s" % engine_id)
        with self._lock:
            if engine_id in self._instances:
                return self._instances[engine_id]
            if engine_id in self._building:
                raise CircularDependencyError(
                    "circular dependency involving: %s" % engine_id)
            self._building.add(engine_id)
            try:
                missing = [d for d in self._deps[engine_id]
                           if d not in self._factories]
                if missing:
                    raise RegistrationError(
                        "engine '%s' has missing dependencies: %s"
                        % (engine_id, ", ".join(missing)))
                instance = self._factories[engine_id](self)
                self._instances[engine_id] = instance
                self._init_times[engine_id] = now_iso()
            finally:
                self._building.discard(engine_id)
            return instance

    # ─── mock support (RFC-002:864-881) ──────────────────────────

    def replace(self, engine_id, instance) -> object:
        """Permanently replace an engine with a mock/stub instance."""
        if engine_id not in self._factories:
            raise UnknownEngineError("unknown engine: %s" % engine_id)
        with self._lock:
            self._instances[engine_id] = instance
            self._init_times[engine_id] = now_iso()
        return instance

    @contextmanager
    def mock(self, engine_id, instance):
        """Temporarily replace an engine; restores the previous state on exit."""
        had = engine_id in self._instances
        previous = self._instances.get(engine_id)
        self.replace(engine_id, instance)
        try:
            yield instance
        finally:
            with self._lock:
                if had:
                    self._instances[engine_id] = previous
                else:
                    self._instances.pop(engine_id, None)

    # ─── introspection ───────────────────────────────────────────

    def has(self, engine_id) -> bool:
        return engine_id in self._factories

    def ids(self):
        return sorted(self._factories)

    def initialized(self):
        return sorted(self._instances)

    def dependency_graph(self):
        return dict(self._deps)

    def __contains__(self, engine_id):
        return engine_id in self._factories

    # ─── health (RFC-002:1645-1656, 922-933) ─────────────────────

    def health_check(self, engine_id) -> bool:
        """Health of one engine; builds it if not yet constructed."""
        engine = self.get(engine_id)
        check = getattr(engine, "health_check", None)
        if callable(check):
            return bool(check())
        return True

    def health(self):
        """Health of every initialized engine (keeps laziness)."""
        return {engine_id: self.health_check(engine_id)
                for engine_id in self.initialized()}

    # ─── lifecycle (RFC-002:751-794) ─────────────────────────────

    def initialize_all(self) -> bool:
        """Construct every engine, run lifecycle hooks, verify health.

        Raises RuntimeError when an engine fails to initialize or fails its
        health check — startup SHALL NOT continue (RFC-002:936-947).
        """
        for engine_id in self.ids():
            engine = self.get(engine_id)
            initialize = getattr(engine, "initialize", None)
            if callable(initialize):
                initialize()
            if not self.health_check(engine_id):
                raise RuntimeError(
                    "engine failed health check during startup: %s" % engine_id)
        return True

    def dispose_all(self) -> None:
        """Run dispose hooks on every constructed engine and drop them."""
        for engine in list(self._instances.values()):
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                dispose()
        self._instances.clear()
        self._init_times.clear()

    # ─── diagnostics (RFC-002:922-933) ───────────────────────────

    def diagnostics(self) -> dict:
        """Registered engines, metadata, init times, graph, and health."""
        engines = []
        for engine_id in self.ids():
            instance = self._instances.get(engine_id)
            if instance is None:
                engines.append({
                    "id": engine_id,
                    "initialized": False,
                    "initialized_at": None,
                    "metadata": None,
                })
                continue
            meta = getattr(instance, "metadata", None)
            category = getattr(instance, "category", None)
            engines.append({
                "id": engine_id,
                "initialized": True,
                "initialized_at": self._init_times.get(engine_id),
                "metadata": {
                    "id": getattr(meta, "id", engine_id),
                    "name": getattr(meta, "name", type(instance).__name__),
                    "version": getattr(meta, "version", "1.0.0"),
                    "owner": getattr(meta, "owner", ""),
                    "category": getattr(category, "value", ""),
                },
            })
        return {
            "user_id": self.user_id,
            "version": self.version,
            "environment": self.environment,
            "registered": self.ids(),
            "initialized": self.initialized(),
            "engines": engines,
            "dependency_graph": self.dependency_graph(),
            "health": self.health(),
        }
