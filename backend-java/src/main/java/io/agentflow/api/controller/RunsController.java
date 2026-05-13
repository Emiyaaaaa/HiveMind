package io.agentflow.api.controller;

import io.agentflow.api.dto.RunCreateRequest;
import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.service.RunService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/runs")
public class RunsController {

    private final RunService service;

    public RunsController(RunService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public RunResponse create(@Valid @RequestBody RunCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping
    public List<RunResponse> list(@RequestParam(defaultValue = "50") int limit) {
        return service.list(limit);
    }

    @GetMapping("/{id}")
    public RunResponse get(@PathVariable String id) {
        return service.get(id);
    }

    @PostMapping("/{id}/cancel")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void cancel(@PathVariable String id) {
        service.cancel(id);
    }
}
