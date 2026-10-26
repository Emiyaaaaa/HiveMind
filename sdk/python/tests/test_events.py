import json

from agentflow_sdk.events import RunEvent, _parse_sse_lines


def test_run_event_from_dict():
    event = RunEvent.from_dict(
        {
            "type": "step.started",
            "run_id": "01ABC",
            "at": "2026-05-13T06:00:00+00:00",
            "data": {"index": 0},
        }
    )
    assert event.type == "step.started"
    assert event.run_id == "01ABC"


def test_parse_sse_lines():
    raw = [
        "id: 1-0",
        "event: run.started",
        'data: {"type":"run.started","run_id":"01ABC","at":"2026-05-13T06:00:00+00:00","data":{}}',
        "",
        "event: ping",
        "data: {}",
        "",
    ]
    frames = list(_parse_sse_lines(iter(raw)))
    assert len(frames) == 2
    assert frames[0][0] == "1-0"
    assert frames[0][1] == "run.started"
    payload = json.loads(frames[0][2])
    assert payload["type"] == "run.started"
