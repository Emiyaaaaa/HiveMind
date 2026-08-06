package io.agentflow.api.controller;

import io.agentflow.api.dto.RegressionExecutionCreateRequest;
import io.agentflow.api.dto.RegressionExecutionResponse;
import io.agentflow.api.dto.RegressionExecutionResultsResponse;
import io.agentflow.api.service.RegressionExecutionService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/regression-executions")
public class RegressionExecutionsController {

    private final RegressionExecutionService service;

    public RegressionExecutionsController(RegressionExecutionService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public RegressionExecutionResponse create(
            @Valid @RequestBody RegressionExecutionCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping("/{executionId}")
    public RegressionExecutionResponse get(@PathVariable String executionId) {
        return service.get(executionId);
    }

    @GetMapping("/{executionId}/results")
    public RegressionExecutionResultsResponse results(@PathVariable String executionId) {
        return service.results(executionId);
    }
}
