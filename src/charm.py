#!/usr/bin/env python3
# Copyright 2023 Canonical
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the Operator Framework:

https://discourse.charmhub.io/t/4208
"""

import logging
import re

import socket
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from cosl.coordinated_workers.worker import CONFIG_FILE, Worker
from ops.charm import CharmBase
from ops.main import main
from ops.pebble import Layer
from typing import Optional

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


@trace_charm(tracing_endpoint="_charm_tracing_endpoint", server_cert="_charm_tracing_cert")
class MimirWorkerK8SOperatorCharm(CharmBase):
    """A Juju Charmed Operator for Mimir."""

    _name = "mimir"
    _mimir_port = 8080

    def __init__(self, *args):
        super().__init__(*args)
        self.worker = Worker(
            charm=self,
            name="mimir",
            pebble_layer=self.pebble_layer,
            endpoints={"cluster": "mimir-cluster"},
            readiness_check_endpoint=self.readiness_check_endpoint,
        )
        self._charm_tracing_endpoint, self._charm_tracing_cert = self.worker.charm_tracing_config()

        self._container = self.model.unit.get_container(self._name)
        self.unit.set_ports(self._mimir_port)

        # === EVENT HANDLER REGISTRATION === #
        self.framework.observe(self.on.loki_pebble_ready, self._on_pebble_ready)  # pyright: ignore

    # === EVENT HANDLERS === #

    def _on_pebble_ready(self, _):
        self.unit.set_workload_version(
            self.version or ""  # pyright: ignore[reportOptionalMemberAccess]
        )

    # === PROPERTIES === #

    @property
    def version(self) -> Optional[str]:
        """Return Mimir workload version."""
        if not self._container.can_connect():
            return None

        version_output, _ = self._container.exec(["/bin/mimir", "-version"]).wait_output()
        # Output looks like this:
        # Mimir, version 2.4.0 (branch: HEAD, revision 32137ee)
        if result := re.search(r"[Vv]ersion:?\s*(\S+)", version_output):
            return result.group(1)
        return None

    # === UTILITY METHODS === #

    @staticmethod
    def readiness_check_endpoint(worker: Worker) -> str:
        """Endpoint for worker readiness checks."""
        scheme = "https" if worker.cluster.get_tls_data() else "http"
        return f"{scheme}://{socket.getfqdn()}:{MimirWorkerK8SOperatorCharm._mimir_port}/ready"

    def pebble_layer(self, worker: Worker) -> Layer:
        """Return a dictionary representing a Pebble layer."""
        targets = ",".join(sorted(worker.roles))

        return Layer(
            {
                "summary": "mimir worker layer",
                "description": "pebble config layer for mimir worker",
                "services": {
                    "mimir": {
                        "override": "replace",
                        "summary": "mimir worker daemon",
                        "command": f"/bin/mimir --config.file={CONFIG_FILE} -target {targets} -auth.multitenancy-enabled=false",
                        "startup": "enabled",
                    }
                },
            }
        )


if __name__ == "__main__":  # pragma: nocover
    main(MimirWorkerK8SOperatorCharm)
