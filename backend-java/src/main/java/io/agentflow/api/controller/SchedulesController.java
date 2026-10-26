package io.agentflow.api.controller;

import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.dto.ScheduleCreateRequest;
import io.agentflow.api.dto.ScheduleResponse;
import io.agentflow.api.dto.ScheduleTriggerRequest;
import io.agentflow.api.dto.ScheduleUpdateRequest;
import io.agentflow.api.service.ScheduleService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/schedules")
public class SchedulesController {

    private final ScheduleService service;

    public SchedulesController(ScheduleService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ScheduleResponse create(@Valid @RequestBody ScheduleCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping
    public List<ScheduleResponse> list(@RequestParam(defaultValue = "50") int limit) {
        return service.list(limit);
    }

    @GetMapping("/{id}")
    public ScheduleResponse get(@PathVariable String id) {
        return service.get(id);
    }

    @PatchMapping("/{id}")
    public ScheduleResponse update(
            @PathVariable String id, @RequestBody ScheduleUpdateRequest payload) {
        return service.update(id, payload);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable String id) {
        service.delete(id);
    }

    @PostMapping("/{id}/trigger")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public RunResponse trigger(
            @PathVariable String id, @RequestBody(required = false) ScheduleTriggerRequest payload) {
        return service.trigger(id, payload);
    }

    @GetMapping("/{id}/runs")
    public List<RunResponse> listRuns(
            @PathVariable String id, @RequestParam(defaultValue = "50") int limit) {
        return service.listRuns(id, limit);
    }
}
