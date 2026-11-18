from datetime import UTC, datetime, timedelta

from omnilink_contracts import TelemetryEvent, entity_urn

from processing.rules_reference import Rule, RuleEvaluator

T0 = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
URN = entity_urn("FloodSensor", "abudhabi", "fs-1")


def ev(v, i=0, **kw):
    return TelemetryEvent(tenant="abudhabi", device_id="fs-1", entity_id=URN, entity_type="FloodSensor",
                          attribute="waterLevel", value=v, unit="m", source_ts=T0 + timedelta(seconds=i),
                          protocol="mqtt", point_ref="x", **kw)


def test_transitions_with_hysteresis():
    r = Rule(id="flood-high", tenant="abudhabi", attribute="waterLevel", condition="gt", threshold=1.5,
             hysteresis=0.2, entity_type="FloodSensor")
    e = RuleEvaluator([r])
    seq = [1.0, 1.6, 1.7, 1.4, 1.29, 1.6]
    out = [[h.active for h in e.evaluate(ev(v, i))] for i, v in enumerate(seq)]
    # raise at 1.6, stays active at 1.7 and 1.4 (inside hysteresis), clears at 1.29, raises again at 1.6
    assert out == [[], [True], [], [], [False], [True]]


def test_rule_scope_and_quality():
    r = Rule(id="r", tenant="abudhabi", attribute="waterLevel", condition="gte", threshold=1,
             entity_id=entity_urn("FloodSensor", "abudhabi", "other"))
    assert RuleEvaluator([r]).evaluate(ev(5)) == []
    r2 = Rule(id="r2", tenant="abudhabi", attribute="waterLevel", condition="gte", threshold=1, entity_type="FloodSensor")
    assert RuleEvaluator([r2]).evaluate(ev(5, quality="bad")) == []
