package io.agentflow.api.service;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class EventStreamServiceTest {

    @Test
    void normalizeEventIdTreatsBlankAsAbsent() {
        assertNull(EventStreamService.normalizeEventId(null));
        assertNull(EventStreamService.normalizeEventId(""));
        assertNull(EventStreamService.normalizeEventId("  "));
        assertTrue(EventStreamService.normalizeEventId("171-0").equals("171-0"));
    }

    @Test
    void ephemeralIdsAreNeverSkipped() {
        assertFalse(EventStreamService.shouldSkip(null, "171-0"));
        assertFalse(EventStreamService.shouldSkip(null, null));
    }

    @Test
    void persistedIdsDedupAgainstLastSent() {
        assertTrue(EventStreamService.shouldSkip("171-0", "171-0"));
        assertTrue(EventStreamService.shouldSkip("170-9", "171-0"));
        assertFalse(EventStreamService.shouldSkip("171-1", "171-0"));
        assertFalse(EventStreamService.shouldSkip("172-0", "171-9"));
    }

    @Test
    void isAfterHandlesNumericAndStreamIds() {
        assertTrue(EventStreamService.isAfter("2", "1"));
        assertFalse(EventStreamService.isAfter("1", "1"));
        assertTrue(EventStreamService.isAfter("1000-1", "999-99"));
        assertTrue(EventStreamService.isAfter("1000-2", "1000-1"));
    }
}
