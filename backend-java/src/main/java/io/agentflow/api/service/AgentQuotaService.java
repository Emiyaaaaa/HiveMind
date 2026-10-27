package io.agentflow.api.service;

import io.agentflow.api.dto.AgentQuotaStatusResponse;
import io.agentflow.api.dto.QuotaConfigRequest;
import io.agentflow.api.entity.AbstractQuotaConfigEntity;
import io.agentflow.api.entity.AbstractQuotaUsageEntity;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.ProjectEntity;
import io.agentflow.api.entity.ProjectQuotaConfigEntity;
import io.agentflow.api.entity.TenantQuotaConfigEntity;
import io.agentflow.api.repository.AgentQuotaUsageRepository;
import io.agentflow.api.repository.ProjectQuotaConfigRepository;
import io.agentflow.api.repository.ProjectQuotaUsageRepository;
import io.agentflow.api.repository.ProjectRepository;
import io.agentflow.api.repository.TenantQuotaConfigRepository;
import io.agentflow.api.repository.TenantQuotaUsageRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.temporal.IsoFields;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Tenant, project, and agent token/cost quotas.
 *
 * <p>Agent limits stay on {@code Agent.config.quota}. Tenant and project limits
 * are rows in {@code tenant_quota_configs} / {@code project_quota_configs}.
 * Counters are written by the Python worker; this service gates run creation
 * and exposes current period status. The gate checks tenant, then project,
 * then agent.
 */
@Service
public class AgentQuotaService {

    private final AgentQuotaUsageRepository agentUsage;
    private final ProjectQuotaUsageRepository projectUsage;
    private final TenantQuotaUsageRepository tenantUsage;
    private final ProjectQuotaConfigRepository projectConfigs;
    private final TenantQuotaConfigRepository tenantConfigs;
    private final ProjectRepository projects;

    public AgentQuotaService(
            AgentQuotaUsageRepository agentUsage,
            ProjectQuotaUsageRepository projectUsage,
            TenantQuotaUsageRepository tenantUsage,
            ProjectQuotaConfigRepository projectConfigs,
            TenantQuotaConfigRepository tenantConfigs,
            ProjectRepository projects) {
        this.agentUsage = agentUsage;
        this.projectUsage = projectUsage;
        this.tenantUsage = tenantUsage;
        this.projectConfigs = projectConfigs;
        this.tenantConfigs = tenantConfigs;
        this.projects = projects;
    }

    @Transactional(readOnly = true)
    public AgentQuotaStatusResponse status(AgentEntity agent) {
        return buildStatus(
                "agent",
                agent.getId(),
                agent.getTenantId(),
                agent.getProjectId(),
                agent.getId(),
                QuotaConfig.parse(agent.getConfig()));
    }

    @Transactional(readOnly = true)
    public AgentQuotaStatusResponse projectStatus(String projectId) {
        return buildStatus(requireProject(projectId));
    }

    @Transactional(readOnly = true)
    public AgentQuotaStatusResponse tenantStatus() {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        return buildStatus(tenantId);
    }

    @Transactional
    public AgentQuotaStatusResponse upsertProject(String projectId, QuotaConfigRequest request) {
        AccessControl.require(Role.ADMIN);
        ProjectEntity project = requireProject(projectId);
        QuotaConfig cfg = QuotaConfig.fromRequest(request);
        ProjectQuotaConfigEntity row =
                Optional.ofNullable(orNull(projectConfigs.findByProjectId(project.getId())))
                        .orElseGet(ProjectQuotaConfigEntity::new);
        row.setTenantId(project.getTenantId());
        row.setProjectId(project.getId());
        applyConfig(row, cfg);
        projectConfigs.save(row);
        return buildStatus(project);
    }

