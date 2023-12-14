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
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from charms.mimir_coordinator_k8s.v0.mimir_cluster import (
    ConfigReceivedEvent,
    MimirClusterRequirer,
    MimirRole,
)
from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
)
from lightkube.models.core_v1 import ServicePort
from ops import pebble
from ops.charm import CharmBase, CollectStatusEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import PathError, ProtocolError

MIMIR_CONFIG = "/etc/mimir/mimir-config.yaml"
MIMIR_DIR = "/mimir"

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class MimirWorkerK8SOperatorCharm(CharmBase):
    """A Juju Charmed Operator for Mimir."""

    _name = "mimir"
    _instance_addr = "127.0.0.1"

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)
        self._root_data_dir = Path(self.meta.containers["mimir"].mounts["data"].location)

        self.topology = JujuTopology.from_charm(self)
        self.mimir_cluster = MimirClusterRequirer(self)

        self.service_path = KubernetesServicePatch(
            self, [ServicePort(8080, name=self.app.name)]  # Same API endpoint for all components
        )

        self.framework.observe(
            self.on.mimir_pebble_ready, self._on_pebble_ready  # pyright: ignore
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(
            self.mimir_cluster.on.config_received, self._on_mimir_config_received
        )
        self.framework.observe(self.mimir_cluster.on.created, self._on_mimir_cluster_created)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _on_mimir_cluster_created(self, _):
        self._update_mimir_cluster()

    def _update_mimir_cluster(self):
        """Share via mimir-cluster all information we need to publish."""
        self.mimir_cluster.publish_unit_address(socket.getfqdn())
        if self.unit.is_leader() and self._mimir_roles:
            logger.info(f"publishing roles: {self._mimir_roles}")
            self.mimir_cluster.publish_app_roles(self._mimir_roles)

    def _on_mimir_config_received(self, _e: ConfigReceivedEvent):
        self._update_config()

    def _on_upgrade_charm(self, _):
        self._update_mimir_cluster()

    def _on_config_changed(self, _):
        # if the user has changed the roles, we might need to let the coordinator know
        self._update_mimir_cluster()

        # if we have a config, we can start mimir
        if self.mimir_cluster.get_mimir_config():
            # determine if a workload restart is necessary
            self._update_config()

    def _update_config(self):
        """Update the mimir config and restart the workload if necessary."""
        restart = any(
            [
                self._update_mimir_config(),
                self._set_pebble_layer(),
            ]
        )

        if restart:
            self.restart()

    def _on_pebble_ready(self, event):
        self.unit.set_workload_version(self._mimir_version or "")
        self._update_config()

    def _set_pebble_layer(self) -> bool:
        """Set Pebble layer.

        Returns: True if Pebble layer was added, otherwise False.
        """
        if not self._container.can_connect():
            return False
        if not self._mimir_roles:
            return False

        current_layer = self._container.get_plan()
        new_layer = self._pebble_layer

        if (
            "services" not in current_layer.to_dict()
            or current_layer.services != new_layer["services"]
        ):
            self._container.add_layer(self._name, new_layer, combine=True)  # pyright: ignore
            return True

        return False

    @property
    def _pebble_layer(self):
        """Return a dictionary representing a Pebble layer."""
        targets = ",".join(sorted(self._mimir_roles))

        return {
            "summary": "mimir worker layer",
            "description": "pebble config layer for mimir worker",
            "services": {
                "mimir": {
                    "override": "replace",
                    "summary": "mimir worker daemon",
                    "command": f"/bin/mimir --config.file={MIMIR_CONFIG} -target {targets}",
                    "startup": "enabled",
                }
            },
        }

    @property
    def _mimir_roles(self) -> List[MimirRole]:
        """Return a set of the roles this Mimir worker should take on."""
        roles: List[MimirRole] = [role for role in MimirRole if self.config[role] is True]
        return roles

    @property
    def _mimir_version(self) -> Optional[str]:
        if not self._container.can_connect():
            return None

        version_output, _ = self._container.exec(["/bin/mimir", "-version"]).wait_output()
        # Output looks like this:
        # Mimir, version 2.4.0 (branch: HEAD, revision 32137ee)
        if result := re.search(r"[Vv]ersion:?\s*(\S+)", version_output):
            return result.group(1)
        return None

    def _update_mimir_config(self) -> bool:
        """Set Mimir config.

        Returns: True if config has changed, otherwise False.
        Raises: BlockedStatusError exception if PebbleError, ProtocolError, PathError exceptions
            are raised by container.remove_path
        """
        mimir_config = self.mimir_cluster.get_mimir_config()
        if not mimir_config:
            logger.warning("cannot update mimir config: coordinator hasn't published one yet.")
            return False

        # Data published by the coordinator won't have the actual common root data directory used by workers
        # Update the configuration with data directory paths using the _set_data_dirs method
        config = self._set_data_dirs(mimir_config)

        if self._running_mimir_config() != config:
            config_as_yaml = yaml.safe_dump(config)
            self._container.push(MIMIR_CONFIG, config_as_yaml, make_dirs=True)
            logger.info("Pushed new Mimir configuration")
            return True

        return False

    def _set_data_dirs(self, config: Dict[str, Any]) -> dict:
        """Set the data directories in the received config from the coordinator.

        - All data directories are placed under a common root data directory to persist
        files across upgrades. The naming follows the default conventions from the
        official Mimir docs: https://grafana.com/docs/mimir/latest/references/configuration-parameters/
        """
        config = config.copy()

        # Define a list of keys, subkeys, and folders in the Mimir config
        # that need to be under the common root data directory
        data_mapping = [
            ("alertmanager", "data_dir", "data-alertmanager"),
            ("alertmanager_storage", "filesystem", "data-alertmanager-recovery"),
            ("compactor", "data_dir", "data-compactor"),
            ("ruler", "rule_path", "data-ruler"),
            ("ruler_storage", "filesystem", "ruler"),
            ("blocks_storage", "filesystem", "blocks"),
            ("blocks_storage", "tsdb", "tsdb"),
            ("blocks_storage", "bucket_store", "tsdb-sync"),
        ]

        # The Mimir coordinator doesn't know the actual location of where the data
        # will reside in the workers. The following loop updates the path of each key
        # in the data_mapping list to match the actual common root data directory where
        # the data will reside.
        for key, subkey, folder in data_mapping:
            # Ensure the key exists in the config dictionary
            config.setdefault(key, {})

            # Check if the subkey exists in the corresponding key's configuration
            if subkey in config[key]:
                # Update the subkey based on its type
                # Both "data_dir" and "rule_path" in Mimir config don't have subkeys
                if "data_dir" == subkey or subkey == "rule_path":
                    config[key][subkey] = str(self._root_data_dir / folder)
                # Both "filesystem" and "tsdb" in Mimir config have a subkey "dir"
                elif "filesystem" == subkey or subkey == "tsdb":
                    config[key][subkey] = {"dir": str(self._root_data_dir / folder)}
                # "bucket_store" in Mimir config has a subkey "sync_dir"
                elif "bucket_store" == subkey:
                    config[key][subkey] = {"sync_dir": str(self._root_data_dir / folder)}
        return config

    def _running_mimir_config(self) -> Optional[dict]:
        """Return the Mimir config as dict, or None if retrieval failed."""
        if not self._container.can_connect():
            logger.debug("Could not connect to Mimir container")
            return None

        try:
            raw_current = self._container.pull(MIMIR_CONFIG).read()
            return yaml.safe_load(raw_current)
        except (ProtocolError, PathError) as e:
            logger.warning(
                "Could not check the current Mimir configuration due to "
                "a failure in retrieving the file: %s",
                e,
            )
            return None

    def restart(self):
        """Restart the pebble service or start if not already running."""
        if not self._container.exists(MIMIR_CONFIG):
            logger.error("cannot restart mimir: config file doesn't exist (yet).")

        try:
            if self._container.get_service(self._name).is_running():
                self._container.restart(self._name)
            else:
                self._container.start(self._name)
        except pebble.ChangeError as e:
            logger.error(f"failed to (re)start mimir job: {e}", exc_info=True)
            return

    def _on_collect_status(self, e: CollectStatusEvent):
        if not self._container.can_connect():
            e.add_status(WaitingStatus("Waiting for `mimir` container"))
        if not self.model.get_relation("mimir-cluster"):
            e.add_status(
                BlockedStatus("Missing mimir-cluster relation to a mimir-coordinator charm")
            )
        elif not self.mimir_cluster.relation:
            e.add_status(WaitingStatus("Mimir-Cluster relation not ready"))
        if not self.mimir_cluster.get_mimir_config():
            e.add_status(WaitingStatus("Waiting for coordinator to publish a mimir config"))
        if not self._mimir_roles:
            e.add_status(BlockedStatus("No roles assigned: please configure some roles"))
        e.add_status(ActiveStatus(""))


if __name__ == "__main__":  # pragma: nocover
    main(MimirWorkerK8SOperatorCharm)
