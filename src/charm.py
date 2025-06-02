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
import os
import socket

import tenacity
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
from coordinated_workers.worker import CONFIG_FILE, Worker
from ops.charm import CharmBase
from ops.main import main
from ops.pebble import Layer

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


_LEGACY_WORKER_PORTS = [8080]


@trace_charm(
    tracing_endpoint="_charm_tracing_endpoint",
    server_cert="_charm_tracing_cert",
    extra_types=[Worker],
)
class MimirWorkerK8SOperatorCharm(CharmBase):
    """A Juju Charmed Operator for Mimir."""

    container_name = "mimir"
    _mimir_port = 8080

    def __init__(self, *args):  # type: ignore
        super().__init__(*args)
        # Override waiting times from the generic worker
        Worker.SERVICE_START_RETRY_STOP = tenacity.stop_after_delay(60)
        Worker.SERVICE_START_RETRY_WAIT = tenacity.wait_fixed(5)

        self.worker = Worker(
            charm=self,
            # name of the container the worker is operating on AND of the executable
            name=self.container_name,
            pebble_layer=self.pebble_layer,
            endpoints={"cluster": "mimir-cluster"},
            readiness_check_endpoint=self.readiness_check_endpoint,
            resources_requests=lambda _: {"cpu": "50m", "memory": "200Mi"},
            # container we want to resource-patch
            container_name=self.container_name,
        )
        self._charm_tracing_endpoint, self._charm_tracing_cert = self.worker.charm_tracing_config()

        self._container = self.model.unit.get_container(self.container_name)

        # if the worker has received some ports from the coordinator,
        # it's in charge of ensuring they're opened.
        if not self.worker.cluster.get_worker_ports():
            # legacy behaviour fallback: older interface versions didn't tell us which
            # ports we should be opening, so we opened all of them.
            # This can happen when talking to an old coordinator revision, or
            # if the coordinator hasn't published its data yet.
            logger.info(
                "Cluster interface hasn't published a list of worker ports (yet?). "
                "If this issue persists after the cluster has settled, you should "
                "upgrade the coordinator to a newer revision. Falling back now to "
                "legacy behaviour and opening all ports."
            )
            self.unit.set_ports(*_LEGACY_WORKER_PORTS)

    # === UTILITY METHODS === #

    @staticmethod
    def readiness_check_endpoint(worker: Worker) -> str:
        """Endpoint for worker readiness checks."""
        scheme = "https" if worker.cluster.get_tls_data() else "http"
        return f"{scheme}://{socket.getfqdn()}:{MimirWorkerK8SOperatorCharm._mimir_port}/ready"

    def pebble_layer(self, worker: Worker) -> Layer:
        """Return a dictionary representing a Pebble layer."""
        targets = ",".join(sorted(worker.roles))

        env = {}
        # add proxy variables
        env.update(
            {
                "https_proxy": os.environ.get("JUJU_CHARM_HTTPS_PROXY", ""),
                "http_proxy": os.environ.get("JUJU_CHARM_HTTP_PROXY", ""),
                "no_proxy": os.environ.get("JUJU_CHARM_NO_PROXY", ""),
            }
        )
        # configure workload traces
        if tempo_endpoint := worker.cluster.get_workload_tracing_receivers().get(
            "jaeger_thrift_http", None
        ):
            topology = worker.cluster.juju_topology
            env.update(
                {
                    "JAEGER_ENDPOINT": (f"{tempo_endpoint}/api/traces?format=jaeger.thrift"),
                    "JAEGER_SAMPLER_PARAM": "1",
                    "JAEGER_SAMPLER_TYPE": "const",
                    "JAEGER_TAGS": f"juju_application={topology.application},juju_model={topology.model}"
                    + f",juju_model_uuid={topology.model_uuid},juju_unit={topology.unit},juju_charm={topology.charm_name}",
                },
            )
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
                        "environment": env,
                    }
                },
            }
        )


if __name__ == "__main__":  # pragma: nocover
    main(MimirWorkerK8SOperatorCharm)
