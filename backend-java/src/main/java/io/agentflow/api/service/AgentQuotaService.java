package io.agentflow.api.service;

import io.agentflow.api.dto.AgentQuotaStatusResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentQuotaUsageEntity;
import io.agentflow.api.repository.AgentQuotaUsageRepository;
import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.IsoFields;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Agent-level token/cost quotas configured via {@code Agent.config.quota}.
 * Counters are written by the Python worker; the Java API only gates
 * {@code POST /v1/runs} and exposes current period status.
 */
@Service
public class AgentQuotaService {

    private final AgentQuotaUsageRepository usageRepository;

    public AgentQuotaService(AgentQuotaUsageRepository usageRepository) {
        this.usageRepository = usageRepository;
    }

    @Transactional(readOnly = true)
    public AgentQuotaStatusResponse status(AgentEntity agent) {
        QuotaConfig cfg = QuotaConfig.parse(agent.getConfig());
        AgentQuotaStatusResponse out = new AgentQuotaStatusResponse();
        out.setAgentId(agent.getId());
        if (cfg == null || !cfg.active()) {
            out.setActive(false);
            return out;
        }
        String key = periodKey(cfg.period(), Instant.now());
        Optional<AgentQuotaUsageEntity> row =
                usageRepository.findByAgentIdAndPeriodKey(agent.getId(), key);
        int tokensIn = row.map(AgentQuotaUsageEntity::getTokensIn).orElse(0);
        int tokensOut = row.map(AgentQuotaUsageEntity::getTokensOut).orElse(0);
        double cost = row.map(AgentQuotaUsageEntity::getCostUsd).orElse(0.0);
        int usedTokens = tokensIn + tokensOut;
        String reason = exceeds(cfg, usedTokens, cost);

        Instant[] bounds = periodBounds(cfg.period(), key);
        out.setActive(true);
        out.setEnforce(cfg.enforce());
        out.setPeriod(cfg.period());
        out.setPeriodKey(key);
        out.setPeriodStart(bounds[0]);
        out.setPeriodEnd(bounds[1]);
        out.setMaxTokens(cfg.maxTokens());
        out.setMaxCostUsd(cfg.maxCostUsd());
        out.setUsedTokens(usedTokens);
        out.setUsedTokensIn(tokensIn);
        out.setUsedTokensOut(tokensOut);
        out.setUsedCostUsd(round6(cost));
        out.setRunCount(row.map(AgentQuotaUsageEntity::getRunCount).orElse(0));
        out.setRemainingTokens(
                cfg.maxTokens() == null ? null : Math.max(0, cfg.maxTokens() - usedTokens));
        out.setRemainingCostUsd(
                cfg.maxCostUsd() == null
                        ? null
                        : round6(Math.max(0.0, cfg.maxCostUsd() - cost)));
        out.setExceeded(reason != null);
        return out;
    }

    @Transactional
    public void assertCanCreateRun(AgentEntity agent) {
        QuotaConfig cfg = QuotaConfig.parse(agent.getConfig());
        if (cfg == null || !cfg.active() || !cfg.enforce()) {
            return;
        }
        String key = periodKey(cfg.period(), Instant.now());
        Optional<AgentQuotaUsageEntity> row =
                usageRepository.findByAgentIdAndPeriodKeyForUpdate(agent.getId(), key);
        int tokensIn = row.map(AgentQuotaUsageEntity::getTokensIn).orElse(0);
        int tokensOut = row.map(AgentQuotaUsageEntity::getTokensOut).orElse(0);
        double cost = row.map(AgentQuotaUsageEntity::getCostUsd).orElse(0.0);
        int usedTokens = tokensIn + tokensOut;
        String reason = exceeds(cfg, usedTokens, cost);
        if (reason == null) {
            return;
        }
        StringBuilder message = new StringBuilder();
        message
                .append("Agent quota exceeded (")
                .append(reason)
                .append("): period=")
                .append(key)
                .append(" tokens=")
                .append(usedTokens);
        if (cfg.maxTokens() != null) {
            message.append('/').append(cfg.maxTokens());
        }
        message.append(" cost_usd=").append(String.format(Locale.US, "%.6f", cost));
        if (cfg.maxCostUsd() != null) {
            message.append('/').append(cfg.maxCostUsd());
        }
        throw new AgentQuotaExceededException(agent.getId(), key, reason, message.toString());
    }