    @Transactional
    public AgentQuotaStatusResponse upsertTenant(QuotaConfigRequest request) {
        AccessControl.require(Role.ADMIN);
        String tenantId = AccessControl.tenantId(Role.ADMIN);
        QuotaConfig cfg = QuotaConfig.fromRequest(request);
        TenantQuotaConfigEntity row =
                Optional.ofNullable(orNull(tenantConfigs.findByTenantId(tenantId)))
                        .orElseGet(TenantQuotaConfigEntity::new);
        row.setTenantId(tenantId);
        applyConfig(row, cfg);
        tenantConfigs.save(row);
        return buildStatus(tenantId);
    }

    @Transactional
    public void assertCanCreateRun(AgentEntity agent) {
        assertScope(
                "tenant",
                agent.getTenantId(),
                agent,
                configFrom(orNull(tenantConfigs.findByTenantId(agent.getTenantId()))));
        if (agent.getProjectId() != null && !agent.getProjectId().isBlank()) {
            assertScope(
                    "project",
                    agent.getProjectId(),
                    agent,
                    configFrom(orNull(projectConfigs.findByProjectId(agent.getProjectId()))));
        }
        assertScope("agent", agent.getId(), agent, QuotaConfig.parse(agent.getConfig()));
    }

    private AgentQuotaStatusResponse buildStatus(ProjectEntity project) {
        ProjectQuotaConfigEntity row = orNull(projectConfigs.findByProjectId(project.getId()));
        return buildStatus(
                "project",
                project.getId(),
                project.getTenantId(),
                project.getId(),
                null,
                configFrom(row));
    }

    private AgentQuotaStatusResponse buildStatus(String tenantId) {
        TenantQuotaConfigEntity row = orNull(tenantConfigs.findByTenantId(tenantId));
        return buildStatus("tenant", tenantId, tenantId, null, null, configFrom(row));
    }

    private AgentQuotaStatusResponse buildStatus(
            String scope,
            String scopeId,
            String tenantId,
            String projectId,
            String agentId,
            QuotaConfig cfg) {
        AgentQuotaStatusResponse out = new AgentQuotaStatusResponse();
        out.setScope(scope);
        out.setScopeId(scopeId);
        out.setTenantId(tenantId);
        out.setProjectId(projectId);
        out.setAgentId(agentId);
        if (cfg == null || !cfg.active()) {
            out.setActive(false);
            return out;
        }
        String key = periodKey(cfg.period(), Instant.now());
        Usage usage = loadUsage(scope, scopeId, key, false);
        int usedTokens = usage.tokens();
        String reason = exceeds(cfg, usedTokens, usage.cost());
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
        out.setUsedTokensIn(usage.tokensIn());
        out.setUsedTokensOut(usage.tokensOut());
        out.setUsedCostUsd(round6(usage.cost()));
        out.setRunCount(usage.runCount());
        out.setRemainingTokens(
                cfg.maxTokens() == null ? null : Math.max(0, cfg.maxTokens() - usedTokens));
        out.setRemainingCostUsd(
                cfg.maxCostUsd() == null
                        ? null
                        : round6(Math.max(0.0, cfg.maxCostUsd() - usage.cost())));
        out.setExceeded(reason != null);
        return out;
    }

    private void assertScope(String scope, String scopeId, AgentEntity agent, QuotaConfig cfg) {
        if (cfg == null || !cfg.active() || !cfg.enforce()) {
            return;
        }
        String key = periodKey(cfg.period(), Instant.now());
        Usage usage = loadUsage(scope, scopeId, key, true);
        int usedTokens = usage.tokens();
        String reason = exceeds(cfg, usedTokens, usage.cost());
        if (reason == null) {
            return;
        }
        throw new AgentQuotaExceededException(
                scope,
                scopeId,
                agent.getId(),
                key,
                reason,
                quotaMessage(scope, reason, key, usedTokens, usage.cost(), cfg));
    }

