import pytest
from uplink_bridge import RejectedMessage, gateway_tenant_from_client_id, route


def test_route_allowed_topic():
    r = route("omnilink/v1/omnilink.telemetry.v1/abudhabi:ahu-03", b"{}", "abudhabi")
    assert r.kafka_topic == "omnilink.telemetry.v1" and r.key == b"abudhabi:ahu-03"


@pytest.mark.parametrize("topic,tenant", [
    ("other/v1/omnilink.telemetry.v1/abudhabi:x", None),
    ("omnilink/v1/omnilink.commands.v1/abudhabi:x", None),      # commands never flow edge -> core
    ("omnilink/v1/omnilink.telemetry.v1", None),
    ("omnilink/v1/omnilink.telemetry.v1/rak:x", "abudhabi"),    # tenant spoofing
])
def test_route_rejections(topic, tenant):
    with pytest.raises(RejectedMessage):
        route(topic, b"{}", tenant)


def test_gateway_identity():
    assert gateway_tenant_from_client_id("gw-abudhabi-site01") == "abudhabi"
    assert gateway_tenant_from_client_id("random") is None
