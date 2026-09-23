import json


def test_direction_publisher_lease_rejects_second_companion(monkeypatch):
    from dashboard import app as dashboard_app
    import dashboard.database as database

    settings = {}
    monkeypatch.setattr(
        dashboard_app,
        "get_client_by_email",
        lambda email: {"client": "Lease Test"} if email == "client@example.com" else None,
    )
    monkeypatch.setattr(database, "get_setting", lambda key: settings.get(key, ""))
    monkeypatch.setattr(
        database,
        "set_setting",
        lambda key, value, updated_by="": settings.__setitem__(key, value),
    )

    payload = {
        "email": "client@example.com",
        "direction": "buy",
        "publisher_id": "companion-one",
    }
    client = dashboard_app.app.test_client()

    first = client.post("/api/signals/direction", json=payload)
    second = client.post(
        "/api/signals/direction",
        json={**payload, "publisher_id": "companion-two", "direction": "sell"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert json.loads(settings[dashboard_app.DIRECTION_SIGNAL_SETTING])["direction"] == "buy"