    private Usage loadUsage(String scope, String scopeId, String key, boolean forUpdate) {
        AbstractQuotaUsageEntity row =
                switch (scope) {
                    case "tenant" ->
                            orNull(
                                    forUpdate
                                            ? tenantUsage.findByTenantIdAndPeriodKeyForUpdate(scopeId, key)
                                            : tenantUsage.findByTenantIdAndPeriodKey(scopeId, key));
                    case "project" ->
                            orNull(
                                    forUpdate
                                            ? projectUsage.findByProjectIdAndPeriodKeyForUpdate(scopeId, key)
                                            : projectUsage.findByProjectIdAndPeriodKey(scopeId, key));
                    default ->
                            orNull(
                                    forUpdate
                                            ? agentUsage.findByAgentIdAndPeriodKeyForUpdate(scopeId, key)
                                            : agentUsage.findByAgentIdAndPeriodKey(scopeId, key));
                };
        if (row == null) {
            return Usage.ZERO;
        }
        return new Usage(row.getTokensIn(), row.getTokensOut(), row.getCostUsd(), row.getRunCount());
    }

    private ProjectEntity requireProject(String projectId) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        return projects
                .findByIdAndTenantId(projectId, tenantId)
                .orElseThrow(ProjectNotFoundException::new);
    }

    private static void applyConfig(AbstractQuotaConfigEntity row, QuotaConfig cfg) {
        row.setPeriod(cfg.period());
        row.setMaxTokens(cfg.maxTokens());
        row.setMaxCostUsd(cfg.maxCostUsd());
        row.setEnforce(cfg.enforce());
    }

    private static <T> T orNull(Optional<T> value) {
        return value == null ? null : value.orElse(null);
    }

    private static QuotaConfig configFrom(AbstractQuotaConfigEntity row) {
        if (row == null) {
            return null;
        }
        return QuotaConfig.fromStored(
                row.getPeriod(), row.getMaxTokens(), row.getMaxCostUsd(), row.isEnforce());
    }

    private static String quotaMessage(
            String scope,
            String reason,
            String key,
            int usedTokens,
            double cost,
            QuotaConfig cfg) {
        String label =
                switch (scope) {
                    case "tenant" -> "Tenant";
                    case "project" -> "Project";
                    default -> "Agent";
                };
        StringBuilder message = new StringBuilder();
        message.append(label)
                .append(" quota exceeded (")
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
        return message.toString();
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

    private record Usage(int tokensIn, int tokensOut, double cost, int runCount) {
        static final Usage ZERO = new Usage(0, 0, 0.0, 0);

        int tokens() {
            return tokensIn + tokensOut;
        }
    }

    record QuotaConfig(String period, Integer maxTokens, Double maxCostUsd, boolean enforce) {

        boolean active() {
            return maxTokens != null || maxCostUsd != null;
        }

        static QuotaConfig fromStored(
                String period, Integer maxTokens, Double maxCostUsd, boolean enforce) {
            Map<String, Object> quota = new HashMap<>();
            quota.put("period", period);
            quota.put("max_tokens", maxTokens);
            quota.put("max_cost_usd", maxCostUsd);
            quota.put("enforce", enforce);
            QuotaConfig parsed = parse(Map.of("quota", quota));
            return parsed == null ? new QuotaConfig("month", null, null, enforce) : parsed;
        }

        static QuotaConfig fromRequest(QuotaConfigRequest request) {
            Map<String, Object> quota = new HashMap<>();
            quota.put(
                    "period",
                    request == null || request.getPeriod() == null ? "month" : request.getPeriod());
            if (request != null && request.getMaxTokens() != null) {
                quota.put("max_tokens", request.getMaxTokens());
            }
            if (request != null && request.getMaxCostUsd() != null) {
                quota.put("max_cost_usd", request.getMaxCostUsd());
            }
            Object enforce =
                    request == null || request.getEnforce() == null ? Boolean.TRUE : request.getEnforce();
            quota.put("enforce", enforce);
            QuotaConfig parsed = parse(Map.of("quota", quota));
            return parsed == null ? new QuotaConfig("month", null, null, true) : parsed;
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
