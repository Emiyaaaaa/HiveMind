package io.agentflow.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class ScheduleTimingTest {

    @Test
    void intervalAdvancesFromBase() {
        Instant base = Instant.parse("2026-09-11T12:00:00Z");
        Instant next = ScheduleTiming.nextFireAt(null, 120, "UTC", base);
        assertThat(next).isEqualTo(base.plus(2, ChronoUnit.MINUTES));
    }

    @Test
    void cronHourlyProducesFutureInstant() {
        Instant base = Instant.parse("2026-09-11T12:10:00Z");
        Instant next = ScheduleTiming.nextFireAt("0 * * * *", null, "UTC", base);
        assertThat(next).isEqualTo(Instant.parse("2026-09-11T13:00:00Z"));
    }

    @Test
    void rejectsMissingTiming() {
        assertThatThrownBy(() -> ScheduleTiming.nextFireAt(null, null, "UTC", Instant.now()))
                .isInstanceOf(ScheduleException.class)
                .extracting(ex -> ((ScheduleException) ex).status())
                .isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
    }

    @Test
    void rejectsShortInterval() {
        assertThatThrownBy(() -> ScheduleTiming.normalizeInterval(30))
                .isInstanceOf(ScheduleException.class);
    }
}
