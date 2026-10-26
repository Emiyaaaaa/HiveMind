package io.agentflow.api.service;

import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.dto.ScheduleCreateRequest;
import io.agentflow.api.dto.ScheduleResponse;
import io.agentflow.api.dto.ScheduleTriggerRequest;
import io.agentflow.api.dto.ScheduleUpdateRequest;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.RunEntity;
import io.agentflow.api.entity.RunScheduleEntity;
import io.agentflow.api.repository.RunRepository;
import io.agentflow.api.repository.RunScheduleRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ScheduleService {

    private static final String INTERNAL_METADATA_KEY = "_agentflow";
    private static final String AGENT_VERSION_METADATA_KEY = "agent_version";

    private final RunScheduleRepository schedules;
    private final RunRepository runs;
    private final AgentService agents;
    private final RunService runService;

    public ScheduleService(
            RunScheduleRepository schedules,
            RunRepository runs,
            AgentService agents,
            RunService runService) {
        this.schedules = schedules;
        this.runs = runs;
        this.agents = agents;
        this.runService = runService;
    }

    @Transactional
    public ScheduleResponse create(ScheduleCreateRequest request) {
        AccessControl.require(Role.OPERATOR);
        AgentEntity agent = agents.getEntity(request.getAgentId());
        String cron = blankToNull(request.getCron());
        Integer interval = request.getIntervalSeconds();
        Timing timing = normalizeTiming(cron, interval, request.getTimezone());
        RunScheduleEntity row = new RunScheduleEntity();
        row.setTenantId(agent.getTenantId());
        row.setAgentId(agent.getId());
        row.setName(blankToNull(request.getName()));
        row.setCron(timing.cron());
        row.setIntervalSeconds(timing.intervalSeconds());
        row.setTimezone(timing.timezone());
        row.setInput(new HashMap<>(request.getInput()));
        row.setMetadata(new HashMap<>(request.getMetadata()));
        row.setAdapter(blankToNull(request.getAdapter()));
        row.setEnabled(request.getEnabled() == null || request.getEnabled());
        row.setNextRunAt(ScheduleTiming.nextFireAt(
                timing.cron(), timing.intervalSeconds(), timing.timezone(), Instant.now()));
        return ScheduleResponse.fromEntity(schedules.save(row));
    }

    @Transactional(readOnly = true)
    public List<ScheduleResponse> list(int limit) {
        String tenantId = AccessControl.tenantId(Role.VIEWER);
        int capped = Math.max(1, Math.min(limit, 200));
        return schedules.findRecentByTenantId(tenantId, PageRequest.of(0, capped)).stream()
                .map(ScheduleResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public ScheduleResponse get(String id) {
        return ScheduleResponse.fromEntity(require(id, Role.VIEWER));
    }

    @Transactional
    public ScheduleResponse update(String id, ScheduleUpdateRequest request) {
        AccessControl.require(Role.OPERATOR);
        RunScheduleEntity row = require(id, Role.OPERATOR);
        boolean timingTouched = false;
        if (request.getName() != null) {
            row.setName(blankToNull(request.getName()));
        }
        if (request.getInput() != null) {
            row.setInput(new HashMap<>(request.getInput()));
        }
        if (request.getMetadata() != null) {
            row.setMetadata(new HashMap<>(request.getMetadata()));
        }
        if (request.getAdapter() != null) {
            row.setAdapter(blankToNull(request.getAdapter()));
        }
        if (request.getEnabled() != null) {
            row.setEnabled(request.getEnabled());
        }
        if (request.getTimezone() != null) {
            row.setTimezone(request.getTimezone());
            timingTouched = true;
        }

        String cron = row.getCron();
        Integer interval = row.getIntervalSeconds();
        if (request.getCron() != null) {
            cron = blankToNull(request.getCron());
            interval = null;
            timingTouched = true;
        }
        if (request.getIntervalSeconds() != null) {
            interval = request.getIntervalSeconds();
            cron = null;
            timingTouched = true;
        }
        if (timingTouched) {
            Timing timing = normalizeTiming(cron, interval, row.getTimezone());
            row.setCron(timing.cron());
            row.setIntervalSeconds(timing.intervalSeconds());
            row.setTimezone(timing.timezone());
            row.setNextRunAt(ScheduleTiming.nextFireAt(
                    timing.cron(), timing.intervalSeconds(), timing.timezone(), Instant.now()));
        }
        return ScheduleResponse.fromEntity(schedules.save(row));
    }

    @Transactional
    public void delete(String id) {
        AccessControl.require(Role.OPERATOR);
        schedules.delete(require(id, Role.OPERATOR));
    }

    @Transactional
    public RunResponse trigger(String id, ScheduleTriggerRequest request) {
        AccessControl.require(Role.OPERATOR);
        RunScheduleEntity row = require(id, Role.OPERATOR);
        boolean advance = request != null && request.isAdvance();
        AgentEntity agent = agents.getEntity(row.getAgentId());
        Map<String, Object> metadata = new HashMap<>(row.getMetadata());
        metadata.put(
                INTERNAL_METADATA_KEY,
                Map.of(
                        AGENT_VERSION_METADATA_KEY,
                        agent.getVersion(),
                        "schedule_id",
                        row.getId()));
        RunEntity run = runService.createTaggedRun(
                agent, row.getAdapter(), row.getInput(), metadata);
        if (advance) {
            Instant when = Instant.now();
            row.setLastRunAt(when);
            row.setLastRunId(run.getId());
            try {
                row.setNextRunAt(ScheduleTiming.nextFireAt(
                        row.getCron(), row.getIntervalSeconds(), row.getTimezone(), when));
            } catch (ScheduleException ex) {
                row.setEnabled(false);
            }
            schedules.save(row);
        }
        return RunResponse.fromEntity(run);
    }

    @Transactional(readOnly = true)
    public List<RunResponse> listRuns(String id, int limit) {
        RunScheduleEntity row = require(id, Role.VIEWER);
        int capped = max(1, Math.min(limit, 200));
        List<RunEntity> recent =
                runs.findRecentByTenantId(row.getTenantId(), PageRequest.of(0, capped * 5));
        List<RunResponse> matched = new ArrayList<>();
        for (RunEntity run : recent) {
            Object internal = run.getMetadata() == null
                    ? null
                    : run.getMetadata().get(INTERNAL_METADATA_KEY);
            if (internal instanceof Map<?, ?> map
                    && row.getId().equals(String.valueOf(map.get("schedule_id")))) {
                matched.add(RunResponse.fromEntity(run));
                if (matched.size() >= capped) {
                    break;
                }
            }
        }
        return matched;
    }

    private RunScheduleEntity require(String id, Role role) {
        String tenantId = AccessControl.tenantId(role);
        return schedules
                .findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> ScheduleException.notFound(id));
    }

    private static Timing normalizeTiming(String cron, Integer interval, String timezone) {
        String tz = timezone == null || timezone.isBlank() ? "UTC" : timezone.strip();
        if ((cron == null) == (interval == null)) {
            throw new ScheduleException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "Provide exactly one of cron or interval_seconds");
        }
        if (cron != null) {
            return new Timing(ScheduleTiming.normalizeCron(cron), null, tz);
        }
        return new Timing(null, ScheduleTiming.normalizeInterval(interval), tz);
    }

    private static String blankToNull(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.strip();
    }

    private static int max(int a, int b) {
        return Math.max(a, b);
    }

    private record Timing(String cron, Integer intervalSeconds, String timezone) {}
}
