package io.agentflow.api.service;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.zone.ZoneRulesException;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.support.CronExpression;

/** Shared cron / interval next-fire helpers for RunSchedule. */
public final class ScheduleTiming {

    public static final int MIN_INTERVAL_SECONDS = 60;

    private ScheduleTiming() {}

    public static Instant nextFireAt(String cron, Integer intervalSeconds, String timezone, Instant after) {
        if ((cron == null || cron.isBlank()) == (intervalSeconds == null)) {
            throw invalid("Provide exactly one of cron or interval_seconds");
        }
        Instant base = after == null ? Instant.now() : after;
        ZoneId zone = zone(timezone);
        if (intervalSeconds != null) {
            if (intervalSeconds < MIN_INTERVAL_SECONDS) {
                throw invalid("interval_seconds must be >= " + MIN_INTERVAL_SECONDS);
            }
            return base.plus(Duration.ofSeconds(intervalSeconds));
        }
        CronExpression expression = parseCron(cron);
        ZonedDateTime local = ZonedDateTime.ofInstant(base, zone);
        ZonedDateTime next = expression.next(local);
        if (next == null) {
            throw invalid("cron expression has no next fire time: " + cron);
        }
        return next.toInstant();
    }

    public static String normalizeCron(String cron) {
        if (cron == null || cron.isBlank()) {
            throw invalid("cron must be a 5-field minute expression");
        }
        String cleaned = cron.strip();
        if (cleaned.split("\\s+").length != 5) {
            throw invalid("cron must be a 5-field minute expression (min hour dom month dow)");
        }
        parseCron(cleaned);
        return cleaned;
    }

    public static int normalizeInterval(Integer seconds) {
        if (seconds == null || seconds < MIN_INTERVAL_SECONDS) {
            throw invalid("interval_seconds must be >= " + MIN_INTERVAL_SECONDS);
        }
        return seconds;
    }

    private static CronExpression parseCron(String fiveField) {
        // Spring CronExpression uses 6 fields (seconds first).
        String spring = "0 " + fiveField.strip();
        try {
            return CronExpression.parse(spring);
        } catch (IllegalArgumentException ex) {
            throw invalid("Invalid cron expression: " + fiveField);
        }
    }

    private static ZoneId zone(String timezone) {
        String label = timezone == null || timezone.isBlank() ? "UTC" : timezone.strip();
        try {
            return ZoneId.of(label);
        } catch (ZoneRulesException ex) {
            throw invalid("Unknown timezone: " + label);
        }
    }

    private static ScheduleException invalid(String message) {
        return new ScheduleException(HttpStatus.UNPROCESSABLE_ENTITY, message);
    }
}
