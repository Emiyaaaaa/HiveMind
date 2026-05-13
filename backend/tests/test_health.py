import pytest


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "echo" in body["adapters"]
    assert "langgraph" in body["adapters"]
