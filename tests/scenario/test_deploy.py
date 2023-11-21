# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from unittest.mock import patch, MagicMock

import pytest
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from scenario import Container, Relation, State

from charms.mimir_coordinator_k8s.v0.mimir_cluster import MimirRole
from tests.scenario.conftest import MIMIR_VERSION_EXEC_OUTPUT


@pytest.mark.parametrize("evt", ["update-status", "config-changed"])
def test_status_cannot_connect_no_relation(ctx, evt):
    state_out = ctx.run(evt, state=State(containers=[Container("mimir", can_connect=False)]))
    assert state_out.unit_status == BlockedStatus(
        "Missing mimir-cluster relation to a mimir-coordinator charm"
    )


@pytest.mark.parametrize("evt", ["update-status", "config-changed"])
def test_status_cannot_connect(ctx, evt):
    state_out = ctx.run(
        evt,
        state=State(
            config={"roles": "ruler"},
            containers=[Container("mimir", can_connect=False)],
            relations=[Relation("mimir-cluster")],
        ),
    )
    assert state_out.unit_status == WaitingStatus("Waiting for `mimir` container")


@pytest.mark.parametrize("evt", ["update-status", "config-changed"])
def test_status_no_config(ctx, evt):
    state_out = ctx.run(
        evt,
        state=State(
            containers=[Container("mimir", can_connect=True)],
            relations=[Relation("mimir-cluster")],
        ),
    )
    assert state_out.unit_status == BlockedStatus("No roles assigned: please configure some roles")


@pytest.mark.parametrize(
    "roles",
    (
        ["alertmanager", "compactor"],
        ["alertmanager", "distributor"],
        ["alertmanager"],
        ["alertmanager", "query_frontend"],
        ["alertmanager", "ruler", "store_gateway"],
        ["alertmanager", "overrides_exporter", "ruler", "store_gateway"],  # order matters
    ),
)
def test_pebble_ready_plan(ctx, roles):
    expected_plan = {
        "services": {
            "mimir": {
                "override": "replace",
                "summary": "mimir worker daemon",
                "command": f"/bin/mimir --config.file=/etc/mimir/mimir-config.yaml -target {','.join(roles)}",
                "startup": "enabled",
            }
        },
    }

    mimir_container = Container(
        "mimir",
        can_connect=True,
        exec_mock={("/bin/mimir", "-version"): MIMIR_VERSION_EXEC_OUTPUT},
    )

    state_out = ctx.run(
        mimir_container.pebble_ready_event,
        state=State(
            config={"roles": ",".join(roles)},
            containers=[mimir_container],
            relations=[
                Relation(
                    "mimir-cluster",
                    remote_app_data={"mimir_config": json.dumps({"alive": "beef"})},
                )
            ],
        ),
    )

    mimir_container_out = state_out.get_container(mimir_container)
    assert mimir_container_out.services.get("mimir").is_running() is True
    assert mimir_container_out.plan.to_dict() == expected_plan

    assert state_out.unit_status == ActiveStatus("")


@pytest.mark.parametrize("roles_config, expected", (
        ("notarole", ()),
        ("notarole,stillnotarole", ()),
        ("foo, and bar;' AASDIEWORQKR<><>!!", ()),
        ("querier", (MimirRole.querier, )),
        ("querier,ingester", (MimirRole.querier, MimirRole.ingester)),
        ("READ,ingester", (MimirRole.query_frontend, MimirRole.querier, MimirRole.ingester)),
        ("READ", (MimirRole.query_frontend, MimirRole.querier)),
        ("WRITE", (MimirRole.distributor, MimirRole.ingester)),
        ("BACKEND", (MimirRole.store_gateway, MimirRole.compactor,
            MimirRole.ruler, MimirRole.alertmanager,
            MimirRole.query_scheduler, MimirRole.overrides_exporter)),
        ("ALL", tuple(MimirRole)),
))
def test_roles(ctx, roles_config, expected):
    with ctx.manager(
        "config-changed",
        state=State(
            leader=True,
            config={"roles": roles_config},
            containers=[Container("mimir", can_connect=True)],
            relations=[Relation("mimir-cluster")],
        ),
    ) as mgr:
        mm = MagicMock()
        with patch.object(mgr.charm.mimir_cluster, "publish_app_roles", mm) as p:
            mgr.run()
        if expected:
            assert set(p.call_args[0][0]) == set(expected)
        else:
            assert not p.called