    static String periodKey(String period, Instant when) {
        LocalDate day = LocalDate.ofInstant(when, ZoneOffset.UTC);
        return switch (period) {
            case "day" -> day.toString();
            case "week" -> {
                int year = day.get(IsoFields.WEEK_BASED_YEAR);
                int week = day.get(IsoFields.WEEK_OF_WEEK_BASED_YEAR);
                yield String.format(Locale.US, "%d-W%02d", year, week);
            }
            default -> String.format(Locale.US, "%04d-%02d", day.getYear(), day.getMonthValue());
        };
    }

    static Instant[] periodBounds(String period, String key) {
        return switch (period) {
            case "day" -> {
                LocalDate day = LocalDate.parse(key);
                yield new Instant[] {
                    day.atStartOfDay().toInstant(ZoneOffset.UTC),
                    day.plusDays(1).atStartOfDay().toInstant(ZoneOffset.UTC)
                };
            }
            case "week" -> {
                String[] parts = key.split("-W");
                int year = Integer.parseInt(parts[0]);
                int week = Integer.parseInt(parts[1]);
                LocalDate start =
                        LocalDate.of(year, 6, 1)
                                .with(IsoFields.WEEK_BASED_YEAR, year)
                                .with(IsoFields.WEEK_OF_WEEK_BASED_YEAR, week)
                                .with(DayOfWeek.MONDAY);
                yield new Instant[] {
                    start.atStartOfDay().toInstant(ZoneOffset.UTC),
                    start.plusDays(7).atStartOfDay().toInstant(ZoneOffset.UTC)
                };
            }
            default -> {
                String[] parts = key.split("-");
                int year = Integer.parseInt(parts[0]);
                int month = Integer.parseInt(parts[1]);
                LocalDate start = LocalDate.of(year, month, 1);
                yield new Instant[] {
                    start.atStartOfDay().toInstant(ZoneOffset.UTC),
                    start.plusMonths(1).atStartOfDay().toInstant(ZoneOffset.UTC)
                };
            }
        };
    }

    private static String exceeds(QuotaConfig cfg, int usedTokens, double usedCost) {
        if (cfg.maxTokens() != null && usedTokens >= cfg.maxTokens()) {
            return "tokens";
        }
        if (cfg.maxCostUsd() != null && usedCost >= cfg.maxCostUsd()) {
            return "cost_usd";
        }
        return null;
    }

    private static double round6(double value) {
        return Math.round(value * 1_000_000.0) / 1_000_000.0;
    }

    record QuotaConfig(
            String period, Integer maxTokens, Double maxCostUsd, boolean enforce) {

        boolean active() {
            return maxTokens != null || maxCostUsd != null;
        }

        @SuppressWarnings("unchecked")
        static QuotaConfig parse(Map<String, Object> config) {
            if (config == null) {
                return null;
            }
            Object raw = config.get("quota");
            if (raw == null) {
                return null;
            }
            if (!(raw instanceof Map<?, ?> map)) {
                return new QuotaConfig("month", null, null, true);
            }
            Map<String, Object> quota = (Map<String, Object>) map;
            String periodRaw = String.valueOf(quota.getOrDefault("period", "month"))
                    .trim()
                    .toLowerCase(Locale.ROOT);
            String period;
            if (periodRaw.equals("day") || periodRaw.equals("daily")) {
                period = "day";
            } else if (periodRaw.equals("week") || periodRaw.equals("weekly")) {
                period = "week";
            } else {
                period = "month";
            }
            Integer maxTokens = asNonNegativeInt(quota.get("max_tokens"));
            Double maxCost = asNonNegativeDouble(quota.get("max_cost_usd"));
            boolean enforce = true;
            Object enforceRaw = quota.get("enforce");
            if (enforceRaw instanceof Boolean b) {
                enforce = b;
            } else if (enforceRaw != null) {
                String s = String.valueOf(enforceRaw).trim().toLowerCase(Locale.ROOT);
                enforce = !(s.equals("0") || s.equals("false") || s.equals("no") || s.equals("off"));
            }
            return new QuotaConfig(period, maxTokens, maxCost, enforce);
        }

        private static Integer asNonNegativeInt(Object value) {
            if (value == null || "".equals(value)) {
                return null;
            }
            try {
                int n = value instanceof Number num ? num.intValue() : Integer.parseInt(String.valueOf(value));
                return n >= 0 ? n : null;
            } catch (NumberFormatException ex) {
                return null;
            }
        }

        private static Double asNonNegativeDouble(Object value) {
            if (value == null || "".equals(value)) {
                return null;
            }
            try {
                double n =
                        value instanceof Number num
                                ? num.doubleValue()
                                : Double.parseDouble(String.valueOf(value));
                return n >= 0 ? n : null;
            } catch (NumberFormatException ex) {
                return null;
            }
        }
    }
}
