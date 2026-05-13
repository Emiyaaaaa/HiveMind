package io.agentflow.api.entity;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

/**
 * Run lifecycle states. Stored as lowercase strings in the database to match
 * the values written by the Python SQLAlchemy enum
 * (see {@code backend/app/models/run.py}).
 */
public enum RunStatus {
    PENDING,
    RUNNING,
    SUCCEEDED,
    FAILED,
    CANCELLED,
    WAITING_HUMAN;

    @JsonValue
    public String wire() {
        return name().toLowerCase();
    }

    @JsonCreator
    public static RunStatus fromWire(String value) {
        if (value == null) {
            return null;
        }
        return RunStatus.valueOf(value.toUpperCase());
    }
}
